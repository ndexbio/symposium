"""The skill's sessions (R-I3, R-I7): where each agent session's state lives, and which session a
command works in. Nobody creates or enters a session directory; the skill keeps them under
`~/.symposium/`, beside the keystore:

    ~/.symposium/admin/                          admin-config's public key files
    ~/.symposium/admin/<community>/              the admin's session for a community (bootstrap)
    ~/.symposium/member/<community>/<handle>/    a member's session (setup, from the invite)

A session directory holds what a working directory holds for the CLI and the tools: the context
(`.symposium/context.json`), the runtime record, the copy of the record (`record/`), the invite
files and the event log. The skill runs every command in its session's directory.

`setup`, `bootstrap`, `import` and `admin-config` name their session themselves. Every other
command uses the one session on the machine, or the one `--community` (and `--as <handle>`, when
that community has more than one session here) selects; the skill takes those two options off
the command line. Relative paths on a command line are the caller's: they are resolved against
the directory the agent ran the command in, before the command moves into its session.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

NO_SESSION = (
    "no Symposium session on this machine: run `/symposium setup --invite-file <file>` "
    "(members) or `/symposium bootstrap --community <file>` (admins) first"
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

    def selector(self) -> str:
        return f"--community {self.community} --as {self.handle}"


class Sessions:
    def __init__(self, root: Path | None = None, caller: Path | None = None):
        self.root = root or Path.home() / ".symposium"
        self.caller = caller or Path.cwd()

    # ── the sessions on this machine ─────────────────────────────────────────────────────
    def all(self) -> list:
        found = []
        for context in sorted(
            self.root.glob("admin/*/.symposium/context.json")
        ) + sorted(self.root.glob("member/*/*/.symposium/context.json")):
            try:
                held = json.loads(context.read_text())
            except (OSError, ValueError):
                continue
            found.append(
                Session(
                    context.parents[1],
                    held.get("community", ""),
                    held.get("handle", ""),
                    held.get("role", ""),
                )
            )
        return found

    def admin_session(self, community: str) -> Path:
        return self.root / "admin" / community

    def member_session(self, community: str, handle: str) -> Path:
        return self.root / "member" / community / handle

    # ── choosing a command's session ─────────────────────────────────────────────────────
    def place(self, command: str, rest: list) -> tuple:
        """-> (the command's session directory, created when needed; its arguments, with the
        caller's paths resolved and the session options taken off)."""
        if command not in NAMED:
            # the session options first: their values are names, never the caller's paths
            rest, community, handle = self.take(rest)
            session = self.choose(community, handle, command in ADMIN_ONLY)
            return session.directory, self.resolve(command, rest)
        rest = self.resolve(command, rest)
        directory = self.named(command, rest)
        if directory is None:
            return self.caller, rest  # the tool reports what is wrong with its file
        directory.mkdir(parents=True, exist_ok=True)
        return directory, rest

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
        option = "--community" if command == "bootstrap" else "--community-file"
        spec = self.read(rest, option)
        return None if spec is None else self.admin_session(spec["community"])

    def choose(
        self, community: str | None, handle: str | None, admin: bool = False
    ) -> Session:
        """The session a command works in. An admin-only command looks only at the admin's
        sessions, one per community, so `--community` alone always chooses among them."""
        sessions = [s for s in self.all() if s.role == "admin" or not admin]
        if not sessions:
            raise SessionError({"error": NO_SESSION})
        matching = [
            s
            for s in sessions
            if (community is None or s.community.lower() == community.lower())
            and (handle is None or s.handle == handle)
        ]
        if len(matching) == 1:
            return matching[0]
        listed = [
            {
                "community": s.community,
                "handle": s.handle,
                "role": s.role,
                "select": s.selector(),
            }
            for s in sessions
        ]
        if not matching:
            raise SessionError(
                {
                    "error": "no session on this machine matches "
                    f"{self.describe(community, handle)}",
                    "sessions": listed,
                }
            )
        raise SessionError(
            {
                "error": "this machine holds several Symposium sessions: choose one with "
                "--community <name> (and --as <handle>)",
                "sessions": listed,
            }
        )

    # ── the command line ─────────────────────────────────────────────────────────────────
    def take(self, rest: list) -> tuple:
        """Take `--community` and `--as` off the command line. -> (rest, community, handle)"""
        kept, chosen = [], {"--community": None, "--as": None}
        args = iter(rest)
        for arg in args:
            name, _, value = arg.partition("=")
            if name in chosen:
                chosen[name] = value if value else next(args, None)
            else:
                kept.append(arg)
        return kept, chosen["--community"], chosen["--as"]

    def resolve(self, command: str, rest: list) -> list:
        """The caller's relative paths, made absolute against the caller's directory."""
        out, expecting = [], False
        options = PATH_OPTIONS | ({"--community"} if command == "bootstrap" else set())
        for arg in rest:
            if expecting:
                out.append(self.absolute(arg))
                expecting = False
                continue
            name, equals, value = arg.partition("=")
            if name in options:
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

    def describe(self, community, handle) -> str:
        parts = [
            f"--community {community}" if community else "",
            f"--as {handle}" if handle else "",
        ]
        return " ".join(p for p in parts if p)
