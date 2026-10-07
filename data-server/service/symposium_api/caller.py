"""Who is calling, once authorized: the one type the generated routers and the generated
service interface share with the hand-written code. It depends on nothing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Caller:
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
