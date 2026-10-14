"""What the generated routers depend on, wired once by `symposium_server`: the data server's
storage, and the service implementation behind the generated interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Runtime:
    """The data server's own singletons, as `symposium_server` hands them over."""

    db: Any
    records: Any
    store: Any
    settings: Any


_wired: dict = {}


def wire(service) -> None:
    _wired.update(service=service)


def service_provider():
    """The FastAPI dependency the generated routers take their service from."""
    return _wired["service"]
