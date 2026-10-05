#!/usr/bin/env python3
"""The `symposium` skill's entry point: every person (admin, operator, member) works through
`/symposium <command>`, and this dispatches it (R-I7). It never contacts a data server itself:
every data interaction runs the `symposium-data` CLI (R-I1).

    setup --invite-file <file>             members: join a community (run first in a session)
    bootstrap --community <file>           admins: bring a community up (run first in a session)
    publish [--role <role>] <artifact.json>
                                           submit an artifact to the gate (`--check`: validate only)
    validate <artifact.json>               validate only: `publish --check`
    sync [--watch]                         bring ./record, this session's copy of the record, up to date
    gate [--dry-run|--verify|--rebuild]    admins: decide the submissions waiting in inbox
    serve [--port N]                       browse ./record in a web browser, rebuilt as it changes
    port <ndex_credentials_file> <url>     admins: port a community's record (port-ndex)
    admin-config | roster | invite | rebind-key | suspect-after | purge | export | import
                                           admins: the server admin's commands
    data <symposium-data command …>        direct data work: put, get, keys, collection, find, …

`publish`, `validate`, `sync`, `gate` and `serve` print a free-text report, and their exit
code is the result (0 = done); every other command prints one JSON object.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
# Installed from the bundle, the toolchain sits inside the skill; in a checkout (the test
# suite) it is the repository itself.
TOOLCHAIN = SKILL / "toolchain" if (SKILL / "toolchain").is_dir() else SKILL.parents[1]
CLI = "symposium-data"
ADMIN = (
    "admin-config",
    "roster",
    "invite",
    "rebind-key",
    "suspect-after",
    "purge",
    "export",
    "import",
)
# the workflow commands: each runs its tool from the toolchain
WORKFLOW = {
    "publish": "publish.py",
    "sync": "sync.py",
    "gate": "gate.py",
    "serve": "serve.py",
}
USAGE = (
    "/symposium <setup|bootstrap|publish|sync|gate|validate|serve|port|admin-config|roster|"
    "invite|rebind-key|suspect-after|purge|export|import|data> [options]    "
    "e.g. /symposium setup --invite-file <file>"
)
INSTALL = (
    "the symposium-data CLI is not on PATH: install the Symposium bundle (`make deploy-local` "
    "from a checkout, or the release's Symposium_skill.zip) and keep ~/.local/bin on PATH"
)


def command_line(command: str, rest: list) -> list | None:
    """The process a /symposium command runs, or None for an unknown command."""
    if command == "setup":
        return [sys.executable, str(TOOLCHAIN / "tools" / "setup.py"), *rest]
    if command == "bootstrap":
        return [sys.executable, str(TOOLCHAIN / "server" / "bootstrap.py"), *rest]
    if command in WORKFLOW:
        return [sys.executable, str(TOOLCHAIN / "tools" / WORKFLOW[command]), *rest]
    if command == "validate":
        return [
            sys.executable,
            str(TOOLCHAIN / "tools" / "publish.py"),
            "--check",
            *rest,
        ]
    if command == "port":  # port-ndex
        return [sys.executable, str(SKILL / "scripts" / "port_ndex.py"), *rest]
    if command in ADMIN:
        return [CLI, command, *rest]
    if command == "data":
        return [CLI, *rest]
    return None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(json.dumps({"usage": USAGE, "instructions": str(SKILL / "README.md")}))
        return 0
    process = command_line(argv[0], argv[1:])
    if process is None:
        print(json.dumps({"error": f"unknown command '{argv[0]}'", "usage": USAGE}))
        return 1
    if shutil.which(CLI) is None:
        print(json.dumps({"error": INSTALL}))
        return 1
    return subprocess.run(process).returncode


if __name__ == "__main__":
    sys.exit(main())
