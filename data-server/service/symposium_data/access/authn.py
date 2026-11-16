"""Authentication: the API key a request presents, and the caller its row names.

Every route takes one credential, `Authorization: Bearer sak_…`, or none. A session key acts
as the user who signed in; a member key acts as the user who issued it; a non-member key is its
own principal. A key keeps its standing only while its user is not removed and, for a session,
while the Ed25519 key that signed it in is active. The caller's `UserContext` is compiled from
its principal's live role assignments on every request and every stream beat.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..api_keys import PREFIX, SESSION, ApiKeys, KeyRow
from . import rbac
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


def standing(conn, records, row: KeyRow) -> str | None:
    """Why a live key may not act now, or None. Runs on every request and every stream beat."""
    if row.user_id is None:
        return None
    user = records.user(conn, row.user_id)
    if user is None or user["removed"] is not None:
        return "the user this key acts as was removed"
    if row.kind == SESSION and not records.key_is_active(
        conn, row.user_id, row.ed25519_kid
    ):
        return "the key this session key was obtained with is retired"
    return None


def context_of(conn, records, row: KeyRow):
    """The `UserContext` of a live key: its user for a session, its issuer for a member key
    (with the key's own roles), itself for a non-member key; an issued key's grants never
    exceed what its issuer reaches now."""
    if row.kind == SESSION:
        return records.context_for(
            conn,
            principal_id=row.user_id,
            principal_name=row.handle,
            community=row.community,
            via_session=True,
            user_id=row.user_id,
        )
    issuer = records.issuer_of(conn, row.community, row.created_by)
    if issuer is None:
        # an issuer removed: its keys go with it; until then the key holds nothing
        return rbac.UserContext(
            principal_id=row.id,
            principal_name=row.label,
            community=row.community,
            via_session=False,
            grants={},
        )
    return records.context_for(
        conn,
        principal_id=row.user_id if row.user_id is not None else row.id,
        principal_name=row.handle if row.user_id is not None else row.label,
        community=row.community,
        via_session=False,
        api_key_id=row.id,
        issuer=issuer,
    )


def authenticate(
    conn,
    records,
    keys: ApiKeys,
    request: Request,
    base_url: str = "",
) -> Caller:
    """The caller behind `request`, anonymous when it presents no key. A key that is not one,
    is unknown or expired, or has lost its standing is refused here (401)."""
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
        raise HTTPException(401, "the API key is unknown or expired")
    refusal = standing(conn, records, row)
    if refusal:
        raise HTTPException(401, refusal)
    caller.kind = row.kind
    caller.context = context_of(conn, records, row)
    caller.user_id, caller.handle, caller.label = row.user_id, row.handle, row.label
    caller.key_id, caller.community = row.id, row.community
    caller.ed25519_kid = row.ed25519_kid
    return caller
