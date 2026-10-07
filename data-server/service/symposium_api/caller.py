"""Who is calling, once authorized: the one type the generated routers and the generated
service interface share with the hand-written code. It depends on nothing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Caller:
    kind: str  # "anonymous" or "api_key"
    role: str | None = None
    username: str | None = None
    key_id: object | None = None
    community: str | None = (
        None  # the key's one community; None for an anonymous caller
    )
    base_url: str = ""
    client_addr: str | None = None

    @property
    def handle(self) -> str | None:
        """The Member this caller publishes as and reads its own submissions as."""
        return self.username if self.role == "member" else None
