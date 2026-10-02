"""Settings, database and payload store: the injectable runtime pieces of the data server.

Everything secret comes from /apps/data/config/service.env, which start.sh generates on first
boot with owner-only permissions. Nothing secret is ever read from argv.
"""

from __future__ import annotations

import hashlib
import os
import time
from importlib import resources
from pathlib import Path

import boto3
from alembic import command
from alembic.config import Config as AlembicConfig
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
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
        self.token_key_file = values["TOKEN_KEY_FILE"]
        self.registration = env.get("SYMPOSIUM_DATA_REGISTRATION", "invite")
        self.public_base_url = env.get("SYMPOSIUM_DATA_PUBLIC_BASE_URL", "")
        self.token_ttl = int(env.get("SYMPOSIUM_DATA_TOKEN_TTL", "900"))
        self.invite_hours = int(env.get("SYMPOSIUM_DATA_INVITE_HOURS", "72"))
        # 0 means no quota. Counted per owner over the payload bytes they uploaded first.
        self.quota_bytes = int(env.get("SYMPOSIUM_DATA_QUOTA_BYTES", "0"))
        self.pending_ttl = int(env.get("SYMPOSIUM_DATA_PENDING_TTL", "86400"))
        self.janitor_interval = int(env.get("SYMPOSIUM_DATA_JANITOR_INTERVAL", "3600"))
        self.scrub_interval = int(env.get("SYMPOSIUM_DATA_SCRUB_INTERVAL", "3600"))
        self.scrub_batch = int(env.get("SYMPOSIUM_DATA_SCRUB_BATCH", "50"))
        # how often a streaming upload refreshes its reservation and pending payload
        self.heartbeat = max(0.2, min(60.0, self.pending_ttl / 3))
        # Test-only: when enabled, S3 deletes fail while FAULT_FILE exists. Off by default.
        self.fault_injection = env.get("SYMPOSIUM_DATA_FAULT_INJECTION") == "1"


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

    FAULT_FILE = Path("/apps/data/config/fault-s3-delete")

    def __init__(self, settings: Settings):
        self.fault_injection = settings.fault_injection
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

    def put_bytes(self, key: str, data: bytes):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def _fault(self):
        if self.fault_injection and self.FAULT_FILE.exists():
            raise RuntimeError("injected S3 delete fault")

    def delete(self, key: str):
        self._fault()
        self.s3.delete_object(Bucket=self.bucket, Key=key)

    def abort(self, key: str, upload_id: str):
        self._fault()
        self.s3.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)

    def remove(self, key: str, upload_id: str | None = None):
        """Remove every byte of a payload: an open multipart upload and the object. Raises
        when anything may remain; an upload or key that is already gone counts as removed,
        so a retry is always safe."""
        if upload_id:
            try:
                self.abort(key, upload_id)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "NoSuchUpload":
                    raise
        self.delete(key)

    def open_read(self, key: str, byte_range: str | None = None):
        kwargs = {"Bucket": self.bucket, "Key": key}
        if byte_range:
            kwargs["Range"] = byte_range
        return self.s3.get_object(**kwargs)

    def digest(self, key: str) -> str:
        """sha256 of an object as stored, streamed (the scrub's check)."""
        sha = hashlib.sha256()
        for chunk in self.open_read(key)["Body"].iter_chunks(1024 * 1024):
            sha.update(chunk)
        return sha.hexdigest()


PART_SIZE = 8 * 1024 * 1024


class MultipartWriter:
    """Streams one payload into S3 while hashing it. Nothing is visible until finish()."""

    def __init__(self, store: PayloadStore, key: str, on_upload_started=None):
        self.store, self.key = store, key
        self.on_upload_started = on_upload_started
        self.sha = hashlib.sha256()
        self.size = 0
        self.buffer = bytearray()
        self.upload_id = None
        self.parts = []

    def write(self, chunk: bytes):
        self.sha.update(chunk)
        self.size += len(chunk)
        self.buffer += chunk
        while len(self.buffer) >= PART_SIZE:
            self._flush(bytes(self.buffer[:PART_SIZE]))
            del self.buffer[:PART_SIZE]

    def _flush(self, data: bytes):
        s3, bucket = self.store.s3, self.store.bucket
        if self.upload_id is None:
            self.upload_id = s3.create_multipart_upload(Bucket=bucket, Key=self.key)[
                "UploadId"
            ]
            if self.on_upload_started:
                self.on_upload_started(self.upload_id)
        number = len(self.parts) + 1
        part = s3.upload_part(
            Bucket=bucket,
            Key=self.key,
            UploadId=self.upload_id,
            PartNumber=number,
            Body=data,
        )
        self.parts.append({"PartNumber": number, "ETag": part["ETag"]})

    def finish(self):
        if self.upload_id is None:
            self.store.put_bytes(self.key, bytes(self.buffer))
        else:
            if self.buffer:
                self._flush(bytes(self.buffer))
            self.store.s3.complete_multipart_upload(
                Bucket=self.store.bucket,
                Key=self.key,
                UploadId=self.upload_id,
                MultipartUpload={"Parts": self.parts},
            )
        self.buffer = bytearray()

    def abort(self):
        """Best effort: whatever is left behind is swept by the janitor."""
        try:
            if self.upload_id is not None:
                self.store.abort(self.key, self.upload_id)
            else:
                self.store.delete(self.key)
        except Exception:
            pass

    def hexdigest(self) -> str:
        return self.sha.hexdigest()
