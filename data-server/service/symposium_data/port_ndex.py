"""The one-time bootstrap of a fresh server from a Symposium community on NDEx (R-M).

This is the only NDEx client code in the server, and only `data-admin port-ndex` imports it.
It runs once, on a fresh server, and never again: it is not a sync. Configured by environment:

    PORT_NDEX_URL               base URL of the NDEx server
    PORT_NDEX_CREDENTIALS_FILE  JSON {"username": ..., "password": ...}: the community admin's
                                account, a bound pair, read from a file (never env or argv)
    PORT_COMMUNITY              the community to create here
    PORT_ADMIN_HANDLE           the admin handle; `data-admin init` must later use the same one
    PORT_NDEX_PAGE_SIZE         listing page size (default 100)

It ports the admin-owned networks marked `symposium_record` into `record` and those marked
`symposium_reply` into `inbox`, keeping each artifact's exact canonical bytes, name, original
`created` and author. Everything is written in one transaction (R-A6): any failure writes
nothing and removes the bytes again.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import urllib.request
from datetime import datetime

from .cleanup import Cleanup
from .records import COLLECTIONS, Conflict, Records
from .runtime import Database, PayloadStore
from .wire import NAME

CANONICAL = "symposium_canonical"
RECORD_MARK = "symposium_record"
REPLY_MARK = "symposium_reply"
IN_REPLY_TO = "symposium_in_reply_to"
HANDLE = re.compile(NAME)

log = logging.getLogger("symposium_data.port_ndex")


class PortRefused(Exception):
    """The port does not apply to this server or this source; nothing was written."""


class NdexClient:
    """The few NDEx 3.0 calls the port needs, read-only, with HTTP Basic auth."""

    def __init__(self, base: str, username: str, password: str, page_size: int):
        self.base = base.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self.page_size = page_size
        self.listing_pages = 0

    def get(self, path: str, raw: bool = False):
        request = urllib.request.Request(self.base + path, headers=self.headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode()
        return body if raw else json.loads(body)

    def paged(self, path: str) -> tuple[dict, int]:
        """A whole permission map -> (map, pages read). `start` is a PAGE index and a short
        page ends the listing; NDEx truncates silently, so every page is read and a repeat is
        an error."""
        out, page = {}, 0
        while True:
            chunk = self.get(f"{path}&start={page}&size={self.page_size}")
            repeated = set(chunk) & set(out)
            if repeated:
                raise RuntimeError(f"paging returned {len(repeated)} entries twice")
            out.update(chunk)
            if len(chunk) < self.page_size:
                return out, page + 1
            page += 1

    def whoami(self) -> dict:
        return self.get("/v2/user?valid=true")

    def owned_networks(self, user_id: str) -> list:
        owned, self.listing_pages = self.paged(
            f"/v2/user/{user_id}/permission?type=NETWORK&permission=ADMIN"
        )
        return list(owned)

    def network_attributes(self, network_id: str) -> dict:
        for aspect in self.get(f"/v3/networks/{network_id}"):
            if "networkAttributes" in aspect:
                return aspect["networkAttributes"][0]
        return {}

    def readers(self, network_id: str) -> list:
        """The usernames holding any permission on a network."""
        users, _ = self.paged(f"/v2/network/{network_id}/permission?type=user")
        return [self.get(f"/v2/user/{uid}")["userName"] for uid in sorted(users)]


class Port:
    def __init__(
        self,
        db: Database,
        store: PayloadStore,
        records: Records,
        cleanup: Cleanup,
        environ: dict,
    ):
        self.db, self.store, self.records, self.cleanup = db, store, records, cleanup
        self.url = environ["PORT_NDEX_URL"].rstrip("/")
        self.community = environ["PORT_COMMUNITY"]
        self.admin = environ["PORT_ADMIN_HANDLE"]
        self.page_size = int(environ.get("PORT_NDEX_PAGE_SIZE", "100"))
        self.credentials_file = environ["PORT_NDEX_CREDENTIALS_FILE"]

    def emit(self, **fields):
        print(json.dumps({"event": "port-ndex", **fields}), flush=True)

    def run(self) -> int:
        try:
            with self.db.connection() as conn:
                if self.check_fresh(conn):
                    self.emit(status="already-ported", source=self.url)
                    return 0
            self.store.ensure_bucket()
            summary = self.port()
        except PortRefused as e:
            self.emit(status="refused", reason=str(e))
            return 1
        except Exception as e:
            log.exception("port-ndex failed")
            self.emit(status="failed", reason=f"{type(e).__name__}: {e}")
            return 1
        self.emit(status="ok", source=self.url, **summary)
        return 0

    def check_fresh(self, conn) -> bool:
        """-> True when this exact source was already ported (a no-op). Refuses anything
        but a fresh server: the port is a one-time bootstrap (R-M)."""
        source = self.records.config(conn, "port_source")
        if source == self.url:
            return True
        if source is not None:
            raise PortRefused(f"this server was already ported from {source}")
        if self.records.config(conn, "admin") is not None:
            raise PortRefused(
                "the server is initialized; the port runs only on a fresh one"
            )
        if conn.execute("SELECT 1 FROM communities LIMIT 1").fetchone():
            raise PortRefused("the server already holds a community")
        for name, value in (
            ("PORT_COMMUNITY", self.community),
            ("PORT_ADMIN_HANDLE", self.admin),
        ):
            if not HANDLE.match(value):
                raise PortRefused(f"{name} '{value}' is not a valid name")
        return False

    # ── reading NDEx ────────────────────────────────────────────────────────────────────────
    def read_source(self) -> tuple[NdexClient, dict]:
        with open(self.credentials_file) as fh:
            credentials = json.load(fh)
        client = NdexClient(
            self.url, credentials["username"], credentials["password"], self.page_size
        )
        me = client.whoami()
        owned = client.owned_networks(me["externalId"])
        found = {"record": [], "inbox": [], "networks": len(owned), "skipped": 0}
        for network_id in owned:
            attributes = client.network_attributes(network_id)
            if attributes.get(RECORD_MARK) is True and CANONICAL in attributes:
                found["record"].append(self.item(attributes, me["userName"]))
            elif attributes.get(REPLY_MARK) is True and CANONICAL in attributes:
                item = self.item(attributes, me["userName"])
                recipients = sorted(
                    self.handle(name, me["userName"])
                    for name in client.readers(network_id)
                    if name != me["userName"]
                )
                item["metadata"] = {
                    REPLY_MARK: True,
                    IN_REPLY_TO: attributes.get(IN_REPLY_TO),
                    "recipients": recipients,
                }
                found["inbox"].append(item)
            else:
                found["skipped"] += 1
        for collection in ("record", "inbox"):
            found[collection].sort(key=lambda x: x["created"])
            self.check_order(collection, found[collection])
        return client, found

    def item(self, attributes: dict, admin_user: str) -> dict:
        raw = attributes[CANONICAL]
        header = json.loads(raw)["artifact"]
        created = datetime.fromisoformat(header["created"])
        if created.tzinfo is None:
            raise PortRefused(f"{header['name']}: created has no timezone")
        return {
            "name": header["name"],
            "bytes": raw.encode(),
            "created": created,
            "author": self.handle(header["published_by"].lstrip("@"), admin_user),
            "metadata": {RECORD_MARK: True},
        }

    def handle(self, user: str, admin_user: str) -> str:
        """An NDEx account as a handle here: the admin account becomes PORT_ADMIN_HANDLE."""
        handle = self.admin if user == admin_user else user
        if not HANDLE.match(handle):
            raise PortRefused(f"'{user}' cannot be a handle here")
        return handle

    def check_order(self, collection: str, items: list):
        for before, after in zip(items, items[1:], strict=False):
            if not before["created"] < after["created"]:
                raise PortRefused(
                    f"{collection}: '{before['name']}' and '{after['name']}' share the "
                    f"instant {after['created'].isoformat()}; created must strictly increase"
                )

    # ── writing ─────────────────────────────────────────────────────────────────────────────
    def port(self) -> dict:
        client, found = self.read_source()
        items = [("record", x) for x in found["record"]] + [
            ("inbox", x) for x in found["inbox"]
        ]
        members = sorted(
            {x["author"] for _, x in items}
            | {h for x in found["inbox"] for h in x["metadata"]["recipients"]}
        )
        members = [h for h in members if h != self.admin]
        pending, duplicates = [], []
        try:
            for _, item in items:
                with self.db.connection() as conn:
                    pid, key = self.records.begin_payload(
                        conn, self.community, item["author"]
                    )
                pending.append(pid)
                self.store.put_bytes(key, item["bytes"])
                item["pid"] = pid
                item["sha256"] = hashlib.sha256(item["bytes"]).hexdigest()
            with self.db.connection() as conn:
                self.write(conn, items, members, duplicates)
        except BaseException:
            for pid in pending:
                self.cleanup.discard_pending(pid)
            raise
        for pid in duplicates:
            self.cleanup.discard_pending(pid)
        return {
            "community": self.community,
            "admin": self.admin,
            "pages": client.listing_pages,
            "networks": found["networks"],
            "skipped": found["skipped"],
            "record": len(found["record"]),
            "replies": len(found["inbox"]),
            "reserved_roster": members,
        }

    def write(self, conn, items: list, members: list, duplicates: list):
        """The one transaction: the community, its roster, every file and version, then the
        checks, then the sentinel. Nothing is visible until it commits."""
        conn.execute("INSERT INTO communities (name) VALUES (%s)", (self.community,))
        self.records.ensure_collections(conn, self.community, self.admin)
        for handle in members:
            self.records.add_to_roster(conn, self.community, handle)
        for handle in members:
            conn.execute(
                "INSERT INTO owners (community, handle, reserved) VALUES (%s, %s, true) "
                "ON CONFLICT (community, handle) DO NOTHING",
                (self.community, handle),
            )
        written = []
        for collection, item in items:
            try:
                file_id = self.records.create_live_file(
                    conn, self.community, collection, item["name"]
                )
            except Conflict as e:
                raise PortRefused(str(e)) from None
            payload, duplicate = self.records.commit_payload(
                conn,
                item["pid"],
                self.community,
                item["sha256"],
                len(item["bytes"]),
                item["author"],
                0,
            )
            if duplicate:
                duplicates.append(duplicate)
            clock = self.records.allocate_at(
                conn, self.community, collection, item["created"]
            )
            self.records.add_version(
                conn,
                file_id,
                payload,
                item["metadata"],
                "application/json",
                item["author"],
                None,
                clock=clock,
            )
            written.append((collection, file_id, item["sha256"]))
        for collection, file_id, sha in written:
            if self.records.version(conn, self.community, file_id, 1)["sha256"] != sha:
                raise RuntimeError(f"sha256 mismatch on {collection} file {file_id}")
        for collection in COLLECTIONS:
            expected = sum(1 for c, _, _ in written if c == collection)
            count = conn.execute(
                "SELECT count(*) AS n FROM files WHERE community = %s AND collection = %s",
                (self.community, collection),
            ).fetchone()["n"]
            if count != expected:
                raise RuntimeError(f"{collection}: {count} files, expected {expected}")
        self.records.set_config(conn, "port_source", self.url)
        self.records.set_config(conn, "port_admin", self.admin)
