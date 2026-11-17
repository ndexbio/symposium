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
from pathlib import Path

from harness import IMAGE, MAX_WAIT, TEST_ENV, Server, docker

REPO = Path(__file__).resolve().parents[1]
CLI_DIR = REPO / "tools" / "symposium-data"
# the CLI's Python entry, run with the suite's interpreter, which has the CLI's packages
CLI = CLI_DIR / "cli.py"
SKILL = REPO / "skills" / "symposium" / "scripts" / "main.py"
ROOT = "demo-admin"  # root, bound from the key file


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
            timeout=MAX_WAIT,
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
            ROOT,
            "--data-server-url",
            self.server.url,
        )
        place_root_key(
            self.server, Path(config["public_key_file"]), config["fingerprint"]
        )

    def tear_down(self):
        if self.server is not None:
            self.server.remove()

    def purge(self):
        shutil.rmtree(self.root, ignore_errors=True)


def place_root_key(server: Server, key_file: Path, fingerprint: str):
    """What the operator does with `admin-config`'s file: copy it in, restart the server."""
    docker("cp", str(key_file), f"{server.name}:/apps/{key_file.name}")
    status = server.restarted()
    assert status.get("fingerprint") == fingerprint, status


def community_file(
    directory: Path,
    server: Server,
    community: str = "demo",
    handles=(),
    first_admin: str = "steward",
) -> Path:
    path = directory / f"{community}.json"
    path.write_text(
        json.dumps(
            {
                "community": community,
                "admin": first_admin,
                "handles": list(handles),
                "data-server-url": server.url,
            }
        )
    )
    return path


def enroll(
    cli: Cli, root_dir: Path, handle: str, access: str = "community-member:*"
) -> Path:
    """A user, entirely through the CLI: an inviter (root's session for the community, or a
    community admin's) writes its invite file carrying `access`; the user sets its context
    from the file, in its own directory, and joins."""
    invite = root_dir / f"{handle}.invite"
    cli.ok(root_dir, "invite", "--handle", handle, "--access", access, "--out", invite)
    member = root_dir / handle
    member.mkdir()
    cli.ok(member, "context", "set", "--invite-file", invite)
    assert cli.ok(member, "owner", "register")["registered"] is True
    return member


class Actor:
    """One person on their own workstation: a HOME of their own, holding their keystore and
    their skill sessions, where they run the skill. Only invite files move between actors,
    handed over as files (`receive`)."""

    def __init__(self, suite: Suite, home: Path, handle: str):
        self.handle = handle
        self.home = home
        self.work = home / "work"
        self.work.mkdir(parents=True, exist_ok=True)
        self.env = {**suite.env, "HOME": str(home)}
        self.skill = Cli(SKILL, self.env)

    def ok(self, *args) -> dict:
        """A skill command that must succeed. -> its JSON object."""
        return self.skill.ok(self.work, *args)

    def run(self, *args) -> tuple[int, dict]:
        """A skill command that may be refused. -> (exit code, its JSON object)."""
        return self.skill(self.work, *args)

    def report(self, *args) -> tuple[int, str]:
        """A workflow command (publish, validate, sync, gate): its free-text report."""
        result = subprocess.run(
            [sys.executable, str(SKILL), *map(str, args)],
            cwd=self.work,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=MAX_WAIT,
        )
        return result.returncode, result.stdout + result.stderr

    def invite(self, handle: str, *access: str, community: str | None = None) -> Path:
        """Write an invite file for `handle` carrying `access`. -> the file."""
        out = self.work / f"{handle}.invite"
        args = ["invite", "--handle", handle, "--out", out]
        for value in access:
            args += ["--access", value]
        if community is not None:
            args += ["--community", community]
        self.ok(*args)
        return out

    def receive(self, invite: Path) -> Path:
        """An invite handed over out of band: copied onto this actor's machine."""
        copy = self.work / invite.name
        shutil.copyfile(invite, copy)
        return copy

    def join(self, invite: Path) -> dict:
        """`/symposium setup` with an invite received from its inviter."""
        return self.ok("setup", "--invite-file", self.receive(invite))

    def api_key(self, issued: dict) -> str:
        """The value of a key this actor issued, read from its 0600 key file."""
        return json.loads(Path(issued["key_file"]).read_text())["key"]
