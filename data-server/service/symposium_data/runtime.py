"""Settings, database and payload store: the injectable runtime pieces of the data server.

Everything secret comes from /apps/data/config/service.env, which start.sh generates on first
boot with owner-only permissions. Nothing secret is ever read from argv.
"""

from __future__ import annotations

import os
import time
from importlib import resources
from pathlib import Path

import boto3
from alembic import command
from alembic.config import Config as AlembicConfig
from botocore.config import Config as BotoConfig
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy import create_engine

DEFAULT_CONFIG = "/apps/data/config/service.env"
# Arbitrary but fixed: every process that migrates takes this lock first, so a starting API
# and a concurrent `data-admin` never run the migrations at the same time.
MIGRATION_LOCK_ID = 7_301_014


class Settings:
    """Reads the generated service.env plus the operator-facing SYMPOSIUM_DATA_* variables."""

    def __init__(self, path: str | None = None, environ: dict | None = None):
        env = os.environ if environ is None else environ
        self.path = Path(path or env.get("SYMPOSIUM_DATA_CONFIG", DEFAULT_CONFIG))
        values = {}
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        self.database_url = values["DATABASE_URL"]
        self.s3_endpoint = values["S3_ENDPOINT"]
        self.s3_access_key = values["S3_ACCESS_KEY"]
        self.s3_secret_key = values["S3_SECRET_KEY"]
        self.s3_bucket = values.get("S3_BUCKET", "symposium-data")
        self.server_id = values["SERVER_ID"]
        self.registration = env.get("SYMPOSIUM_DATA_REGISTRATION", "invite")
        self.public_base_url = env.get("SYMPOSIUM_DATA_PUBLIC_BASE_URL", "")


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=20,
            kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"},
            # Validate each connection on checkout, so a PostgreSQL restart costs one failed
            # request at most instead of leaving broken connections in the pool.
            check=ConnectionPool.check_connection,
            open=False,
        )

    def open(self, attempts: int = 60):
        """Open the pool, waiting for PostgreSQL to come up (supervisord starts it alongside)."""
        for attempt in range(attempts):
            try:
                self.pool.open(wait=True, timeout=5)
                return
            except Exception:
                if attempt + 1 == attempts:
                    raise
                time.sleep(1)

    def connection(self, timeout: float | None = None):
        return self.pool.connection(timeout=timeout)

    def migrate(self):
        """Bring the schema to the latest Alembic revision under an advisory lock."""
        url = self.settings.database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"SELECT pg_advisory_lock({MIGRATION_LOCK_ID})")
                try:
                    cfg = AlembicConfig()
                    location = resources.files("symposium_data") / "migrations"
                    cfg.set_main_option("script_location", str(location))
                    cfg.attributes["connection"] = conn
                    command.upgrade(cfg, "head")
                finally:
                    conn.exec_driver_sql(
                        f"SELECT pg_advisory_unlock({MIGRATION_LOCK_ID})"
                    )
        finally:
            engine.dispose()


class PayloadStore:
    """The internal S3 store. Its port is never exposed; the service streams every byte."""

    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name="us-east-1",
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 5},
            ),
        )

    def ensure_bucket(self, attempts: int = 60):
        """Create the bucket if missing, waiting for SeaweedFS to come up."""
        for attempt in range(attempts):
            try:
                self.s3.head_bucket(Bucket=self.bucket)
                return
            except Exception:
                try:
                    self.s3.create_bucket(Bucket=self.bucket)
                    return
                except Exception:
                    if attempt + 1 == attempts:
                        raise
                    time.sleep(1)

    def healthy(self) -> bool:
        try:
            self.s3.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False
