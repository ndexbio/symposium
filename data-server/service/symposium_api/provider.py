"""What the generated routers depend on, wired once by `symposium_server`: the data server's
storage, and the service implementation behind the generated interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Runtime:
    """The data server's own singletons, as `symposium_server` hands them over."""

    db: Any
    records: Any
    store: Any
    settings: Any
    admin_mode: Callable[[], Any]
    # SYMPOSIUM_SERVER_PUBLIC_URL: the base of every canonical URL
    public_url: str | None


_wired: dict = {}


def wire(runtime: Runtime, service) -> None:
    _wired.update(runtime=runtime, service=service)


def runtime() -> Runtime:
    return _wired["runtime"]


def service_provider():
    """The FastAPI dependency the generated routers take their service from."""
    return _wired["service"]
