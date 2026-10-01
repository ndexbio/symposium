"""Symposium Data HTTP API. Every byte is streamed by this service; S3 is never exposed."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from . import API_VERSION, version
from .records import Records
from .runtime import Database, PayloadStore, Settings

settings = Settings()
db = Database(settings)
store = PayloadStore(settings)
records = Records()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.migrate()
    db.open()
    store.ensure_bucket()
    yield
    db.pool.close()


app = FastAPI(title="Symposium Data", version=version(), lifespan=lifespan)


@app.get("/v1/status")
def status(response: Response):
    """Version and health. Answers 503 while PostgreSQL or the S3 store is unavailable, so a
    readiness probe never routes traffic to a server that cannot serve it."""
    admin, postgres_ok = None, True
    try:
        with db.connection(timeout=3) as conn:
            admin = records.config(conn, "admin")
    except Exception:
        postgres_ok = False
    s3_ok = store.healthy()
    if not (postgres_ok and s3_ok):
        response.status_code = 503
    return {
        "api": API_VERSION,
        "version": version(),
        "server_id": settings.server_id,
        "initialized": (admin is not None) if postgres_ok else None,
        "registration": settings.registration,
        "postgres": "ok" if postgres_ok else "unavailable",
        "s3": "ok" if s3_ok else "unavailable",
        "public_base_url": settings.public_base_url or None,
    }
