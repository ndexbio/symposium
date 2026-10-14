"""The composition root (api/DESIGN.md §9): one API at /v1. The data server's hand-written routes
and the routes generated from the contract are served by one app. uvicorn starts
`symposium_server:app`; neither `symposium_data` nor `symposium_api` imports the other's app, so
every import points one way.

It adds three things to the data server's app: the generated routers over the hand-written
service, the contract the access checks read, and, at startup, the notify listener and the
sweep of expired API keys. The keys themselves are the data server's: it issues them, and every
route authenticates with them (`symposium_data.access`).
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from symposium_api import provider
from symposium_api.generated import ROUTERS
from symposium_api.service import ApiService
from symposium_data import access
from symposium_data import app as data

API_PREFIX = "/v1"
log = logging.getLogger("symposium_server")

app = data.app
public_url = (os.environ.get("SYMPOSIUM_SERVER_PUBLIC_URL") or "").rstrip("/") or None
runtime = provider.Runtime(
    db=data.db,
    records=data.records,
    store=data.store,
    settings=data.settings,
)
contract = access.load()
keys = data.api_keys
access.wire(contract=contract, public_url=public_url)
service = ApiService(runtime, keys, contract)
provider.wire(service)
for router in ROUTERS:
    app.include_router(router, prefix=API_PREFIX)


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
            log.info("api keys: %d expired values erased by the startup sweep", swept)
        service.notifier.start()
        # the derived index is rebuilt at startup, in the background, so the server serves
        # while it catches up; a read before then folds in what it needs itself
        threading.Thread(target=catch_up_all, name="api-index", daemon=True).start()
        try:
            yield
        finally:
            service.notifier.stop()


app.router.lifespan_context = lifespan
