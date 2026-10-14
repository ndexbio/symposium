"""Access to the server: one place that authenticates a request's API key (`authn`), and one
that decides whether its caller may call an operation (`authz`), for every route of `/v1`.
Collections decide the rest (`records.can_read` and the checks beside it)."""

from .authn import authenticate, bearer, standing
from .authz import (
    authorize,
    caller_for,
    check,
    require_admin,
    require_key,
    require_session,
    resolve_community,
    wire,
)
from .caller import Caller
from .contract import ANONYMOUS_ALWAYS, ANONYMOUS_PUBLIC, Contract, Rule, load

__all__ = [
    "ANONYMOUS_ALWAYS",
    "ANONYMOUS_PUBLIC",
    "Caller",
    "Contract",
    "Rule",
    "authenticate",
    "authorize",
    "bearer",
    "caller_for",
    "check",
    "load",
    "require_admin",
    "require_key",
    "require_session",
    "resolve_community",
    "standing",
    "wire",
]
