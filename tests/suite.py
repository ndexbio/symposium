"""The top-level test suite's shared pieces: its lifecycle (`Suite`) and the helpers its tests
use to run the CLI and the skill.

One suite run is one pytest session: setUp creates one directory under /tmp for everything the
run needs (`HOME` and its keystore, the operator's and every test's working directory) and one
data-server container, onboarded the way an operator does it; the tests run
(`tests/symposium-data/`, then `tests/skills/`); tearDown removes the container and its volume
and deletes the directory, failures included. The data server's own suites run on their own
container (`make -C data-server test`); this suite imports their shared harness and port stub.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from harness import IMAGE, TEST_ENV, Server, docker

REPO = Path(__file__).resolve().parents[1]
CLI_DIR = REPO / "tools" / "symposium-data"
# the CLI's Python entry, run with the suite's interpreter, which has the CLI's packages
CLI = CLI_DIR / "cli.py"
SKILL = REPO / "skills" / "symposium" / "scripts" / "main.py"
ADMIN = "demo-admin"


class Cli:
    """Runs a command line (the CLI, or the skill) the way an agent does, and reads the one
    JSON object it prints."""

    def __init__(self, program: Path, env: dict):
        self.program, self.env = program, env

    def __call__(self, cwd: Path, *args, env: dict | None = None) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(self.program), *map(str, args)],
            cwd=cwd,
            env=env or self.env,
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


class Suite:
    """Everything one suite run owns, created by `set_up` and removed by `tear_down`."""

    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.operator = root / "operator"
        self.server: Server | None = None
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            # the CLI command the skill hands its tools: the tools the suite runs directly use
            # the repository's CLI with the suite's interpreter
            "SYMPOSIUM_DATA_CLI": json.dumps([sys.executable, str(CLI)]),
            # no OS keychain in a test run: the keys' passphrase comes from the environment
            "SYMPOSIUM_KEY_PASSPHRASE": "suite-passphrase",
        }
        self.cli = Cli(CLI, self.env)
        self.skill = Cli(SKILL, self.env)

    def set_up(self):
        for directory in (self.home, self.operator):
            directory.mkdir(parents=True)
        if not IMAGE:
            raise RuntimeError(
                "SYMPOSIUM_DATA_TEST_IMAGE is not set; run through the top-level make test"
            )
        self.server = Server(TEST_ENV)
        self.server.start()  # no key: it starts non-operational, as a new server does
        assert self.server.status()["mode"] == "non-operational"
        config = self.cli.ok(
            self.operator,
            "admin-config",
            "--handle",
            ADMIN,
            "--data-server-url",
            self.server.url,
        )
        place_admin_key(
            self.server, Path(config["public_key_file"]), config["fingerprint"]
        )

    def tear_down(self):
        if self.server is not None:
            self.server.remove()

    def purge(self):
        shutil.rmtree(self.root, ignore_errors=True)


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


def community_file(
    directory: Path, server: Server, community: str = "demo", handles=()
) -> Path:
    path = directory / f"{community}.json"
    path.write_text(
        json.dumps(
            {
                "community": community,
                "handles": list(handles),
                "data-server-url": server.url,
            }
        )
    )
    return path


def enroll(cli: Cli, admin_dir: Path, handle: str) -> Path:
    """A member, entirely through the CLI: the admin adds the handle and writes its invite
    file; the member sets its context from the file, in its own directory, and registers."""
    cli.ok(admin_dir, "roster", "add", "--handle", handle)
    invite = admin_dir / f"{handle}.invite"
    cli.ok(admin_dir, "invite", "--handle", handle, "--out", invite)
    member = admin_dir / handle
    member.mkdir()
    cli.ok(member, "context", "set", "--invite-file", invite)
    assert cli.ok(member, "owner", "register")["registered"] is True
    return member
