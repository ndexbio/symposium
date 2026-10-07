"""The Symposium Control API, `/v1`. Every byte is streamed by this service; S3 is never exposed.

Communities are tenants (R-G8): every community-dependent route is under /v1/{community}/...,
with collection-scoped routes under collections/{collection}/ and file routes under files/{id}/.
Only /v1/status, /v1/communities and the server admin's sign-in (/v1/admin/...) are server-wide.

Nobody has a shell on the server (R-D7): every admin operation is an admin-only route, and the
admin's key comes from the key file on the volume (R-D4). Without a usable one the server is
non-operational: every route but /v1/status answers 501.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from . import API_VERSION, version
from .admin_key import AdminKeyFile, AdminMode
from .api_keys import ApiKeys, Sealer, key_file_from
from .archive import Archive, Malformed, Refused
from .auth import PublicKeys, Secrets, Tokens
from .jobs import Jobs
from .records import (
    Conflict,
    Forbidden,
    NotFound,
    PreconditionFailed,
    QuotaExceeded,
    Records,
    iso,
)
from .runtime import Database, MultipartWriter, PayloadStore, Settings
from .wire import (
    NAME,
    WireError,
    digest_header,
    etag,
    parse_citation,
    parse_digest,
    parse_if_match,
    parse_instant,
    parse_metadata,
    stamp,
    valid_community,
    valid_file_name,
    valid_sha256,
)

settings = Settings()
db = Database(settings)
store = PayloadStore(settings)
records = Records()
keys = PublicKeys()
secrets = Secrets()
tokens = Tokens(settings.token_key_file, settings.server_id, settings.token_ttl)
api_keys = ApiKeys(Sealer(key_file_from(Path(settings.path))))
jobs = Jobs(settings, db, store, records)
cleanup = jobs.cleanup
archive = Archive(db, store, records, cleanup, settings.heartbeat)
log = logging.getLogger("symposium_data.app")
admin_key_file = AdminKeyFile(Path("/apps"), db, records, keys)
admin_mode = AdminMode(False, reason="starting")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global admin_mode
    db.migrate()
    db.open()
    with db.connection() as conn:
        records.fail_running_ports(conn)
    store.ensure_bucket()
    admin_mode = admin_key_file.resolve()
    jobs.start()
    yield
    jobs.shutdown()
    db.pool.close()


app = FastAPI(title="Symposium Data", version=version(), lifespan=lifespan)


@app.middleware("http")
async def operational_only(request: Request, call_next):
    """Non-operational mode (R-D4): only /v1/status answers; the jobs keep running."""
    if not admin_mode.operational and request.url.path != "/v1/status":
        return JSONResponse(
            {"detail": f"the server is not operational: {admin_mode.reason}"},
            status_code=501,
        )
    return await call_next(request)


@app.exception_handler(NotFound)
async def _not_found(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=404)


@app.exception_handler(Forbidden)
async def _forbidden(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=403)


@app.exception_handler(Conflict)
async def _conflict(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=409)


# Callables that add to /v1/status once the server is operational and healthy: the
# composition root registers the Symposium Data API's index position here, so this module never
# imports the API.
status_extensions: list = []


@app.get("/v1/status")
def status(response: Response):
    """Version, mode and health. Answers 503 while PostgreSQL or the S3 store is unavailable,
    so a readiness probe never routes traffic to a server that cannot serve it. In both modes it
    reports the server's id; once operational, the admin's handle and key fingerprint."""
    postgres_ok = True
    try:
        with db.connection(timeout=0.5) as conn:  # inside the probe's 1 s
            conn.execute("SELECT 1")
    except Exception:
        postgres_ok = False
    s3_ok = store.healthy()
    if not (postgres_ok and s3_ok):
        response.status_code = 503
    body = {
        "api": API_VERSION,
        "version": version(),
        "server_id": settings.server_id,
        "mode": "operational" if admin_mode.operational else "non-operational",
        "postgres": "ok" if postgres_ok else "unavailable",
        "s3": "ok" if s3_ok else "unavailable",
    }
    if admin_mode.operational:
        body.update(admin=admin_mode.handle, fingerprint=admin_mode.fingerprint)
        if postgres_ok:
            for extend in status_extensions:
                body.update(extend())
    else:
        body["reason"] = admin_mode.reason
    return body


# ── identity ────────────────────────────────────────────────────────────────────────────────
class ChallengeIn(BaseModel):
    handle: str = Field(pattern=NAME)


class TokenIn(BaseModel):
    handle: str = Field(pattern=NAME)
    nonce: str
    signature: str


class AdminTokenIn(BaseModel):
    nonce: str
    signature: str


class RegisterIn(BaseModel):
    handle: str = Field(pattern=NAME)
    public_jwk: dict
    nonce: str
    signature: str
    invite: str | None = None


class RotateIn(BaseModel):
    public_jwk: dict
    nonce: str
    signature: str


class InviteIn(BaseModel):
    handle: str = Field(pattern=NAME)
    hours: int | None = Field(default=None, ge=1, le=24 * 366)


class CommunityIn(BaseModel):
    name: str


def refuse(status: int, message: str, conn=None):
    """Raise an HTTP error. With `conn`, commit first: work already done (a challenge consumed)
    must stay done even though the request is refused."""
    if conn is not None:
        conn.commit()
    raise HTTPException(status, message)


READ_KEY_PREFIX = "sdr_"


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header.split(None, 1)[1].strip()


def community_of(conn, name: str) -> str:
    """The community a path names, as it was created; 404 for a non-slug or unknown name,
    without touching the database for a non-slug (R-G8)."""
    if not valid_community(name):
        refuse(404, f"no community '{name}'")
    found = records.community_name(conn, name)
    if found is None:
        refuse(404, f"no community '{name}'")
    return found


def owner_of(conn, request: Request, community: str | None) -> tuple[str, str]:
    """The (handle, kid) behind a valid bearer token whose key is still active. A member's
    token is valid only in its own community; the server admin's token in every community.
    `community` None accepts only the admin. Read keys never authorize anything but reads."""
    credential = bearer(request)
    if credential is None:
        refuse(401, "a bearer token is required")
    if credential.startswith(READ_KEY_PREFIX):
        refuse(403, "a read key can only read")
    claims = tokens.read(credential)
    if claims is None:
        refuse(401, "the token is not valid or has expired")
    if claims.get("adm"):
        if not records.admin_key_is_active(conn, claims["kid"]):
            refuse(401, "the token's key is no longer active")
        return claims["sub"], claims["kid"]
    if community is None:
        refuse(403, "only the admin may do this")
    if claims.get("com") != community:
        refuse(401, "the token is for another community")
    if not records.key_is_active(conn, community, claims["sub"], claims["kid"]):
        refuse(401, "the token's key is no longer active")
    return claims["sub"], claims["kid"]


def require_admin(conn, request: Request, community: str | None = None) -> str:
    handle, _ = owner_of(conn, request, community)
    if not records.is_admin(conn, handle):
        refuse(403, "only the admin may do this")
    return handle


def checked_new_key(conn, community: str, handle: str, body) -> tuple[str, dict]:
    """Consume the challenge and check the new key's proof of possession -> (kid, jwk)."""
    if not records.take_challenge(conn, community, handle, body.nonce):
        refuse(401, "the challenge is unknown, spent or expired")
    try:
        keys.validate(body.public_jwk)
    except ValueError as e:
        refuse(400, str(e), conn)
    if not keys.verify(body.public_jwk, body.nonce.encode(), body.signature):
        refuse(
            401,
            "proof of possession failed: the signature does not match the key",
            conn,
        )
    return keys.thumbprint(body.public_jwk), body.public_jwk


# ── the server admin and communities (server-wide) ──────────────────────────────────────────
@app.post("/v1/admin/challenge")
def admin_challenge():
    nonce = secrets.new("n_")
    with db.connection() as conn:
        admin = records.config(conn, "admin")
        records.add_challenge(conn, None, admin, nonce)
    return {"nonce": nonce, "expires_in": 300}


@app.post("/v1/admin/token")
def admin_token(body: AdminTokenIn):
    """The server admin's token: signed by the admin's key, valid in every community."""
    with db.connection() as conn:
        admin = records.config(conn, "admin")
        if not records.take_challenge(conn, None, admin, body.nonce):
            refuse(401, "the challenge is unknown, spent or expired", conn)
        for key in records.admin_keys(conn):
            if keys.verify(key["jwk"], body.nonce.encode(), body.signature):
                return {
                    "token": tokens.issue(admin, key["kid"]),
                    "expires_in": tokens.ttl,
                    "kid": key["kid"],
                }
        refuse(401, "the signature does not match the admin's key", conn)


@app.post("/v1/communities")
def create_community(body: CommunityIn, request: Request, response: Response):
    """Create a community and its default collections (R-G8); admin only, idempotent: the
    exact existing name answers 200, a new one 201."""
    if not valid_community(body.name):
        refuse(
            400,
            "a community name is 1-20 letters, digits or underscores, and not "
            "'status', 'communities' or 'admin'",
        )
    with db.connection() as conn:
        admin = require_admin(conn, request)
        try:
            created = records.create_community(conn, body.name, admin)
        except Conflict as e:
            conn.rollback()
            refuse(400, f"{e}; names are unique ignoring case")
        response.status_code = 201 if created else 200
        return {"name": body.name, "created": created}


@app.get("/v1/communities")
def list_communities(request: Request):
    with db.connection() as conn:
        require_admin(conn, request)
        return {
            "communities": [
                {"name": r["name"], "created": iso(r["created"])}
                for r in records.communities(conn)
            ]
        }


# ── identity within a community ─────────────────────────────────────────────────────────────
@app.post("/v1/{community}/auth/challenge")
def challenge(community: str, body: ChallengeIn):
    nonce = secrets.new("n_")
    with db.connection() as conn:
        community = community_of(conn, community)
        records.add_challenge(conn, community, body.handle, nonce)
    return {"nonce": nonce, "expires_in": 300}


@app.post("/v1/{community}/auth/token")
def token(community: str, body: TokenIn):
    with db.connection() as conn:
        community = community_of(conn, community)
        if not records.take_challenge(conn, community, body.handle, body.nonce):
            refuse(401, "the challenge is unknown, spent or expired", conn)
        for key in records.active_keys(conn, community, body.handle):
            if keys.verify(key["jwk"], body.nonce.encode(), body.signature):
                return {
                    "token": tokens.issue(body.handle, key["kid"], community),
                    "expires_in": tokens.ttl,
                    "kid": key["kid"],
                }
        refuse(401, "the signature does not match an active key of this handle", conn)


@app.post("/v1/{community}/owners", status_code=201)
def register(community: str, body: RegisterIn):
    """Register a handle in this community with a key generated on the member's machine
    (R-D1, R-D5). Identity is per community."""
    with db.connection() as conn:
        community = community_of(conn, community)
        kid, jwk = checked_new_key(conn, community, body.handle, body)
        if not records.on_roster(conn, community, body.handle):
            refuse(403, f"'{body.handle}' is not on the {community} roster", conn)
        if records.active_keys(conn, community, body.handle):
            refuse(409, f"'{body.handle}' is already registered in {community}", conn)
        if not records.consume_invite(
            conn, secrets.digest(body.invite or ""), community, body.handle
        ):
            refuse(
                403,
                "a valid, unused invite for this handle and community is required",
                conn,
            )
        records.register(conn, community, body.handle, kid, jwk)
        return {"handle": body.handle, "kid": kid, "community": community}


@app.post("/v1/{community}/owners/{handle}/keys", status_code=201)
def rotate(community: str, handle: str, body: RotateIn, request: Request):
    """Replace the caller's key in this community. Signed by the current token and proven by
    the new key; the old key is retired, not deleted, so attribution survives."""
    with db.connection() as conn:
        community = community_of(conn, community)
        current, _ = owner_of(conn, request, community)
        if current != handle or records.is_admin(conn, current):
            refuse(403, "an owner may rotate only their own key")
        kid, jwk = checked_new_key(conn, community, handle, body)
        if records.key_on_record(conn, community, kid):
            refuse(409, "that key is already on record", conn)
        records.rotate(conn, community, handle, kid, jwk)
        return {"handle": handle, "kid": kid}


@app.get("/v1/{community}/whoami")
def whoami(community: str, request: Request):
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, kid = owner_of(conn, request, community)
        if records.is_admin(conn, handle):
            return {
                "handle": handle,
                "kid": kid,
                "community": community,
                "admin": True,
                "grants": [],
                "suspect_after": None,
            }
        owner = records.owner(conn, community, handle)
        return {
            "handle": handle,
            "kid": kid,
            "community": community,
            "admin": False,
            "grants": [
                {"collection": collection, "perm": perm}
                for collection, perm in records.grants(conn, community, handle)
            ],
            "suspect_after": owner["suspect_after"].isoformat()
            if owner["suspect_after"]
            else None,
        }


@app.get("/v1/{community}/roster")
def roster(community: str, request: Request):
    """The roster, one entry per handle, registered or not yet: whether it has registered,
    and when its pending invite expires (R-D6). Any member of the community may read it, as
    the admin may: members validate addresses to one another (`@handle`) against it."""
    with db.connection() as conn:
        community = community_of(conn, community)
        owner_of(conn, request, community)  # a member of this community, or the admin
        return {
            "community": community,
            "roster": [
                {
                    "handle": r["handle"],
                    "registered": r["registered"],
                    "invite_expires": iso(r["invite_expires"]),
                }
                for r in records.roster(conn, community)
            ],
        }


def roster_handle(handle: str) -> str:
    if not re.match(NAME, handle):
        refuse(422, "a handle is a plain name")
    return handle


@app.post("/v1/{community}/roster/{handle}")
def add_member(community: str, handle: str, request: Request, response: Response):
    """Add one handle, with the default grants (admin only; R-D6). Idempotent: 201 when added,
    200 when already there. Adding never removes anyone; the admin's handle is refused."""
    handle = roster_handle(handle)
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        try:
            added = records.add_to_roster(conn, community, handle)
        except Forbidden as e:
            conn.rollback()
            refuse(400, str(e))
        response.status_code = 201 if added else 200
        return {"community": community, "handle": handle, "added": added}


@app.delete("/v1/{community}/roster/{handle}")
def remove_member(community: str, handle: str, request: Request):
    """Remove one handle: its grants and pending invite go; its identity and attribution stay
    (admin only)."""
    handle = roster_handle(handle)
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        removed = records.remove_from_roster(conn, community, handle)
        if not removed:
            refuse(404, f"'{handle}' is not on the {community} roster")
        return {"community": community, "handle": handle, "removed": True}


@app.post("/v1/{community}/invites", status_code=201)
def create_invite(community: str, body: InviteIn, request: Request):
    """A single-use invite for a roster handle, returned once (admin only; R-D5, R-D6). It
    revokes any earlier unused invite for the handle, and stays retrievable from
    GET .../invites only while pending."""
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        if not records.on_roster(conn, community, body.handle):
            refuse(403, f"'{body.handle}' is not on the {community} roster")
        return mint_invite(conn, community, body.handle, body.hours)


def mint_invite(conn, community: str, handle: str, hours: int | None) -> dict:
    invite = secrets.new("sdi_")
    hours = settings.invite_hours if hours is None else hours
    expires = records.add_invite(
        conn, secrets.digest(invite), invite, community, handle, hours
    )
    return {
        "community": community,
        "handle": handle,
        "invite": invite,
        "expires": iso(expires),
    }


@app.get("/v1/{community}/invites")
def list_invites(community: str, request: Request):
    """Every pending invite of the community, with its secret, so the admin can hand it over
    again (admin only). Used, expired and revoked invites are never listed."""
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        return {
            "community": community,
            "invites": [
                {
                    "handle": r["handle"],
                    "invite": r["secret"],
                    "expires": iso(r["expires"]),
                }
                for r in records.pending_invites(conn, community)
            ],
        }


# ── the Data API's keys: issued here, per community, by the admin (api/DESIGN.md §4) ─────────
class ApiKeyIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: Literal["non-member", "member"]
    label: str | None = Field(default=None, max_length=200)
    expires_days: int | None = Field(default=None, ge=1, le=366)


def api_key_out(row) -> dict:
    """One key as the admin sees it, its value decrypted; `key` is null once revoked."""
    out = {
        "id": str(row["id"]),
        "community": row["community"],
        "username": row["username"],
        "role": row["role"],
        "key": api_keys.value(row),
        "created": iso(row["created"]),
        "created_by": row["created_by"],
        "expires": iso(row["expires"]),
        "revoked": iso(row["revoked"]),
        "revoked_by": row["revoked_by"],
        "last_used": iso(row["last_used"]),
        "uses": row["uses"],
    }
    if row["label"]:
        out["label"] = row["label"]
    return out


def api_key_id(key_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(key_id)
    except ValueError:
        refuse(404, f"no API key '{key_id}'")


@app.post("/v1/{community}/api-keys", status_code=201)
def create_api_key(
    community: str, body: ApiKeyIn, request: Request, response: Response
):
    """A Data API key for this community, answered once with its value (admin only). A
    `member` key names a handle registered on the roster and publishes as it; a `non-member`
    key's username is a label that names no handle."""
    with db.connection() as conn:
        community = community_of(conn, community)
        admin = require_admin(conn, request, community)
        if body.role == "member":
            if not records.on_roster(
                conn, community, body.username
            ) or not records.active_keys(conn, community, body.username):
                refuse(
                    422, f"'{body.username}' is not a registered member of {community}"
                )
        elif records.on_roster(conn, community, body.username) or body.username == (
            records.config(conn, "admin")
        ):
            refuse(
                422,
                f"a non-member key's label must match no handle; '{body.username}' does",
            )
        row, _ = api_keys.create(
            conn,
            username=body.username,
            role=body.role,
            community=community,
            label=body.label,
            expires_days=body.expires_days,
            created_by=admin,
        )
        conn.commit()
        response.headers["Cache-Control"] = "no-store"
        return api_key_out(row)


@app.get("/v1/{community}/api-keys")
def list_api_keys(
    community: str,
    request: Request,
    response: Response,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    username: str | None = None,
    include_revoked: bool = True,
):
    """The community's keys in creation order, each with its value, so the admin can hand a
    lost key back (admin only). Expired keys' values are erased before anything is listed."""
    after = None
    if cursor:
        try:
            state = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            )
            after = (datetime.fromisoformat(state["c"]), uuid.UUID(state["k"]))
        except (ValueError, KeyError, TypeError, binascii.Error):
            refuse(400, "the cursor is not one this server issued")
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        api_keys.sweep(conn)
        conn.commit()
        rows = api_keys.page(
            conn,
            community=community,
            after=after,
            limit=limit + 1,
            username=username,
            include_revoked=include_revoked,
        )
    more, rows = len(rows) > limit, rows[:limit]
    following = None
    if more:
        position = {"c": rows[-1]["created"].isoformat(), "k": str(rows[-1]["id"])}
        following = (
            base64.urlsafe_b64encode(json.dumps(position).encode()).decode().rstrip("=")
        )
    response.headers["Cache-Control"] = "no-store"
    return {
        "community": community,
        "items": [api_key_out(r) for r in rows],
        "next": following,
    }


@app.get("/v1/{community}/api-keys/{key_id}")
def get_api_key(community: str, key_id: str, request: Request, response: Response):
    """One of the community's keys, with its value (admin only)."""
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        row = api_keys.row(conn, community, api_key_id(key_id))
        if row is None:
            refuse(404, f"no API key '{key_id}' in {community}")
        response.headers["Cache-Control"] = "no-store"
        return api_key_out(row)


@app.delete("/v1/{community}/api-keys/{key_id}")
def revoke_api_key(community: str, key_id: str, request: Request):
    """Revoke one of the community's keys (admin only): it stops authenticating at once, its
    value is erased, and its row stays as the record of who held it."""
    with db.connection() as conn:
        community = community_of(conn, community)
        admin = require_admin(conn, request, community)
        row = api_keys.revoke(conn, community, api_key_id(key_id), admin)
        if row is None:
            refuse(404, f"no API key '{key_id}' in {community}")
        conn.commit()
        return api_key_out(row)


class RebindIn(BaseModel):
    hours: int | None = Field(default=None, ge=1, le=24 * 366)


@app.post("/v1/{community}/owners/{handle}/rebind")
def rebind(community: str, handle: str, request: Request, body: RebindIn | None = None):
    """A lost or compromised key (admin only): retire the member's keys and return a fresh
    invite, so they register a new key under the same handle. Attribution is untouched."""
    handle = roster_handle(handle)
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        if not records.on_roster(conn, community, handle):
            refuse(404, f"'{handle}' is not on the {community} roster")
        retired = records.retire_keys(conn, community, handle)
        hours = body.hours if body else None
        return {"retired_keys": retired, **mint_invite(conn, community, handle, hours)}


class SuspectIn(BaseModel):
    at: datetime


@app.put("/v1/{community}/owners/{handle}/suspect-after")
def suspect_after(community: str, handle: str, body: SuspectIn, request: Request):
    """Flag everything the handle writes after an instant (admin only); nothing is deleted."""
    if body.at.tzinfo is None:
        refuse(400, "the instant needs a timezone, e.g. 2026-10-01T12:00:00+00:00")
    handle = roster_handle(handle)
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        if not records.set_suspect_after(conn, community, handle, body.at):
            refuse(404, f"no owner '{handle}' in {community}")
    return {
        "community": community,
        "handle": handle,
        "suspect_after": iso(body.at),
    }


# ── export and import (R-J6) ────────────────────────────────────────────────────────────────
def pipe() -> tuple:
    reader, writer = os.pipe()
    return os.fdopen(reader, "rb"), os.fdopen(writer, "wb")


def close_quietly(stream):
    try:
        stream.close()
    except OSError:
        pass  # the other end is gone already


@app.get("/v1/{community}/export")
def export(community: str, request: Request):
    """The community as a tar stream (admin only): one consistent snapshot of its rows, then
    every stored payload. Written by a thread into a pipe, so no copy lands on disk."""
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
    reader, writer = pipe()

    def produce():
        try:
            archive.export(community, writer)
        except BrokenPipeError:
            pass  # the client went away; the snapshot's transaction just ends
        except Exception:
            log.exception("export of %s failed", community)
        finally:
            close_quietly(writer)

    threading.Thread(target=produce, name="export", daemon=True).start()

    def chunks():
        try:
            while chunk := reader.read(1 << 16):
                yield chunk
        finally:
            reader.close()

    return StreamingResponse(
        iterate_in_threadpool(chunks()),
        media_type="application/x-tar",
        headers={"Content-Disposition": f'attachment; filename="{community}.tar"'},
    )


@app.post("/v1/communities/import", status_code=201)
async def import_community(request: Request):
    """Create a community from an export (admin only), in one transaction (R-J6): refused if
    the community exists here (there is no merge), and nothing is written on any failure. What
    the exported admin owned becomes this server's admin's."""

    def authorize():
        with db.connection() as conn:
            require_admin(conn, request)

    await run_in_threadpool(authorize)
    reader, writer = pipe()

    def consume():
        try:
            return archive.import_(reader)
        finally:
            reader.close()  # an import that stops early ends the upload below

    imported = asyncio.create_task(asyncio.to_thread(consume))
    try:
        async for chunk in request.stream():
            try:
                await run_in_threadpool(writer.write, chunk)
            except BrokenPipeError:
                break
    finally:
        await run_in_threadpool(close_quietly, writer)
    try:
        return await imported
    except Refused as e:
        refuse(409, str(e))
    except Malformed as e:
        refuse(400, str(e))


# ── files and versions ──────────────────────────────────────────────────────────────────────
def wire(call, *args):
    try:
        return call(*args)
    except WireError as e:
        refuse(e.status, str(e))


class Upload:
    """One streamed, verified, still-pending payload. It becomes durable only inside the
    commit transaction that references it (R-A6); otherwise discard() removes it, bytes first
    and row second, leaving the row for the janitor if S3 refuses."""

    def __init__(self, pid, sha: str, size: int):
        self.pid, self.sha, self.size = pid, sha, size

    def discard(self):
        cleanup.discard_pending(self.pid)


def quota_for(conn, handle: str) -> int:
    """The per-owner quota; the server admin's own writes are exempt (R-H2)."""
    return 0 if records.is_admin(conn, handle) else settings.quota()


async def stream_upload(
    request: Request, community: str, owner: str, quota: int, file_id=None
) -> Upload:
    """Stream the body into S3 as a pending payload, hashing it in flight. Only a body that
    matches its declared Repr-Digest (and size, when declared) is returned; anything else is
    removed before raising."""
    declared = wire(parse_digest, request.headers.get("repr-digest"))
    size_header = request.headers.get("x-data-size") or request.headers.get(
        "content-length"
    )
    declared_size = int(size_header) if size_header and size_header.isdigit() else None

    def begin():
        with db.connection() as conn:
            # an early, advisory check; the binding one runs in the commit transaction
            if quota and declared_size is not None:
                if records.usage(conn, community, owner) + declared_size > quota:
                    refuse(413, "this upload would exceed the owner's quota")
            return records.begin_payload(conn, community, owner)

    pid, key = await run_in_threadpool(begin)

    def started(upload_id):
        with db.connection() as conn:
            records.note_upload(conn, pid, upload_id)

    def heartbeat():
        with db.connection() as conn:
            records.touch_pending(conn, pid, file_id)

    writer = MultipartWriter(store, key, on_upload_started=started)
    upload = Upload(pid, "", 0)
    last_beat = time.monotonic()
    try:
        async for chunk in request.stream():
            if chunk:
                await run_in_threadpool(writer.write, chunk)
            if time.monotonic() - last_beat >= settings.heartbeat:
                await run_in_threadpool(heartbeat)
                last_beat = time.monotonic()
        if writer.hexdigest() != declared or (
            declared_size is not None and writer.size != declared_size
        ):
            refuse(400, "the body does not match its declared Repr-Digest or size")
        await run_in_threadpool(writer.finish)
    except BaseException:
        await run_in_threadpool(writer.abort)
        await run_in_threadpool(upload.discard)
        raise
    upload.sha, upload.size = writer.hexdigest(), writer.size
    return upload


def written(conn, community, file_id, n, status_code=201) -> JSONResponse:
    info = records.stat(conn, records.version(conn, community, file_id, n))
    return JSONResponse(info, status_code=status_code, headers={"ETag": etag(n)})


def commit_version(
    conn, community, file_id, upload, head, metadata, content_type, handle, kid
) -> tuple:
    """The atomic step (R-A6): quota under the owner's lock, the payload turned ready (or an
    identical one reused), and the version inserted, all in the caller's transaction.
    -> (version number, s3 key to delete after commit or None)."""
    if upload is None:
        payload, duplicate = head["payload_id"], None
    else:
        payload, duplicate = records.commit_payload(
            conn,
            upload.pid,
            community,
            upload.sha,
            upload.size,
            handle,
            quota_for(conn, handle),
        )
    n = records.add_version(conn, file_id, payload, metadata, content_type, handle, kid)
    return n, duplicate


def finish_after_commit(duplicate_pid):
    """Identical content was already stored: remove this upload's own copy, bytes first."""
    if duplicate_pid:
        cleanup.discard_pending(duplicate_pid)


def mapped(error: Exception):
    """Domain errors raised inside a commit transaction -> HTTP errors."""
    if isinstance(error, QuotaExceeded):
        refuse(413, str(error))
    if isinstance(error, PreconditionFailed):
        refuse(412, str(error))
    raise error


@app.put("/v1/{community}/collections/{collection}/files/{name}", status_code=201)
async def put_file(community: str, collection: str, name: str, request: Request):
    """Create a file; its content and metadata become version 1. The name is reserved before
    any bytes move, and the file turns live only in the transaction that inserts v1."""
    if not valid_file_name(name):
        refuse(400, "a file name is one path segment of 1-255 characters")
    metadata = wire(parse_metadata, request.headers.get("x-data-metadata")) or {}
    content_type = request.headers.get("content-type", "application/octet-stream")

    def reserve():
        with db.connection() as conn:
            found = community_of(conn, community)
            handle, kid = owner_of(conn, request, found)
            if not records.collection_exists(conn, found, collection):
                refuse(404, f"no collection {found}/{collection}")
            if not records.can_create(conn, handle, found, collection):
                refuse(403, f"no write access to {found}/{collection}")
            return (
                found,
                handle,
                kid,
                quota_for(conn, handle),
                records.reserve_file(conn, found, collection, name, handle),
            )

    community, handle, kid, quota, file_id = await run_in_threadpool(reserve)

    def release():
        with db.connection() as conn:
            records.release_reservation(conn, file_id)

    try:
        upload = await stream_upload(request, community, handle, quota, file_id)
    except BaseException:
        await run_in_threadpool(release)
        raise

    def commit():
        with db.connection() as conn:
            try:
                records.claim_reservation(conn, file_id, handle)
                n, duplicate = commit_version(
                    conn,
                    community,
                    file_id,
                    upload,
                    None,
                    metadata,
                    content_type,
                    handle,
                    kid,
                )
            except (QuotaExceeded, PreconditionFailed) as e:
                conn.rollback()
                mapped(e)
            conn.commit()
            response = written(conn, community, file_id, n)
        finish_after_commit(duplicate)
        return response

    try:
        return await run_in_threadpool(commit)
    except BaseException:
        await run_in_threadpool(upload.discard)
        await run_in_threadpool(release)
        raise


@app.post("/v1/{community}/files/{file_id}/versions", status_code=201)
async def put_version(community: str, file_id: uuid.UUID, request: Request):
    """Append a version: new content, new metadata, or both (R-A2). A metadata-only version
    reuses the payload; a content-only version keeps the file's metadata. With If-Match the
    write applies only if the head is still the version the client built on (R-A6)."""
    metadata = wire(parse_metadata, request.headers.get("x-data-metadata"))
    expected = wire(parse_if_match, request.headers.get("if-match"))
    metadata_only = request.headers.get("x-data-metadata-only") == "1"
    if metadata_only and metadata is None:
        refuse(400, "a metadata-only version needs X-Data-Metadata")

    def check():
        with db.connection() as conn:
            found = community_of(conn, community)
            handle, kid = owner_of(conn, request, found)
            row = records.file_row(conn, found, file_id)
            if not records.can_modify(conn, handle, row):
                refuse(403, "only the file's creator or the admin may add versions")
            head = records.latest_version(conn, file_id)
            if expected is not None and head["n"] != expected:
                # fail fast, before any bytes are streamed; re-checked under the lock below
                refuse(412, f"the file is at v{head['n']}, not v{expected}")
            return found, handle, kid, quota_for(conn, handle)

    community, handle, kid, quota = await run_in_threadpool(check)
    upload = (
        None
        if metadata_only
        else await stream_upload(request, community, handle, quota)
    )

    def commit():
        with db.connection() as conn:
            try:
                head = records.lock_head(conn, file_id, expected)
                n, duplicate = commit_version(
                    conn,
                    community,
                    file_id,
                    upload,
                    head,
                    head["metadata"] if metadata is None else metadata,
                    head["content_type"]
                    if upload is None
                    else request.headers.get("content-type", head["content_type"]),
                    handle,
                    kid,
                )
            except (QuotaExceeded, PreconditionFailed) as e:
                conn.rollback()
                mapped(e)
            conn.commit()
            response = written(conn, community, file_id, n)
        finish_after_commit(duplicate)
        return response

    try:
        return await run_in_threadpool(commit)
    except BaseException:
        if upload is not None:
            await run_in_threadpool(upload.discard)
        raise


@app.delete("/v1/{community}/files/{file_id}")
def delete_file(
    community: str, file_id: uuid.UUID, request: Request, reason: str | None = None
):
    """Soft delete (R-B1): append a tombstone that keeps serving the previous content."""
    expected = wire(parse_if_match, request.headers.get("if-match"))
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, kid = owner_of(conn, request, community)
        row = records.file_row(conn, community, file_id)
        if not records.can_modify(conn, handle, row):
            refuse(403, "only the file's creator or the admin may delete it")
        try:
            n = records.tombstone(conn, file_id, handle, kid, reason, expected)
        except PreconditionFailed as e:
            conn.rollback()
            mapped(e)
        conn.commit()
        return written(conn, community, file_id, n, status_code=200)


@app.post("/v1/{community}/files/{file_id}/v/{n}/purge")
def purge(community: str, file_id: uuid.UUID, n: int, request: Request):
    """Free one version's content (admin only; R-B3). The version stays addressable and
    answers 410 with its metadata; the bytes go only when no other live version shares them.
    When S3 refuses, the payload stays purging and the janitor finishes the job."""
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        records.version(
            conn, community, file_id, n
        )  # 404 unless it is this community's
        pid = records.purge(conn, file_id, n)
    freed = pid is not None and cleanup.finish_purge(pid)
    result = {"purged": f"symposium-data:{file_id}@v{n}", "bytes_freed": freed}
    if pid is not None and not freed:
        result["note"] = "the bytes could not be removed yet; the janitor will retry"
    return result


def reader_of(conn, request: Request, community: str) -> tuple[str | None, dict | None]:
    """Who is reading: (handle, None) for a signed-in owner, (None, key) for a read key of
    this community, (None, None) for an anonymous request (enough only for a public
    collection)."""
    credential = bearer(request)
    if credential is None:
        return None, None
    if credential.startswith(READ_KEY_PREFIX):
        key = records.use_key(conn, community, secrets.digest(credential))
        if key is None:
            refuse(401, "the read key is not valid, has expired, or was revoked")
        return None, key
    return owner_of(conn, request, community)[0], None


def readable(request: Request, community: str, file_id, ref):
    """-> (community, stat, s3 key) of a version the caller may read."""
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, key = reader_of(conn, request, community)
        row = records.version(conn, community, file_id, ref)
        if not records.can_read(conn, handle, row, key):
            if handle is None and key is None:
                refuse(401, "sign in, or use a read key, to read this file")
            refuse(403, "no read access to this file")
        return community, records.stat(conn, row), row["s3_key"]


@app.get("/v1/{community}/files/{file_id}/v/{ref}/stat")
def stat(community: str, file_id: uuid.UUID, ref: str, request: Request):
    info = readable(request, community, file_id, ref)[1]
    return JSONResponse(info, headers={"ETag": etag(info["version"])})


@app.get("/v1/{community}/files/{file_id}/versions")
def versions(community: str, file_id: uuid.UUID, request: Request):
    community = readable(request, community, file_id, 1)[0]
    with db.connection() as conn:
        return {"versions": records.versions(conn, community, file_id)}


@app.get("/v1/{community}/files/{file_id}/v/{ref}")
async def content(community: str, file_id: uuid.UUID, ref: str, request: Request):
    """Stream one version (R-E5): the service authorizes and streams every byte itself."""
    community, info, key = await run_in_threadpool(
        readable, request, community, file_id, ref
    )
    if info["purged"]:
        return JSONResponse(
            {"detail": "this version's content was purged", **info}, status_code=410
        )
    byte_range = request.headers.get("range")
    obj = await run_in_threadpool(store.open_read, key, byte_range)
    base = f"/v1/{community}/files/{file_id}/v"
    links = [f'<{base}/{info["latest"]}>; rel="latest"']
    if info["prev"]:
        links.append(f'<{base}/{info["prev"]}>; rel="prev"')
    if info["next"]:
        links.append(f'<{base}/{info["next"]}>; rel="next"')
    headers = {
        "Repr-Digest": digest_header(info["sha256"]),
        "X-Data-Citation": info["citation"],
        "X-Data-Version": str(info["version"]),
        "X-Data-Deleted": str(info["deleted"]).lower(),
        "X-Data-File-Deleted": str(info["file_deleted"]).lower(),
        "Link": ", ".join(links),
        "ETag": etag(info["version"]),
        "Accept-Ranges": "bytes",
        "Content-Length": str(obj["ContentLength"]),
    }
    status_code = 200
    if byte_range and obj.get("ContentRange"):
        headers["Content-Range"] = obj["ContentRange"]
        status_code = 206
    return StreamingResponse(
        iterate_in_threadpool(obj["Body"].iter_chunks(1024 * 1024)),
        status_code=status_code,
        media_type=info["content_type"],
        headers=headers,
    )


# ── collections and sharing ─────────────────────────────────────────────────────────────────
class CollectionIn(BaseModel):
    name: str = Field(pattern=NAME)


class PublicIn(BaseModel):
    public: bool


class GrantIn(BaseModel):
    handle: str = Field(pattern=NAME)
    perm: str = Field(pattern=r"^(read|write)$")
    granted: bool = True


class KeyIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    file_id: uuid.UUID | None = None
    expires_hours: int | None = Field(default=None, ge=1, le=24 * 366)


def key_view(row) -> dict:
    """A read key as it may be shown: never its secret."""
    return {
        "id": str(row["id"]),
        "label": row["label"],
        "community": row["community"],
        "collection": row["collection"],
        "file_id": str(row["file_id"]) if row["file_id"] else None,
        "created_by": row["created_by"],
        "created": iso(row["created"]),
        "expires": iso(row["expires"]),
        "revoked": iso(row["revoked"]),
        "uses": row["uses"],
        "last_used": iso(row["last_used"]),
    }


def require_manager(conn, request, community, collection) -> str:
    handle, _ = owner_of(conn, request, community)
    records.collection_row(conn, community, collection)
    if not records.can_manage(conn, handle, community, collection):
        refuse(403, "only the collection's owner or the admin may do this")
    return handle


@app.post("/v1/{community}/collections", status_code=201)
def create_collection(community: str, body: CollectionIn, request: Request):
    """A roster member, or the admin, creates a collection and becomes its owner (R-D3)."""
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, _ = owner_of(conn, request, community)
        if not (
            records.is_admin(conn, handle) or records.on_roster(conn, community, handle)
        ):
            refuse(403, f"'{handle}' is not on the {community} roster")
        records.create_collection(conn, community, body.name, handle)
        return {
            "community": community,
            "name": body.name,
            "owner": handle,
            "public": False,
        }


@app.put("/v1/{community}/collections/{collection}/public")
def set_public(community: str, collection: str, body: PublicIn, request: Request):
    with db.connection() as conn:
        community = community_of(conn, community)
        require_manager(conn, request, community, collection)
        records.set_public(conn, community, collection, body.public)
        return {"community": community, "collection": collection, "public": body.public}


@app.put("/v1/{community}/collections/{collection}/grants")
def set_grant(community: str, collection: str, body: GrantIn, request: Request):
    """The owner grants (or withdraws) read or write to a roster member (R-D3)."""
    with db.connection() as conn:
        community = community_of(conn, community)
        require_manager(conn, request, community, collection)
        records.set_grant(
            conn, community, collection, body.handle, body.perm, body.granted
        )
        return {
            "community": community,
            "collection": collection,
            "handle": body.handle,
            "perm": body.perm,
            "granted": body.granted,
        }


@app.post("/v1/{community}/collections/{collection}/keys", status_code=201)
def mint_key(community: str, collection: str, body: KeyIn, request: Request):
    """A read key for non-members (R-E2): for the whole collection by its owner, or for one
    file by the collection's owner or that file's creator. The secret is shown only here."""
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, _ = owner_of(conn, request, community)
        records.collection_row(conn, community, collection)
        manager = records.can_manage(conn, handle, community, collection)
        if body.file_id is None:
            if not manager:
                refuse(
                    403, "only the collection's owner or the admin may key a collection"
                )
        else:
            row = records.file_row(conn, community, body.file_id)
            if row["collection"] != collection:
                refuse(404, f"no such file in {community}/{collection}")
            creator = records.first_writer(conn, body.file_id) == handle and (
                records.on_roster(conn, community, handle)
            )
            if not (manager or creator):
                refuse(
                    403, "only the file's creator or the collection's owner may key it"
                )
        secret = secrets.new(READ_KEY_PREFIX)
        row = records.mint_key(
            conn,
            community,
            collection,
            body.file_id,
            body.label,
            handle,
            body.expires_hours,
            secrets.digest(secret),
        )
        return {**key_view(row), "key": secret}


@app.get("/v1/{community}/collections/{collection}/keys")
def list_keys(community: str, collection: str, request: Request):
    """The owner and the admin see every key of the collection; others only the keys they
    minted. Secrets are never listed."""
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, _ = owner_of(conn, request, community)
        records.collection_row(conn, community, collection)
        mine_only = not records.can_manage(conn, handle, community, collection)
        rows = records.list_keys(
            conn, community, collection, created_by=handle if mine_only else None
        )
        return {"keys": [key_view(r) for r in rows]}


@app.delete("/v1/{community}/keys/{key_id}")
def revoke_key(community: str, key_id: uuid.UUID, request: Request):
    """Revoke a read key: refused from the very next request on (R-E5)."""
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, _ = owner_of(conn, request, community)
        row = records.key_row(conn, community, key_id)
        if not (
            row["created_by"] == handle
            or records.can_manage(conn, handle, row["community"], row["collection"])
        ):
            refuse(
                403,
                "only the key's minter, the collection's owner or the admin may revoke it",
            )
        records.revoke_key(conn, key_id)
        return key_view(records.key_row(conn, community, key_id))


# ── parity: the change feed, lookups, promote and verify (R-G) ──────────────────────────────
MAX_PAGE = 1000


class QueryIn(BaseModel):
    contains: dict
    since: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=MAX_PAGE)


class PromoteIn(BaseModel):
    collection: str = Field(pattern=NAME)
    name: str | None = None
    metadata: dict | None = None
    stamp_json_pointer: str | None = None


def lister(conn, request: Request, community: str, collection: str):
    """Who may list a collection -> (handle, key); refuses everyone else."""
    handle, key = reader_of(conn, request, community)
    records.collection_row(conn, community, collection)
    if not records.can_read_collection(conn, handle, community, collection, key):
        if handle is None and key is None:
            refuse(401, "sign in, or use a read key, to read this collection")
        refuse(403, f"no read access to {community}/{collection}")
    return handle, key


def page(conn, handle, key, rows, since: int, limit: int) -> dict:
    """One page of a seq-ordered listing. `more` and `next_since` come from the rows scanned,
    not the rows shown, so a reader who sees only some rows still pages to the end and never
    meets a silent cap."""
    return {
        "items": [
            records.stat(conn, r)
            for r in rows
            if records.can_read(conn, handle, r, key)
        ],
        "next_since": rows[-1]["seq"] if rows else since,
        "more": len(rows) == limit,
    }


@app.get("/v1/{community}/collections/{collection}/changes")
def changes(
    community: str,
    collection: str,
    request: Request,
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=MAX_PAGE),
):
    """Every version written into the collection after seq `since`, in seq order (R-G3)."""
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, key = lister(conn, request, community, collection)
        rows = records.changes(conn, community, collection, since, limit)
        return page(conn, handle, key, rows, since, limit)


@app.post("/v1/{community}/collections/{collection}/query")
def query(community: str, collection: str, body: QueryIn, request: Request):
    """Versions whose metadata contains `contains`, paged like changes (R-G6)."""
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, key = lister(conn, request, community, collection)
        rows = records.query(
            conn, community, collection, body.contains, body.since, body.limit
        )
        return page(conn, handle, key, rows, body.since, body.limit)


@app.get("/v1/{community}/collections/{collection}/find")
def find(community: str, collection: str, name: str, request: Request):
    """The file holding a name (R-G1), at its newest version, tombstone or not: a deleted
    file still holds its name."""
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, key = lister(conn, request, community, collection)
        file_id = records.find_name(conn, community, collection, name)
        if file_id is None:
            refuse(404, f"no file named '{name}' in {community}/{collection}")
        row = records.version(
            conn, community, file_id, records.latest_version(conn, file_id)["n"]
        )
        if not records.can_read(conn, handle, row, key):
            refuse(404, f"no file named '{name}' in {community}/{collection}")
        return JSONResponse(records.stat(conn, row), headers={"ETag": etag(row["n"])})


@app.get("/v1/{community}/sha256/{sha}")
def by_hash(community: str, sha: str, request: Request):
    """Every version of this community the caller may read that holds this content (R-F2)."""
    if not valid_sha256(sha):
        refuse(400, "a sha256 is 64 lowercase hex characters")
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, key = reader_of(conn, request, community)
        return {
            "items": [
                records.stat(conn, r)
                for r in records.by_hash(conn, community, sha)
                if records.can_read(conn, handle, r, key)
            ]
        }


@app.post("/v1/{community}/files/{file_id}/v/{n}/promote", status_code=201)
def promote(
    community: str, file_id: uuid.UUID, n: int, body: PromoteIn, request: Request
):
    """Copy one version into a collection as a new file, atomically (R-G4); admin only.

    With `stamp_json_pointer` the content is a JSON document, and the server writes the new
    version's own `created` at that pointer: the clock is the server's, never the caller's.
    The stamped bytes are a pending payload until the one transaction that allocates
    `created`, creates the file and inserts its version (R-A6). They are re-serialized the
    way Symposium serializes canonical JSON: json.dumps defaults. The new version is
    credited to the source version's creator, with no key id."""
    name = body.name
    pointer = body.stamp_json_pointer
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, _ = owner_of(conn, request, community)
        if not records.is_admin(conn, handle):
            refuse(403, "only the admin promotes")
        source = records.version(conn, community, file_id, n)
        records.collection_row(conn, community, body.collection)
        name = name or source["name"]
        if not valid_file_name(name):
            refuse(400, "a file name is one path segment of 1-255 characters")
        if source["purged"]:
            refuse(410, "this version's content was purged")
        if source["deleted"]:
            refuse(409, "a tombstone cannot be promoted")
        if records.find_name(conn, community, body.collection, name):
            refuse(409, f"'{name}' already exists in {community}/{body.collection}")
        document = None
        if pointer is not None:
            raw = store.open_read(source["s3_key"])["Body"].read()
            try:
                document = json.loads(raw)
            except ValueError:
                refuse(422, "only a JSON document can be stamped")
            wire(
                stamp, json.loads(raw), pointer, ""
            )  # refuse a bad pointer before writing
            pid, s3_key = records.begin_payload(conn, community, handle)
    metadata = {**source["metadata"], **(body.metadata or {})}

    def commit():
        duplicate = None
        with db.connection() as conn:
            records.lock_owner(conn, community, handle)
            new = records.create_live_file(conn, community, body.collection, name)
            clock, payload = None, source["payload_id"]
            if document is not None:
                clock = records.allocate(conn, community, body.collection)
                data = json.dumps(stamp(document, pointer, iso(clock[1]))).encode()
                store.put_bytes(s3_key, data)
                try:
                    payload, duplicate = records.commit_payload(
                        conn,
                        pid,
                        community,
                        hashlib.sha256(data).hexdigest(),
                        len(data),
                        handle,
                        quota_for(conn, handle),
                    )
                except QuotaExceeded as e:
                    conn.rollback()
                    mapped(e)
            records.add_version(
                conn,
                new,
                payload,
                metadata,
                source["content_type"],
                # credited to the submitter, like a ported record (R-G4, R-M2); the
                # admin's token only authorizes the promote
                source["created_by"],
                None,
                clock=clock,
            )
            conn.commit()
            response = written(conn, community, new, 1)
        finish_after_commit(duplicate)
        return response

    try:
        return commit()
    except BaseException:
        if document is not None:
            cleanup.discard_pending(pid)
        raise


@app.get("/v1/{community}/verify")
def verify(
    community: str,
    cite: str,
    request: Request,
    before: str | None = None,
    sha256: str | None = None,
):
    """The gate's check of a cited download (R-G9). A version the caller cannot read answers
    exactly like one that never existed, and a citation resolves only inside this community,
    so verify reveals nothing the caller may not read."""
    when = wire(parse_instant, before) if before else None
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, _ = owner_of(conn, request, community)
        cited = parse_citation(cite)
        if cited is None:
            return {
                "ok": False,
                "exists": False,
                "reason": "not a symposium-data citation",
            }
        missing = {"ok": False, "exists": False, "reason": "no such file version"}
        try:
            row = records.version(conn, community, *cited)
        except NotFound:
            return missing
        if not records.can_read(conn, handle, row):
            return missing
        return records.verify(row, when, sha256)


# ── the port (R-M1, see PORT_NDEX.md) ──────────────────────────────────────────────────────────
class PortCredentials(BaseModel):
    """The source's admin account for a port-ndex: a bound pair, held in memory only."""

    username: str
    password: str


class PortIn(BaseModel):
    ndex_url: str = Field(pattern=r"^https?://")  # the source server of a port-ndex
    credentials: PortCredentials
    page_size: int = Field(default=100, ge=1, le=10000)


def port_view(row) -> dict:
    return {
        "id": str(row["id"]),
        "community": row["community"],
        "requested_by": row["requested_by"],
        "source": row["source"],
        "state": row["state"],
        "result": row["result"],
        "started": iso(row["started"]),
        "finished": iso(row["finished"]),
    }


@app.post("/v1/{community}/port-ndex", status_code=202)
def start_port(community: str, body: PortIn, request: Request):
    """Start a port-ndex into this empty community, in the background; one at a time,
    server-wide. Poll GET /v1/{community}/port-ndex/{id} for its outcome."""
    from . import port_ndex  # the port feature, isolated: imported only here

    with db.connection() as conn:
        community = community_of(conn, community)
        admin = require_admin(conn, request, community)
        if records.holds_files(conn, community):
            refuse(
                400, f"community '{community}' holds files; a port-ndex needs it empty"
            )
        source = body.ndex_url.rstrip("/")  # the port-ndex source
        port_id = records.start_port(conn, community, admin, source)
    run = port_ndex.Port(
        db,
        store,
        records,
        cleanup,
        community,
        source,
        body.credentials.username,
        body.credentials.password,
        body.page_size,
        settings.heartbeat,
    ).run
    threading.Thread(target=run, args=(port_id,), name="port-ndex", daemon=True).start()
    with db.connection() as conn:
        return port_view(records.port(conn, community, port_id))


@app.get("/v1/{community}/port-ndex/{port_id}")
def port_status(community: str, port_id: uuid.UUID, request: Request):
    with db.connection() as conn:
        community = community_of(conn, community)
        require_admin(conn, request, community)
        row = records.port(conn, community, port_id)
        if row is None:
            refuse(404, f"no port-ndex {port_id} in {community}")
        return port_view(row)
