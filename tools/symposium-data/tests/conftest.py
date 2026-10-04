"""The CLI's suites: one data-server container for the session (the shared harness in
data-server/service/tests/harness.py), onboarded the way an operator does it. It starts without
an admin key; `admin-config` makes one, the key file is copied in with `docker cp`, and the API
restarts. Every test then runs the real CLI, in its own working directory, as a subprocess.

`HOME` is a temporary directory for the whole session, so the keystore never touches the real
one, and the key passphrase comes from SYMPOSIUM_KEY_PASSPHRASE (no OS keychain in tests).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from harness import IMAGE, TEST_ENV, Server, docker

CLI_DIR = Path(__file__).resolve().parents[1]
CLI = CLI_DIR / "symposium-data"
ADMIN = "demo-admin"
sys.path.insert(0, str(CLI_DIR))


class Cli:
    """Runs `symposium-data` the way the skill does, and reads its one JSON object."""

    def __init__(self, home: Path):
        self.env = {
            **os.environ,
            "HOME": str(home),
            "SYMPOSIUM_KEY_PASSPHRASE": "test-passphrase",
        }

    def __call__(self, cwd: Path, *args) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(CLI), *map(str, args)],
            cwd=cwd,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        try:
            out = json.loads(result.stdout)
        except ValueError:
            raise AssertionError(
                f"not one JSON object: {result.stdout!r} {result.stderr[-2000:]!r}"
            ) from None
        return result.returncode, out

    def ok(self, cwd: Path, *args) -> dict:
        code, out = self(cwd, *args)
        assert code == 0, out
        return out


def status_until(server: Server, predicate, message: str, timeout: float = 30) -> dict:
    """Poll /v1/status every 0.2 s, through an API restart, until `predicate` holds."""
    deadline = time.time() + timeout
    while True:
        try:
            status = httpx.get(server.url + "/v1/status", timeout=5).json()
            if predicate(status):
                return status
        except httpx.HTTPError:
            pass
        assert time.time() < deadline, message
        time.sleep(0.2)


def place_admin_key(server: Server, key_file: Path, fingerprint: str):
    """What the operator does with `admin-config`'s file: copy it in, restart the server."""
    docker("cp", str(key_file), f"{server.name}:/apps/{key_file.name}")
    server.restart_api()
    status_until(
        server,
        lambda s: s.get("fingerprint") == fingerprint,
        "the server never bound the admin key",
    )


@pytest.fixture(scope="session")
def cli(tmp_path_factory) -> Cli:
    return Cli(tmp_path_factory.mktemp("home"))


@pytest.fixture(scope="session")
def server(tmp_path_factory, cli):
    if not IMAGE:
        pytest.fail(
            "SYMPOSIUM_DATA_TEST_IMAGE is not set; run through the top-level make test"
        )
    server = Server(TEST_ENV)
    try:
        server.start()  # no key: it starts non-operational, as a new server does
        assert server.status()["mode"] == "non-operational"
        operator = tmp_path_factory.mktemp("operator")
        config = cli.ok(
            operator, "admin-config", "--handle", ADMIN, "--data-server-url", server.url
        )
        place_admin_key(server, Path(config["public_key_file"]), config["fingerprint"])
        yield server
    finally:
        server.remove()


@pytest.fixture(autouse=True)
def clean_slate(request):
    """Every test that uses the server starts from an empty, operational server."""
    if "server" in request.fixturenames:
        request.getfixturevalue("server").reset()
    yield


def community_file(directory: Path, server: Server, community: str = "demo") -> Path:
    path = directory / f"{community}.json"
    path.write_text(
        json.dumps(
            {"community": community, "handles": [], "data-server-url": server.url}
        )
    )
    return path


@pytest.fixture
def admin_dir(tmp_path, server, cli) -> Path:
    """A working directory whose context is the admin's, on an existing `demo` community."""
    cli.ok(
        tmp_path, "context", "set", "--community-file", community_file(tmp_path, server)
    )
    cli.ok(tmp_path, "communities", "create", "--name", "demo")
    return tmp_path
