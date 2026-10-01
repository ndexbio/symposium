"""Symposium Data HTTP API. Every byte is streamed by this service; S3 is never exposed."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import API_VERSION, version
from .auth import PublicKeys, Secrets, Tokens
from .records import Records
from .runtime import Database, PayloadStore, Settings

settings = Settings()
db = Database(settings)
store = PayloadStore(settings)
records = Records()
keys = PublicKeys()
secrets = Secrets()
tokens = Tokens(settings.token_key_file, settings.server_id, settings.token_ttl)

# Handles and community names: what Symposium account names look like (agent_lyra, demo-admin).
NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


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
        require_admin(conn, request)
        added, removed = records.set_roster(conn, community, body.handles)
        return {
            "community": community,
            "roster": sorted(set(body.handles)),
            "added": added,
            "removed": removed,
        }
