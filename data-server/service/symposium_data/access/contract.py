"""The contract, `api/openapi.yaml`, as the server reads it: the document it serves, and each
operation's access rule taken from its `x-roles`, `x-session`, `security` and `x-anonymous`.
Authorization reads these rules, so no role list is written in Python."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml

# In the image the contract is copied beside the service; in a checkout it is the repository's.
IMAGE_CONTRACT = Path("/opt/symposium-api/openapi.yaml")
CHECKOUT_CONTRACT = Path(__file__).resolve().parents[4] / "api" / "openapi.yaml"
# x-anonymous: the operation always answers without a key
ANONYMOUS_ALWAYS = "always"
# x-anonymous: it answers without a key when the collection it reads is public
ANONYMOUS_PUBLIC = "public"


@dataclass(frozen=True)
class Rule:
    """Who may call one operation."""

    roles: tuple  # in the order the contract lists them
    anonymous: str | None  # None, ANONYMOUS_ALWAYS or ANONYMOUS_PUBLIC
    session: bool = False  # True when only a session key may call it


class Contract:
    def __init__(self, path: Path):
        self.path = path
        self.text = path.read_text(encoding="utf-8")

    @cached_property
    def document(self) -> dict:
        return yaml.safe_load(self.text)

    @cached_property
    def json(self) -> str:
        return json.dumps(self.document, ensure_ascii=False)

    @cached_property
    def rules(self) -> dict[str, Rule]:
        rules = {}
        default = self.document.get("security", [])
        for item in self.document["paths"].values():
            for operation in item.values():
                if not isinstance(operation, dict) or "operationId" not in operation:
                    continue
                security = operation.get("security", default)
                rules[operation["operationId"]] = Rule(
                    roles=tuple(operation["x-roles"]),
                    anonymous=operation.get("x-anonymous") if {} in security else None,
                    session=bool(operation.get("x-session", False)),
                )
        return rules


def load() -> Contract:
    configured = os.environ.get("SYMPOSIUM_SERVER_CONTRACT")
    if configured:
        return Contract(Path(configured))
    return Contract(IMAGE_CONTRACT if IMAGE_CONTRACT.is_file() else CHECKOUT_CONTRACT)
