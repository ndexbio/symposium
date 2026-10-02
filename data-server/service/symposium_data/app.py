"""Symposium Data HTTP API. Every byte is streamed by this service; S3 is never exposed."""

from __future__ import annotations

import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from . import API_VERSION, version
from .auth import PublicKeys, Secrets, Tokens
from .jobs import Jobs
from .records import Conflict, NotFound, PreconditionFailed, QuotaExceeded, Records
from .runtime import Database, MultipartWriter, PayloadStore, Settings
from .wire import (
    WireError,
    digest_header,
    etag,
    parse_digest,
    parse_if_match,
    parse_metadata,
    valid_file_name,
)

settings = Settings()
db = Database(settings)
store = PayloadStore(settings)
records = Records()
keys = PublicKeys()
secrets = Secrets()
tokens = Tokens(settings.token_key_file, settings.server_id, settings.token_ttl)
jobs = Jobs(settings, db, store, records)
cleanup = jobs.cleanup

# Handles and community names: what Symposium account names look like (agent_lyra, demo-admin).
NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.migrate()
    db.open()
    store.ensure_bucket()
    jobs.start()
    yield
    jobs.shutdown()
    db.pool.close()


app = FastAPI(title="Symposium Data", version=version(), lifespan=lifespan)


@app.exception_handler(NotFound)
async def _not_found(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=404)


@app.exception_handler(Conflict)
async def _conflict(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=409)


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


# ── identity ────────────────────────────────────────────────────────────────────────────────
class ChallengeIn(BaseModel):
    handle: str = Field(pattern=NAME)


class TokenIn(BaseModel):
    handle: str = Field(pattern=NAME)
    nonce: str
    signature: str


class RegisterIn(BaseModel):
    handle: str = Field(pattern=NAME)
    community: str = Field(pattern=NAME)
    public_jwk: dict
    nonce: str
    signature: str
    invite: str | None = None


class RotateIn(BaseModel):
    public_jwk: dict
    nonce: str
    signature: str


class RosterIn(BaseModel):
    handles: list[str] = Field(max_length=10_000)


def refuse(status: int, message: str, conn=None):
    """Raise an HTTP error. With `conn`, commit first: work already done (a challenge consumed)
    must stay done even though the request is refused."""
    if conn is not None:
        conn.commit()
    raise HTTPException(status, message)


def owner_of(conn, request: Request) -> tuple[str, str]:
    """The (handle, kid) behind a valid bearer token whose key is still active."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        refuse(401, "a bearer token is required")
    claims = tokens.read(header.split(None, 1)[1].strip())
    if claims is None:
        refuse(401, "the token is not valid or has expired")
    if not records.key_is_active(conn, claims["sub"], claims["kid"]):
        refuse(401, "the token's key is no longer active")
    return claims["sub"], claims["kid"]


def require_admin(conn, request: Request) -> str:
    handle, _ = owner_of(conn, request)
    if handle != records.config(conn, "admin"):
        refuse(403, "only the admin may do this")
    return handle


def checked_new_key(conn, handle: str, body) -> tuple[str, dict]:
    """Consume the challenge and check the new key's proof of possession -> (kid, jwk)."""
    if not records.take_challenge(conn, handle, body.nonce):
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


@app.post("/v1/auth/challenge")
def challenge(body: ChallengeIn):
    nonce = secrets.new("n_")
    with db.connection() as conn:
        records.add_challenge(conn, body.handle, nonce)
    return {"nonce": nonce, "expires_in": 300}


@app.post("/v1/auth/token")
def token(body: TokenIn):
    with db.connection() as conn:
        if not records.take_challenge(conn, body.handle, body.nonce):
            refuse(401, "the challenge is unknown, spent or expired", conn)
        for key in records.active_keys(conn, body.handle):
            if keys.verify(key["jwk"], body.nonce.encode(), body.signature):
                return {
                    "token": tokens.issue(body.handle, key["kid"]),
                    "expires_in": tokens.ttl,
                    "kid": key["kid"],
                }
        refuse(401, "the signature does not match an active key of this handle", conn)


@app.post("/v1/owners", status_code=201)
def register(body: RegisterIn):
    """Register a handle with a key generated on the member's machine (R-D1, R-D5)."""
    with db.connection() as conn:
        if records.config(conn, "admin") is None:
            refuse(503, "the server is not initialized")
        kid, jwk = checked_new_key(conn, body.handle, body)
        if not records.on_roster(conn, body.community, body.handle):
            refuse(403, f"'{body.handle}' is not on the {body.community} roster", conn)
        if records.active_keys(conn, body.handle):
            refuse(409, f"'{body.handle}' is already registered", conn)
        if settings.registration == "invite" and not records.consume_invite(
            conn, secrets.digest(body.invite or ""), body.community, body.handle
        ):
            refuse(
                403,
                "a valid, unused invite for this handle and community is required",
                conn,
            )
        records.register(conn, body.handle, kid, jwk)
        return {"handle": body.handle, "kid": kid, "community": body.community}


@app.post("/v1/owners/{handle}/keys", status_code=201)
def rotate(handle: str, body: RotateIn, request: Request):
    """Replace the caller's key. Signed by the current token and proven by the new key; the
    old key is retired, not deleted, so attribution survives."""
    with db.connection() as conn:
        current, _ = owner_of(conn, request)
        if current != handle:
            refuse(403, "an owner may rotate only their own key")
        kid, jwk = checked_new_key(conn, handle, body)
        if conn.execute("SELECT 1 FROM owner_keys WHERE kid = %s", (kid,)).fetchone():
            refuse(409, "that key is already on record", conn)
        records.rotate(conn, handle, kid, jwk)
        return {"handle": handle, "kid": kid}


@app.get("/v1/whoami")
def whoami(request: Request):
    with db.connection() as conn:
        handle, kid = owner_of(conn, request)
        owner = records.owner(conn, handle)
        return {
            "handle": handle,
            "kid": kid,
            "admin": handle == records.config(conn, "admin"),
            "communities": {
                community: [
                    {"collection": collection, "perm": perm}
                    for collection, perm in records.grants(conn, community, handle)
                ]
                for community in records.communities_of(conn, handle)
            },
            "suspect_after": owner["suspect_after"].isoformat()
            if owner["suspect_after"]
            else None,
        }


@app.put("/v1/c/{community}/roster")
def roster(community: str, body: RosterIn, request: Request):
    """Replace the community roster (admin only). Members get the default grants (R-D6)."""
    if not re.match(NAME, community) or not all(
        re.match(NAME, h) for h in body.handles
    ):
        refuse(422, "community and handles must be plain names")
    with db.connection() as conn:
        admin = require_admin(conn, request)
        records.ensure_collections(conn, community, admin)
        added, removed = records.set_roster(conn, community, body.handles)
        return {
            "community": community,
            "roster": sorted(set(body.handles)),
            "added": added,
            "removed": removed,
        }


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


async def stream_upload(request: Request, owner: str, file_id=None) -> Upload:
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
            if settings.quota_bytes and declared_size is not None:
                if records.usage(conn, owner) + declared_size > settings.quota_bytes:
                    refuse(413, "this upload would exceed the owner's quota")
            return records.begin_payload(conn, owner)

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


def written(conn, file_id, n, status_code=201) -> JSONResponse:
    info = records.stat(conn, records.version(conn, file_id, n))
    return JSONResponse(info, status_code=status_code, headers={"ETag": etag(n)})


def commit_version(
    conn, file_id, upload, head, metadata, content_type, handle, kid
) -> tuple:
    """The atomic step (R-A6): quota under the owner's lock, the payload turned ready (or an
    identical one reused), and the version inserted, all in the caller's transaction.
    -> (version number, s3 key to delete after commit or None)."""
    if upload is None:
        payload, duplicate = head["payload_id"], None
    else:
        payload, duplicate = records.commit_payload(
            conn, upload.pid, upload.sha, upload.size, handle, settings.quota_bytes
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


@app.put("/v1/c/{community}/{collection}/files/{name}", status_code=201)
async def put_file(community: str, collection: str, name: str, request: Request):
    """Create a file; its content and metadata become version 1. The name is reserved before
    any bytes move, and the file turns live only in the transaction that inserts v1."""
    if not valid_file_name(name):
        refuse(400, "a file name is one path segment of 1-255 characters")
    metadata = wire(parse_metadata, request.headers.get("x-data-metadata")) or {}
    content_type = request.headers.get("content-type", "application/octet-stream")

    def reserve():
        with db.connection() as conn:
            handle, kid = owner_of(conn, request)
            if not records.collection_exists(conn, community, collection):
                refuse(404, f"no collection {community}/{collection}")
            if not records.can_create(conn, handle, community, collection):
                refuse(403, f"no write access to {community}/{collection}")
            return (
                handle,
                kid,
                records.reserve_file(conn, community, collection, name, handle),
            )

    handle, kid, file_id = await run_in_threadpool(reserve)

    def release():
        with db.connection() as conn:
            records.release_reservation(conn, file_id)

    try:
        upload = await stream_upload(request, handle, file_id)
    except BaseException:
        await run_in_threadpool(release)
        raise

    def commit():
        with db.connection() as conn:
            try:
                records.claim_reservation(conn, file_id, handle)
                n, duplicate = commit_version(
                    conn, file_id, upload, None, metadata, content_type, handle, kid
                )
            except (QuotaExceeded, PreconditionFailed) as e:
                conn.rollback()
                mapped(e)
            conn.commit()
            response = written(conn, file_id, n)
        finish_after_commit(duplicate)
        return response

    try:
        return await run_in_threadpool(commit)
    except BaseException:
        await run_in_threadpool(upload.discard)
        await run_in_threadpool(release)
        raise


@app.post("/v1/files/{file_id}/versions", status_code=201)
async def put_version(file_id: uuid.UUID, request: Request):
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
            handle, kid = owner_of(conn, request)
            row = records.file_row(conn, file_id)
            if not records.can_modify(conn, handle, row):
                refuse(403, "only the file's creator or the admin may add versions")
            head = records.latest_version(conn, file_id)
            if expected is not None and head["n"] != expected:
                # fail fast, before any bytes are streamed; re-checked under the lock below
                refuse(412, f"the file is at v{head['n']}, not v{expected}")
            return handle, kid

    handle, kid = await run_in_threadpool(check)
    upload = None if metadata_only else await stream_upload(request, handle)

    def commit():
        with db.connection() as conn:
            try:
                head = records.lock_head(conn, file_id, expected)
                n, duplicate = commit_version(
                    conn,
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
            response = written(conn, file_id, n)
        finish_after_commit(duplicate)
        return response

    try:
        return await run_in_threadpool(commit)
    except BaseException:
        if upload is not None:
            await run_in_threadpool(upload.discard)
        raise


@app.delete("/v1/files/{file_id}")
def delete_file(file_id: uuid.UUID, request: Request, reason: str | None = None):
    """Soft delete (R-B1): append a tombstone that keeps serving the previous content."""
    expected = wire(parse_if_match, request.headers.get("if-match"))
    with db.connection() as conn:
        handle, kid = owner_of(conn, request)
        row = records.file_row(conn, file_id)
        if not records.can_modify(conn, handle, row):
            refuse(403, "only the file's creator or the admin may delete it")
        try:
            n = records.tombstone(conn, file_id, handle, kid, reason, expected)
        except PreconditionFailed as e:
            conn.rollback()
            mapped(e)
        conn.commit()
        return written(conn, file_id, n, status_code=200)


def readable(request: Request, file_id, ref):
    with db.connection() as conn:
        handle, _ = owner_of(conn, request)
        row = records.version(conn, file_id, ref)
        if not records.can_read(conn, handle, row):
            refuse(403, "no read access to this file")
        return records.stat(conn, row), row["s3_key"]


@app.get("/v1/files/{file_id}/v/{ref}/stat")
def stat(file_id: uuid.UUID, ref: str, request: Request):
    info = readable(request, file_id, ref)[0]
    return JSONResponse(info, headers={"ETag": etag(info["version"])})


@app.get("/v1/files/{file_id}/versions")
def versions(file_id: uuid.UUID, request: Request):
    readable(request, file_id, 1)
    with db.connection() as conn:
        return {"versions": records.versions(conn, file_id)}


@app.get("/v1/files/{file_id}/v/{ref}")
async def content(file_id: uuid.UUID, ref: str, request: Request):
    """Stream one version (R-E5): the service authorizes and streams every byte itself."""
    info, key = await run_in_threadpool(readable, request, file_id, ref)
    if info["purged"]:
        return JSONResponse(
            {"detail": "this version's content was purged", **info}, status_code=410
        )
    byte_range = request.headers.get("range")
    obj = await run_in_threadpool(store.open_read, key, byte_range)
    links = [f'</v1/files/{file_id}/v/{info["latest"]}>; rel="latest"']
    if info["prev"]:
        links.append(f'</v1/files/{file_id}/v/{info["prev"]}>; rel="prev"')
    if info["next"]:
        links.append(f'</v1/files/{file_id}/v/{info["next"]}>; rel="next"')
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
