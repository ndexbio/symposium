"""The skill's sessions (R-I3, R-I7): every agent session's directory is kept under
`~/.symposium/`; `/symposium use` chooses this agent session's current one, kept per agent
process (its PID and start time); each command finds its session; the paths a caller gives stay
the caller's. On a temporary `~/.symposium/` and an injected process table, with no server."""

import json
import sys
from pathlib import Path

import pytest
from suite import REPO

sys.path.insert(0, str(REPO / "skills" / "symposium" / "scripts"))

from agent_process import AgentProcess, Process  # noqa: E402
from sessions import SessionError, Sessions  # noqa: E402


class Table:
    """An injected process table: two agents (pids 200 and 400), each starting a shell."""

    def __init__(self):
        self.rows = {
            1: Process(1, 0, "boot", "init"),
            200: Process(200, 1, "a1", "agent"),
            300: Process(300, 200, "s1", "zsh"),
            400: Process(400, 1, "a2", "agent"),
            500: Process(500, 400, "s2", "bash"),
        }

    def get(self, pid):
        return self.rows.get(pid)


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path / "home" / ".symposium"


@pytest.fixture
def caller(tmp_path) -> Path:
    directory = tmp_path / "anywhere"
    directory.mkdir()
    return directory


@pytest.fixture
def table() -> Table:
    return Table()


def agent_session(root, caller, table, shell: int) -> Sessions:
    """The skill as run by one agent session: its commands start in that agent's shell."""
    return Sessions(root, caller, AgentProcess(table, windows=False, start=shell))


def session(root: Path, *parts, handle: str, role: str) -> Path:
    """A session as setup or bootstrap leaves it: its directory and its context."""
    directory = root.joinpath(*parts)
    (directory / ".symposium").mkdir(parents=True)
    context = {"community": parts[1], "handle": handle, "role": role}
    (directory / ".symposium" / "context.json").write_text(json.dumps(context))
    return directory


def test_setup_and_bootstrap_make_their_sessions_from_their_files(root, caller, table):
    (caller / "community.json").write_text(json.dumps({"community": "demo"}))
    (caller / "lyra.invite").write_text(
        json.dumps({"community": "demo", "handle": "lyra"})
    )
    sessions = agent_session(root, caller, table, 300)
    directory, _, rest = sessions.place(
        "bootstrap", ["--community-file", "community.json"]
    )
    assert directory == root / "admin" / "demo" and directory.is_dir()
    assert rest == ["--community-file", str(caller / "community.json")]  # the caller's
    directory, _, rest = sessions.place("setup", ["--invite-file", "lyra.invite"])
    assert directory == root / "member" / "demo" / "lyra" and directory.is_dir()
    assert rest == ["--invite-file", str(caller / "lyra.invite")]
    assert sessions.place("admin-config", ["--handle", "a"])[0] == root / "admin"


def test_an_unusable_file_makes_no_session(root, caller, table):
    (caller / "community.json").write_text(json.dumps({"community": "not ok!"}))
    sessions = agent_session(root, caller, table, 300)
    assert (
        sessions.place("bootstrap", ["--community-file", "community.json"])[0] == caller
    )
    assert sessions.place("setup", ["--invite-file", "missing.invite"])[0] == caller
    assert not root.exists()


def test_with_no_choice_the_machines_only_session_is_used(root, caller, table):
    lyra = session(root, "member", "demo", "lyra", handle="lyra", role="member")
    directory, chosen, rest = agent_session(root, caller, table, 300).place(
        "sync", ["--watch"]
    )
    assert (directory, chosen.label(), rest) == (lyra, "demo/lyra", ["--watch"])


def test_several_sessions_need_a_choice(root, caller, table):
    session(root, "admin", "demo", handle="demo-admin", role="admin")
    session(root, "member", "demo", "lyra", handle="lyra", role="member")
    with pytest.raises(SessionError) as several:
        agent_session(root, caller, table, 300).place("sync", [])
    assert "/symposium use <community> <handle>" in several.value.report["error"]
    assert sorted(s["use"] for s in several.value.report["sessions"]) == [
        "/symposium use demo demo-admin",
        "/symposium use demo lyra",
    ]


def test_use_switches_this_agent_session_only(root, caller, table):
    admin = session(root, "admin", "demo", handle="demo-admin", role="admin")
    lyra = session(root, "member", "demo", "lyra", handle="lyra", role="member")
    first = agent_session(root, caller, table, 300)  # agent 200
    second = agent_session(root, caller, table, 500)  # agent 400
    assert first.use(["demo", "lyra"])["directory"] == str(lyra)
    assert second.use(["demo", "demo-admin"])["role"] == "admin"
    assert first.place("sync", [])[0] == lyra  # unchanged by the other agent's choice
    assert second.place("gate", [])[0] == admin
    first.use(["demo", "demo-admin"])
    assert first.place("gate", [])[0] == admin
    records = sorted(p.name for p in (root / "current").glob("*.json"))
    assert records == ["200.json", "400.json"]


def test_use_with_no_arguments_or_no_such_session_lists_them_and_changes_nothing(
    root, caller, table
):
    session(root, "admin", "demo", handle="demo-admin", role="admin")
    sessions = agent_session(root, caller, table, 300)
    for args in ([], ["demo", "nobody"]):
        with pytest.raises(SessionError) as refused:
            sessions.use(args)
        listed = refused.value.report["sessions"]
        assert listed[0]["use"] == "/symposium use demo demo-admin"
    assert not (root / "current").exists()


def test_no_session_names_setup_and_bootstrap(root, caller, table):
    with pytest.raises(SessionError) as missing:
        agent_session(root, caller, table, 300).place("roster", ["list"])
    error = missing.value.report["error"]
    assert "/symposium setup --invite-file" in error
    assert "/symposium bootstrap --community-file" in error


def test_an_admin_command_is_refused_in_a_members_session(root, caller, table):
    session(root, "admin", "demo", handle="demo-admin", role="admin")
    session(root, "member", "demo", "lyra", handle="lyra", role="member")
    sessions = agent_session(root, caller, table, 300)
    sessions.use(["demo", "lyra"])
    with pytest.raises(SessionError) as refused:
        sessions.place("roster", ["add", "--handle", "vega"])
    assert "/symposium use demo <the admin's handle>" in refused.value.report["error"]


def test_a_member_lists_the_roster_but_does_not_change_it(root, caller, table):
    session(root, "admin", "demo", handle="demo-admin", role="admin")
    lyra = session(root, "member", "demo", "lyra", handle="lyra", role="member")
    sessions = agent_session(root, caller, table, 300)
    sessions.use(["demo", "lyra"])
    assert sessions.place("roster", ["list"])[0] == lyra  # any member reads it
    for change in (["add", "--handle", "vega"], ["remove", "--handle", "vega"]):
        with pytest.raises(SessionError) as refused:
            sessions.place("roster", change)
        assert refused.value.report["error"].startswith(
            f"`roster {change[0]}` is the admin's"
        )
    with pytest.raises(SessionError):
        sessions.place("roster", [])


def test_a_reused_pid_is_a_new_agent_session(root, caller, table):
    session(root, "admin", "demo", handle="demo-admin", role="admin")
    session(root, "member", "demo", "lyra", handle="lyra", role="member")
    agent_session(root, caller, table, 300).use(["demo", "lyra"])
    # agent 200 ends, and a new process gets its PID: it has not chosen anything
    table.rows[200] = Process(200, 1, "a9", "agent")
    with pytest.raises(SessionError):
        agent_session(root, caller, table, 300).place("sync", [])


def test_records_of_ended_agent_processes_are_purged(root, caller, table):
    session(root, "member", "demo", "lyra", handle="lyra", role="member")
    agent_session(root, caller, table, 500).use(["demo", "lyra"])  # agent 400
    del table.rows[400], table.rows[500]  # agent 400 ends
    agent_session(root, caller, table, 300).use(["demo", "lyra"])  # agent 200 records
    assert sorted(p.name for p in (root / "current").glob("*.json")) == ["200.json"]


def test_the_callers_paths_are_resolved_and_nothing_else(root, caller, table):
    session(root, "member", "demo", "lyra", handle="lyra", role="member")
    (caller / "note.json").write_text("{}")
    (caller / "lyra").mkdir()  # a directory named like a handle is not a path argument
    sessions = agent_session(root, caller, table, 300)
    assert sessions.place("publish", ["--role", "researcher", "note.json"])[2] == [
        "--role",
        "researcher",
        str(caller / "note.json"),
    ]
    assert sessions.resolve("roster", ["add", "--handle", "lyra"]) == [
        "add",
        "--handle",
        "lyra",
    ]
    assert sessions.place("data", ["get", "x", "--out", "copy.bin"])[2] == [
        "get",
        "x",
        "--out",
        str(caller / "copy.bin"),
    ]
