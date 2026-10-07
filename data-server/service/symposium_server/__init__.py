"""The composition root (api/DESIGN.md §9): the data server's app with the Symposium API
mounted at /api/v1. uvicorn starts `symposium_server:app`; neither `symposium_data` nor
`symposium_api` imports the other's app, so every import points one way.

It adds three things to the data server's app: the generated routers over the hand-written
service, the API's error body on every /api/v1 refusal, and, at startup, the notify listener
and the sweep that revokes admin API keys bound to a retired admin key.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from symposium_api import contract as contract_module
from symposium_api import provider
from symposium_api.errors import ApiError, body_for
from symposium_api.generated import ROUTERS
from symposium_api.keys import ApiKeys, Sealer, key_file_from
from symposium_api.service import ApiService
from symposium_data import app as data
from symposium_data.records import Conflict, Forbidden, NotFound

API_PREFIX = "/api/v1"
log = logging.getLogger("symposium_server")

app = data.app
runtime = provider.Runtime(
    db=data.db,
    records=data.records,
    store=data.store,
    settings=data.settings,
    tokens=data.tokens,
    admin_mode=lambda: data.admin_mode,
    public_url=(os.environ.get("SYMPOSIUM_DATA_PUBLIC_URL") or "").rstrip("/") or None,
)
contract = contract_module.load()
keys = ApiKeys(Sealer(key_file_from(Path(data.settings.path))))
service = ApiService(runtime, keys, contract)
provider.wire(runtime, service, keys, contract, service.caps)
for router in ROUTERS:
    app.include_router(router, prefix=API_PREFIX)


def in_api(request: Request) -> bool:
    return (
        request.url.path.startswith(API_PREFIX + "/") or request.url.path == API_PREFIX
    )


@app.middleware("http")
async def api_operational_only(request: Request, call_next):
    """The API speaks its own error body while the server is non-operational."""
    mode = data.admin_mode
    if in_api(request) and not mode.operational:
        return JSONResponse(
            body_for(501, f"the server is not operational: {mode.reason}"),
            status_code=501,
        )
    return await call_next(request)


@app.exception_handler(ApiError)
async def _api_error(_request, error: ApiError):
    return JSONResponse(error.body(), status_code=error.status, headers=error.headers)


def _refusal(status: int):
    async def handler(request: Request, error):
        body = (
            body_for(status, str(error)) if in_api(request) else {"detail": str(error)}
        )
        return JSONResponse(body, status_code=status)

    return handler


# /v1 keeps its own bodies; under /api/v1 the same refusals answer the API's Error body
app.add_exception_handler(NotFound, _refusal(404))
app.add_exception_handler(Forbidden, _refusal(403))
app.add_exception_handler(Conflict, _refusal(409))


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, error: StarletteHTTPException):
    if in_api(request):
        return JSONResponse(
            body_for(error.status_code, error.detail),
            status_code=error.status_code,
            headers=getattr(error, "headers", None),
        )
    return await http_exception_handler(request, error)


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, error: RequestValidationError):
    if in_api(request):
        return JSONResponse(body_for(400, error.errors()), status_code=400)
    return await request_validation_exception_handler(request, error)


def index_status() -> dict:
    """/v1/status's view of the API, server-wide and naming no community: how many record
    versions the index has yet to fold in, across every community."""
    with runtime.db.connection(timeout=0.5) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(GREATEST(c.seq - COALESCE(p.seq, 0), 0)), 0) AS behind "
            "FROM collections c LEFT JOIN api_index_position p ON p.community = c.community "
            "WHERE c.name = 'record'"
        ).fetchone()
    return {"api_index": {"behind": int(row["behind"])}}


data.status_extensions.append(index_status)


def catch_up_all() -> None:
    """Fold every community's record into the derived index."""
    try:
        with runtime.db.connection() as conn:
            communities = [r["name"] for r in runtime.records.communities(conn)]
        for community in communities:
            with runtime.db.connection() as conn:
                service.index.catch_up(conn, community)
        log.info("api index: %d communities caught up", len(communities))
    except Exception:
        log.exception(
            "api index: the startup catch-up stopped; reads catch up on their own"
        )


data_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async with data_lifespan(application):
        with runtime.db.connection() as conn:
            swept = keys.sweep(conn)
        if swept:
            log.info("api keys: %d revoked or erased by the startup sweep", swept)
        service.notifier.start()
        # the derived index is rebuilt at startup, in the background, so the server serves
        # while it catches up; a read before then folds in what it needs itself
        threading.Thread(target=catch_up_all, name="api-index", daemon=True).start()
        try:
            yield
        finally:
            service.notifier.stop()


app.router.lifespan_context = lifespan
