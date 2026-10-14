"""The CLI against the API's contract, with no server: every call the CLI's client
(`main.DataServer`) can make is recorded, and each one's method and path must be an operation
in `api/openapi.yaml`. The client is written by hand, so this is what keeps it in step with the
contract: a route renamed or removed there fails here."""

from __future__ import annotations

import importlib.util
import inspect
import re
import sys
from pathlib import Path

import yaml
from suite import CLI_DIR

CONTRACT = Path(__file__).resolve().parents[2] / "api" / "openapi.yaml"


def load_cli():
    """The CLI's own `main.py`, by its path: the skill's scripts hold a `main` and a
    `port_ndex` module too, so the CLI's siblings are loaded from its own directory."""
    siblings = {name: sys.modules.pop(name, None) for name in ("port_ndex", "keystore")}
    sys.path.insert(0, str(CLI_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "symposium_data_cli", CLI_DIR / "main.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(CLI_DIR))
        for name, module in siblings.items():
            if module is not None:
                sys.modules[name] = module


main = load_cli()
# the client's own plumbing, which every call below goes through
PLUMBING = {"request", "refusal", "check_api", "c", "api_keys_path", "upload"}
ARGUMENTS = {
    "name": "lab",
    "handle": "lyra",
    "hours": 24,
    "at": "2026-10-01T12:00:00+00:00",
    "community": "demo",
    "body": {},
    "key_id": "5779183b-bb3d-439f-bdbf-d042c2e58306",
    "jwk": {"kty": "OKP", "crv": "Ed25519", "x": "x"},
    "nonce": "n",
    "signature": "s",
    "invite": "sdi_x",
    "source": None,
    "headers": {},
    "file_id": "5779183b-bb3d-439f-bdbf-d042c2e58306",
    "reason": "done",
    "n": "1",
    "ref": "latest",
    "collection": "lab",
    "contains": {},
    "since": 0,
    "limit": 10,
    "cite": "symposium-data:5779183b-bb3d-439f-bdbf-d042c2e58306@v1",
    "before": None,
    "sha256": "0" * 64,
    "grantee": {"handle": "vega"},
    "perm": "read",
    "granted": True,
    "public": True,
    "port_id": "5779183b-bb3d-439f-bdbf-d042c2e58306",
    "path": Path(__file__),
}


class Keystore:
    def sign(self, *_args):
        return "signature"


def contract_operations() -> list:
    """(method, compiled path pattern) of every operation, under `/v1`."""
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    ops = []
    for path, item in spec["paths"].items():
        pattern = re.sub(r"\{[^}]+\}", "[^/]+", "/v1" + path)
        for method in item:
            if method in ("get", "post", "put", "delete"):
                ops.append((method.upper(), re.compile(f"^{pattern}$")))
    return ops


def recorded_calls(monkeypatch) -> dict:
    """{client method: [(METHOD, path)]} for every method of the client."""
    calls, current = {}, [None]

    def record(method, path, *args, **kwargs):
        calls.setdefault(current[0], []).append((method, path.split("?")[0]))
        return {"nonce": "n", "key": "sak_x", "items": [], "next": None}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"{}"

    def urlopen(url, *args, **kwargs):
        target = url if isinstance(url, str) else url.full_url
        calls.setdefault(current[0], []).append(
            ("GET", target.removeprefix("http://data.test"))
        )
        return Response()

    server = main.DataServer("http://data.test", "demo")
    server.checked = True
    monkeypatch.setattr(server, "request", record)
    monkeypatch.setattr(server, "upload", record)
    monkeypatch.setattr(main.urllib.request, "urlopen", urlopen)
    for name, method in inspect.getmembers(server, inspect.ismethod):
        if name.startswith("_") or name in PLUMBING:
            continue
        current[0] = name
        params = inspect.signature(method).parameters
        args = {
            p: Keystore() if p == "keystore" else ARGUMENTS[p]
            for p in params
            if params[p].default is inspect.Parameter.empty
        }
        method(**args)
    return calls


def test_every_call_the_cli_makes_is_an_operation_of_the_contract(monkeypatch):
    operations = contract_operations()
    calls = recorded_calls(monkeypatch)
    assert calls, "the client made no calls"
    for name, made in calls.items():
        assert made, f"{name} made no call"
        for method, path in made:
            assert any(
                verb == method and pattern.match(path) for verb, pattern in operations
            ), f"DataServer.{name}: {method} {path} is no operation in api/openapi.yaml"


def test_every_method_of_the_client_reaches_the_server(monkeypatch):
    """A client method that no longer calls the server is dead code: it fails here."""
    calls = recorded_calls(monkeypatch)
    methods = {
        name
        for name, _ in inspect.getmembers(main.DataServer, inspect.isfunction)
        if not name.startswith("_") and name not in PLUMBING
    }
    assert set(calls) == methods
