"""Authorization from the contract (api/DESIGN.md §3, §4.4). Every generated route depends on
`authorize("<operationId>")`, which applies that operation's `x-roles`, `security` and
`x-anonymous` as `contract.Contract.rules` read them from api/openapi.yaml.

A caller is an API key (`sak_…`) or nobody; the Data API takes no other credential. Each key
belongs to one community and acts only there. A `member` key names its Member in the key's
own row, the Member having created it, and that Member is checked again on every request:
still on the roster and still registered.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from symposium_data.api_keys import PREFIX, ApiKeys, KeyRow

from . import provider
from .caller import Caller
from .contract import ANONYMOUS_ALWAYS, Contract, Rule
from .errors import ApiError


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header.split(None, 1)[1].strip()


def resolve_community(conn, records, name: str | None) -> str | None:
    """The community a path names, as it was created; 404 when it is unknown."""
    if name is None:
        return None
    found = records.community_name(conn, name)
    if found is None:
        raise ApiError(404, f"no community '{name}'")
    return found


def standing(
    conn, records, row: KeyRow, community: str | None
) -> tuple[int, str] | None:
    """(status, why) when a live key may not act now, or None. Runs on every request and every
    stream beat. A key that lost its standing answers 401; a sound key used on another
    community answers 403."""
    if row.handle is not None:
        if not records.on_roster(conn, row.community, row.handle):
            return (
                401,
                f"'{row.handle}' is no longer on the roster of {row.community}",
            )
        if not records.active_keys(conn, row.community, row.handle):
            return 401, f"'{row.handle}' has no registered key in {row.community}"
    if community is not None and row.community != community:
        return 403, f"this key belongs to {row.community}"
    return None


def check(
    rule: Rule, request: Request, runtime: provider.Runtime, keys: ApiKeys
) -> Caller:
    """Who `request` comes from, when `rule` lets them call; ApiError otherwise. Everything it
    reads arrives as an argument, so one rule is testable without the server wired."""
    path_community = request.path_params.get("community")
    caller = Caller(
        kind="anonymous",
        base_url=runtime.public_url or str(request.base_url).rstrip("/"),
        client_addr=request.client.host if request.client else None,
    )
    credential = bearer(request)
    with runtime.db.connection() as conn:
        community = resolve_community(conn, runtime.records, path_community)
        if credential is None:
            if rule.anonymous is None:
                raise ApiError(
                    401, "an API key is required: Authorization: Bearer sak_…"
                )
            if rule.anonymous != ANONYMOUS_ALWAYS:
                row = runtime.records.collection_row(conn, community, "record")
                if not row["public"]:
                    raise ApiError(
                        401,
                        f"the record of {community} is private: an API key is required",
                    )
            return caller
        if not credential.startswith(PREFIX):
            raise ApiError(
                401, "this API takes an API key: Authorization: Bearer sak_…"
            )
        row = keys.find(conn, credential)
        conn.commit()
        if row is None:
            raise ApiError(401, "the API key is unknown, expired or revoked")
        refusal = standing(conn, runtime.records, row, community)
        if refusal:
            raise ApiError(*refusal)
        if row.role not in rule.roles:
            raise ApiError(
                403,
                f"a {row.role} key may not do this; it takes " + ", ".join(rule.roles),
            )
        caller.kind, caller.role = "api_key", row.role
        caller.handle, caller.label = row.handle, row.label
        caller.key_id, caller.community = row.id, row.community
        return caller


def authorize(operation_id: str):
    """The dependency each generated route declares, for its own operation. The runtime, the
    keys and the contract arrive as FastAPI dependencies, so a test may override any of them."""

    def dependency(
        request: Request,
        runtime: Annotated[provider.Runtime, Depends(provider.runtime)],
        keys: Annotated[ApiKeys, Depends(provider.keys)],
        contract: Annotated[Contract, Depends(provider.contract)],
    ) -> Caller:
        return check(contract.rules[operation_id], request, runtime, keys)

    dependency.__name__ = f"authorize_{operation_id}"
    return dependency
