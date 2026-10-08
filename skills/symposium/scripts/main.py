#!/usr/bin/env python3
"""The `symposium` skill's entry point: every person (admin, operator, member) works through
`/symposium <command>`, and this dispatches it (R-I7). It never contacts a data server itself:
every data interaction runs the `symposium-data` CLI (R-I1).

    setup --invite-file <file>             members: join a community (run first in a session)
    bootstrap --community-file <file>      admins: bring a community up (run first in a session)
    use [<community> <handle>]             choose this agent session's session; alone, list them
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
    gen-api-key | list-api-keys | revoke-api-key
                                           Data API keys, as 0600 files in the session's api-keys/:
                                           a member's own keys, or the admin's application keys
    data <symposium-data command …>        direct data work: put, get, keys, collection, find, …

`publish`, `validate`, `sync`, `gate` and `serve` print a free-text report, and their exit
code is the result (0 = done); every other command prints one JSON object. Every command names
the session it worked in: a `session` key in its JSON object, or a first line
`session: <community>/<handle>` before its free text, which then streams through as it comes.

Every command runs in its session's directory, which the skill keeps under ~/.symposium/
(sessions.py): `setup`, `bootstrap`, `import` and `admin-config` name theirs, and `setup` and
`bootstrap` make theirs this agent session's current one; any other command works in the
current session (`use` chooses it), or the machine's only one. The first command of a session prepares the CLI's Python runtime (runtime.py) before anything
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

from long_running import LongRunning
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
# the Data API's keys: a member makes its own, the admin makes applications'
KEYS = ("gen-api-key", "list-api-keys", "revoke-api-key")
# the commands that print free text: their session goes on a first line of its own
FREE_TEXT = {"publish", "validate", "sync", "gate", "serve"}
# the workflow commands: each runs its tool from the toolchain
WORKFLOW = {
    "publish": "publish.py",
    "sync": "sync.py",
    "gate": "gate.py",
    "serve": "serve.py",
}
USAGE = (
    "/symposium <setup|bootstrap|use|publish|sync|gate|validate|serve|port|admin-config|roster|"
    "invite|rebind-key|suspect-after|purge|export|import|gen-api-key|list-api-keys|"
    "revoke-api-key|data> [options]    "
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
    if command in ADMIN or command in KEYS:
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
    command, sessions = argv[0], Sessions()
    if command == "use":
        try:
            print(json.dumps(sessions.use(argv[1:])))
        except SessionError as e:
            print(json.dumps(e.report))
            return 1
        return 0
    if command_line(command, argv[1:], []) is None:
        print(json.dumps({"error": f"unknown command '{command}'", "usage": USAGE}))
        return 1
    try:
        directory, session, rest = sessions.place(command, argv[1:])
        # the session's runtime, before anything else
        cli = Runtime(SKILL, CLI, session=directory).command()
    except (SessionError, RuntimeUnavailable) as e:
        print(json.dumps(e.report))
        return 1
    process = command_line(command, rest, cli)
    environment = {**os.environ, "SYMPOSIUM_DATA_CLI": json.dumps(cli)}
    if command in FREE_TEXT:
        # the session first; the report then streams through, each line as it is printed
        print(f"session: {session.label()}", flush=True)
        environment["PYTHONUNBUFFERED"] = "1"
        if keeps_running(command, rest):
            return LongRunning().run(process, environment, directory)
        return subprocess.run(process, env=environment, cwd=directory).returncode
    result = subprocess.run(
        process, env=environment, cwd=directory, stdout=subprocess.PIPE, text=True
    )
    if command in ("setup", "bootstrap") and result.returncode == 0:
        made = sessions.at(directory)
        if made is not None:
            sessions.make_current(
                made
            )  # the session it made is this agent session's now
            session = made
    print(named(result.stdout, session), end="")
    return result.returncode


def keeps_running(command: str, rest: list) -> bool:
    """`serve`, `gate --watch` and `sync --watch` run until stopped."""
    return command == "serve" or (command in ("gate", "sync") and "--watch" in rest)


def named(output: str, session) -> str:
    """A command's one JSON object with the session it worked in added; anything else (a
    command's --help, or no session yet) as it was."""
    if session is None:
        return output
    try:
        report = json.loads(output)
    except ValueError:
        return output
    if not isinstance(report, dict):
        return output
    return json.dumps({**report, "session": session.label()}) + "\n"


if __name__ == "__main__":
    sys.exit(main())
