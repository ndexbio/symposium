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


MEMBER = {"publish": None, "read": ["*"], "write": ["*"], "manage": []}
ADMIN = {"gate": None, "members": None, "export": None, "communities": None}


def session(root: Path, *parts, handle: str, grants=None) -> Path:
    """A session as setup, bootstrap or admin-config leaves it: its directory and its context,
    with the access `access` cached. A session under `admin/` is a server-level user's."""
    directory = root.joinpath(*parts)
    (directory / ".symposium").mkdir(parents=True)
    server_level = parts[0] == "admin"
    community = parts[1] if len(parts) > 1 else None
    context = {
        "community": community,
        "handle": handle,
        "home": None if server_level else community,
    }
    if grants is not None:
        context["access"] = {"roles": [], "context": {"grants": grants}}
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
    # a server-level invite: the server-wide session; use-community: a community's
    (caller / "ana.invite").write_text(json.dumps({"community": None, "handle": "ana"}))
    directory, _, _ = sessions.place("setup", ["--invite-file", "ana.invite"])
    assert directory == root / "admin"
    assert sessions.place("use-community", ["demo"])[0] == root / "admin" / "demo"


def test_an_unusable_file_makes_no_session(root, caller, table):
    (caller / "community.json").write_text(json.dumps({"community": "not ok!"}))
    sessions = agent_session(root, caller, table, 300)
    assert (
        sessions.place("bootstrap", ["--community-file", "community.json"])[0] == caller
    )
    assert sessions.place("setup", ["--invite-file", "missing.invite"])[0] == caller
    assert not root.exists()


def test_with_no_choice_the_machines_only_session_is_used(root, caller, table):
    lyra = session(root, "member", "demo", "lyra", handle="lyra", grants=MEMBER)
    directory, chosen, rest = agent_session(root, caller, table, 300).place(
        "sync", ["--watch"]
    )
    assert (directory, chosen.label(), rest) == (lyra, "demo/lyra", ["--watch"])


def test_several_sessions_need_a_choice(root, caller, table):
    session(root, "admin", "demo", handle="demo-admin", grants=ADMIN)
    session(root, "member", "demo", "lyra", handle="lyra", grants=MEMBER)
    with pytest.raises(SessionError) as several:
        agent_session(root, caller, table, 300).place("sync", [])
    assert "/symposium use <community> <handle>" in several.value.report["error"]
    assert sorted(s["use"] for s in several.value.report["sessions"]) == [
        "/symposium use demo demo-admin",
        "/symposium use demo lyra",
    ]


def test_use_switches_this_agent_session_only(root, caller, table):
    admin = session(root, "admin", "demo", handle="demo-admin", grants=ADMIN)
    lyra = session(root, "member", "demo", "lyra", handle="lyra", grants=MEMBER)
    first = agent_session(root, caller, table, 300)  # agent 200
    second = agent_session(root, caller, table, 500)  # agent 400
    assert first.use(["demo", "lyra"])["directory"] == str(lyra)
    assert second.use(["demo", "demo-admin"])["server_level"] is True
    assert first.place("sync", [])[0] == lyra  # unchanged by the other agent's choice
    assert second.place("gate", [])[0] == admin
    first.use(["demo", "demo-admin"])
    assert first.place("gate", [])[0] == admin
    records = sorted(p.name for p in (root / "current").glob("*.json"))
    assert records == ["200.json", "400.json"]


def test_use_with_no_arguments_or_no_such_session_lists_them_and_changes_nothing(
    root, caller, table
):
    session(root, "admin", "demo", handle="demo-admin", grants=ADMIN)
    sessions = agent_session(root, caller, table, 300)
    for args in ([], ["demo", "nobody"]):
        with pytest.raises(SessionError) as refused:
            sessions.use(args)
        listed = refused.value.report["sessions"]
        assert listed[0]["use"] == "/symposium use demo demo-admin"
    assert not (root / "current").exists()


def test_no_session_names_setup_and_admin_config(root, caller, table):
    with pytest.raises(SessionError) as missing:
        agent_session(root, caller, table, 300).place("roster", ["list"])
    error = missing.value.report["error"]
    assert "/symposium setup --invite-file" in error
    assert "/symposium admin-config" in error


def test_a_command_is_refused_where_its_grant_is_not_held(root, caller, table):
    session(root, "admin", "demo", handle="demo-admin", grants=ADMIN)
    session(root, "member", "demo", "lyra", handle="lyra", grants=MEMBER)
    sessions = agent_session(root, caller, table, 300)
    sessions.use(["demo", "lyra"])
    _, lyra, _ = sessions.place("invite", ["--handle", "vega"])
    refused = sessions.refusal("invite", lyra)
    assert "`members` or `delegate`" in refused["error"]
    assert [s["use"] for s in refused["sessions"]] == ["/symposium use demo demo-admin"]
    assert sessions.refusal("publish", lyra) is None
    assert sessions.refusal("roster", lyra) is None  # any member reads it
    sessions.use(["demo", "demo-admin"])
    _, admin, _ = sessions.place("gate", [])
    assert sessions.refusal("gate", admin) is None
    assert "`publish`" in sessions.refusal("publish", admin)["error"]


def test_with_nothing_cached_the_server_decides(root, caller, table):
    session(root, "member", "demo", "lyra", handle="lyra")
    sessions = agent_session(root, caller, table, 300)
    _, lyra, _ = sessions.place("invite", [])
    assert sessions.refusal("invite", lyra) is None


def test_a_server_wide_session_runs_server_commands_and_no_community_ones(
    root, caller, table
):
    server = session(root, "admin", handle="demo-admin", grants=ADMIN)
    sessions = agent_session(root, caller, table, 300)
    assert sessions.use(["demo-admin"])["use"] == "/symposium use demo-admin"
    assert sessions.place("invite", ["--handle", "ana"])[0] == server
    with pytest.raises(SessionError) as refused:
        sessions.place("gate", [])
    assert "/symposium use-community <community>" in refused.value.report["error"]


def test_a_reused_pid_is_a_new_agent_session(root, caller, table):
    session(root, "admin", "demo", handle="demo-admin", grants=ADMIN)
    session(root, "member", "demo", "lyra", handle="lyra", grants=MEMBER)
    agent_session(root, caller, table, 300).use(["demo", "lyra"])
    # agent 200 ends, and a new process gets its PID: it has not chosen anything
    table.rows[200] = Process(200, 1, "a9", "agent")
    with pytest.raises(SessionError):
        agent_session(root, caller, table, 300).place("sync", [])


def test_records_of_ended_agent_processes_are_purged(root, caller, table):
    session(root, "member", "demo", "lyra", handle="lyra", grants=MEMBER)
    agent_session(root, caller, table, 500).use(["demo", "lyra"])  # agent 400
    del table.rows[400], table.rows[500]  # agent 400 ends
    agent_session(root, caller, table, 300).use(["demo", "lyra"])  # agent 200 records
    assert sorted(p.name for p in (root / "current").glob("*.json")) == ["200.json"]


def test_the_callers_paths_are_resolved_and_nothing_else(root, caller, table):
    session(root, "member", "demo", "lyra", handle="lyra", grants=MEMBER)
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
    # an issued key's file, read with no session context, is the caller's path too
    (caller / "dashboard.key").write_text("{}")
    assert sessions.place(
        "data", ["get", "x", "--out", "copy.bin", "--api-key-file", "dashboard.key"]
    )[2] == [
        "get",
        "x",
        "--out",
        str(caller / "copy.bin"),
        "--api-key-file",
        str(caller / "dashboard.key"),
    ]
    # an option's value names something on the server, even when a local file shares its name
    (caller / "scores.csv").write_text("gene,score\n")
    assert sessions.place(
        "data", ["put", "scores.csv", "--collection", "lab", "--name", "scores.csv"]
    )[2] == [
        "put",
        str(caller / "scores.csv"),
        "--collection",
        "lab",
        "--name",
        "scores.csv",
    ]
    assert sessions.place(
        "data", ["collection", "set-public", "--public", "--collection", "scores.csv"]
    )[2] == ["collection", "set-public", "--public", "--collection", "scores.csv"]
