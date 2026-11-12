"""Authorization at the door: who may call an operation at all.

Every route of `/v1`, generated or hand-written, depends on `authorize("<operationId>")`, which
applies that operation's `x-grants`, `x-session` and `x-anonymous` as `contract.Contract.rules`
reads them, through the caller's `UserContext.allowsRequest`. Which collections a caller may
then use, the handler decides with the same check, naming the collection.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..wire import valid_community
from .authn import anonymous, authenticate, presents_key
from .caller import Caller
from .contract import Rule

# what the server wires in at startup: db, records, keys, contract and public_url
_wired: dict = {}


def wire(**parts) -> None:
    _wired.update(parts)


def contract_rules() -> dict:
    """The contract's rule for each operation, once the server has wired the contract."""
    contract = _wired.get("contract")
    return contract.rules if contract is not None else {}


def public_url() -> str | None:
    """The server's configured public URL (SYMPOSIUM_SERVER_PUBLIC_URL), or None."""
    return _wired.get("public_url")


def base_url(request: Request) -> str:
    return _wired.get("public_url") or str(request.base_url).rstrip("/")


def resolve_community(conn, records, name: str | None) -> str | None:
    """The community a path names, as it was created; 404 when it is not a slug or unknown."""
    if name is None:
        return None
    found = records.community_name(conn, name) if valid_community(name) else None
    if found is None:
        raise HTTPException(404, f"no community '{name}'")
    return found


def caller_for(conn, request: Request) -> Caller:
    """The caller behind `request`."""
    return authenticate(
        conn,
        _wired["records"],
        _wired["keys"],
        request,
        base_url(request),
    )


def check(rule: Rule, caller: Caller, community: str | None) -> Caller:
    """`caller` when `rule` lets it call for `community` (the path's, or the caller's own on a
    server-wide route); refused otherwise. An anonymous caller passes only an operation that
    answers without a key; the operation then reads only public collections."""
    if caller.anonymous:
        if rule.anonymous is None:
            raise HTTPException(
                401, "an API key is required: Authorization: Bearer sak_…"
            )
        return caller
    if rule.session and not caller.session:
        raise HTTPException(
            403, "this takes a signed-in session, not an issued API key"
        )
    if not rule.grants:
        if community is not None and caller.community not in (None, community):
            raise HTTPException(403, f"this key belongs to {caller.community}")
        return caller
    if not any(caller.allows(grant, community) for grant in rule.grants):
        raise HTTPException(
            403,
            "this needs one of these grants here: " + ", ".join(rule.grants),
        )
    return caller


def authorize(operation_id: str):
    """The dependency each generated route declares, for its own operation."""

    def dependency(request: Request) -> Caller:
        rule = _wired["contract"].rules[operation_id]
        name = request.path_params.get("community")
        if name is None and not presents_key(request):
            # nothing to look up: /v1/status answers even while PostgreSQL is down
            return check(rule, anonymous(request, base_url(request)), None)
        with _wired["db"].connection() as conn:
            community = resolve_community(
                conn, _wired["records"], request.path_params.get("community")
            )
            caller = caller_for(conn, request)
            return check(
                rule, caller, community if name is not None else caller.community
            )

    dependency.__name__ = f"authorize_{operation_id}"
    return dependency
