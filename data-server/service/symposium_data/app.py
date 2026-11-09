"""The hand-written routes of `/v1`: sign-in, users, invites, role assignments, communities,
API keys, collections and files. Every byte is streamed by this service; S3 is never exposed.
The record's routes are generated from the contract and mounted beside these by
`symposium_server`.

Communities are tenants: every community-dependent route is under
/v1/communities/{community}/..., with collection-scoped routes under collections/{collection}/
and file routes under files/{file_id}/. Sign-in (/v1/challenges, /v1/sessions), registrations,
/v1/me, server-level users, invites, roles and /v1/status are server-wide.

Every request presents one API key or none (`access`), and is decided by its caller's
`UserContext`: the operation's grants at the door, then each collection it touches here.

Nobody has a shell on the server: every administrative operation is a route, and the root
user's key comes from the key file on the volume. Without a usable one the server is
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

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
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
    PRIVILEGED_REFUSAL,
    WireError,
    digest_header,
    etag,
    parse_citation,
    parse_digest,
    parse_if_match,
    parse_instant,
    parse_metadata,
    privileged_community,
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
    """Non-operational mode: only /v1/status answers, so a readiness probe sees why;
    the jobs keep running."""
    if not admin_mode.operational and request.url.path != STATUS:
        return JSONResponse(
            body_for(501, f"the server is not operational: {admin_mode.reason}"),
            status_code=501,
        )
    return await call_next(request)


# A request body is at most 8 MiB, except where one streams: a file's content (creating a file,
# adding a version), which quota bounds instead, and a community's archive (an import).
BODY_LIMIT = 8 * 1024 * 1024
TOO_LARGE = "the request body is over 8 MiB"
STREAMED = (
    ("PUT", re.compile(r"^/v1/communities/[^/]+/collections/[^/]+/files/[^/]+$"), None),
    ("POST", re.compile(r"^/v1/communities/[^/]+/files/[^/]+/versions$"), None),
    ("POST", re.compile(r"^/v1/communities$"), b"application/x-tar"),
)


def streams(scope) -> bool:
    """Whether a request's body streams past the limit: a route above, with its media type."""
    media = dict(scope["headers"]).get(b"content-type", b"").split(b";")[0].strip()
    return any(
        scope["method"] == method
        and path.match(scope["path"])
        and (wanted is None or media == wanted)
        for method, path, wanted in STREAMED
    )


class BodyLimit:
    """Refuses a body over BODY_LIMIT with 413: at once when its Content-Length says so, or once
    the bytes read pass it. A body within the limit is read here and handed on whole, so the
    route reads it as it was sent."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or streams(scope):
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
    roles: list[RoleIn] = Field(min_length=1)
    hours: int | None = Field(default=None, ge=1, le=24 * 366)


class RoleValueIn(BaseModel):
    collections: list[str] | None = None


class UserPatch(BaseModel):
    suspect_after: datetime


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
    without touching the database for a non-slug."""
    if not valid_community(name):
        refuse(404, f"no community '{name}'")
    found = records.community_name(conn, name)
    if found is None:
        refuse(404, f"no community '{name}'")
    return found


def home_of(conn, name: str | None) -> str | None:
    return None if name is None else community_of(conn, name)


def located(response: Response, caller: Caller, path: str):
    """The `Location` of a resource a request created: an absolute URL on this server."""
    response.headers["Location"] = caller.base_url + "/v1" + path


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


@app.post("/v1/challenges")
def create_challenge(
    caller: Annotated[Caller, Depends(authorize("createChallenge"))], body: ChallengeIn
):
    """A nonce to sign, for signing in or for proving a new key, by any handle: the answer is
    the same whether or not the handle exists."""
    nonce = secrets.new("n_")
    with db.connection() as conn:
        home = home_of(conn, body.community)
        records.add_challenge(conn, home, body.handle, nonce)
    return {"nonce": nonce, "expires_in": 300}


@app.post("/v1/sessions")
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


def user_path(home: str | None, handle: str) -> str:
    """A user's path under /v1: its scope's users, by handle."""
    scope = "" if home is None else f"/communities/{home}"
    return f"{scope}/users/{handle}"


@app.post("/v1/registrations", status_code=201)
def register(
    caller: Annotated[Caller, Depends(authorize("register"))],
    body: RegisterIn,
    response: Response,
):
    """Join with an invite: register a key generated on the invitee's machine.
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
        located(response, caller, user_path(home, body.handle))
        return {
            "handle": body.handle,
            "community": home,
            "kid": kid,
            "roles": records.role_list(conn, user_id=user["id"]),
        }


@app.post("/v1/me/keys")
def rotate(caller: Annotated[Caller, Depends(authorize("rotateKey"))], body: RotateIn):
    """Replace the signed-in user's key, proven by the new key; the old key retires (versions
    name it) and the sessions it obtained end."""
    with db.connection() as conn:
        kid, jwk = checked_new_key(conn, caller.community, caller.handle, body)
        if records.key_on_record(conn, kid):
            refuse(409, "that key is already on record", conn)
        records.add_key(conn, caller.user_id, kid, jwk)
        return {"handle": caller.handle, "kid": kid}


# ── users: server-level, and a community's ──────────────────────────────────────────────────
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


def require_user_admin(caller: Caller, home: str | None):
    """`delegate` for server-level users, `members` in their community otherwise."""
    if home is None:
        if not caller.allows(rbac.DELEGATE, None):
            refuse(403, "only the root administrator manages server-level users")
    elif not caller.allows(rbac.MEMBERS, home):
        refuse(403, f"this needs the members grant in {home}")


def require_reader(caller: Caller, home: str | None):
    """A community's users are read by any principal of the community; the server-level users
    by `delegate` holders."""
    if home is None:
        require_user_admin(caller, None)
    elif caller.community not in (None, home):
        refuse(403, f"this key belongs to {caller.community}")


def scoped_user(conn, home: str | None, handle: str):
    user = records.user_by_handle(conn, home, handle)
    if user is None:
        refuse(404, f"no user '{handle}'" + (f" in {home}" if home else ""))
    return user


def list_users_in(conn, caller: Caller, home: str | None) -> dict:
    require_reader(caller, home)
    out = {
        "community": home,
        "users": [user_out(conn, r) for r in records.users(conn, home)],
    }
    if home is not None:
        out["server_users"] = [r["handle"] for r in records.users(conn, None)]
    return out


def get_user_in(conn, caller: Caller, home: str | None, handle: str) -> dict:
    require_reader(caller, home)
    return user_out(conn, scoped_user(conn, home, handle))


def update_user_in(conn, caller: Caller, home, handle, body: UserPatch) -> dict:
    if body.suspect_after.tzinfo is None:
        refuse(400, "the instant needs a timezone, e.g. 2026-10-01T12:00:00+00:00")
    require_user_admin(caller, home)
    user = scoped_user(conn, home, handle)
    if not records.set_suspect_after(conn, user["id"], body.suspect_after):
        refuse(409, f"'{handle}' was removed")
    return user_out(conn, records.user(conn, user["id"]))


def remove_user_in(conn, caller: Caller, home, handle) -> dict:
    """Remove a user. It stays as a tombstone: its handle is never used again, and everything
    it published keeps its name. Its roles end, its keys retire, and its sessions and every
    API key it issued are deleted."""
    require_user_admin(caller, home)
    user = scoped_user(conn, home, handle)
    if records.current_value(conn, rbac.SERVER_ROOT, user_id=user["id"]) is not False:
        refuse(
            409, "the root administrator is bound by the key file and not removed here"
        )
    try:
        removed = records.remove_user(conn, user["id"], caller.handle)
    except Conflict as e:
        conn.rollback()
        refuse(409, str(e))
    if not removed:
        refuse(409, f"'{handle}' was already removed")
    return user_out(conn, records.user(conn, user["id"]))


class RebindIn(BaseModel):
    hours: int | None = Field(default=None, ge=1, le=24 * 366)


def rebind_user_in(conn, caller: Caller, home, handle, body, response) -> dict:
    """A lost or compromised key: retire the user's keys, end its sessions, and return a fresh
    invite that registers a new key for the same user, with its roles as they are."""
    require_user_admin(caller, home)
    user = scoped_user(conn, home, handle)
    if user["removed"] is not None:
        refuse(409, f"'{handle}' was removed")
    retired = records.retire_keys(conn, user["id"])
    issued = mint_invite(
        conn,
        handle=user["handle"],
        home=home,
        roles=[],
        by=caller.handle,
        hours=body.hours if body else None,
        url=caller.base_url,
        user_id=user["id"],
    )
    located(response, caller, invite_path(home, issued["id"]))
    return {"retired_keys": retired, **issued}


@app.get("/v1/users")
def list_server_users(caller: Annotated[Caller, Depends(authorize("listServerUsers"))]):
    """The server-level users, removed ones included and marked, each with its roles."""
    with db.connection() as conn:
        return list_users_in(conn, caller, None)


@app.get("/v1/communities/{community}/users")
def list_users(
    caller: Annotated[Caller, Depends(authorize("listUsers"))], community: str
):
    """The community's users, removed ones included and marked, each with its roles, and the
    server-level users. Members resolve one another's `@handle` against it."""
    with db.connection() as conn:
        return list_users_in(conn, caller, community_of(conn, community))


@app.get("/v1/users/{handle}")
def get_server_user(
    caller: Annotated[Caller, Depends(authorize("getServerUser"))], handle: str
):
    with db.connection() as conn:
        return get_user_in(conn, caller, None, handle)


@app.get("/v1/communities/{community}/users/{handle}")
def get_user(
    caller: Annotated[Caller, Depends(authorize("getUser"))],
    community: str,
    handle: str,
):
    with db.connection() as conn:
        return get_user_in(conn, caller, community_of(conn, community), handle)


@app.patch("/v1/users/{handle}")
def update_server_user(
    caller: Annotated[Caller, Depends(authorize("updateServerUser"))],
    handle: str,
    body: UserPatch,
):
    with db.connection() as conn:
        return update_user_in(conn, caller, None, handle, body)


@app.patch("/v1/communities/{community}/users/{handle}")
def update_user(
    caller: Annotated[Caller, Depends(authorize("updateUser"))],
    community: str,
    handle: str,
    body: UserPatch,
):
    with db.connection() as conn:
        return update_user_in(conn, caller, community_of(conn, community), handle, body)


@app.delete("/v1/users/{handle}")
def remove_server_user(
    caller: Annotated[Caller, Depends(authorize("removeServerUser"))], handle: str
):
    with db.connection() as conn:
        return remove_user_in(conn, caller, None, handle)


@app.delete("/v1/communities/{community}/users/{handle}")
def remove_user(
    caller: Annotated[Caller, Depends(authorize("removeUser"))],
    community: str,
    handle: str,
):
    with db.connection() as conn:
        return remove_user_in(conn, caller, community_of(conn, community), handle)


@app.post("/v1/users/{handle}/invites", status_code=201)
def rebind_server_user(
    caller: Annotated[Caller, Depends(authorize("rebindServerUser"))],
    handle: str,
    response: Response,
    body: RebindIn | None = None,
):
    with db.connection() as conn:
        return rebind_user_in(conn, caller, None, handle, body, response)


@app.post("/v1/communities/{community}/users/{handle}/invites", status_code=201)
def rebind_user(
    caller: Annotated[Caller, Depends(authorize("rebindUser"))],
    community: str,
    handle: str,
    response: Response,
    body: RebindIn | None = None,
):
    with db.connection() as conn:
        home = community_of(conn, community)
        return rebind_user_in(conn, caller, home, handle, body, response)


# ── roles: the registry, and each principal's assignments ───────────────────────────────────
def role_info(r) -> dict:
    return {
        "role": r.id,
        "assignable_to": sorted(r.assignable_to),
        "takes_collections": r.takes_collections,
        "keys_may_carry": r.key_assignable,
        "assignable": r.assignable,
        # the collections a user holding the role always reads, whatever its collection value
        "user_reads": list(r.user_reads),
        "grants": {
            g: ("assignment" if v is rbac.VALUE else None if v is None else list(v))
            for g, v in r.grants.items()
        },
    }


@app.get("/v1/roles")
def roles(caller: Annotated[Caller, Depends(authorize("listRoles"))]):
    """The six roles and what each grants: the registry, read-only."""
    return {"roles": [role_info(r) for r in rbac.ROLES.values()]}


@app.get("/v1/roles/{role}")
def get_role(caller: Annotated[Caller, Depends(authorize("getRole"))], role: str):
    if role not in rbac.ROLES:
        refuse(404, f"no role '{role}'")
    return role_info(rbac.ROLES[role])


def refs_for(conn, community: str | None, names) -> dict:
    """The CollectionRef of each named collection; 404 for one that does not exist."""
    if community is None:
        return {}
    return {
        name: records.collection_ref(conn, community, name)
        for name in rbac.names_in(None if names is None else tuple(names))
    }


def checked_value(role_id: str, collections) -> tuple | None:
    if role_id not in rbac.ROLES:
        refuse(404, f"no role '{role_id}'")
    try:
        return rbac.collection_value(role_id, collections)
    except rbac.AssignmentError as e:
        refuse(400, str(e))


def user_principal(conn, home: str | None, handle: str) -> dict:
    user = scoped_user(conn, home, handle)
    if user["removed"] is not None:
        refuse(409, f"'{handle}' was removed")
    return {
        "kind": rbac.SERVER_USER if home is None else rbac.HOMED_USER,
        "community": home,
        "user_id": user["id"],
        "api_key_id": None,
    }


def key_principal(conn, caller: Caller, community: str, key_id: str) -> dict:
    key = conn.execute(
        "SELECT * FROM api_keys WHERE id = %s AND kind = 'issued' AND community = %s",
        (api_key_id(key_id), community),
    ).fetchone()
    if key is None:
        refuse(404, f"no API key '{key_id}'")
    if not (issued_by(key, caller) or caller.allows(rbac.MEMBERS, key["community"])):
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
    issuer = records.issuer_of(conn, key["community"], key["created_by"])
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


def require_change(conn, caller: Caller, who: dict, role_id: str, value):
    if not may_change(conn, caller, who, role_id, value):
        refuse(403, f"changing '{role_id}' here is not within this caller's grants")


def require_role_reader(caller: Caller, who: dict):
    """A principal's own roles, a key's for its issuer (checked on resolving it), and anyone's
    for a holder of `members` (`delegate` for a server-level user)."""
    if who["user_id"] is not None and who["user_id"] != caller.user_id:
        require_user_admin(caller, who["community"])


def role_etag(role_id: str, value) -> str:
    material = json.dumps([role_id, None if value is None else sorted(value)])
    return '"' + hashlib.sha256(material.encode()).hexdigest()[:24] + '"'


def roles_of(conn, who: dict) -> dict:
    return {
        "roles": records.role_list(
            conn, user_id=who["user_id"], api_key_id=who["api_key_id"]
        )
    }


def assignment_out(conn, who: dict, role_id: str, response: Response) -> dict:
    current = records.current_value(
        conn, role_id, user_id=who["user_id"], api_key_id=who["api_key_id"]
    )
    if current is False:
        refuse(404, f"no '{role_id}' assignment")
    response.headers["ETag"] = role_etag(role_id, current)
    return {"role": role_id, "collections": None if current is None else list(current)}


def get_role_of(conn, caller, who, role_id, response) -> dict:
    require_role_reader(caller, who)
    return assignment_out(conn, who, role_id, response)


def set_role_of(conn, caller, who, role_id, body, if_match, response, path) -> dict:
    """Assign the role, or replace its whole collection value under `If-Match`."""
    value = checked_value(role_id, body.collections if body else None)
    if who["kind"] not in rbac.role(role_id).assignable_to:
        refuse(400, f"'{role_id}' is not assigned to this kind of principal")
    principal = {"user_id": who["user_id"], "api_key_id": who["api_key_id"]}
    current = records.current_value(conn, role_id, **principal)
    if current is False:
        require_change(conn, caller, who, role_id, value)
        records.assign(conn, role_id, value, caller.handle, **principal)
        response.status_code = 201
        located(response, caller, path)
    else:
        # authority first, so a caller without it learns nothing of the assignment
        if value is None or rbac.ALL in value or rbac.ALL in (current or ()):
            changed = value
        else:
            changed = tuple(sorted(set(value) ^ set(current or ())))
        require_change(conn, caller, who, role_id, changed if changed else value)
        if if_match is None:
            refuse(428, "replacing an assignment takes If-Match with its ETag")
        if if_match != role_etag(role_id, current):
            refuse(412, "the assignment changed since its ETag was read")
        records.replace_value(conn, role_id, value, caller.handle, **principal)
    return assignment_out(conn, who, role_id, response)


def unset_role_of(conn, caller, who, role_id) -> dict:
    principal = {"user_id": who["user_id"], "api_key_id": who["api_key_id"]}
    current = records.current_value(conn, role_id, **principal)
    if current is False:
        refuse(404, f"no '{role_id}' assignment")
    allowed = may_change(conn, caller, who, role_id, current)
    if not allowed and who["community"] is not None:
        allowed = caller.allows(rbac.MEMBERS, who["community"])
    if not allowed:
        refuse(403, f"ending '{role_id}' here is not within this caller's grants")
    try:
        records.unassign(conn, role_id, None, caller.handle, **principal)
    except Conflict as e:
        conn.rollback()
        refuse(409, str(e))
    return roles_of(conn, who)


def add_role_collection_of(conn, caller, who, role_id, collection, response) -> dict:
    value = checked_value(role_id, [collection])
    if who["kind"] not in rbac.role(role_id).assignable_to:
        refuse(400, f"'{role_id}' is not assigned to this kind of principal")
    require_change(conn, caller, who, role_id, value)
    records.assign(
        conn,
        role_id,
        value,
        caller.handle,
        user_id=who["user_id"],
        api_key_id=who["api_key_id"],
    )
    return assignment_out(conn, who, role_id, response)


def remove_role_collection_of(conn, caller, who, role_id, collection) -> dict:
    principal = {"user_id": who["user_id"], "api_key_id": who["api_key_id"]}
    current = records.current_value(conn, role_id, **principal)
    if current is False or current is None or collection not in current:
        refuse(404, f"no '{collection}' in a '{role_id}' assignment")
    require_change(conn, caller, who, role_id, checked_value(role_id, [collection]))
    try:
        records.unassign(conn, role_id, [collection], caller.handle, **principal)
    except Conflict as e:
        conn.rollback()
        refuse(409, str(e))
    return roles_of(conn, who)


# the same five operations on three kinds of principal: server-level users, a community's
# users, and a community's API keys
@app.get("/v1/users/{handle}/roles")
def list_server_user_roles(
    caller: Annotated[Caller, Depends(authorize("listServerUserRoles"))], handle: str
):
    with db.connection() as conn:
        who = user_principal(conn, None, handle)
        require_role_reader(caller, who)
        return roles_of(conn, who)


@app.get("/v1/users/{handle}/roles/{role}")
def get_server_user_role(
    caller: Annotated[Caller, Depends(authorize("getServerUserRole"))],
    handle: str,
    role: str,
    response: Response,
):
    with db.connection() as conn:
        return get_role_of(
            conn, caller, user_principal(conn, None, handle), role, response
        )


@app.put("/v1/users/{handle}/roles/{role}")
def set_server_user_role(
    caller: Annotated[Caller, Depends(authorize("setServerUserRole"))],
    handle: str,
    role: str,
    response: Response,
    body: RoleValueIn | None = None,
    if_match: Annotated[str | None, Header()] = None,
):
    with db.connection() as conn:
        who = user_principal(conn, None, handle)
        return set_role_of(
            conn,
            caller,
            who,
            role,
            body,
            if_match,
            response,
            f"/users/{handle}/roles/{role}",
        )


@app.delete("/v1/users/{handle}/roles/{role}")
def unset_server_user_role(
    caller: Annotated[Caller, Depends(authorize("unsetServerUserRole"))],
    handle: str,
    role: str,
):
    with db.connection() as conn:
        return unset_role_of(conn, caller, user_principal(conn, None, handle), role)


@app.get("/v1/communities/{community}/users/{handle}/roles")
def list_user_roles(
    caller: Annotated[Caller, Depends(authorize("listUserRoles"))],
    community: str,
    handle: str,
):
    with db.connection() as conn:
        who = user_principal(conn, community_of(conn, community), handle)
        require_role_reader(caller, who)
        return roles_of(conn, who)


@app.get("/v1/communities/{community}/users/{handle}/roles/{role}")
def get_user_role(
    caller: Annotated[Caller, Depends(authorize("getUserRole"))],
    community: str,
    handle: str,
    role: str,
    response: Response,
):
    with db.connection() as conn:
        who = user_principal(conn, community_of(conn, community), handle)
        return get_role_of(conn, caller, who, role, response)


@app.put("/v1/communities/{community}/users/{handle}/roles/{role}")
def set_user_role(
    caller: Annotated[Caller, Depends(authorize("setUserRole"))],
    community: str,
    handle: str,
    role: str,
    response: Response,
    body: RoleValueIn | None = None,
    if_match: Annotated[str | None, Header()] = None,
):
    with db.connection() as conn:
        home = community_of(conn, community)
        who = user_principal(conn, home, handle)
        return set_role_of(
            conn,
            caller,
            who,
            role,
            body,
            if_match,
            response,
            f"/communities/{home}/users/{handle}/roles/{role}",
        )


@app.delete("/v1/communities/{community}/users/{handle}/roles/{role}")
def unset_user_role(
    caller: Annotated[Caller, Depends(authorize("unsetUserRole"))],
    community: str,
    handle: str,
    role: str,
):
    with db.connection() as conn:
        who = user_principal(conn, community_of(conn, community), handle)
        return unset_role_of(conn, caller, who, role)


@app.put(
    "/v1/communities/{community}/users/{handle}/roles/{role}/collections/{role_collection}"
)
def add_user_role_collection(
    caller: Annotated[Caller, Depends(authorize("addUserRoleCollection"))],
    community: str,
    handle: str,
    role: str,
    role_collection: str,
    response: Response,
):
    with db.connection() as conn:
        who = user_principal(conn, community_of(conn, community), handle)
        return add_role_collection_of(
            conn, caller, who, role, role_collection, response
        )


@app.delete(
    "/v1/communities/{community}/users/{handle}/roles/{role}/collections/{role_collection}"
)
def remove_user_role_collection(
    caller: Annotated[Caller, Depends(authorize("removeUserRoleCollection"))],
    community: str,
    handle: str,
    role: str,
    role_collection: str,
):
    with db.connection() as conn:
        who = user_principal(conn, community_of(conn, community), handle)
        return remove_role_collection_of(conn, caller, who, role, role_collection)


@app.get("/v1/communities/{community}/api-keys/{key_id}/roles")
def list_api_key_roles(
    caller: Annotated[Caller, Depends(authorize("listApiKeyRoles"))],
    community: str,
    key_id: str,
):
    with db.connection() as conn:
        return roles_of(
            conn, key_principal(conn, caller, community_of(conn, community), key_id)
        )


@app.get("/v1/communities/{community}/api-keys/{key_id}/roles/{role}")
def get_api_key_role(
    caller: Annotated[Caller, Depends(authorize("getApiKeyRole"))],
    community: str,
    key_id: str,
    role: str,
    response: Response,
):
    with db.connection() as conn:
        who = key_principal(conn, caller, community_of(conn, community), key_id)
        return assignment_out(conn, who, role, response)


@app.put("/v1/communities/{community}/api-keys/{key_id}/roles/{role}")
def set_api_key_role(
    caller: Annotated[Caller, Depends(authorize("setApiKeyRole"))],
    community: str,
    key_id: str,
    role: str,
    response: Response,
    body: RoleValueIn | None = None,
    if_match: Annotated[str | None, Header()] = None,
):
    with db.connection() as conn:
        home = community_of(conn, community)
        who = key_principal(conn, caller, home, key_id)
        return set_role_of(
            conn,
            caller,
            who,
            role,
            body,
            if_match,
            response,
            f"/communities/{home}/api-keys/{key_id}/roles/{role}",
        )


@app.delete("/v1/communities/{community}/api-keys/{key_id}/roles/{role}")
def unset_api_key_role(
    caller: Annotated[Caller, Depends(authorize("unsetApiKeyRole"))],
    community: str,
    key_id: str,
    role: str,
):
    with db.connection() as conn:
        who = key_principal(conn, caller, community_of(conn, community), key_id)
        return unset_role_of(conn, caller, who, role)


@app.put(
    "/v1/communities/{community}/api-keys/{key_id}/roles/{role}/collections/{role_collection}"
)
def add_api_key_role_collection(
    caller: Annotated[Caller, Depends(authorize("addApiKeyRoleCollection"))],
    community: str,
    key_id: str,
    role: str,
    role_collection: str,
    response: Response,
):
    with db.connection() as conn:
        who = key_principal(conn, caller, community_of(conn, community), key_id)
        return add_role_collection_of(
            conn, caller, who, role, role_collection, response
        )


@app.delete(
    "/v1/communities/{community}/api-keys/{key_id}/roles/{role}/collections/{role_collection}"
)
def remove_api_key_role_collection(
    caller: Annotated[Caller, Depends(authorize("removeApiKeyRoleCollection"))],
    community: str,
    key_id: str,
    role: str,
    role_collection: str,
):
    with db.connection() as conn:
        who = key_principal(conn, caller, community_of(conn, community), key_id)
        return remove_role_collection_of(conn, caller, who, role, role_collection)


# ── invites ─────────────────────────────────────────────────────────────────────────────────
def invite_path(home: str | None, invite_id: str) -> str:
    scope = "" if home is None else f"/communities/{home}"
    return f"{scope}/invites/{invite_id}"


def mint_invite(conn, *, handle, home, roles, by, hours, url, user_id=None) -> dict:
    invite = secrets.new("sdi_")
    hours = settings.invite_hours if hours is None else hours
    digest = secrets.digest(invite)
    expires = records.add_invite(
        conn,
        digest=digest,
        secret=invite,
        handle=handle,
        home=home,
        roles=roles,
        by=by,
        hours=hours,
        user_id=user_id,
    )
    return invite_out(digest, handle, home, roles, invite, expires, url)


def invite_out(digest, handle, home, roles, invite, expires, url) -> dict:
    return {
        "id": digest,
        "handle": handle,
        "community": home,
        "roles": roles,
        "invite": invite,
        "expires": iso(expires),
        "data-server-url": url,
    }


def invite_row_out(row, url) -> dict:
    return invite_out(
        row["hash"],
        row["handle"],
        row["home"],
        row["roles"],
        row["secret"],
        row["expires"],
        url,
    )


def create_invite_in(conn, caller: Caller, home: str | None, body: InviteIn, response):
    """A single-use invite for a new user, returned once. It carries the user's home and roles,
    which the server keeps and applies when the invite is redeemed; the inviter needs the
    authority to assign every one of them. Any earlier pending invite for the handle is
    revoked."""
    if caller.community is not None and home != caller.community:
        refuse(403, f"this key belongs to {caller.community}")
    kind = rbac.SERVER_USER if home is None else rbac.HOMED_USER
    roles_ = []
    for entry in body.roles:
        value = checked_value(entry.role, entry.collections)
        refs = refs_for(conn, home, value)
        if not rbac.may_assign(caller.context, entry.role, value, kind, home, refs):
            refuse(
                403, f"assigning '{entry.role}' here is not within this caller's grants"
            )
        roles_.append(
            {"role": entry.role, "collections": None if value is None else list(value)}
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
    issued = mint_invite(
        conn,
        handle=body.handle,
        home=home,
        roles=roles_,
        by=caller.handle,
        hours=body.hours,
        url=caller.base_url,
        user_id=claimed,
    )
    located(response, caller, invite_path(home, issued["id"]))
    return issued


def pending_invite_in(conn, caller: Caller, home: str | None, invite_id: str):
    require_user_admin(caller, home)
    row = records.invite_by_id(conn, home, invite_id)
    if row is None:
        refuse(404, f"no pending invite '{invite_id}'")
    return row


@app.post("/v1/invites", status_code=201)
def create_server_invite(
    caller: Annotated[Caller, Depends(authorize("createServerInvite"))],
    body: InviteIn,
    response: Response,
):
    with db.connection() as conn:
        return create_invite_in(conn, caller, None, body, response)


@app.post("/v1/communities/{community}/invites", status_code=201)
def create_invite(
    caller: Annotated[Caller, Depends(authorize("createInvite"))],
    community: str,
    body: InviteIn,
    response: Response,
):
    with db.connection() as conn:
        return create_invite_in(
            conn, caller, community_of(conn, community), body, response
        )


@app.get("/v1/invites")
def list_server_invites(
    caller: Annotated[Caller, Depends(authorize("listServerInvites"))],
):
    """The server-level users' pending invites, with their secrets, so one can be handed over
    again. Used, expired and revoked invites are never listed."""
    with db.connection() as conn:
        require_user_admin(caller, None)
        return {
            "community": None,
            "invites": [
                invite_row_out(r, caller.base_url)
                for r in records.pending_invites(conn, None)
            ],
        }


@app.get("/v1/communities/{community}/invites")
def list_invites(
    caller: Annotated[Caller, Depends(authorize("listInvites"))], community: str
):
    """The community's pending invites, with their secrets."""
    with db.connection() as conn:
        home = community_of(conn, community)
        require_user_admin(caller, home)
        return {
            "community": home,
            "invites": [
                invite_row_out(r, caller.base_url)
                for r in records.pending_invites(conn, home)
            ],
        }


@app.get("/v1/invites/{invite_id}")
def get_server_invite(
    caller: Annotated[Caller, Depends(authorize("getServerInvite"))], invite_id: str
):
    with db.connection() as conn:
        return invite_row_out(
            pending_invite_in(conn, caller, None, invite_id), caller.base_url
        )


@app.get("/v1/communities/{community}/invites/{invite_id}")
def get_invite(
    caller: Annotated[Caller, Depends(authorize("getInvite"))],
    community: str,
    invite_id: str,
):
    with db.connection() as conn:
        row = pending_invite_in(conn, caller, community_of(conn, community), invite_id)
        return invite_row_out(row, caller.base_url)


@app.delete("/v1/invites/{invite_id}")
def revoke_server_invite(
    caller: Annotated[Caller, Depends(authorize("revokeServerInvite"))], invite_id: str
):
    with db.connection() as conn:
        row = pending_invite_in(conn, caller, None, invite_id)
        records.revoke_invite(conn, row["hash"])
        return invite_row_out({**row, "secret": None}, caller.base_url)


@app.delete("/v1/communities/{community}/invites/{invite_id}")
def revoke_invite(
    caller: Annotated[Caller, Depends(authorize("revokeInvite"))],
    community: str,
    invite_id: str,
):
    with db.connection() as conn:
        row = pending_invite_in(conn, caller, community_of(conn, community), invite_id)
        records.revoke_invite(conn, row["hash"])
        return invite_row_out({**row, "secret": None}, caller.base_url)


# ── communities ─────────────────────────────────────────────────────────────────────────────
@app.post("/v1/communities")
async def create_community(
    caller: Annotated[Caller, Depends(authorize("createCommunity"))],
    request: Request,
    response: Response,
):
    """Create a community, its default collections, and the invite of its first
    community admin, from `{name, admin}`; or, from an archive (`application/x-tar`), import
    one. Creating is idempotent: the exact existing name answers 200 and changes nothing."""
    media = request.headers.get("content-type", "").split(";")[0].strip()
    if media == "application/x-tar":
        return await import_archive(caller, request, response)
    if media != "application/json":
        refuse(415, "a community is created from application/json or application/x-tar")
    try:
        body = CommunityIn.model_validate_json(await request.body())
    except ValidationError as e:
        raise RequestValidationError(e.errors()) from None
    return await run_in_threadpool(create_community_from, caller, body, response)


def create_community_from(
    caller: Caller, body: CommunityIn, response: Response
) -> dict:
    if not valid_community(body.name):
        refuse(400, "a community name is 1-20 letters, digits or underscores")
    if privileged_community(body.name):
        refuse(400, PRIVILEGED_REFUSAL)
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
            located(response, caller, f"/communities/{body.name}")
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


@app.get("/v1/communities/{community}")
def get_community(
    caller: Annotated[Caller, Depends(authorize("getCommunity"))], community: str
):
    """The community: its name and when it was created, to any principal of it."""
    with db.connection() as conn:
        name = community_of(conn, community)
        row = next(r for r in records.communities(conn) if r["name"] == name)
        return {
            "name": name,
            "created": iso(row["created"]),
            "url": caller.base_url + f"/v1/communities/{name}",
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


@app.post("/v1/communities/{community}/api-keys", status_code=201)
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
        located(response, caller, f"/communities/{community}/api-keys/{row['id']}")
        return api_key_out(conn, row, reveal=True)


@app.get("/v1/communities/{community}/api-keys")
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


@app.get("/v1/communities/{community}/api-keys/{key_id}")
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


@app.delete("/v1/communities/{community}/api-keys/{key_id}")
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


# ── export and import ────────────────────────────────────────────────────────────────
def pipe() -> tuple:
    reader, writer = os.pipe()
    return os.fdopen(reader, "rb"), os.fdopen(writer, "wb")


def close_quietly(stream):
    try:
        stream.close()
    except OSError:
        pass  # the other end is gone already


@app.get("/v1/communities/{community}/archive")
def export(
    caller: Annotated[Caller, Depends(authorize("exportCommunity"))],
    community: str,
):
    """The community's archive, a tar stream (`export`): one consistent snapshot of its rows,
    then every stored payload. Written by a thread into a pipe, so no copy lands on disk."""
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


async def import_archive(caller: Caller, request: Request, response: Response):
    """Create a community from its archive, in one transaction: refused if the
    community exists here (there is no merge), and nothing is written on any failure. What the
    exported root owned becomes this server's root's."""
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
        result = await imported
    except Refused as e:
        refuse(409, str(e))
    except Malformed as e:
        refuse(400, str(e))
    response.status_code = 201
    located(response, caller, f"/communities/{result['imported']}")
    return result


# ── files and versions ──────────────────────────────────────────────────────────────────────
def wire(call, *args):
    try:
        return call(*args)
    except WireError as e:
        refuse(e.status, str(e))


class Upload:
    """One streamed, verified, still-pending payload. It becomes durable only inside the
    commit transaction that references it; otherwise discard() removes it, bytes first
    and row second, leaving the row for the janitor if S3 refuses."""

    def __init__(self, pid, sha: str, size: int):
        self.pid, self.sha, self.size = pid, sha, size

    def discard(self):
        cleanup.discard_pending(self.pid)


def quota_for(caller: Caller) -> int:
    """The per-owner quota; a holder of `communities` writes without one."""
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


def file_path(community, file_id, n=None) -> str:
    path = f"/communities/{community}/files/{file_id}"
    return path if n is None else f"{path}/versions/{n}"


def written(
    conn, community, file_id, n, status_code=201, location=None
) -> JSONResponse:
    """A version as written: its metadata, its ETag, and, for a created resource, its
    `Location` (`location` is the server's base URL)."""
    info = records.stat(conn, records.version(conn, community, file_id, n))
    headers = {"ETag": etag(n)}
    if location is not None:
        headers["Location"] = (
            location + "/v1" + file_path(community, file_id, n if n > 1 else None)
        )
    return JSONResponse(info, status_code=status_code, headers=headers)


def commit_version(
    conn, community, file_id, upload, head, metadata, content_type, handle, kid, quota
) -> tuple:
    """The atomic step: quota under the owner's lock, the payload turned ready (or an
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


@app.put(
    "/v1/communities/{community}/collections/{collection}/files/{name}", status_code=201
)
async def put_file(
    caller: Annotated[Caller, Depends(authorize("putFile"))],
    community: str,
    collection: str,
    name: str,
    request: Request,
):
    """Create a file; its content and metadata become version 1. Creating is the one thing a
    `PUT` here does, so it takes `If-None-Match: *` (412 when the name holds a file). The name
    is reserved before any bytes move, and the file turns live only in the transaction that
    inserts v1."""
    precondition = request.headers.get("if-none-match")
    if precondition is None:
        refuse(428, "creating a file takes If-None-Match: *")
    if precondition.strip() != "*":
        refuse(400, "If-None-Match takes `*`: create only when the name holds no file")
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
            try:
                reserved = records.reserve_file(conn, found, collection, name, handle)
            except Conflict as e:
                conn.rollback()
                refuse(412, str(e))
            return found, handle, kid, quota_for(caller), reserved

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
            response = written(conn, community, file_id, n, location=caller.base_url)
        finish_after_commit(duplicate)
        return response

    try:
        return await run_in_threadpool(commit)
    except BaseException:
        await run_in_threadpool(upload.discard)
        await run_in_threadpool(release)
        raise


@app.post("/v1/communities/{community}/files/{file_id}/versions", status_code=201)
async def put_version(
    caller: Annotated[Caller, Depends(authorize("addFileVersion"))],
    community: str,
    file_id: uuid.UUID,
    request: Request,
):
    """Append a version: new content, new metadata, or both. A metadata-only version
    reuses the payload; a content-only version keeps the file's metadata. With If-Match the
    write applies only if the head is still the version the client built on."""
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
            response = written(conn, community, file_id, n, location=caller.base_url)
        finish_after_commit(duplicate)
        return response

    try:
        return await run_in_threadpool(commit)
    except BaseException:
        if upload is not None:
            await run_in_threadpool(upload.discard)
        raise


@app.delete("/v1/communities/{community}/files/{file_id}")
def delete_file(
    caller: Annotated[Caller, Depends(authorize("deleteFile"))],
    community: str,
    file_id: uuid.UUID,
    request: Request,
    reason: str | None = None,
):
    """Soft delete: append a tombstone version. The file still answers, serving the
    previous content with `X-Data-Deleted: true`; a later version restores it."""
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


def version_number(ref: str) -> int:
    if not ref.isdigit() or int(ref) < 1:
        refuse(400, "name a version by its number")
    return int(ref)


@app.delete("/v1/communities/{community}/files/{file_id}/versions/{ref}")
def purge(
    caller: Annotated[Caller, Depends(authorize("purgeVersion"))],
    community: str,
    file_id: uuid.UUID,
    ref: str,
):
    """Free one version's content (`manage` on its collection). The version stays
    addressable and answers 410 with its metadata; the bytes go only when no other live version
    shares them. When S3 refuses, the payload stays purging and the janitor finishes the job."""
    n = version_number(ref)
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


@app.get("/v1/communities/{community}/files/{file_id}/versions/{ref}/metadata")
def stat(
    caller: Annotated[Caller, Depends(authorize("statFileVersion"))],
    community: str,
    file_id: uuid.UUID,
    ref: str,
):
    info = readable(caller, community, file_id, ref)[1]
    return JSONResponse(info, headers={"ETag": etag(info["version"])})


@app.get("/v1/communities/{community}/files/{file_id}/versions")
def versions(
    caller: Annotated[Caller, Depends(authorize("listFileVersions"))],
    community: str,
    file_id: uuid.UUID,
):
    community = readable(caller, community, file_id, 1)[0]
    with db.connection() as conn:
        return {"versions": records.versions(conn, community, file_id)}


@app.get("/v1/communities/{community}/files/{file_id}/versions/{ref}")
async def content(
    caller: Annotated[Caller, Depends(authorize("getFileContent"))],
    community: str,
    file_id: uuid.UUID,
    ref: str,
    request: Request,
):
    """Stream one version: the service authorizes and streams every byte itself."""
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
    base = f"/v1/communities/{community}/files/{file_id}/versions"
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


@app.get("/v1/communities/{community}/files/{file_id}")
def get_file(
    caller: Annotated[Caller, Depends(authorize("getFile"))],
    community: str,
    file_id: uuid.UUID,
):
    """The file at its newest version: its metadata, as `…/versions/latest/metadata`."""
    info = readable(caller, community, file_id, "latest")[1]
    headers = {"ETag": etag(info["version"])}
    if info["file_deleted"]:
        headers["X-Data-Deleted"] = "true"
    return JSONResponse(info, headers=headers)


# ── collections and sharing ─────────────────────────────────────────────────────────────────
class CollectionIn(BaseModel):
    name: str = Field(pattern=NAME)


class CollectionPatch(BaseModel):
    public: bool


def require_manager(conn, caller: Caller, community, collection) -> Caller:
    """Changing a collection takes `manage` on it: its owner, or a holder of `manage` on
    every collection."""
    if not records.allows(conn, caller.context, rbac.MANAGE, community, collection):
        refuse(403, f"this needs manage on {community}/{collection}")
    return caller


@app.get("/v1/communities/{community}/collections")
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


@app.post("/v1/communities/{community}/collections", status_code=201)
def create_collection(
    caller: Annotated[Caller, Depends(authorize("createCollection"))],
    community: str,
    body: CollectionIn,
    response: Response,
):
    """Create a collection, owned by the caller's user, who reaches it through the
    owner allowance. It takes `write` in the community, with any collection value."""
    with db.connection() as conn:
        community = community_of(conn, community)
        if caller.user_id is None:
            refuse(403, "a collection is owned by a user: create it as a member")
        records.create_collection(conn, community, body.name, caller.user_id)
        located(response, caller, f"/communities/{community}/collections/{body.name}")
        return {
            "community": community,
            "name": body.name,
            "owner": caller.handle,
            "public": False,
        }


def collection_view(conn, caller: Caller, community: str, collection: str) -> dict:
    for item in records.readable_collections(conn, caller.context, community):
        if item["name"] == collection:
            return item
    records.collection_row(
        conn, community, collection
    )  # 404 for one that does not exist
    if caller.anonymous:
        refuse(401, "use an API key to read this collection")
    refuse(403, f"no read access to {community}/{collection}")


@app.get("/v1/communities/{community}/collections/{collection}")
def get_collection(
    caller: Annotated[Caller, Depends(authorize("getCollection"))],
    community: str,
    collection: str,
):
    """The collection, with what the caller may do in it."""
    with db.connection() as conn:
        return collection_view(conn, caller, community_of(conn, community), collection)


@app.patch("/v1/communities/{community}/collections/{collection}")
def update_collection(
    caller: Annotated[Caller, Depends(authorize("updateCollection"))],
    community: str,
    collection: str,
    body: CollectionPatch,
):
    """A collection's manager opens it to reads without a key, or closes it again."""
    with db.connection() as conn:
        community = community_of(conn, community)
        require_manager(conn, caller, community, collection)
        records.set_public(conn, community, collection, body.public)
        return {"community": community, "collection": collection, "public": body.public}


# ── parity: the change feed, lookups, promote and verify ──────────────────────────────
MAX_PAGE = 1000


class QueryIn(BaseModel):
    contains: dict
    since: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=MAX_PAGE)


class PromoteIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: str = Field(alias="from")  # the version to copy, by its citation
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


@app.get("/v1/communities/{community}/collections/{collection}/changes")
def changes(
    caller: Annotated[Caller, Depends(authorize("listChanges"))],
    community: str,
    collection: str,
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=MAX_PAGE),
):
    """Every version written into the collection after seq `since`, in seq order."""
    with db.connection() as conn:
        community = community_of(conn, community)
        who = lister(conn, caller, community, collection)
        rows = records.changes(conn, community, collection, since, limit)
        return page(conn, who, rows, since, limit)


@app.post("/v1/communities/{community}/collections/{collection}/files/search")
def query(
    caller: Annotated[Caller, Depends(authorize("queryCollection"))],
    community: str,
    collection: str,
    body: QueryIn,
):
    """Versions whose metadata contains `contains`, paged like changes."""
    with db.connection() as conn:
        community = community_of(conn, community)
        who = lister(conn, caller, community, collection)
        rows = records.query(
            conn, community, collection, body.contains, body.since, body.limit
        )
        return page(conn, who, rows, body.since, body.limit)


@app.get("/v1/communities/{community}/collections/{collection}/files")
def list_files(
    caller: Annotated[Caller, Depends(authorize("listFiles"))],
    community: str,
    collection: str,
    name: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=MAX_PAGE),
):
    """The collection's files, each at its newest version, tombstone or not (a deleted file
    still holds its name), ordered by name. With `name`, the file holding it."""
    after = ""
    if cursor is not None:
        try:
            after = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        except (binascii.Error, UnicodeDecodeError):
            refuse(400, "not a cursor this server issued")
    with db.connection() as conn:
        community = community_of(conn, community)
        who = lister(conn, caller, community, collection)
        if name is not None:
            found = records.find_name(conn, community, collection, name)
            files, more = ([] if found is None else [(found, name)]), False
        else:
            files = records.files_after(conn, community, collection, after, limit + 1)
            more = len(files) > limit
            files = files[:limit]
        items = []
        for file_id, _ in files:
            row = records.version(
                conn, community, file_id, records.latest_version(conn, file_id)["n"]
            )
            if records.can_read(conn, who, row):
                items.append(records.stat(conn, row))
        following = (
            base64.urlsafe_b64encode(files[-1][1].encode()).decode().rstrip("=")
            if more
            else None
        )
        return {"items": items, "next": following}


@app.get("/v1/communities/{community}/versions")
def by_hash(
    caller: Annotated[Caller, Depends(authorize("findByHash"))],
    community: str,
    sha: str = Query(alias="sha256"),
):
    """Every version of this community the caller may read that holds this content."""
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


@app.post("/v1/communities/{community}/collections/{collection}/files", status_code=201)
def promote(
    caller: Annotated[Caller, Depends(authorize("promoteVersion"))],
    community: str,
    collection: str,
    body: PromoteIn,
):
    """Copy one version, named by its citation in `from`, into the collection as a new file,
    atomically. Into `record` this is the gate's accept and takes `gate`; into any
    other collection, `manage` on it.

    With `stamp_json_pointer` the content is a JSON document, and the server writes the new
    version's own `created` at that pointer: the clock is the server's, never the caller's.
    The stamped bytes are a pending payload until the one transaction that allocates
    `created`, creates the file and inserts its version. They are re-serialized the
    way Symposium serializes canonical JSON: json.dumps defaults. The new version is
    credited to the source version's creator, with no key id."""
    name = body.name
    pointer = body.stamp_json_pointer
    cited = parse_citation(body.source)
    if cited is None:
        refuse(400, "`from` takes a citation: symposium-data:<file id>@v<n>")
    file_id, n = cited
    with db.connection() as conn:
        community = community_of(conn, community)
        handle = caller.handle
        source = records.version(conn, community, file_id, n)
        records.collection_row(conn, community, collection)
        if collection == "record":
            allowed = caller.allows(rbac.GATE, community)
        else:
            allowed = records.allows(
                conn, caller.context, rbac.MANAGE, community, collection
            )
        if not allowed or not records.can_read(conn, caller.context, source):
            refuse(
                403,
                f"promoting into {community}/{collection} is not within these grants",
            )
        name = name or source["name"]
        if not valid_file_name(name):
            refuse(400, "a file name is one path segment of 1-255 characters")
        if source["purged"]:
            refuse(410, "this version's content was purged")
        if source["deleted"]:
            refuse(409, "a tombstone cannot be promoted")
        if records.find_name(conn, community, collection, name):
            refuse(409, f"'{name}' already exists in {community}/{collection}")
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
            new = records.create_live_file(conn, community, collection, name)
            clock, payload = None, source["payload_id"]
            if document is not None:
                clock = records.allocate(conn, community, collection)
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
                # credited to the submitter, like a ported record; the
                # promoter's session only authorizes it
                source["created_by"],
                None,
                clock=clock,
            )
            conn.commit()
            response = written(conn, community, new, 1, location=caller.base_url)
        finish_after_commit(duplicate)
        return response

    try:
        return commit()
    except BaseException:
        if document is not None:
            cleanup.discard_pending(pid)
        raise


@app.get("/v1/communities/{community}/files/{file_id}/versions/{ref}/verification")
def verify(
    caller: Annotated[Caller, Depends(authorize("verifyCitation"))],
    community: str,
    file_id: uuid.UUID,
    ref: str,
    before: str | None = None,
    sha256: str | None = None,
):
    """The gate's check of a cited download: the citation
    `symposium-data:<file id>@v<n>` names this version. A version the caller cannot read
    answers exactly like one that never existed, so the check reveals nothing the caller may
    not read."""
    when = wire(parse_instant, before) if before else None
    n = version_number(ref)
    with db.connection() as conn:
        community = community_of(conn, community)
        who = caller.context
        missing = {"ok": False, "exists": False, "reason": "no such file version"}
        try:
            row = records.version(conn, community, file_id, n)
        except NotFound:
            return missing
        if not records.can_read(conn, who, row):
            return missing
        return records.verify(row, when, sha256)


# ── the port (see PORT_NDEX.md) ──────────────────────────────────────────────────────────
class PortCredentials(BaseModel):
    """The NDEx account a port-ndex reads from: a bound pair, held in memory only."""

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


@app.post("/v1/communities/{community}/ndex-imports", status_code=202)
def start_port(
    caller: Annotated[Caller, Depends(authorize("startNdexImport"))],
    community: str,
    body: PortIn,
    response: Response,
):
    """Start an import of a record from NDEx (port-ndex) into this empty community, in the
    background; one at a time, server-wide. Poll its `Location` for the outcome."""
    from . import port_ndex  # the port feature, isolated: imported only here

    with db.connection() as conn:
        community = community_of(conn, community)
        if records.holds_files(conn, community):
            refuse(
                400, f"community '{community}' holds files; a port-ndex needs it empty"
            )
        source = body.ndex_url.rstrip("/")  # the port-ndex source
        port_id = records.start_port(conn, community, caller.handle, source)
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
    located(response, caller, f"/communities/{community}/ndex-imports/{port_id}")
    with db.connection() as conn:
        return port_view(records.port(conn, community, port_id))


@app.get("/v1/communities/{community}/ndex-imports/{import_id}")
def port_status(
    caller: Annotated[Caller, Depends(authorize("getNdexImport"))],
    community: str,
    import_id: uuid.UUID,
):
    with db.connection() as conn:
        community = community_of(conn, community)
        port_id = import_id
        row = records.port(conn, community, port_id)
        if row is None:
            refuse(404, f"no port-ndex {port_id} in {community}")
        return port_view(row)
