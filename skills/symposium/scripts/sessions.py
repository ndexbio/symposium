"""The skill's sessions (R-I3, R-I7): where each agent session's state lives, and which session a
command works in. Nobody creates or enters a session directory; the skill keeps them under
`~/.symposium/`, beside the keystore:

    ~/.symposium/admin/                          a server-level user's server-wide session
                                                 (admin-config for root, setup for a server
                                                 admin) and root's public key files
    ~/.symposium/admin/<community>/              a server-level user's session for a community
                                                 (bootstrap, use-community)
    ~/.symposium/member/<community>/<handle>/    a community user's session (setup, from the
                                                 invite)
    ~/.symposium/current/<pid>.json              each agent session's current session

A session directory holds what a working directory holds for the CLI and the tools: the context
(`.symposium/context.json`, with the access the server resolved for its user), the runtime
record, the copy of the record (`record/`), the invite files and the event log. The skill runs
every command in its session's directory.

`setup`, `bootstrap`, `use-community`, `import` and `admin-config` name their session
themselves. Every other command works in the agent session's current session: the one
`/symposium use` chose, or the one `setup`, `bootstrap` or `use-community` made; when the agent
session has chosen none, the machine's only session. The choice is kept per agent process
(agent_process.py), so two agent sessions on one machine never change each other's. Relative
paths on a command line are the caller's: they are resolved against the directory the agent ran
the command in, before the command moves into its session.

A command that takes a grant (`REQUIRES`) is checked against the session's cached access first,
so the refusal names the grant and the sessions that hold it.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from agent_process import AgentProcess

NO_SESSION = (
    "no Symposium session on this machine: run `/symposium setup --invite-file <file>` (with "
    "an invite) or, as root, `/symposium admin-config` first"
)
# names that may name a session directory: a community (a slug, R-G8) and a handle
COMMUNITY = re.compile(r"^[A-Za-z0-9_]{1,20}$")
HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
# commands that name their own session, from their own arguments
NAMED = {"admin-config", "bootstrap", "import", "setup", "use-community"}
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


class SessionError(Exception):
    """A command whose session cannot be chosen: `report` says why, and how to choose."""

    def __init__(self, report: dict):
        super().__init__(report["error"])
        self.report = report


@dataclass(frozen=True)
class Session:
    directory: Path
    community: str  # "" for a server-wide session
    handle: str
    home: str  # "" for a server-level user
    access: dict

    def label(self) -> str:
        return f"{self.community or 'server'}/{self.handle}"

    def use_command(self) -> str:
        if not self.community:
            return f"/symposium use {self.handle}"
        return f"/symposium use {self.community} {self.handle}"

    def grants(self) -> dict | None:
        """The grants the server last resolved for this session's user, or None before the
        session has read them (`/symposium access`)."""
        context = (self.access or {}).get("context")
        return None if context is None else context.get("grants") or {}

    def holds(self, grants) -> bool | None:
        """Whether the cached access holds any of `grants` in this session's community; None
        when nothing is cached."""
        held = self.grants()
        if held is None:
            return None
        return any(g in held for g in grants)

    def view(self) -> dict:
        return {
            "community": self.community or None,
            "handle": self.handle,
            "server_level": not self.home,
            "roles": [r["role"] for r in (self.access or {}).get("roles", [])],
            "directory": str(self.directory),
            "use": self.use_command(),
        }


class Sessions:
    def __init__(
        self,
        root: Path | None = None,
        caller: Path | None = None,
        agent: AgentProcess | None = None,
    ):
        self.root = root or Path.home() / ".symposium"
        self.caller = caller or Path.cwd()
        self.agent = agent or AgentProcess()

    # ── the sessions on this machine ─────────────────────────────────────────────────────
    def all(self) -> list:
        return [
            s
            for context in sorted(self.root.glob("admin/.symposium/context.json"))
            + sorted(self.root.glob("admin/*/.symposium/context.json"))
            + sorted(self.root.glob("member/*/*/.symposium/context.json"))
            if (s := self.at(context.parents[1])) is not None
        ]

    def at(self, directory: Path) -> Session | None:
        """The session in a directory, from its context, or None."""
        try:
            held = json.loads((directory / ".symposium" / "context.json").read_text())
        except (OSError, ValueError):
            return None
        return Session(
            directory,
            held.get("community") or "",
            held.get("handle", ""),
            held.get("home") or "",
            held.get("access") or {},
        )

    def server_session(self) -> Path:
        return self.root / "admin"

    def admin_session(self, community: str) -> Path:
        return self.root / "admin" / community

    def member_session(self, community: str, handle: str) -> Path:
        return self.root / "member" / community / handle

    # ── this agent session's current session ─────────────────────────────────────────────
    def current(self) -> Session | None:
        """What this agent session chose, while its record matches the agent process."""
        agent = self.agent.find()
        if agent is None:
            return None
        try:
            record = json.loads(self.record(agent.pid).read_text())
        except (OSError, ValueError):
            return None
        if record.get("started") != agent.started:
            return None  # the PID was reused: the record belongs to an ended process
        found = [
            s
            for s in self.all()
            if s.community == record.get("community")
            and s.handle == record.get("handle")
        ]
        return found[0] if found else None

    def make_current(self, session: Session):
        """Record `session` as this agent session's current one, and purge the records of
        agent processes that have ended (or whose PID is now another process's)."""
        agent = self.agent.find()
        if agent is None:
            return
        directory = self.root / "current"
        directory.mkdir(parents=True, exist_ok=True)
        for record in directory.glob("*.json"):
            if record.stem == str(agent.pid) or not record.stem.isdigit():
                continue
            try:
                started = json.loads(record.read_text()).get("started")
            except (OSError, ValueError):
                started = None
            if started is None or self.agent.started(int(record.stem)) != started:
                record.unlink(missing_ok=True)
        self.record(agent.pid).write_text(
            json.dumps(
                {
                    "community": session.community,
                    "handle": session.handle,
                    "started": agent.started,
                }
            )
            + "\n"
        )

    def record(self, pid: int) -> Path:
        return self.root / "current" / f"{pid}.json"

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

    def chosen(self) -> Session:
        """The current session, or the machine's only one."""
        current = self.current()
        if current is not None:
            return current
        sessions = self.all()
        if len(sessions) == 1:
            return sessions[0]
        if not sessions:
            raise SessionError({"error": NO_SESSION})
        raise SessionError(
            {
                "error": "this machine holds several Symposium sessions: choose one for this "
                "agent session with `/symposium use <community> <handle>`",
                "sessions": [s.view() for s in sessions],
            }
        )

    def named(self, command: str, rest: list) -> Path | None:
        """The session a NAMED command names: the server-wide one for admin-config; the
        community file's for bootstrap and import; the community's for use-community; the
        invite's for setup. None for a file it cannot read."""
        if command == "admin-config":
            return self.server_session()
        if command == "use-community":
            community = rest[0] if rest and COMMUNITY.match(rest[0]) else None
            return None if community is None else self.admin_session(community)
        if command == "setup":
            invite = self.read(rest, "--invite-file", community_required=False)
            if invite is None or not invite["handle"]:
                return None
            if not invite["community"]:
                return self.server_session()
            return self.member_session(invite["community"], invite["handle"])
        spec = self.read(rest, "--community-file")
        return None if spec is None else self.admin_session(spec["community"])

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
