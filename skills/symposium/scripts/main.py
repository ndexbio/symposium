#!/usr/bin/env python3
"""The `symposium` skill's entry point: every person works through `/symposium <command>`, and
this dispatches it. It never contacts a data server itself: every data interaction runs
the `symposium-data` CLI. What a person may run follows from their access roles
(`access` lists them); "who" below names the role that holds what a command takes.

    setup --invite-file <file>             anyone invited: join a community, or as a server admin
    admin-config --handle <h> --data-server-url <url>
                                           root: make root's key and its server-wide session
    bootstrap --community-file <file> [--handle <h>]
                                           server admins: create a community and its community admin's invite
    use-community <community> [--handle <h>]
                                           server admins: a session for an existing community
                                           (--handle: which server-level user, when this machine
                                           holds several)
    use [<community>] <handle>             choose this agent session's session; alone, list them
    access                                 your access roles and grants, and the six roles
    publish [--role <role>] <artifact.json>
                                           community-member: submit an artifact to the gate
                                           (`--check`: validate only)
    validate <artifact.json>               community-member: validate only, `publish --check`
    sync [--watch|--messages]              bring ./record, this session's copy of the record, up to
                                           date; list the gate's replies and the Messages addressed
                                           to you (`--messages`: all of them, newest first)
    gate [--dry-run|--verify|--rebuild|--watch]
                                           community-admin, gate-keeper: decide the submissions
                                           waiting in inbox
    serve [<record dir>] [--port N]        browse ./record (or a record dir), rebuilt as it changes
                                           `--watch` and `serve` run until stopped, with no time
                                           limit of their own: start them in the background, and
                                           again if the agent's limit stops them; a restart resumes
                                           and takes over. SIGINT or SIGTERM stops one within a second.
    invite | assign | unassign | users | rebind-key | suspect-after
                                           community-admin (in its community), server admins: users
                                           and their access roles; anyone in the community lists its users, and
                                           an owner shares its collections with `assign`; from a
                                           server-wide session, name the community with --community
    purge | export | import | port <ndex_credentials_file> <url>
                                           community-admin (purge, export), server admins
    gen-api-key | list-api-keys | revoke-api-key
                                           API keys, as 0600 files in the session's api-keys/,
                                           each carrying access roles (`--access`)
    data <symposium-data command …>        direct data work: put, get, collection, find, …

`publish`, `validate`, `sync`, `gate` and `serve` print a free-text report, and their exit
code is the result (0 = done); every other command prints one JSON object. Every command names
the session it worked in: a `session` key in its JSON object, or a first line
`session: <community>/<handle>` before its free text, which then streams through as it comes.

Every command runs in its session's directory, which the skill keeps under ~/.symposium/
(sessions.py): `setup`, `bootstrap`, `use-community`, `import` and `admin-config` name theirs,
and make theirs this agent session's current one; any other command works in the current
session (`use` chooses it), or the machine's only one. The first command of a session prepares
the CLI's Python runtime (runtime.py) before anything else; later commands in the session reuse
it. Every tool started here gets the CLI command in SYMPOSIUM_DATA_CLI.

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
# the CLI's own commands, run as they are
CLI_COMMANDS = (
    "admin-config",
    "access",
    "invite",
    "assign",
    "unassign",
    "users",
    "rebind-key",
    "suspect-after",
    "purge",
    "export",
    "import",
    "gen-api-key",
    "list-api-keys",
    "revoke-api-key",
)
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
    "/symposium <setup|admin-config|bootstrap|use-community|use|access|publish|validate|sync|"
    "gate|serve|invite|assign|unassign|users|rebind-key|suspect-after|purge|export|"
    "import|port|gen-api-key|list-api-keys|revoke-api-key|data> [options]    "
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
    if command == "use-community":
        return [*cli, "context", "set", "--community", *rest[:1], *rest[1:]]
    if command in CLI_COMMANDS:
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
    sessions.settle()
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
    environment = {**os.environ, "SYMPOSIUM_DATA_CLI": json.dumps(cli)}
    if session is not None and sessions.refusal(command, session) is not None:
        # the cached access may predate a change: read it afresh before refusing
        subprocess.run(
            [*cli, "access"], env=environment, cwd=directory, capture_output=True
        )
        session = sessions.at(directory)
        refused = sessions.refusal(command, session)
        if refused is not None:
            print(json.dumps(refused))
            return 1
    if command == "use-community":
        url = server_url(sessions, Sessions.option(rest, "--handle"))
        if url is None:
            print(
                json.dumps(
                    {
                        "error": "no server-wide session for "
                        f"{Sessions.option(rest, '--handle')} on this machine: "
                        "`/symposium use` lists the sessions"
                    }
                )
            )
            return 1
        rest = [*rest, "--data-server-url", url]
    process = command_line(command, rest, cli)
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
    if command == "use-community" and result.returncode == 0:
        # the session knows what it may do
        subprocess.run(
            [*cli, "access"], env=environment, cwd=directory, capture_output=True
        )
    if command in ("setup", "bootstrap", "use-community") and result.returncode == 0:
        made = sessions.at(directory)
        if made is not None:
            sessions.make_current(
                made
            )  # the session it made is this agent session's now
            session = made
    print(named(result.stdout, session), end="")
    return result.returncode


def server_url(sessions: Sessions, handle: str | None) -> str | None:
    """The data server of the server-level user's server-wide session, for `use-community`;
    None when this machine holds no such session."""
    if not handle:
        return None
    context = sessions.server_session(handle) / ".symposium" / "context.json"
    try:
        return json.loads(context.read_text())["data-server-url"]
    except (OSError, ValueError, KeyError):
        return None


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
