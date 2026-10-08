"""Who is calling, once authorized: the one type the generated routers and the generated
service interface share with the hand-written code. It depends on nothing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Caller:
    kind: str  # "anonymous" or "api_key"
    role: str | None = None
    # the Member a `member` key acts as, from the key's own row: who publishes and whose
    # submissions are read; None for a `non-member` key or an anonymous caller
    handle: str | None = None
    label: str | None = None  # the name the key's owner gave it
    key_id: object | None = None
    # the key's one community; None for an anonymous caller
    community: str | None = None
    base_url: str = ""
    client_addr: str | None = None
