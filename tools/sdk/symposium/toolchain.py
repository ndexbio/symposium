"""Finding the installed Symposium skill, and running its tools.

A skill built on Symposium installs this package from the skill beside it, so the toolchain it
needs is on disk somewhere. This module finds it and runs it, and nothing above this module
constructs a path into another skill.

**Why the tools are run rather than imported.** `publish.py` reads its role contracts from
`roles/*.md` beside itself, and the policies and the SOP sit beside those; they are what the
community's documents link to by path, and what an agent reads. Importing them into this package
would mean moving those directories out from under every link that names them. So the Symposium
layer is invoked the way it already invokes its own data client: as a process, with the session's
recorded CLI command in its environment. What a caller gets is a Python method either way.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Inside the installed skill, the Symposium base sits under `toolchain/`; in a checkout of the
# repository it is the repository itself.
TOOLCHAIN = "toolchain"


class ToolchainError(Exception):
    """The Symposium skill could not be found, or one of its tools failed: `report` says which,
    and what was tried."""

    def __init__(self, report: dict):
        super().__init__(report["error"])
        self.report = report


def _candidates() -> list:
    """Where an installed Symposium skill is looked for, in order."""
    named = os.environ.get("SYMPOSIUM_SKILL_DIR")
    if named:
        return [Path(named).expanduser()]
    here = Path(__file__).resolve()
    found = [
        # a sibling of the skill this package was installed into, which is how skills install
        *(p / "symposium" for p in here.parents if p.name == "skills"),
        Path.home() / ".claude" / "skills" / "symposium",
    ]
    # a project-local skills directory, from the working directory upward
    for parent in [Path.cwd(), *Path.cwd().parents]:
        found.append(parent / ".claude" / "skills" / "symposium")
    return found


def skill_root() -> Path:
    """The installed Symposium skill. Raises ToolchainError naming every path tried."""
    tried = []
    for candidate in _candidates():
        tried.append(str(candidate))
        if (candidate / "SKILL.md").is_file() and (candidate / "scripts").is_dir():
            return candidate
    raise ToolchainError(
        {
            "error": "the Symposium skill is not installed beside this one: install it, or "
            "name it in SYMPOSIUM_SKILL_DIR",
            "searched": tried,
        }
    )


def base(skill: Path | None = None) -> Path:
    """The Symposium base inside an installed skill, or the repository in a checkout."""
    skill = skill or skill_root()
    inner = skill / TOOLCHAIN
    return inner if inner.is_dir() else skill.parents[1]


def cli_command(session: Path) -> list | None:
    """The data-server CLI command this session recorded, or None before the Symposium skill has
    run once in it. It is the skill's to build, and reading it is how this package stays out of
    the business of making virtual environments."""
    try:
        command = json.loads((session / ".symposium" / "runtime.json").read_text())[
            "cli"
        ]
    except (OSError, ValueError, KeyError):
        return None
    return command if isinstance(command, list) and command else None


def run(tool: str, args: list, session: Path, skill: Path | None = None) -> tuple:
    """Run one of the Symposium tools in a session's directory -> (exit code, output).

    The tools print for a person to read and answer with their exit code, so that is what comes
    back: nothing here parses their prose into a structure that would then have to track it.
    """
    root = base(skill)
    program = root / "tools" / tool
    if not program.is_file():
        raise ToolchainError(
            {"error": f"the Symposium skill has no {tool}", "looked_in": str(program)}
        )
    command = cli_command(session)
    if command is None:
        raise ToolchainError(
            {
                "error": "this session has no data-server CLI yet: run any `/symposium` "
                "command in it once, which builds the skill's runtime and records it",
                "session": str(session),
            }
        )
    environment = {**os.environ, "SYMPOSIUM_DATA_CLI": json.dumps(command)}
    result = subprocess.run(
        [sys.executable, str(program), *map(str, args)],
        cwd=str(session),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.returncode, result.stdout
