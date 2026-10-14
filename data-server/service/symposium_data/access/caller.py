"""Who is calling, once authenticated: the one type every route, hand-written or generated,
shares. It depends on nothing but the principal the collection checks take."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import ANONYMOUS, Principal

ANONYMOUS_KIND = "anonymous"


@dataclass
class Caller:
    kind: str  # "anonymous", or the key's kind: "session" or "issued"
    role: str | None = None  # "admin", "member" or "non-member"; None when anonymous
    # the Member a member key or session acts as, or the admin; None for a non-member key
    handle: str | None = None
    label: str | None = None  # the name an issued key's owner gave it
    key_id: object | None = None
    # the key's one community; None for an anonymous caller and for the admin's session
    community: str | None = None
    ed25519_kid: str | None = None  # a session's signing key
    base_url: str = ""
    client_addr: str | None = None

    @property
    def anonymous(self) -> bool:
        return self.kind == ANONYMOUS_KIND

    @property
    def admin(self) -> bool:
        return self.role == "admin"

    def principal(self) -> Principal:
        """What the collection checks take: the Member or admin by handle, a non-member key by
        its id, nobody for an anonymous caller."""
        if self.anonymous:
            return ANONYMOUS
        if self.role == "non-member":
            return Principal(api_key_id=self.key_id)
        return Principal(handle=self.handle)
