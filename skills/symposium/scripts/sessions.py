"""Which session a `/symposium` command works in, and how its command line is read.

Where the sessions live, how one is found and which one this agent session chose is
`symposium.session`, in the package the bundle ships: a skill built on Symposium resolves the
same session this one does, from one implementation. What is here is the part that only a
dispatcher has — which commands name their own session, which take a grant, and which arguments
are the caller's paths:

`setup`, `bootstrap`, `use-community`, `import` and `admin-config` name their session themselves;
`bootstrap`, `use-community` and `import` work as the server-level user named with `--handle`,
else the current session's, else the machine's only one. Every other command works in the agent
session's current session: the one `/symposium use` chose, or the one `setup`, `bootstrap` or
`use-community` made; when the agent session has chosen none, the machine's only session.
Relative paths on a command line are the caller's: they are resolved against the directory the
agent ran the command in, before the command moves into its session.

A command that takes a grant (`REQUIRES`) is checked against the session's cached access first,
so the refusal names the grant and the sessions that hold it.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
# Installed from the bundle the toolchain sits inside the skill; in a checkout it is the
# repository itself. Same resolution as main.py, which cannot be imported from here.
TOOLCHAIN = SKILL / "toolchain" if (SKILL / "toolchain").is_dir() else SKILL.parents[1]
sys.path.insert(0, str(TOOLCHAIN / "tools" / "sdk"))

from symposium.session import (  # noqa: E402
    COMMUNITY,
    HANDLE,
    NO_SESSION,
    SERVER,
    Session,
    SessionError,
)
from symposium.session import Sessions as Discovered  # noqa: E402

__all__ = [
    "COMMUNITY",
    "HANDLE",
    "NO_SESSION",
    "SERVER",
    "Session",
    "SessionError",
    "Sessions",
]

# commands that name their own session, from their own arguments
NAMED = {"admin-config", "bootstrap", "import", "setup", "use-community"}
# the NAMED commands that work as a server-level user in a community's session
AS_SERVER_USER = {"bootstrap", "import", "use-community"}
# the grant a command takes, any one of several sufficing: checked against the session's cached
# access before it runs (the server decides either way)
REQUIRES = {
    "publish": ("publish",),
    "validate": ("publish",),
    "gate": ("gate",),
    "invite": ("members", "delegate"),
    "rebind-key": ("members", "delegate"),
    "suspect-after": ("members", "delegate"),
    "purge": ("manage",),
    "export": ("export",),
    "port": ("communities",),
}
# commands that run in a community's session: a server-wide session has no community
COMMUNITY_COMMANDS = {
    "publish",
    "validate",
    "sync",
    "gate",
    "serve",
    "port",
    "purge",
    "export",
    "gen-api-key",
    "list-api-keys",
    "revoke-api-key",
}
# options whose value is a path the caller gave, relative to the caller's directory
PATH_OPTIONS = {
    "--invite-file",
    "--community-file",
    "--from",
    "--out",
    "--out-dir",
    "--api-key-file",
}
# commands whose positional arguments may be the caller's files (artifacts, a record
# directory, a credentials file, a file to store)
PATH_POSITIONALS = {"publish", "validate", "serve", "port", "data"}
# the options of those commands that take no value: the word after any other option is that
# option's value (a file's `--name`, a `--collection`), kept as given
FLAGS = {
    "--all",
    "--server",
    "--new-key",
    "--non-member",
    "--private",
    "--public",
    "--quiet",
    "--reference",
    "--revoke",
    "--verbose",
}


class Sessions(Discovered):
    """The sessions on this machine, read as a `/symposium` command line reads them."""

    def server_handle(self, rest: list) -> str:
        """The server-level user a command works as: `--handle`, else the current session's
        user when it is server-level, else the machine's only server-level user (by its
        server-wide sessions and the server-level keys it holds)."""
        named = self.option(rest, "--handle")
        if named:
            return named
        current = self.current()
        if current is not None and not current.home:
            return current.handle
        wide = [s for s in self.all() if not s.home and not s.community]
        handles = sorted(
            {s.handle for s in wide}
            | {
                key.name[: -len(".ed25519.pem")]
                for key in self.root.glob(f"keys/*/{SERVER}/*.ed25519.pem")
            }
        )
        if len(handles) == 1:
            return handles[0]
        if not handles:
            raise SessionError(
                {
                    "error": "no server-level user on this machine: root runs "
                    "`/symposium admin-config`; a server admin joins with "
                    "`/symposium setup --invite-file <file>`"
                }
            )
        raise SessionError(
            {
                "error": "this machine holds the server-level users "
                f"{', '.join(handles)}: name one with --handle",
                "sessions": [s.view() for s in wide],
            }
        )

    def use(self, rest: list) -> dict:
        """`/symposium use <community> <handle>` (or `use <handle>`, a server-wide session):
        make that session this agent session's current one. With no arguments, or a session
        that does not exist, list them all."""
        sessions = self.all()
        if len(rest) in (1, 2):
            community, handle = ("", rest[0]) if len(rest) == 1 else rest
            for session in sessions:
                if (
                    session.community.lower() == community.lower()
                    and session.handle == handle
                ):
                    self.make_current(session)
                    return {**session.view(), "current": True}
            where = community or "the server-wide sessions"
            error = f"no session for {handle} in {where} on this machine"
        else:
            error = (
                "usage: /symposium use <community> <handle>, or /symposium use <handle>"
            )
        raise SessionError(
            {
                "error": error if sessions else NO_SESSION,
                "sessions": [s.view() for s in sessions],
            }
        )

    # ── a command's session ──────────────────────────────────────────────────────────────
    def place(self, command: str, rest: list) -> tuple:
        """-> (the command's session directory, created when needed; its Session, or None
        when it has none yet; its arguments, with the caller's paths resolved)."""
        rest = self.resolve(command, rest)
        if command in NAMED:
            if (
                command in AS_SERVER_USER
                and self.option(rest, "--handle") is None
                and self.community_named(command, rest) is not None
            ):
                rest = [*rest, "--handle", self.server_handle(rest)]
            directory = self.named(command, rest)
            if directory is None:
                return (
                    self.caller,
                    None,
                    rest,
                )  # the tool reports what is wrong with its file
            directory.mkdir(parents=True, exist_ok=True)
            return directory, self.at(directory), rest
        session = self.chosen()
        if command in COMMUNITY_COMMANDS and not session.community:
            raise SessionError(
                {
                    "error": f"`{command}` works in a community, and this agent session works "
                    f"server-wide as {session.handle}: choose a community's session with "
                    "`/symposium use-community <community>`, or `/symposium use`",
                    "sessions": [s.view() for s in self.all() if s.community],
                }
            )
        return session.directory, session, rest

    def refusal(self, command: str, session: Session) -> dict | None:
        """The refusal of a command whose grant the session's cached access lacks, naming the
        sessions on this machine that hold it; None when it holds it, or nothing is cached."""
        grants = REQUIRES.get(command)
        if not grants or session.holds(grants) is not False:
            return None
        named = " or ".join(f"`{g}`" for g in grants)
        return {
            "error": f"`{command}` takes the {named} grant, which {session.label()} does not "
            "hold: `/symposium access` shows what it holds; switch with `/symposium use`",
            "sessions": [s.view() for s in self.all() if s.holds(grants)],
        }

    def named(self, command: str, rest: list) -> Path | None:
        """The session a NAMED command names: the server-wide one for admin-config; the
        community file's for bootstrap and import; the community's for use-community; the
        invite's for setup. None for a file it cannot read."""
        if command == "setup":
            invite = self.read(rest, "--invite-file", community_required=False)
            if invite is None or not invite["handle"]:
                return None
            if not invite["community"]:
                return self.server_session(invite["handle"])
            return self.member_session(invite["community"], invite["handle"])
        handle = self.option(rest, "--handle") or ""
        if not HANDLE.match(handle):
            return None
        if command == "admin-config":
            return self.server_session(handle)
        community = self.community_named(command, rest)
        return None if community is None else self.admin_session(community, handle)

    def community_named(self, command: str, rest: list) -> str | None:
        """The community `use-community` names, or the community file of `bootstrap` and
        `import`; None when it names none a community may take."""
        if command == "use-community":
            community = rest[0] if rest and COMMUNITY.match(rest[0]) else None
        else:
            spec = self.read(rest, "--community-file")
            community = None if spec is None else spec["community"]
        return None if community is None or community.lower() == SERVER else community

    @staticmethod
    def option(rest: list, name: str) -> str | None:
        """The value of option `name` on a command line, or None."""
        for i, arg in enumerate(rest):
            key, equals, value = arg.partition("=")
            if key == name:
                return value if equals else (rest[i + 1] if i + 1 < len(rest) else None)
        return None

    # ── the command line ─────────────────────────────────────────────────────────────────
    def resolve(self, command: str, rest: list) -> list:
        """The caller's relative paths, made absolute against the caller's directory."""
        out, expecting, value_of_option = [], False, False
        for arg in rest:
            if expecting:
                out.append(self.absolute(arg))
                expecting = False
                continue
            if value_of_option:
                out.append(arg)
                value_of_option = False
                continue
            name, equals, value = arg.partition("=")
            if name in PATH_OPTIONS:
                if equals:
                    out.append(f"{name}={self.absolute(value)}")
                else:
                    out.append(arg)
                    expecting = True
            elif arg.startswith("-"):
                out.append(arg)
                value_of_option = not equals and arg not in FLAGS
            elif command in PATH_POSITIONALS and (self.caller / arg).exists():
                out.append(self.absolute(arg))
            else:
                out.append(arg)
        return out

    def absolute(self, path: str) -> str:
        expanded = Path(path).expanduser()
        return str(
            expanded if expanded.is_absolute() else (self.caller / expanded).resolve()
        )

    def read(
        self, rest: list, option: str, community_required: bool = True
    ) -> dict | None:
        """The names in the JSON file an option names (a community file or an invite), or None
        when the option or the file is missing, or its `community` is invalid (or missing,
        where one is required; an invite's is null for a server-level user)."""
        path = None
        for i, arg in enumerate(rest):
            name, equals, value = arg.partition("=")
            if name == option:
                path = value if equals else (rest[i + 1] if i + 1 < len(rest) else None)
        if path is None:
            return None
        try:
            spec = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(spec, dict):
            return None
        community = spec.get("community")
        if community is None and not community_required:
            community = ""
        elif not COMMUNITY.match(str(community or "")):
            return None
        handle = str(spec.get("handle") or "")
        return {
            "community": community,
            "handle": handle if HANDLE.match(handle) else "",
        }
