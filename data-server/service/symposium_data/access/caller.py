"""Who is calling, once authenticated: the one type every route, hand-written or generated,
shares. Its `context` is the resolved `UserContext` every access check consults."""

from __future__ import annotations

from dataclasses import dataclass

from .rbac import UserContext

ANONYMOUS_KIND = "anonymous"


@dataclass
class Caller:
    kind: str  # "anonymous", or the key's kind: "session" or "issued"
    context: UserContext | None = None  # None when anonymous
    user_id: object | None = None  # the user it acts as; None for a non-member key
    handle: str | None = None  # that user's handle
    label: str | None = None  # the name an issued key's owner gave it
    key_id: object | None = None
    community: str | None = None  # the principal's community; None when server-level
    ed25519_kid: str | None = None  # a session's signing key
    base_url: str = ""
    client_addr: str | None = None

    @property
    def anonymous(self) -> bool:
        return self.kind == ANONYMOUS_KIND

    @property
    def session(self) -> bool:
        return self.kind == "session"

    def allows(self, grant: str, community: str | None, collection=None) -> bool:
        """`context.allowsRequest`, false for an anonymous caller."""
        return self.context is not None and self.context.allowsRequest(
            grant, community, collection
        )
