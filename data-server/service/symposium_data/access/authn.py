"""Authentication: the API key a request presents, and the caller its row names.

Every route takes one credential, `Authorization: Bearer sak_…`, or none. A key's row says who
calls: its kind (session or issued), its role, its community and its Member. A key keeps its
standing only while what it stands on holds: a Member's key while the Member is on the roster
and registered, a session while the Ed25519 key that signed it in is active.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..api_keys import PREFIX, SESSION, ApiKeys, KeyRow
from .caller import ANONYMOUS_KIND, Caller


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header.split(None, 1)[1].strip()


def presents_key(request: Request) -> bool:
    return bearer(request) is not None


def anonymous(request: Request, base_url: str = "") -> Caller:
    return Caller(
        kind=ANONYMOUS_KIND,
        base_url=base_url,
        client_addr=request.client.host if request.client else None,
    )


def standing(
    conn, records, row: KeyRow, community: str | None
) -> tuple[int, str] | None:
    """(status, why) when a live key may not act now, or None. Runs on every request and every
    stream beat. A key that lost its standing answers 401; a sound key used on another
    community answers 403."""
    if row.role == "admin":
        if not records.admin_key_is_active(conn, row.ed25519_kid):
            return 401, "the admin key this session was signed in with is retired"
        return None
    if row.role == "member":
        if not records.on_roster(conn, row.community, row.handle):
            return (
                401,
                f"'{row.handle}' is no longer on the roster of {row.community}",
            )
        if row.kind == SESSION:
            if not records.key_is_active(
                conn, row.community, row.handle, row.ed25519_kid
            ):
                return 401, "the key this session was signed in with is retired"
        elif not records.active_keys(conn, row.community, row.handle):
            return 401, f"'{row.handle}' has no registered key in {row.community}"
    if community is not None and row.community != community:
        return 403, f"this key belongs to {row.community}"
    return None


def authenticate(
    conn,
    records,
    keys: ApiKeys,
    request: Request,
    community: str | None,
    base_url: str = "",
) -> Caller:
    """The caller behind `request`, anonymous when it presents no key. A key that is not one,
    is unknown, revoked or expired, or has lost its standing is refused here."""
    caller = anonymous(request, base_url)
    credential = bearer(request)
    if credential is None:
        return caller
    if not credential.startswith(PREFIX):
        raise HTTPException(
            401, "this API takes an API key: Authorization: Bearer sak_…"
        )
    row = keys.find(conn, credential)
    conn.commit()  # a refreshed last_used stays, even when the request is refused
    if row is None:
        raise HTTPException(401, "the API key is unknown, expired or revoked")
    refusal = standing(conn, records, row, community)
    if refusal:
        raise HTTPException(*refusal)
    caller.kind, caller.role = row.kind, row.role
    caller.handle, caller.label = row.handle, row.label
    caller.key_id, caller.community = row.id, row.community
    caller.ed25519_kid = row.ed25519_kid
    return caller
