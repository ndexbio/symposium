"""Authorization at the door: who may call an operation at all.

Every route of `/v1`, generated or hand-written, depends on `authorize("<operationId>")`, which
applies that operation's `x-roles`, `x-session` and `x-anonymous` as `contract.Contract.rules`
reads them. What a caller may then do to a collection, the collection decides: its owner, its grants and whether it is public
(`records.can_read` and the checks beside it).
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


def caller_for(conn, request: Request, community: str | None) -> Caller:
    """The caller behind `request`, for a route of `community` (None: server-wide)."""
    return authenticate(
        conn,
        _wired["records"],
        _wired["keys"],
        request,
        community,
        base_url(request),
    )


def check(rule: Rule, caller: Caller) -> Caller:
    """`caller` when `rule` lets it call; refused otherwise. An anonymous caller passes only an
    operation that answers without a key; the operation then reads only public collections."""
    if caller.anonymous:
        if rule.anonymous is None:
            raise HTTPException(
                401, "an API key is required: Authorization: Bearer sak_…"
            )
        return caller
    if caller.role not in rule.roles:
        raise HTTPException(
            403,
            f"a {caller.role} key may not do this; it takes " + ", ".join(rule.roles),
        )
    if rule.session and caller.kind != "session":
        raise HTTPException(
            403, "this takes a session key, from the session management routes"
        )
    return caller


def authorize(operation_id: str):
    """The dependency each generated route declares, for its own operation."""

    def dependency(request: Request) -> Caller:
        rule = _wired["contract"].rules[operation_id]
        name = request.path_params.get("community")
        if name is None and not presents_key(request):
            # nothing to look up: /v1/status answers even while PostgreSQL is down
            return check(rule, anonymous(request, base_url(request)))
        with _wired["db"].connection() as conn:
            community = resolve_community(
                conn, _wired["records"], request.path_params.get("community")
            )
            return check(rule, caller_for(conn, request, community))

    dependency.__name__ = f"authorize_{operation_id}"
    return dependency
