"""The skill's sessions (R-I3, R-I7): where each agent session's state lives, and which session a
command works in. Nobody creates or enters a session directory; the skill keeps them under
`~/.symposium/`, beside the keystore:

    ~/.symposium/admin/                          admin-config's public key files
    ~/.symposium/admin/<community>/              the admin's session for a community (bootstrap)
    ~/.symposium/member/<community>/<handle>/    a member's session (setup, from the invite)
    ~/.symposium/current/<pid>.json              each agent session's current session

A session directory holds what a working directory holds for the CLI and the tools: the context
(`.symposium/context.json`), the runtime record, the copy of the record (`record/`), the invite
files and the event log. The skill runs every command in its session's directory.

`setup`, `bootstrap`, `import` and `admin-config` name their session themselves. Every other
command works in the agent session's current session: the one `/symposium use <community>
<handle>` chose, or the one `setup` or `bootstrap` made; when the agent session has chosen none,
the machine's only session. The choice is kept per agent process (agent_process.py), so two agent
sessions on one machine never change each other's. Relative paths on a command line are the
caller's: they are resolved against the directory the agent ran the command in, before the
command moves into its session.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from agent_process import AgentProcess

NO_SESSION = (
    "no Symposium session on this machine: run `/symposium setup --invite-file <file>` "
    "(members) or `/symposium bootstrap --community-file <file>` (admins) first"
)
# names that may name a session directory: a community (a slug, R-G8) and a handle
COMMUNITY = re.compile(r"^[A-Za-z0-9_]{1,20}$")
HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
# commands that name their own session, from their own arguments
NAMED = {"admin-config", "bootstrap", "import", "setup"}
# commands only the admin runs: they work in an admin's session
ADMIN_ONLY = {
    "roster",
    "invite",
    "rebind-key",
    "suspect-after",
    "purge",
    "export",
    "gate",
    "port",
}
# options whose value is a path the caller gave, relative to the caller's directory
PATH_OPTIONS = {
    "--invite-file",
    "--community-file",
    "--from",
    "--out",
    "--out-dir",
    "--read-key-file",
}
# commands whose positional arguments may be the caller's files (artifacts, a record
# directory, a credentials file, a file to store)
PATH_POSITIONALS = {"publish", "validate", "serve", "port", "data"}


class SessionError(Exception):
    """A command whose session cannot be chosen: `report` says why, and how to choose."""

    def __init__(self, report: dict):
        super().__init__(report["error"])
        self.report = report


@dataclass(frozen=True)
class Session:
    directory: Path
    community: str
    handle: str
    role: str

    def label(self) -> str:
        return f"{self.community}/{self.handle}"

    def view(self) -> dict:
        return {
            "community": self.community,
            "handle": self.handle,
            "role": self.role,
            "directory": str(self.directory),
            "use": f"/symposium use {self.community} {self.handle}",
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
            for context in sorted(self.root.glob("admin/*/.symposium/context.json"))
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
            held.get("community", ""),
            held.get("handle", ""),
            held.get("role", ""),
        )

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
        """`/symposium use <community> <handle>`: make that session this agent session's
        current one. With no arguments, or a session that does not exist, list them all."""
        sessions = self.all()
        if len(rest) == 2:
            community, handle = rest
            for session in sessions:
                if (
                    session.community.lower() == community.lower()
                    and session.handle == handle
                ):
                    self.make_current(session)
                    return {**session.view(), "current": True}
            error = f"no session for {handle} in {community} on this machine"
        else:
            error = "usage: /symposium use <community> <handle>"
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
        if command in ADMIN_ONLY and session.role != "admin":
            raise SessionError(
                {
                    "error": f"`{command}` is the admin's, and this agent session works as "
                    f"{session.label()}: switch with "
                    f"`/symposium use {session.community} <the admin's handle>`",
                    "sessions": [s.view() for s in self.all() if s.role == "admin"],
                }
            )
        return session.directory, session, rest

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
        """The session a NAMED command names: the server's for admin-config; the community
        file's for bootstrap and import; the invite's for setup. None for a file it cannot
        read."""
        if command == "admin-config":
            return self.root / "admin"
        if command == "setup":
            invite = self.read(rest, "--invite-file")
            if invite is None or not invite["handle"]:
                return None
            return self.member_session(invite["community"], invite["handle"])
        spec = self.read(rest, "--community-file")
        return None if spec is None else self.admin_session(spec["community"])

    # ── the command line ─────────────────────────────────────────────────────────────────
    def resolve(self, command: str, rest: list) -> list:
        """The caller's relative paths, made absolute against the caller's directory."""
        out, expecting = [], False
        for arg in rest:
            if expecting:
                out.append(self.absolute(arg))
                expecting = False
                continue
            name, equals, value = arg.partition("=")
            if name in PATH_OPTIONS:
                if equals:
                    out.append(f"{name}={self.absolute(value)}")
                else:
                    out.append(arg)
                    expecting = True
            elif (
                command in PATH_POSITIONALS
                and not arg.startswith("-")
                and (self.caller / arg).exists()
            ):
                out.append(self.absolute(arg))
            else:
                out.append(arg)
        return out

    def absolute(self, path: str) -> str:
        expanded = Path(path).expanduser()
        return str(
            expanded if expanded.is_absolute() else (self.caller / expanded).resolve()
        )

    def read(self, rest: list, option: str) -> dict | None:
        """The names in the JSON file an option names (a community file or an invite), or None
        when the option, the file or its `community` is missing."""
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
        if not isinstance(spec, dict) or not COMMUNITY.match(
            str(spec.get("community") or "")
        ):
            return None
        handle = str(spec.get("handle") or "")
        return {
            "community": spec["community"],
            "handle": handle if HANDLE.match(handle) else "",
        }
