"""The hand-written routes of `/v1`: sign-in, users, invites, role assignments, communities,
API keys, collections and files. Every byte is streamed by this service; S3 is never exposed.
The record's routes are generated from the contract and mounted beside these by
`symposium_server`.

Communities are tenants (R-G8): every community-dependent route is under /v1/{community}/...,
with collection-scoped routes under collections/{collection}/ and file routes under files/{id}/.
Sign-in (/v1/auth/...), users, invites, roles, assignments, communities and /v1/status are
server-wide.

Every request presents one API key or none (`access`), and is decided by its caller's
`UserContext`: the operation's grants at the door, then each collection it touches here.

Nobody has a shell on the server (R-D7): every administrative operation is a route, and the root
user's key comes from the key file on the volume (R-D4). Without a usable one the server is
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
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import API_VERSION, access, version
from .access import Caller, authorize, rbac
from .admin_key import AdminKeyFile, AdminMode
from .api_keys import ApiKeys, LabelInUse, Sealer, key_file_from
from .archive import Archive, Malformed, Refused
from .auth import PublicKeys, Secrets
from .errors import ApiError, body_for
from .jobs import Jobs
from .records import (
    Conflict,
    Forbidden,
    Invalid,
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
api_keys = ApiKeys(Sealer(key_file_from(Path(settings.path))))
access.wire(db=db, records=records, keys=api_keys)
jobs = Jobs(settings, db, store, records, api_keys)
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


# FastAPI's generated /docs, /redoc and /openapi.json are off: api/openapi.yaml is the
# contract, served at /v1/openapi.yaml and /v1/openapi.json
app = FastAPI(
    title="Symposium Data",
    version=version(),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
STATUS = "/v1/status"


@app.middleware("http")
async def operational_only(request: Request, call_next):
    """Non-operational mode (R-D4): only /v1/status answers, so a readiness probe sees why;
    the jobs keep running."""
    if not admin_mode.operational and request.url.path != STATUS:
        return JSONResponse(
            body_for(501, f"the server is not operational: {admin_mode.reason}"),
            status_code=501,
        )
    return await call_next(request)


# A request body is at most 8 MiB, except the three routes that stream one: a file's content
# and an import, which quota bounds instead.
BODY_LIMIT = 8 * 1024 * 1024
TOO_LARGE = "the request body is over 8 MiB"
STREAMED = (
    ("PUT", re.compile(r"^/v1/[^/]+/collections/[^/]+/files/[^/]+$")),
    ("POST", re.compile(r"^/v1/[^/]+/files/[^/]+/versions$")),
    ("POST", re.compile(r"^/v1/communities/import$")),
)


class BodyLimit:
    """Refuses a body over BODY_LIMIT with 413: at once when its Content-Length says so, or once
    the bytes read pass it. A body within the limit is read here and handed on whole, so the
    route reads it as it was sent."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or any(
            scope["method"] == method and path.match(scope["path"])
            for method, path in STREAMED
        ):
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length", b"")
        too_large = JSONResponse(body_for(413, TOO_LARGE), status_code=413)
        if length.isdigit() and int(length) > BODY_LIMIT:
            return await too_large(scope, receive, send)
        chunks, size, more = [], 0, True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return  # the client went away before its body arrived
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if size > BODY_LIMIT:
                return await too_large(scope, receive, send)
            more = message.get("more_body", False)
        whole = {"type": "http.request", "body": b"".join(chunks), "more_body": False}
        handed = False

        async def replay():
            nonlocal handed
            if not handed:
                handed = True
                return whole
            return await receive()

        await self.app(scope, replay, send)


app.add_middleware(BodyLimit)

# Browser apps on the configured origins may call the API; outermost, so a preflight is
# answered before anything else runs.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Repr-Digest",
            "If-Match",
            "Range",
            "Last-Event-ID",
            "X-Data-Metadata",
            "X-Data-Metadata-Only",
            "X-Data-Size",
        ],
        expose_headers=[
            "ETag",
            "Link",
            "Location",
            "Repr-Digest",
            "Content-Range",
            "X-Data-Citation",
            "X-Data-Version",
            "X-Data-Deleted",
            "X-Data-File-Deleted",
        ],
    )


# Every refusal answers the one Error body, {detail, code}, whoever raises it.
@app.exception_handler(ApiError)
async def _api_error(_request, error: ApiError):
    return JSONResponse(error.body(), status_code=error.status, headers=error.headers)


def _refusal(status: int):
    async def handler(_request: Request, error):
        return JSONResponse(body_for(status, str(error)), status_code=status)

    return handler


app.add_exception_handler(NotFound, _refusal(404))
app.add_exception_handler(Forbidden, _refusal(403))
app.add_exception_handler(Conflict, _refusal(409))
app.add_exception_handler(Invalid, _refusal(400))


@app.exception_handler(StarletteHTTPException)
async def _http_error(_request: Request, error: StarletteHTTPException):
    return JSONResponse(
        body_for(error.status_code, error.detail),
        status_code=error.status_code,
        headers=getattr(error, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def _unreadable(request: Request, error: RequestValidationError):
    """A request its route cannot read: 400 on a route generated from the contract, as the
    contract states; 422 on a hand-written route."""
    route = request.scope.get("route")
    generated = getattr(route, "operation_id", None) in access.contract_rules()
    status = 400 if generated else 422
    return JSONResponse(body_for(status, error.errors()), status_code=status)


# Callables that add to /v1/status once the server is operational and healthy: the
# composition root registers the record index's position here, so this module never
# imports the API.
status_extensions: list = []


@app.get("/v1/status")
def status(
    caller: Annotated[Caller, Depends(authorize("getStatus"))], response: Response
):
    """Version, mode and health. Answers 503 while PostgreSQL or the S3 store is unavailable,
    so a readiness probe never routes traffic to a server that cannot serve it. In both modes it
    reports the server's id; once operational, the root user's handle and key fingerprint, and
    the server's public URL when one is configured."""
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
        body.update(root=admin_mode.handle, fingerprint=admin_mode.fingerprint)
        if caller.base_url and access.authz.public_url():
            body["public_url"] = access.authz.public_url()
        if postgres_ok:
            for extend in status_extensions:
                body.update(extend())
    else:
        body["reason"] = admin_mode.reason
    return body


# ── identity ────────────────────────────────────────────────────────────────────────────────
class ChallengeIn(BaseModel):
    handle: str = Field(pattern=NAME)
    community: str | None = None  # the user's home; None for a server-level user


class SessionIn(BaseModel):
    handle: str = Field(pattern=NAME)
    community: str | None = None
    nonce: str
    signature: str


class RegisterIn(BaseModel):
    """Joining with an invite: the request names no roles and no home; the invite holds them."""

    model_config = ConfigDict(extra="allow")

    handle: str = Field(pattern=NAME)
    public_jwk: dict
    nonce: str
    signature: str
    invite: str


class RotateIn(BaseModel):
    public_jwk: dict
    nonce: str
    signature: str


class RoleIn(BaseModel):
    role: str
    # community-member and community-observer only: ["*"], [] or collection names
    collections: list[str] | None = None


class InviteIn(BaseModel):
    handle: str = Field(pattern=NAME)
    # the invitee's home; a homed caller's own community when omitted, and for a
    # server-level caller, omitted means a server-level user
    community: str | None = None
    roles: list[RoleIn] = Field(min_length=1)
    hours: int | None = Field(default=None, ge=1, le=24 * 366)


class AssignmentIn(BaseModel):
    """A principal (a user by handle and community, or an API key by id) and one role. On
    DELETE, `collections` names the collections to remove; omitted, the whole assignment."""

    handle: str | None = Field(default=None, pattern=NAME)
    community: str | None = None
    api_key_id: str | None = None
    role: str
    collections: list[str] | None = None


class CommunityIn(BaseModel):
    name: str
    admin: str = Field(pattern=NAME)  # the first community admin's handle


def refuse(status: int, message: str, conn=None):
    """Raise an HTTP error. With `conn`, commit first: work already done (a challenge consumed)
    must stay done even though the request is refused."""
    if conn is not None:
        conn.commit()
    raise HTTPException(status, message)


def community_of(conn, name: str) -> str:
    """The community a path names, as it was created; 404 for a non-slug or unknown name,
    without touching the database for a non-slug (R-G8)."""
    if not valid_community(name):
        refuse(404, f"no community '{name}'")
    found = records.community_name(conn, name)
    if found is None:
        refuse(404, f"no community '{name}'")
    return found


def home_of(conn, name: str | None) -> str | None:
    return None if name is None else community_of(conn, name)


def checked_new_key(conn, home: str | None, handle: str, body) -> tuple[str, dict]:
    """Consume the challenge and check the new key's proof of possession -> (kid, jwk)."""
    if not records.take_challenge(conn, home, handle, body.nonce):
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


def session_out(row, key: str) -> dict:
    return {
        "key": key,
        "expires": iso(row["expires"]),
        "expires_in": settings.session_ttl,
        "kid": row["ed25519_kid"],
    }


def removed_message(home: str | None) -> str:
    return "this account was removed" + (f" from {home}" if home else "")


@app.post("/v1/auth/challenge")
def challenge(
    caller: Annotated[Caller, Depends(authorize("challenge"))], body: ChallengeIn
):
    """A nonce to sign, for signing in or for proving a new key, by any handle: the answer is
    the same whether or not the handle exists."""
    nonce = secrets.new("n_")
    with db.connection() as conn:
        home = home_of(conn, body.community)
        records.add_challenge(conn, home, body.handle, nonce)
    return {"nonce": nonce, "expires_in": 300}


@app.post("/v1/auth/token")
def create_session(
    caller: Annotated[Caller, Depends(authorize("createSession"))],
    body: SessionIn,
    response: Response,
):
    """A session key: the challenge signed with the user's private key file. It acts as that
    user, with the user's roles."""
    with db.connection() as conn:
        home = home_of(conn, body.community)
        if not records.take_challenge(conn, home, body.handle, body.nonce):
            refuse(401, "the challenge is unknown, spent or expired", conn)
        user = records.user_by_handle(conn, home, body.handle)
        if user is None:
            refuse(
                401, "the signature does not match an active key of this handle", conn
            )
        if user["removed"] is not None:
            refuse(401, removed_message(home), conn)
        for key in records.active_keys(conn, user["id"]):
            if keys.verify(key["jwk"], body.nonce.encode(), body.signature):
                row, session = api_keys.create_session(
                    conn,
                    user_id=user["id"],
                    community=home,
                    handle=user["handle"],
                    ed25519_kid=key["kid"],
                    ttl_seconds=settings.session_ttl,
                )
                response.headers["Cache-Control"] = "no-store"
                return session_out(row, session)
        refuse(401, "the signature does not match an active key of this handle", conn)


@app.post("/v1/users", status_code=201)
def register(
    caller: Annotated[Caller, Depends(authorize("register"))], body: RegisterIn
):
    """Join with an invite: register a key generated on the invitee's machine (R-D1, R-D5).
    The invite, held by the server, says the home and the roles; the request names neither."""
    if body.model_extra:
        refuse(
            400,
            "joining takes the invite, the handle and the key; the invite holds the rest",
        )
    digest = secrets.digest(body.invite)
    with db.connection() as conn:
        invite = records.pending_invite(conn, digest, body.handle)
        if invite is None:
            refuse(403, "a valid, unused invite for this handle is required")
        home = invite["home"]
        kid, jwk = checked_new_key(conn, home, body.handle, body)
        if records.take_invite(conn, digest, body.handle) is None:
            refuse(403, "a valid, unused invite for this handle is required", conn)
        if invite["user_id"] is not None:
            user = records.user(conn, invite["user_id"])
            if user is None or user["removed"] is not None:
                refuse(409, f"handle '{body.handle}' belongs to a removed member")
            if records.active_keys(conn, user["id"]):
                refuse(409, f"'{body.handle}' is already registered")
        else:
            try:
                user = records.create_user(conn, body.handle, home)
            except Conflict as e:
                conn.rollback()
                refuse(409, str(e))
        records.add_key(conn, user["id"], kid, jwk)
        for entry in invite["roles"]:
            records.assign(
                conn,
                entry["role"],
                entry.get("collections"),
                invite["created_by"],
                user_id=user["id"],
            )
        return {
            "handle": body.handle,
            "community": home,
            "kid": kid,
            "roles": records.role_list(conn, user_id=user["id"]),
        }


@app.post("/v1/users/me/keys", status_code=201)
def rotate(caller: Annotated[Caller, Depends(authorize("rotateKey"))], body: RotateIn):
    """Replace the signed-in user's key, proven by the new key; the old key retires (versions
    name it) and the sessions it obtained end."""
    with db.connection() as conn:
        kid, jwk = checked_new_key(conn, caller.community, caller.handle, body)
        if records.key_on_record(conn, kid):
            refuse(409, "that key is already on record", conn)
        records.add_key(conn, caller.user_id, kid, jwk)
        return {"handle": caller.handle, "kid": kid}


def user_out(conn, row) -> dict:
    return {
        "id": str(row["id"]),
        "handle": row["handle"],
        "community": row["home"],
        "registered": row["registered"],
        "removed": iso(row["removed"]),
        "removed_by": row["removed_by"],
        "suspect_after": iso(row["suspect_after"]),
        "roles": records.role_list(conn, user_id=row["id"]),
    }


def target_home(conn, caller: Caller, community: str | None) -> str | None:
    """The home a request names: its `community`, or a homed caller's own."""
    if community is None:
        return caller.community
    return community_of(conn, community)


def require_user_admin(caller: Caller, home: str | None):
    """`delegate` for server-level users, `members` in their community otherwise."""
    if home is None:
        if not caller.allows(rbac.DELEGATE, None):
            refuse(403, "only the root administrator manages server-level users")
    elif not caller.allows(rbac.MEMBERS, home):
        refuse(403, f"this needs the members grant in {home}")


def user_row(conn, user_id: str):
    try:
        found = records.user(conn, uuid.UUID(user_id))
    except ValueError:
        found = None
    if found is None:
        refuse(404, f"no user '{user_id}'")
    return found


@app.get("/v1/users")
def list_users(
    caller: Annotated[Caller, Depends(authorize("listUsers"))],
    community: str | None = None,
):
    """A community's users (or, with no community, the server-level users), removed ones
    included and marked, each with its roles."""
    with db.connection() as conn:
        home = target_home(conn, caller, community)
        require_user_admin(caller, home)
        return {
            "community": home,
            "users": [user_out(conn, r) for r in records.users(conn, home)],
        }


@app.delete("/v1/users/{user_id}")
def remove_user(
    caller: Annotated[Caller, Depends(authorize("removeUser"))],
    user_id: str,
):
    """Remove a user. It stays as a tombstone: its handle is never used again, and everything
    it published keeps its name. Its roles end, its keys retire, and its sessions and every
    API key it issued are deleted."""
    with db.connection() as conn:
        user = user_row(conn, user_id)
        require_user_admin(caller, user["home"])
        if (
            records.current_value(conn, rbac.SERVER_ROOT, user_id=user["id"])
            is not False
        ):
            refuse(
                409,
                "the root administrator is bound by the key file and not removed here",
            )
        try:
            removed = records.remove_user(conn, user["id"], caller.handle)
        except Conflict as e:
            conn.rollback()
            refuse(409, str(e))
        if not removed:
            refuse(409, f"'{user['handle']}' was already removed")
        return user_out(conn, records.user(conn, user["id"]))


class RebindIn(BaseModel):
    hours: int | None = Field(default=None, ge=1, le=24 * 366)


@app.post("/v1/users/{user_id}/rebind", status_code=201)
def rebind(
    caller: Annotated[Caller, Depends(authorize("rebindUser"))],
    user_id: str,
    body: RebindIn | None = None,
):
    """A lost or compromised key: retire the user's keys, end its sessions, and return a fresh
    invite that registers a new key for the same user, with its roles as they are."""
    with db.connection() as conn:
        user = user_row(conn, user_id)
        require_user_admin(caller, user["home"])
        if user["removed"] is not None:
            refuse(409, f"'{user['handle']}' was removed")
        retired = records.retire_keys(conn, user["id"])
        issued = mint_invite(
            conn,
            handle=user["handle"],
            home=user["home"],
            roles=[],
            by=caller.handle,
            hours=body.hours if body else None,
            url=caller.base_url,
            user_id=user["id"],
        )
        return {"retired_keys": retired, **issued}


class SuspectIn(BaseModel):
    at: datetime


@app.put("/v1/users/{user_id}/suspect-after")
def suspect_after(
    caller: Annotated[Caller, Depends(authorize("setSuspectAfter"))],
    user_id: str,
    body: SuspectIn,
):
    """Flag everything the user writes after an instant; nothing is deleted."""
    if body.at.tzinfo is None:
        refuse(400, "the instant needs a timezone, e.g. 2026-10-01T12:00:00+00:00")
    with db.connection() as conn:
        user = user_row(conn, user_id)
        require_user_admin(caller, user["home"])
        if not records.set_suspect_after(conn, user["id"], body.at):
            refuse(409, f"'{user['handle']}' was removed")
        return user_out(conn, records.user(conn, user["id"]))


# ── roles, invites and assignments ──────────────────────────────────────────────────────────
@app.get("/v1/roles")
def roles(caller: Annotated[Caller, Depends(authorize("listRoles"))]):
    """The six roles and what each grants: the registry, read-only."""
    return {
        "roles": [
            {
                "role": r.id,
                "assignable_to": sorted(r.assignable_to),
                "takes_collections": r.takes_collections,
                "keys_may_carry": r.key_assignable,
                "assignable": r.assignable,
                "grants": {
                    g: (
                        "assignment"
                        if v is rbac.VALUE
                        else None
                        if v is None
                        else list(v)
                    )
                    for g, v in r.grants.items()
                },
            }
            for r in rbac.ROLES.values()
        ]
    }


def refs_for(conn, community: str | None, names) -> dict:
    """The CollectionRef of each named collection; 404 for one that does not exist."""
    if community is None:
        return {}
    return {
        name: records.collection_ref(conn, community, name)
        for name in rbac.names_in(None if names is None else tuple(names))
    }


def checked_value(role_id: str, collections) -> tuple | None:
    try:
        return rbac.collection_value(role_id, collections)
    except rbac.AssignmentError as e:
        refuse(400, str(e))


def mint_invite(conn, *, handle, home, roles, by, hours, url, user_id=None) -> dict:
    invite = secrets.new("sdi_")
    hours = settings.invite_hours if hours is None else hours
    expires = records.add_invite(
        conn,
        digest=secrets.digest(invite),
        secret=invite,
        handle=handle,
        home=home,
        roles=roles,
        by=by,
        hours=hours,
        user_id=user_id,
    )
    return invite_out(handle, home, roles, invite, expires, url)


def invite_out(handle, home, roles, invite, expires, url) -> dict:
    return {
        "handle": handle,
        "community": home,
        "roles": roles,
        "invite": invite,
        "expires": iso(expires),
        "data-server-url": url,
    }


@app.post("/v1/invites", status_code=201)
def create_invite(
    caller: Annotated[Caller, Depends(authorize("createInvite"))],
    body: InviteIn,
):
    """A single-use invite for a new user, returned once. It carries the user's home and roles,
    which the server keeps and applies when the invite is redeemed; the inviter needs the
    authority to assign every one of them. Any earlier pending invite for the handle is
    revoked."""
    with db.connection() as conn:
        home = target_home(conn, caller, body.community)
        if caller.community is not None and home != caller.community:
            refuse(403, f"this key belongs to {caller.community}")
        kind = rbac.SERVER_USER if home is None else rbac.HOMED_USER
        roles_ = []
        for entry in body.roles:
            value = checked_value(entry.role, entry.collections)
            refs = refs_for(conn, home, value)
            if not rbac.may_assign(caller.context, entry.role, value, kind, home, refs):
                refuse(
                    403,
                    f"assigning '{entry.role}' here is not within this caller's grants",
                )
            roles_.append(
                {
                    "role": entry.role,
                    "collections": None if value is None else list(value),
                }
            )
        # a user without a key (a ported author) claims its handle with this invite
        existing = records.user_by_handle(conn, home, body.handle)
        if (
            existing is not None
            and existing["removed"] is None
            and not existing["registered"]
        ):
            claimed = existing["id"]
        else:
            claimed = None
            try:
                records.check_new_handle(conn, body.handle, home)
            except Conflict as e:
                refuse(409, str(e))
        return mint_invite(
            conn,
            handle=body.handle,
            home=home,
            roles=roles_,
            by=caller.handle,
            hours=body.hours,
            url=caller.base_url,
            user_id=claimed,
        )


@app.get("/v1/invites")
def list_invites(
    caller: Annotated[Caller, Depends(authorize("listInvites"))],
    community: str | None = None,
):
    """The pending invites of a community (or of server-level users), with their secrets, so
    they can be handed over again. Used, expired and revoked invites are never listed."""
    with db.connection() as conn:
        home = target_home(conn, caller, community)
        require_user_admin(caller, home)
        return {
            "community": home,
            "invites": [
                invite_out(
                    r["handle"],
                    r["home"],
                    r["roles"],
                    r["secret"],
                    r["expires"],
                    caller.base_url,
                )
                for r in records.pending_invites(conn, home)
            ],
        }


def assignee(conn, caller: Caller, body: AssignmentIn) -> dict:
    """The principal an assignment request names: kind, community, and its user or key."""
    if (body.handle is None) == (body.api_key_id is None):
        refuse(400, "name either a user (handle) or an API key (api_key_id)")
    if body.handle is not None:
        home = target_home(conn, caller, body.community)
        user = records.user_by_handle(conn, home, body.handle)
        if user is None:
            refuse(404, f"no user '{body.handle}'")
        if user["removed"] is not None:
            refuse(409, f"'{body.handle}' was removed")
        return {
            "kind": rbac.SERVER_USER if home is None else rbac.HOMED_USER,
            "community": home,
            "user_id": user["id"],
            "api_key_id": None,
        }
    key = conn.execute(
        "SELECT * FROM api_keys WHERE id = %s AND kind = 'issued'",
        (api_key_id(body.api_key_id),),
    ).fetchone()
    if key is None:
        refuse(404, f"no API key '{body.api_key_id}'")
    if not (
        (
            key["created_by"] == caller.handle
            and caller.community in (None, key["community"])
        )
        or caller.allows(rbac.MEMBERS, key["community"])
    ):
        refuse(403, "only the key's issuer, or a members holder, changes a key")
    return {
        "kind": rbac.MEMBER_KEY if key["user_id"] is not None else rbac.NON_MEMBER_KEY,
        "community": key["community"],
        "user_id": None,
        "api_key_id": key["id"],
        "key": key,
    }


def issuer_context(conn, key) -> rbac.UserContext:
    """The context of the user who issued `key`: what the key may never exceed."""
    issuer = records.user_by_handle(conn, key["community"], key["created_by"])
    if issuer is None:
        issuer = records.user_by_handle(conn, None, key["created_by"])
    if issuer is None:
        refuse(409, "the key's issuer is gone")
    return records.context_for(
        conn,
        principal_id=issuer["id"],
        principal_name=issuer["handle"],
        community=issuer["home"],
        via_session=True,
        user_id=issuer["id"],
    )


def may_change(conn, caller: Caller, who: dict, role_id: str, value) -> bool:
    """Whether `caller` may assign `role_id` with `value` (or remove `value`'s names) on `who`."""
    community = who["community"]
    refs = refs_for(conn, community, value)
    if who["kind"] == rbac.MEMBER_KEY:
        return rbac.may_carry(
            issuer_context(conn, who["key"]), role_id, value, True, community, refs
        )
    allowed = rbac.may_assign(
        caller.context, role_id, value, who["kind"], community, refs
    )
    if allowed and who["kind"] == rbac.NON_MEMBER_KEY:
        allowed = rbac.may_carry(
            issuer_context(conn, who["key"]), role_id, value, False, community, refs
        )
    return allowed


@app.get("/v1/assignments")
def list_assignments(
    caller: Annotated[Caller, Depends(authorize("listAssignments"))],
    handle: str | None = None,
    community: str | None = None,
    api_key_id: str | None = None,
):
    """A principal's live roles: one's own, or another's for a members (or delegate) holder,
    or a key's for its issuer."""
    with db.connection() as conn:
        if handle is None and api_key_id is None:
            return {"roles": records.role_list(conn, user_id=caller.user_id)}
        body = AssignmentIn(
            handle=handle,
            community=community,
            api_key_id=api_key_id,
            role=rbac.COMMUNITY_MEMBER,
        )
        who = assignee(conn, caller, body)
        if who["user_id"] is not None and who["user_id"] != caller.user_id:
            require_user_admin(caller, who["community"])
        return {
            "roles": records.role_list(
                conn, user_id=who["user_id"], api_key_id=who["api_key_id"]
            )
        }


@app.post("/v1/assignments")
def assign(
    caller: Annotated[Caller, Depends(authorize("assignRole"))], body: AssignmentIn
):
    """Assign a role, or add collections to the principal's assignment of it."""
    with db.connection() as conn:
        who = assignee(conn, caller, body)
        if who["kind"] not in rbac.role(body.role).assignable_to:
            refuse(400, f"'{body.role}' is not assigned to this kind of principal")
        value = checked_value(body.role, body.collections)
        if not may_change(conn, caller, who, body.role, value):
            refuse(
                403, f"assigning '{body.role}' here is not within this caller's grants"
            )
        records.assign(
            conn,
            body.role,
            value,
            caller.handle,
            user_id=who["user_id"],
            api_key_id=who["api_key_id"],
        )
        return {
            "roles": records.role_list(
                conn, user_id=who["user_id"], api_key_id=who["api_key_id"]
            )
        }


@app.delete("/v1/assignments")
def unassign(
    caller: Annotated[Caller, Depends(authorize("unassignRole"))], body: AssignmentIn
):
    """Remove collections from a principal's assignment of a role, ending it when none remain;
    without collections, end it. Removing a collection needs the authority to assign it."""
    with db.connection() as conn:
        who = assignee(conn, caller, body)
        current = records.current_value(
            conn, body.role, user_id=who["user_id"], api_key_id=who["api_key_id"]
        )
        if current is False:
            refuse(404, f"no '{body.role}' assignment to remove")
        removing = (
            current
            if body.collections is None
            else checked_value(body.role, body.collections)
        )
        allowed = may_change(conn, caller, who, body.role, removing)
        if not allowed and body.collections is None and who["community"] is not None:
            allowed = caller.allows(rbac.MEMBERS, who["community"])
        if not allowed:
            refuse(
                403, f"removing '{body.role}' here is not within this caller's grants"
            )
        try:
            records.unassign(
                conn,
                body.role,
                None if body.collections is None else rbac.names_in(removing),
                caller.handle,
                user_id=who["user_id"],
                api_key_id=who["api_key_id"],
            )
        except Conflict as e:
            conn.rollback()
            refuse(409, str(e))
        return {
            "roles": records.role_list(
                conn, user_id=who["user_id"], api_key_id=who["api_key_id"]
            )
        }


# ── communities (server-wide) ───────────────────────────────────────────────────────────────
@app.post("/v1/communities")
def create_community(
    caller: Annotated[Caller, Depends(authorize("createCommunity"))],
    body: CommunityIn,
    response: Response,
):
    """Create a community, its default collections, and the invite of its first community
    admin (R-G8). Idempotent: the exact existing name answers 200 and changes nothing."""
    if not valid_community(body.name):
        refuse(
            400,
            "a community name is 1-20 letters, digits or underscores, and not a "
            "server-wide route name",
        )
    with db.connection() as conn:
        root = records.root_user(conn)
        try:
            created = records.create_community(conn, body.name, root["id"])
        except Conflict as e:
            conn.rollback()
            refuse(400, f"{e}; names are unique ignoring case")
        out = {"name": body.name, "created": created}
        if created:
            try:
                records.check_new_handle(conn, body.admin, body.name)
            except Conflict as e:
                conn.rollback()
                refuse(409, str(e))
            out["admin_invite"] = mint_invite(
                conn,
                handle=body.admin,
                home=body.name,
                roles=[{"role": rbac.COMMUNITY_ADMIN, "collections": None}],
                by=caller.handle,
                hours=None,
                url=caller.base_url,
            )
        response.status_code = 201 if created else 200
        return out


@app.get("/v1/communities")
def list_communities(caller: Annotated[Caller, Depends(authorize("listCommunities"))]):
    with db.connection() as conn:
        return {
            "communities": [
                {"name": r["name"], "created": iso(r["created"])}
                for r in records.communities(conn)
            ]
        }


@app.get("/v1/{community}/roster")
def roster(
    caller: Annotated[Caller, Depends(authorize("listRoster"))],
    community: str,
):
    """Every user homed in the community, removed ones included and marked, with whether it
    has registered and its roles, and the server-level users. Members resolve one another's
    `@handle` against it."""
    with db.connection() as conn:
        community = community_of(conn, community)
        return {
            "community": community,
            "roster": [
                {
                    "handle": r["handle"],
                    "registered": r["registered"],
                    "removed": iso(r["removed"]),
                    "roles": r["roles"],
                }
                for r in records.users(conn, community)
            ],
            "server_users": [r["handle"] for r in records.users(conn, None)],
        }


# ── API keys: a signed-in user issues keys for applications ─────────────────────────────────
class ApiKeyIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    # a member key acts as its issuer; a non-member key is its own principal
    non_member: bool = False
    roles: list[RoleIn] = Field(min_length=1)
    expires_days: int | None = Field(default=None, ge=1, le=366)


def api_key_out(conn, row, reveal: bool) -> dict:
    """One issued key as its caller sees it; its value only when `reveal` (its issuer)."""
    return {
        "id": str(row["id"]),
        "community": row["community"],
        "member_key": row["user_id"] is not None,
        "handle": row["handle"],
        "label": row["label"],
        "key": api_keys.value(row) if reveal else None,
        "roles": records.role_list(conn, api_key_id=row["id"]),
        "created": iso(row["created"]),
        "created_by": row["created_by"],
        "expires": iso(row["expires"]),
        "last_used": iso(row["last_used"]),
    }


def issued_by(row, caller: Caller) -> bool:
    return row["created_by"] == caller.handle and caller.community in (
        None,
        row["community"],
    )


def api_key_id(key_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(key_id)
    except ValueError:
        refuse(404, f"no API key '{key_id}'")


@app.post("/v1/{community}/api-keys", status_code=201)
def create_api_key(
    caller: Annotated[Caller, Depends(authorize("createApiKey"))],
    community: str,
    body: ApiKeyIn,
    response: Response,
):
    """An issued API key for this community, answered once with its value, carrying the roles
    named. A member key acts as its issuer and never exceeds the issuer's grants; a non-member
    key is its own principal, and its roles also need the authority to assign them."""
    with db.connection() as conn:
        community = community_of(conn, community)
        kind = rbac.NON_MEMBER_KEY if body.non_member else rbac.MEMBER_KEY
        values = []
        for entry in body.roles:
            value = checked_value(entry.role, entry.collections)
            refs = refs_for(conn, community, value)
            ok = rbac.may_carry(
                caller.context, entry.role, value, not body.non_member, community, refs
            )
            if ok and body.non_member:
                ok = rbac.may_assign(
                    caller.context, entry.role, value, kind, community, refs
                )
            if not ok:
                refuse(
                    403, f"a key may not carry '{entry.role}' with these collections"
                )
            values.append((entry.role, value))
        try:
            row, _ = api_keys.create(
                conn,
                community=community,
                user_id=None if body.non_member else caller.user_id,
                handle=None if body.non_member else caller.handle,
                label=body.label,
                expires_days=body.expires_days,
                created_by=caller.handle,
            )
        except LabelInUse:
            refuse(409, f"a key is already labelled '{body.label}'")
        for role_id, value in values:
            records.assign(conn, role_id, value, caller.handle, api_key_id=row["id"])
        conn.commit()
        response.headers["Cache-Control"] = "no-store"
        return api_key_out(conn, row, reveal=True)


@app.get("/v1/{community}/api-keys")
def list_api_keys(
    caller: Annotated[Caller, Depends(authorize("listApiKeys"))],
    community: str,
    response: Response,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    """The keys the caller issued, with their values and roles; for a members holder, every key
    in the community, others' without their values. Expired keys' values are erased first."""
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
        api_keys.sweep(conn)
        conn.commit()
        everyone = caller.allows(rbac.MEMBERS, community)
        rows = api_keys.page(
            conn,
            community=community,
            after=after,
            limit=limit + 1,
            issuer=None if everyone else caller.handle,
        )
        more, rows = len(rows) > limit, rows[:limit]
        following = None
        if more:
            position = {"c": rows[-1]["created"].isoformat(), "k": str(rows[-1]["id"])}
            following = (
                base64.urlsafe_b64encode(json.dumps(position).encode())
                .decode()
                .rstrip("=")
            )
        response.headers["Cache-Control"] = "no-store"
        return {
            "community": community,
            "items": [api_key_out(conn, r, reveal=issued_by(r, caller)) for r in rows],
            "next": following,
        }


def key_for(conn, caller: Caller, community: str, key_id: str):
    """The community's key `key_id`, when the caller issued it or holds `members` there."""
    row = api_keys.row(conn, community, api_key_id(key_id))
    if row is None:
        refuse(404, f"no API key '{key_id}' in {community}")
    if not (issued_by(row, caller) or caller.allows(rbac.MEMBERS, community)):
        refuse(
            403, "only the key's issuer, or a members holder, may use this key's record"
        )
    return row


@app.get("/v1/{community}/api-keys/{key_id}")
def get_api_key(
    caller: Annotated[Caller, Depends(authorize("getApiKey"))],
    community: str,
    key_id: str,
    response: Response,
):
    """One issued key: its issuer reads it with its value; a members holder without."""
    with db.connection() as conn:
        community = community_of(conn, community)
        row = key_for(conn, caller, community, key_id)
        response.headers["Cache-Control"] = "no-store"
        return api_key_out(conn, row, reveal=issued_by(row, caller))


@app.delete("/v1/{community}/api-keys/{key_id}")
def revoke_api_key(
    caller: Annotated[Caller, Depends(authorize("revokeApiKey"))],
    community: str,
    key_id: str,
):
    """Revoke a key by deleting it, with its roles: its issuer's, or any key for a members
    holder. Its next request answers 401; a new key is issued if one is needed."""
    with db.connection() as conn:
        community = community_of(conn, community)
        row = key_for(conn, caller, community, key_id)
        out = api_key_out(conn, row, reveal=False)
        api_keys.delete(conn, community, row["id"])
        conn.commit()
        return out


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
def export(
    caller: Annotated[Caller, Depends(authorize("exportCommunity"))],
    community: str,
):
    """The community as a tar stream (admin only): one consistent snapshot of its rows, then
    every stored payload. Written by a thread into a pipe, so no copy lands on disk."""
    with db.connection() as conn:
        community = community_of(conn, community)
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
async def import_community(
    caller: Annotated[Caller, Depends(authorize("importCommunity"))], request: Request
):
    """Create a community from an export (admin only), in one transaction (R-J6): refused if
    the community exists here (there is no merge), and nothing is written on any failure. What
    the exported admin owned becomes this server's admin's."""
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


def quota_for(caller: Caller) -> int:
    """The per-owner quota; a holder of `communities` writes without one (R-H2)."""
    return 0 if caller.allows(rbac.COMMUNITIES, None) else settings.quota()


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
            if not records.touch_pending(conn, pid, file_id):
                raise Conflict("the upload expired before it finished; send it again")

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
        # one last beat before completing it in S3: an upload the janitor expired while its
        # body was in flight stops here, before anything is completed or committed
        await run_in_threadpool(heartbeat)
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
    conn, community, file_id, upload, head, metadata, content_type, handle, kid, quota
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
            quota,
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
async def put_file(
    caller: Annotated[Caller, Depends(authorize("putFile"))],
    community: str,
    collection: str,
    name: str,
    request: Request,
):
    """Create a file; its content and metadata become version 1. The name is reserved before
    any bytes move, and the file turns live only in the transaction that inserts v1."""
    if not valid_file_name(name):
        refuse(400, "a file name is one path segment of 1-255 characters")
    metadata = wire(parse_metadata, request.headers.get("x-data-metadata")) or {}
    content_type = request.headers.get("content-type", "application/octet-stream")

    def reserve():
        with db.connection() as conn:
            found = community_of(conn, community)
            handle, kid = caller.handle, caller.ed25519_kid
            if not records.collection_exists(conn, found, collection):
                refuse(404, f"no collection {found}/{collection}")
            if not records.can_create(
                conn, caller.context, found, collection, metadata
            ):
                refuse(403, f"no write access to {found}/{collection}")
            return (
                found,
                handle,
                kid,
                quota_for(caller),
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
                    quota,
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
async def put_version(
    caller: Annotated[Caller, Depends(authorize("addFileVersion"))],
    community: str,
    file_id: uuid.UUID,
    request: Request,
):
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
            handle, kid = caller.handle, caller.ed25519_kid
            row = records.file_row(conn, found, file_id)
            if not records.can_modify(conn, caller.context, row):
                refuse(
                    403,
                    "only the file's creator, or manage on its collection, adds versions",
                )
            head = records.latest_version(conn, file_id)
            if expected is not None and head["n"] != expected:
                # fail fast, before any bytes are streamed; re-checked under the lock below
                refuse(412, f"the file is at v{head['n']}, not v{expected}")
            return found, handle, kid, quota_for(caller)

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
                    quota,
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
    caller: Annotated[Caller, Depends(authorize("deleteFile"))],
    community: str,
    file_id: uuid.UUID,
    request: Request,
    reason: str | None = None,
):
    """Soft delete (R-B1): append a tombstone that keeps serving the previous content."""
    expected = wire(parse_if_match, request.headers.get("if-match"))
    with db.connection() as conn:
        community = community_of(conn, community)
        handle, kid = caller.handle, caller.ed25519_kid
        row = records.file_row(conn, community, file_id)
        if not records.can_modify(conn, caller.context, row):
            refuse(
                403, "only the file's creator, or manage on its collection, deletes it"
            )
        try:
            n = records.tombstone(conn, file_id, handle, kid, reason, expected)
        except PreconditionFailed as e:
            conn.rollback()
            mapped(e)
        conn.commit()
        return written(conn, community, file_id, n, status_code=200)


@app.post("/v1/{community}/files/{file_id}/v/{n}/purge")
def purge(
    caller: Annotated[Caller, Depends(authorize("purgeVersion"))],
    community: str,
    file_id: uuid.UUID,
    n: int,
):
    """Free one version's content (`manage` on its collection; R-B3). The version stays
    addressable and answers 410 with its metadata; the bytes go only when no other live version
    shares them. When S3 refuses, the payload stays purging and the janitor finishes the job."""
    with db.connection() as conn:
        community = community_of(conn, community)
        row = records.version(
            conn, community, file_id, n
        )  # 404 unless it is this community's
        if row["collection"] == rbac.INBOX:
            allowed = caller.context.allowsAllCollections(rbac.MANAGE, community)
        else:
            allowed = records.allows(
                conn, caller.context, rbac.MANAGE, community, row["collection"]
            )
        if not allowed:
            refuse(403, f"purging needs manage on {community}/{row['collection']}")
        pid = records.purge(conn, file_id, n)
    freed = pid is not None and cleanup.finish_purge(pid)
    result = {"purged": f"symposium-data:{file_id}@v{n}", "bytes_freed": freed}
    if pid is not None and not freed:
        result["note"] = "the bytes could not be removed yet; the janitor will retry"
    return result


def readable(caller: Caller, community: str, file_id, ref):
    """-> (community, stat, s3 key) of a version the caller may read: any caller, a key or
    none, as the version's collection allows."""
    with db.connection() as conn:
        community = community_of(conn, community)
        row = records.version(conn, community, file_id, ref)
        if not records.can_read(conn, caller.context, row):
            if caller.anonymous:
                refuse(401, "use an API key to read this file")
            refuse(403, "no read access to this file")
        return community, records.stat(conn, row), row["s3_key"]


@app.get("/v1/{community}/files/{file_id}/v/{ref}/stat")
def stat(
    caller: Annotated[Caller, Depends(authorize("statFileVersion"))],
    community: str,
    file_id: uuid.UUID,
    ref: str,
):
    info = readable(caller, community, file_id, ref)[1]
    return JSONResponse(info, headers={"ETag": etag(info["version"])})


@app.get("/v1/{community}/files/{file_id}/versions")
def versions(
    caller: Annotated[Caller, Depends(authorize("listFileVersions"))],
    community: str,
    file_id: uuid.UUID,
):
    community = readable(caller, community, file_id, 1)[0]
    with db.connection() as conn:
        return {"versions": records.versions(conn, community, file_id)}


@app.get("/v1/{community}/files/{file_id}/v/{ref}")
async def content(
    caller: Annotated[Caller, Depends(authorize("getFileContent"))],
    community: str,
    file_id: uuid.UUID,
    ref: str,
    request: Request,
):
    """Stream one version (R-E5): the service authorizes and streams every byte itself."""
    community, info, key = await run_in_threadpool(
        readable, caller, community, file_id, ref
    )
    if info["purged"]:
        return JSONResponse(
            {**body_for(410, "this version's content was purged"), **info},
            status_code=410,
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


def require_manager(conn, caller: Caller, community, collection) -> Caller:
    """Changing a collection takes `manage` on it: its owner, or a holder of `manage` on
    every collection."""
    if not records.allows(conn, caller.context, rbac.MANAGE, community, collection):
        refuse(403, f"this needs manage on {community}/{collection}")
    return caller


@app.get("/v1/{community}/collections")
def list_collections(
    caller: Annotated[Caller, Depends(authorize("listCollections"))],
    community: str,
):
    """The collections the caller may use, with what it may do in each: public ones, and
    those its grants or ownership reach. Without a key, the public ones."""
    with db.connection() as conn:
        community = community_of(conn, community)
        return {
            "collections": records.readable_collections(conn, caller.context, community)
        }


@app.post("/v1/{community}/collections", status_code=201)
def create_collection(
    caller: Annotated[Caller, Depends(authorize("createCollection"))],
    community: str,
    body: CollectionIn,
):
    """Create a collection, owned by the caller's user (R-D3), who reaches it through the
    owner allowance. It takes `write` in the community, with any collection value."""
    with db.connection() as conn:
        community = community_of(conn, community)
        if caller.user_id is None:
            refuse(403, "a collection is owned by a user: create it as a member")
        records.create_collection(conn, community, body.name, caller.user_id)
        return {
            "community": community,
            "name": body.name,
            "owner": caller.handle,
            "public": False,
        }


@app.put("/v1/{community}/collections/{collection}/public")
def set_public(
    caller: Annotated[Caller, Depends(authorize("setPublic"))],
    community: str,
    collection: str,
    body: PublicIn,
):
    """The owner opens a collection to reads without a key, or closes it again."""
    with db.connection() as conn:
        community = community_of(conn, community)
        require_manager(conn, caller, community, collection)
        records.set_public(conn, community, collection, body.public)
        return {"community": community, "collection": collection, "public": body.public}


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


def lister(conn, caller: Caller, community: str, collection: str):
    """Who may list a collection -> their context; refuses everyone else."""
    records.collection_row(conn, community, collection)
    who = caller.context
    if not records.can_read_collection(conn, who, community, collection):
        if caller.anonymous:
            refuse(401, "use an API key to read this collection")
        refuse(403, f"no read access to {community}/{collection}")
    return who


def page(conn, who, rows, since: int, limit: int) -> dict:
    """One page of a seq-ordered listing. `more` and `next_since` come from the rows scanned,
    not the rows shown, so a reader who sees only some rows still pages to the end and never
    meets a silent cap."""
    return {
        "items": [
            records.stat(conn, r) for r in rows if records.can_read(conn, who, r)
        ],
        "next_since": rows[-1]["seq"] if rows else since,
        "more": len(rows) == limit,
    }


@app.get("/v1/{community}/collections/{collection}/changes")
def changes(
    caller: Annotated[Caller, Depends(authorize("listChanges"))],
    community: str,
    collection: str,
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=MAX_PAGE),
):
    """Every version written into the collection after seq `since`, in seq order (R-G3)."""
    with db.connection() as conn:
        community = community_of(conn, community)
        who = lister(conn, caller, community, collection)
        rows = records.changes(conn, community, collection, since, limit)
        return page(conn, who, rows, since, limit)


@app.post("/v1/{community}/collections/{collection}/query")
def query(
    caller: Annotated[Caller, Depends(authorize("queryCollection"))],
    community: str,
    collection: str,
    body: QueryIn,
):
    """Versions whose metadata contains `contains`, paged like changes (R-G6)."""
    with db.connection() as conn:
        community = community_of(conn, community)
        who = lister(conn, caller, community, collection)
        rows = records.query(
            conn, community, collection, body.contains, body.since, body.limit
        )
        return page(conn, who, rows, body.since, body.limit)


@app.get("/v1/{community}/collections/{collection}/find")
def find(
    caller: Annotated[Caller, Depends(authorize("findFile"))],
    community: str,
    collection: str,
    name: str,
):
    """The file holding a name (R-G1), at its newest version, tombstone or not: a deleted
    file still holds its name."""
    with db.connection() as conn:
        community = community_of(conn, community)
        who = lister(conn, caller, community, collection)
        file_id = records.find_name(conn, community, collection, name)
        if file_id is None:
            refuse(404, f"no file named '{name}' in {community}/{collection}")
        row = records.version(
            conn, community, file_id, records.latest_version(conn, file_id)["n"]
        )
        if not records.can_read(conn, who, row):
            refuse(404, f"no file named '{name}' in {community}/{collection}")
        return JSONResponse(records.stat(conn, row), headers={"ETag": etag(row["n"])})


@app.get("/v1/{community}/sha256/{sha}")
def by_hash(
    caller: Annotated[Caller, Depends(authorize("findByHash"))],
    community: str,
    sha: str,
):
    """Every version of this community the caller may read that holds this content (R-F2)."""
    if not valid_sha256(sha):
        refuse(400, "a sha256 is 64 lowercase hex characters")
    with db.connection() as conn:
        community = community_of(conn, community)
        who = caller.context
        return {
            "items": [
                records.stat(conn, r)
                for r in records.by_hash(conn, community, sha)
                if records.can_read(conn, who, r)
            ]
        }


@app.post("/v1/{community}/files/{file_id}/v/{n}/promote", status_code=201)
def promote(
    caller: Annotated[Caller, Depends(authorize("promoteVersion"))],
    community: str,
    file_id: uuid.UUID,
    n: int,
    body: PromoteIn,
):
    """Copy one version into a collection as a new file, atomically (R-G4). Into `record`
    this is the gate's accept and takes `gate`; into any other collection, `manage` on it.

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
        handle = caller.handle
        source = records.version(conn, community, file_id, n)
        records.collection_row(conn, community, body.collection)
        if body.collection == "record":
            allowed = caller.allows(rbac.GATE, community)
        else:
            allowed = records.allows(
                conn, caller.context, rbac.MANAGE, community, body.collection
            )
        if not allowed or not records.can_read(conn, caller.context, source):
            refuse(
                403,
                f"promoting into {community}/{body.collection} is not within these grants",
            )
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
                        0,  # a promotion copy counts against no one's quota
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
                # promoter's session only authorizes it
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
    caller: Annotated[Caller, Depends(authorize("verifyCitation"))],
    community: str,
    cite: str,
    before: str | None = None,
    sha256: str | None = None,
):
    """The gate's check of a cited download (R-G9). A version the caller cannot read answers
    exactly like one that never existed, and a citation resolves only inside this community,
    so verify reveals nothing the caller may not read."""
    when = wire(parse_instant, before) if before else None
    with db.connection() as conn:
        community = community_of(conn, community)
        who = caller.context
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
        if not records.can_read(conn, who, row):
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
def start_port(
    caller: Annotated[Caller, Depends(authorize("startPortNdex"))],
    community: str,
    body: PortIn,
):
    """Start a port-ndex into this empty community, in the background; one at a time,
    server-wide. Poll GET /v1/{community}/port-ndex/{id} for its outcome."""
    from . import port_ndex  # the port feature, isolated: imported only here

    with db.connection() as conn:
        community = community_of(conn, community)
        admin = caller.handle
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
def port_status(
    caller: Annotated[Caller, Depends(authorize("getPortNdex"))],
    community: str,
    port_id: uuid.UUID,
):
    with db.connection() as conn:
        community = community_of(conn, community)
        row = records.port(conn, community, port_id)
        if row is None:
            refuse(404, f"no port-ndex {port_id} in {community}")
        return port_view(row)
