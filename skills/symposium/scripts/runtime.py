"""The skill's Python runtime for the symposium-data CLI.

The skill's own scripts and the toolchain's tools use only the standard library and run with the
interpreter running the skill. The CLI needs its packages (`requirements.txt`), so it runs in the
skill's own virtual environment, `<skill>/.venv`:

  * **once per machine**, the environment is built with the Python running the skill
    (`python -m venv`, then its pip installs `requirements.txt`) and shared by every session; it
    is rebuilt when `requirements.txt` changes, which a stamp file inside it records;
  * **once per agent session**, the CLI command is recorded in the session's
    `./.symposium/runtime.json`; every later command in the session runs the CLI with that
    record and checks nothing else.

The environment is built in a directory beside its final place and renamed in, the stamp written
last, under a build lock (`<skill>/.venv.lock`): commands that start at once build it once, and
each uses a whole one. Nothing is printed to stdout:
the skill's commands print one JSON object there.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STAMP = "symposium-requirements.sha256"
NEEDS = (
    "Python 3.9+ with its venv module (on Debian and Ubuntu, the python3-venv package), and "
    "network access to PyPI the first time the skill is used on this machine"
)


class RuntimeUnavailable(Exception):
    """The CLI's environment could not be built: `report` says what failed and what is needed."""

    def __init__(self, what: str, detail: str):
        super().__init__(what)
        self.report = {"error": f"the skill could not {what}: {detail}", "needs": NEEDS}


class Runtime:
    def __init__(
        self,
        skill: Path,
        cli: Path,
        session: Path | None = None,
        python: str = sys.executable,
    ):
        self.skill = skill
        self.cli = cli
        self.requirements = cli.parent / "requirements.txt"
        self.venv = skill / ".venv"
        self.record = (session or Path.cwd()) / ".symposium" / "runtime.json"
        self.python = python

    def command(self) -> list:
        """The session's CLI command. The session's first command builds or reuses the shared
        environment and records the command; later commands only read the record."""
        recorded = self.recorded()
        if recorded:
            return recorded
        self.ensure_environment()
        command = [str(self.interpreter(self.venv)), str(self.cli)]
        self.record.parent.mkdir(parents=True, exist_ok=True)
        # whole or not at all: commands that start together in one session each write theirs
        staged = self.record.with_name(f"{self.record.name}.{os.getpid()}.tmp")
        staged.write_text(json.dumps({"cli": command}) + "\n")
        os.replace(staged, self.record)
        return command

    def recorded(self) -> list | None:
        """The recorded command, while the interpreter and the CLI it names are still there
        (they are gone when the skill is reinstalled)."""
        try:
            command = json.loads(self.record.read_text())["cli"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if all(Path(part).exists() for part in command):
            return command
        return None

    # ── the shared environment ────────────────────────────────────────────────────────────
    def interpreter(self, environment: Path) -> Path:
        if os.name == "nt":
            return environment / "Scripts" / "python.exe"
        return environment / "bin" / "python"

    def wanted(self) -> str:
        return hashlib.sha256(self.requirements.read_bytes()).hexdigest()

    def ready(self) -> bool:
        try:
            stamp = (self.venv / STAMP).read_text().strip()
        except OSError:
            return False
        return stamp == self.wanted() and self.interpreter(self.venv).exists()

    @contextlib.contextmanager
    def one_build(self):
        """Hold the environment's build lock, `<skill>/.venv.lock`, until the context exits:
        commands that start together on a machine build the environment once, and the ones
        that waited use the build they find."""
        handle = open(self.skill / ".venv.lock", "a+")
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write("\0")
                    handle.flush()
                while True:
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            handle.close()  # closing the file releases its lock

    def ensure_environment(self):
        if self.ready():
            return
        with self.one_build():
            if not self.ready():
                self.build()

    def build(self):
        building = Path(tempfile.mkdtemp(prefix=".venv-building-", dir=self.skill))
        try:
            self.run(
                [self.python, "-m", "venv", str(building)],
                "create its Python environment",
            )
            self.run(
                [
                    str(self.interpreter(building)),
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--disable-pip-version-check",
                    "-r",
                    str(self.requirements),
                ],
                "install the CLI's packages",
            )
            (building / STAMP).write_text(self.wanted() + "\n")
            self.place(building)
        finally:
            shutil.rmtree(building, ignore_errors=True)

    def place(self, built: Path):
        """Rename the built environment into place. A stale environment (from an older
        `requirements.txt`) is moved aside and removed."""
        if self.venv.exists():
            stale = Path(tempfile.mkdtemp(prefix=".venv-stale-", dir=self.skill))
            os.replace(self.venv, stale / "venv")
            shutil.rmtree(stale, ignore_errors=True)
        os.replace(built, self.venv)

    def run(self, command: list, what: str):
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except OSError as e:
            raise RuntimeUnavailable(what, str(e)) from None
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            raise RuntimeUnavailable(
                what, detail[-1] if detail else f"exit {result.returncode}"
            )
