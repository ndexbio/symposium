"""Authorization from the contract (api/DESIGN.md §3, §4.4). Every generated route depends on
`authorize("<operationId>")`, which applies that operation's `x-roles`, `security` and
`x-anonymous` as `contract.Contract.rules` read them from api/openapi.yaml.

Callers are an API key (`sak_…`), the server admin's Ed25519 token, or nobody. A key is
checked again on every request: its roster entry for a `member`, its admin binding for an
`admin`, and its label against the roster for a `non-member`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Request

from . import provider
from .contract import ANONYMOUS_ALWAYS, Rule
from .errors import ApiError
from .keys import PREFIX, KeyRow

ROLE_ORDER = ("non-member", "member", "admin")


@dataclass
class Caller:
    """Who is calling, once authorized."""

    kind: str  # "anonymous", "api_key" or "admin_token"
    role: str | None = None
    username: str | None = None
    key_id: object | None = None
    scope: str | None = None  # the key's community; None for server scope or no key
    base_url: str = ""
    client_addr: str | None = None
    extras: dict = field(default_factory=dict)

    @property
    def handle(self) -> str | None:
        """The Member this caller publishes as and reads its own submissions as."""
        if self.role in ("member", "admin"):
            return self.username
        return None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header.split(None, 1)[1].strip()


def resolve_community(conn, name: str | None) -> str | None:
    """The community a path names, as it was created; 404 when it is unknown."""
    if name is None:
        return None
    found = provider.runtime().records.community_name(conn, name)
    if found is None:
        raise ApiError(404, f"no community '{name}'")
    return found


def standing(conn, row: KeyRow, community: str | None) -> str | None:
    """Why a live key may not act now, or None. Runs on every request and every stream beat."""
    records = provider.runtime().records
    if row.role == "member":
        if not records.on_roster(conn, row.community, row.username):
            return f"'{row.username}' is no longer on the roster of {row.community}"
        if not records.active_keys(conn, row.community, row.username):
            return f"'{row.username}' has not registered in {row.community}"
    elif row.role == "admin":
        if not records.admin_key_is_active(conn, row.admin_kid):
            return "the admin key this API key was bound to has been retired"
        if row.username != records.config(conn, "admin"):
            return f"'{row.username}' is not the server's admin"
    elif row.community and records.on_roster(conn, row.community, row.username):
        return f"the label '{row.username}' now names a member of {row.community}"
    if row.community and community and row.community != community:
        return f"this key is scoped to {row.community}"
    return None


def check(rule: Rule, request: Request) -> Caller:
    runtime = provider.runtime()
    path_community = request.path_params.get("community")
    caller = Caller(
        kind="anonymous",
        base_url=runtime.public_url or str(request.base_url).rstrip("/"),
        client_addr=request.client.host if request.client else None,
    )
    credential = bearer(request)
    with runtime.db.connection() as conn:
        community = resolve_community(conn, path_community)
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
        if credential.startswith(PREFIX):
            row = provider.keys().find(conn, credential)
            conn.commit()
            if row is None:
                raise ApiError(401, "the API key is unknown, expired or revoked")
            if not rule.api_key:
                raise ApiError(
                    403, "this operation takes the server admin's Ed25519 token alone"
                )
            why = standing(conn, row, community)
            if why:
                raise ApiError(403 if "scoped" in why else 401, why)
            if row.role not in rule.roles:
                raise ApiError(
                    403,
                    f"a {row.role} key may not do this; it takes "
                    + ", ".join(r for r in ROLE_ORDER if r in rule.roles),
                )
            caller.kind, caller.role, caller.username = (
                "api_key",
                row.role,
                row.username,
            )
            caller.key_id, caller.scope = row.id, row.community
            return caller
        claims = runtime.tokens.read(credential)
        if claims is None:
            raise ApiError(401, "the token is not valid or has expired")
        if not rule.admin_token:
            raise ApiError(
                401, "this API takes an API key: Authorization: Bearer sak_…"
            )
        if not claims.get("adm") or not runtime.records.admin_key_is_active(
            conn, claims["kid"]
        ):
            raise ApiError(403, "only the server admin's token may do this")
        caller.kind, caller.role, caller.username = (
            "admin_token",
            "admin",
            claims["sub"],
        )
        caller.extras["admin_kid"] = claims["kid"]
        return caller


def authorize(operation_id: str):
    """The dependency each generated route declares, for its own operation."""
    rule = None

    def dependency(request: Request) -> Caller:
        nonlocal rule
        if rule is None:
            rule = provider.contract().rules[operation_id]
        return check(rule, request)

    dependency.__name__ = f"authorize_{operation_id}"
    return dependency
