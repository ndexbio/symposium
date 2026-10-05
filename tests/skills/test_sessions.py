"""The skill's sessions (R-I3, R-I7): every agent session's directory is kept under
`~/.symposium/`, each command finds its own, and the paths a caller gives stay the caller's.
On a temporary `~/.symposium/`, with no server."""

import json
import sys
from pathlib import Path

import pytest
from suite import REPO

sys.path.insert(0, str(REPO / "skills" / "symposium" / "scripts"))

from sessions import SessionError, Sessions  # noqa: E402


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path / "home" / ".symposium"


@pytest.fixture
def caller(tmp_path) -> Path:
    directory = tmp_path / "anywhere"
    directory.mkdir()
    return directory


def session(root: Path, *parts, handle: str, role: str) -> Path:
    """A session as setup or bootstrap leaves it: its directory and its context."""
    directory = root.joinpath(*parts)
    (directory / ".symposium").mkdir(parents=True)
    context = {"community": parts[1], "handle": handle, "role": role}
    (directory / ".symposium" / "context.json").write_text(json.dumps(context))
    return directory


def test_setup_and_bootstrap_make_their_sessions_from_their_files(root, caller):
    (caller / "community.json").write_text(json.dumps({"community": "demo"}))
    (caller / "lyra.invite").write_text(
        json.dumps({"community": "demo", "handle": "lyra"})
    )
    sessions = Sessions(root, caller)
    directory, rest = sessions.place("bootstrap", ["--community", "community.json"])
    assert directory == root / "admin" / "demo" and directory.is_dir()
    assert rest == ["--community", str(caller / "community.json")]  # the caller's file
    directory, rest = sessions.place("setup", ["--invite-file", "lyra.invite"])
    assert directory == root / "member" / "demo" / "lyra" and directory.is_dir()
    assert rest == ["--invite-file", str(caller / "lyra.invite")]
    assert sessions.place("admin-config", ["--handle", "a"])[0] == root / "admin"


def test_an_unusable_file_makes_no_session(root, caller):
    (caller / "community.json").write_text(json.dumps({"community": "not ok!"}))
    sessions = Sessions(root, caller)
    assert sessions.place("bootstrap", ["--community", "community.json"])[0] == caller
    assert sessions.place("setup", ["--invite-file", "missing.invite"])[0] == caller
    assert not root.exists()


def test_one_session_needs_no_options(root, caller):
    lyra = session(root, "member", "demo", "lyra", handle="lyra", role="member")
    assert Sessions(root, caller).place("sync", ["--watch"]) == (lyra, ["--watch"])


def test_several_sessions_are_chosen_by_community_and_handle(root, caller):
    admin = session(root, "admin", "demo", handle="demo-admin", role="admin")
    lyra = session(root, "member", "demo", "lyra", handle="lyra", role="member")
    other = session(root, "admin", "other", handle="demo-admin", role="admin")
    sessions = Sessions(root, caller)
    assert sessions.place("gate", ["--community", "other"]) == (other, [])
    assert sessions.place("sync", ["--community", "demo", "--as", "lyra"]) == (lyra, [])
    assert sessions.place("sync", ["--community=demo", "--as=demo-admin"]) == (
        admin,
        [],
    )
    # an admin-only command looks only at the admin's sessions: --community is enough
    assert sessions.place("gate", ["--community", "demo"]) == (admin, [])
    # and a command's own --handle is left alone
    assert sessions.place(
        "roster", ["add", "--community", "demo", "--handle", "vega"]
    ) == (
        admin,
        ["add", "--handle", "vega"],
    )
    with pytest.raises(SessionError) as several:
        sessions.place("sync", [])
    assert "several Symposium sessions" in several.value.report["error"]
    assert sorted(s["select"] for s in several.value.report["sessions"]) == [
        "--community demo --as demo-admin",
        "--community demo --as lyra",
        "--community other --as demo-admin",
    ]
    with pytest.raises(SessionError) as none:
        sessions.place("sync", ["--community", "nowhere"])
    assert "--community nowhere" in none.value.report["error"]


def test_no_session_names_setup_and_bootstrap(root, caller):
    with pytest.raises(SessionError) as missing:
        Sessions(root, caller).place("roster", ["list"])
    error = missing.value.report["error"]
    assert "/symposium setup --invite-file" in error
    assert "/symposium bootstrap --community" in error


def test_the_callers_paths_are_resolved_and_nothing_else(root, caller):
    session(root, "admin", "demo", handle="demo-admin", role="admin")
    session(root, "member", "demo", "lyra", handle="lyra", role="member")
    (caller / "note.json").write_text("{}")
    (caller / "lyra").mkdir()  # a directory named like a handle is not a path argument
    sessions = Sessions(root, caller)
    lyra = ["--as", "lyra"]
    assert sessions.place("publish", [*lyra, "--role", "researcher", "note.json"])[
        1
    ] == [
        "--role",
        "researcher",
        str(caller / "note.json"),
    ]
    assert sessions.place("roster", ["add", "--handle", "lyra"])[1] == [
        "add",
        "--handle",
        "lyra",
    ]
    assert sessions.place("data", [*lyra, "get", "x", "--out", "copy.bin"])[1] == [
        "get",
        "x",
        "--out",
        str(caller / "copy.bin"),
    ]
