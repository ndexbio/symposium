"""The sessions on a machine, and which one a command works in.

Nobody creates or enters a session directory; they are kept under `~/.symposium/`, beside the
keystore, one folder per community and user (`admin`, the one name no community may take, holds
the server-wide sessions):

    ~/.symposium/admin/admin/<handle>/           a server-level user's server-wide session
    ~/.symposium/admin/<community>/<handle>/     a server-level user's session for a community
    ~/.symposium/member/<community>/<handle>/    a community user's session, from the invite
    ~/.symposium/current/<pid>.json              each agent session's current session

A session directory holds what a working directory holds for the CLI and the tools: the context
(`.symposium/context.json`, with the access the server resolved for its user), the runtime record,
the copy of the record (`record/`), the invite files and the event log.

**This is here rather than in the skill so that a skill built on Symposium resolves the same
session the Symposium skill does.** The choice is kept per agent process (`agent_process`), which
is found by walking up past shells and wrappers, so every skill a given agent runs lands on the
same record and `/symposium use` applies to all of them. Where an agent session has chosen none,
the machine's only session is used.

What this module does NOT know is how a command line is written: which commands name their own
session, which take a grant, which arguments are the caller's paths. That is the dispatcher's, and
it subclasses `Sessions` to add it.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .agent_process import AgentProcess
from .record import Record

NO_SESSION = (
    "no Symposium session on this machine: run `/symposium setup --invite-file <file>` (with "
    "an invite) or, as root, `/symposium admin-config` first"
)
# the scope of the server-wide sessions under admin/: the one name no community may take
SERVER = "admin"
# names that may name a session directory: a community (a slug) and a handle
COMMUNITY = re.compile(r"^[A-Za-z0-9_]{1,20}$")
HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class SessionError(Exception):
    """A command whose session cannot be chosen: `report` says why, and how to choose."""

    def __init__(self, report: dict):
        super().__init__(report["error"])
        self.report = report


@dataclass(frozen=True)
class Result:
    """What one of the Symposium tools answered. The tools print for a person to read and carry
    their verdict in the exit code, so that is what is passed on rather than a parse of their
    prose: `ok` to branch on, `output` to show or to record."""

    ok: bool
    code: int
    output: str


@dataclass(frozen=True)
class Session:
    directory: Path
    community: str  # "" for a server-wide session
    handle: str
    home: str  # "" for a server-level user
    access: dict

    @classmethod
    def from_env(cls) -> Session:
        """The session this agent session is working in: the one `/symposium use` chose, else
        the machine's only one. Raises SessionError naming the alternatives otherwise."""
        return Sessions().chosen()

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

    # ── working in the record ────────────────────────────────────────────────────────────
    @property
    def record(self) -> Record:
        """The local copy of this community's record, for reading."""
        return Record(self.directory / "record")

    def sync(self) -> Result:
        """Bring the local copy of the record up to date with the server."""
        return self._run("sync.py", [])

    def check(self, artifact: Path | str, role: str | None = None) -> Result:
        """What the gate would say about an artifact, uploading nothing. A refusal is an
        answer rather than a failure, so it comes back as `ok` false with the reasons in
        `output`, and only a broken toolchain raises."""
        return self._run("publish.py", [*self._role(role), "--check", artifact])

    def publish(self, artifact: Path | str, role: str | None = None) -> Result:
        """Submit one artifact to the gate. One per call, because the gate stamps one `created`
        per artifact and validates each against the record as it stood at that moment."""
        return self._run("publish.py", [*self._role(role), artifact])

    @staticmethod
    def _role(role: str | None) -> list:
        return ["--role", role] if role else []

    def _run(self, tool: str, args: list) -> Result:
        from . import toolchain

        code, output = toolchain.run(tool, args, self.directory)
        return Result(ok=code == 0, code=code, output=output)


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
            for context in sorted(self.root.glob("admin/*/*/.symposium/context.json"))
            + sorted(self.root.glob("member/*/*/.symposium/context.json"))
            if (s := self.at(context.parents[1])) is not None
        ]

    def settle(self):
        """Give each server-level session its user's own folder: a session whose context sits
        directly in `admin/<community>/` moves to `admin/<community>/<handle>/`, and one in
        `admin/` itself (the server-wide session, with root's public key files and API key
        files) to `admin/admin/<handle>/`."""
        folder = self.root / "admin"
        if not folder.is_dir():
            return
        for directory in sorted(p for p in folder.iterdir() if p.is_dir()):
            handle = self.handle_in(directory)
            if directory.name == SERVER or handle is None:
                continue
            moving = folder / f".{directory.name}.moving"
            directory.rename(moving)
            directory.mkdir()
            moving.rename(directory / handle)
        handle = self.handle_in(folder)
        if handle is None:
            return
        target = self.server_session(handle)
        if (target / ".symposium").exists():
            return
        target.mkdir(parents=True)
        for entry in list(folder.iterdir()):
            if entry.name == SERVER or (
                entry.is_dir() and any(entry.glob("*/.symposium/context.json"))
            ):
                continue
            entry.rename(target / entry.name)

    @staticmethod
    def handle_in(directory: Path) -> str | None:
        """The handle of the session whose context is directly in `directory`, or None."""
        try:
            handle = json.loads(
                (directory / ".symposium" / "context.json").read_text()
            ).get("handle")
        except (OSError, ValueError):
            return None
        return handle if isinstance(handle, str) and HANDLE.match(handle) else None

    def at(self, directory: Path) -> Session | None:
        """The session in a directory, from its context, or None."""
        try:
            held = json.loads((directory / ".symposium" / "context.json").read_text())
        except (OSError, ValueError):
            return None
        # a session the 0.1 skill made names no home until the CLI's next command writes it:
        # a member's session sits under member/, in its home community
        home = held.get("home")
        if "home" not in held and held.get("role") == "member":
            home = held.get("community")
        return Session(
            directory,
            held.get("community") or "",
            held.get("handle", ""),
            home or "",
            held.get("access") or {},
        )

    def server_session(self, handle: str) -> Path:
        return self.root / "admin" / SERVER / handle

    def admin_session(self, community: str, handle: str) -> Path:
        return self.root / "admin" / community / handle

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
