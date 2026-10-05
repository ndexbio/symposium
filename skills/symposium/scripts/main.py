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
    gate [--dry-run|--verify|--rebuild|--watch]
                                           admins: decide the submissions waiting in inbox
    serve [<record dir>] [--port N]        browse ./record (or a record dir), rebuilt as it changes
    port <ndex_credentials_file> <url>     admins: port a community's record (port-ndex)
    admin-config | roster | invite | rebind-key | suspect-after | purge | export | import
                                           admins: the server admin's commands
    data <symposium-data command …>        direct data work: put, get, keys, collection, find, …

`publish`, `validate`, `sync`, `gate` and `serve` print a free-text report, and their exit
code is the result (0 = done); every other command prints one JSON object.

Every command runs in its session's directory, which the skill keeps under ~/.symposium/
(sessions.py): `setup`, `bootstrap`, `import` and `admin-config` name theirs; any other command
uses the machine's one session, or the one `--community <name>` (and `--handle <h>`) selects.
The first command of a session prepares the CLI's Python runtime (runtime.py) before anything
else; later commands in the session reuse it. Every tool started here gets the CLI command in
SYMPOSIUM_DATA_CLI.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from runtime import Runtime, RuntimeUnavailable
from sessions import SessionError, Sessions

SKILL = Path(__file__).resolve().parents[1]
# Installed from the bundle, the toolchain sits inside the skill; in a checkout (the test
# suite) it is the repository itself.
TOOLCHAIN = SKILL / "toolchain" if (SKILL / "toolchain").is_dir() else SKILL.parents[1]
CLI = TOOLCHAIN / "tools" / "symposium-data" / "cli.py"
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


def data_server_image() -> str:
    """The data-server image this skill was built for: the bundle's compat.json, or in a
    checkout the data server's own version."""
    compat = CLI.parent / "compat.json"
    if compat.is_file():
        version = json.loads(compat.read_text())["data_server_version"]
    else:
        pyproject = (
            TOOLCHAIN / "data-server" / "service" / "pyproject.toml"
        ).read_text()
        version = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)
    return f"ndexbio/symposium-data:{version}"


def command_line(command: str, rest: list, cli: list) -> list | None:
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
        return [*cli, command, *rest]
    if command == "data":
        return [*cli, *rest]
    return None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(
            json.dumps(
                {
                    "usage": USAGE,
                    "instructions": str(SKILL / "README.md"),
                    "data_server_image": data_server_image(),
                }
            )
        )
        return 0
    if command_line(argv[0], argv[1:], []) is None:
        print(json.dumps({"error": f"unknown command '{argv[0]}'", "usage": USAGE}))
        return 1
    try:
        session, rest = Sessions().place(argv[0], argv[1:])
        # the session's runtime, before anything else
        cli = Runtime(SKILL, CLI, session=session).command()
    except (SessionError, RuntimeUnavailable) as e:
        print(json.dumps(e.report))
        return 1
    process = command_line(argv[0], rest, cli)
    environment = {**os.environ, "SYMPOSIUM_DATA_CLI": json.dumps(cli)}
    return subprocess.run(process, env=environment, cwd=session).returncode


if __name__ == "__main__":
    sys.exit(main())
