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
    tokens: Any
    admin_mode: Callable[[], Any]
    # SYMPOSIUM_DATA_API_PUBLIC_URL: the base of every canonical URL
    public_url: str | None


_wired: dict = {}


def wire(runtime: Runtime, service, keys, contract, streams) -> None:
    _wired.update(
        runtime=runtime, service=service, keys=keys, contract=contract, streams=streams
    )


def runtime() -> Runtime:
    return _wired["runtime"]


def keys():
    return _wired["keys"]


def contract():
    return _wired["contract"]


def streams():
    return _wired["streams"]


def service_provider():
    """The FastAPI dependency the generated routers take their service from."""
    return _wired["service"]
