"""Access to the server: one place that authenticates a request's API key (`authn`), and one
that decides whether its caller may call an operation (`authz`), for every route of `/v1`.
Collections decide the rest (`records.can_read` and the checks beside it)."""

from .authn import authenticate, standing
from .authz import authorize, check, contract_rules, wire
from .caller import Caller
from .contract import Contract, Rule, load

__all__ = [
    "Caller",
    "Contract",
    "Rule",
    "authenticate",
    "authorize",
    "check",
    "contract_rules",
    "load",
    "standing",
    "wire",
]
