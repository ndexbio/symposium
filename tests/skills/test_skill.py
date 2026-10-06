"""The `symposium` skill as people use it (R-I7): `/symposium bootstrap` (admins) and
`/symposium setup` (members) over the CLI, the sessions they make under `~/.symposium/`, and
what the skill says when something is missing; and the workflow commands (`publish`,
`validate`, `sync`, `gate`, `serve`) through the skill, run from any directory."""

import json
import re
import shlex
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

from skills.test_workflow import note
from suite import ADMIN, REPO, SKILL, Cli, community_file


def invite_files(directory: Path) -> list:
    return sorted(p.name for p in directory.glob("*.invite"))


def admin_session(suite, community: str) -> Path:
    return suite.home / ".symposium" / "admin" / community


def report(suite, cwd: Path, *args) -> tuple[int, str]:
    """A workflow command through the skill: a free-text report, its exit code the result."""
    result = subprocess.run(
        [sys.executable, str(SKILL), *map(str, args)],
        cwd=cwd,
        env=suite.env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode, result.stdout + result.stderr


# a stand-in agent: a long-lived process that starts the command's shell, and keeps running
STAND_IN_AGENT = "import subprocess, sys, time; subprocess.Popen(['sh', '-c', sys.argv[1]]); time.sleep(300)"


def in_the_background(suite, cwd: Path, log: Path, *args) -> subprocess.Popen:
    """A command an agent runs in the background, its output going to a file; -> the agent."""
    command = shlex.join([sys.executable, str(SKILL), *map(str, args)])
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            STAND_IN_AGENT,
            f"{command} > {shlex.quote(str(log))} 2>&1",
        ],
        cwd=cwd,
        env={**suite.env, "SYMPOSIUM_POLL": "1"},
    )


def until(log: Path, text: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if log.exists() and text in log.read_text():
            return True
        time.sleep(0.2)
    return False


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_help_names_the_data_server_image_and_prepares_nothing(skill, suite, tmp_path):
    version = re.search(
        r'^version = "([^"]+)"',
        (REPO / "data-server" / "service" / "pyproject.toml").read_text(),
        re.MULTILINE,
    ).group(1)
    usage = skill.ok(tmp_path, "--help")
    assert usage["data_server_image"] == f"ndexbio/symposium-data:{version}"
    code, _ = skill(tmp_path, "frobnicate")
    assert code == 1
    assert not (tmp_path / ".symposium").exists()  # no runtime prepared for either
    assert not (suite.home / ".symposium" / "admin").exists()  # and no session made


def test_usage_and_an_unknown_command(skill, tmp_path):
    usage = skill.ok(tmp_path, "--help")
    assert usage["usage"].startswith(
        "/symposium <setup|bootstrap|use|publish|sync|gate|validate|serve|port|admin-config"
    )
    code, out = skill(tmp_path, "frobnicate")
    assert code == 1 and "unknown command 'frobnicate'" in out["error"]


def test_a_workflow_command_without_a_context_names_setup_and_bootstrap(
    suite, tmp_path
):
    for command in (["publish", "a.json"], ["validate", "a.json"], ["sync"], ["gate"]):
        code, out = report(suite, tmp_path, *command)
        assert code == 1, (command, out)
        assert "/symposium setup --invite-file" in out, (command, out)
        assert "/symposium bootstrap --community-file" in out, (command, out)
        assert "COULD NOT REACH" not in out and "could not be reached" not in out


def test_serve_without_a_record_copy_says_to_sync(server, skill, suite, tmp_path):
    skill.ok(
        tmp_path, "bootstrap", "--community-file", community_file(tmp_path, server)
    )
    code, out = report(suite, tmp_path, "serve")
    assert code == 1 and "no record copy at" in out and "/symposium sync" in out
    assert str(admin_session(suite, "demo") / "record") in out  # the session's own copy


def test_the_workflow_through_the_skill_from_any_directory(
    server, skill, suite, tmp_path
):
    spec = community_file(tmp_path, server, "demo", ["lyra", "vega"])
    invites = skill.ok(tmp_path, "bootstrap", "--community-file", spec)["invite_files"]
    for invite in invites:
        skill.ok(tmp_path, "setup", "--invite-file", invite)
    # three sessions on one machine, the admin's and two members': `use` switches between them
    skill.ok(tmp_path, "use", "demo", "lyra")
    code, out = report(suite, tmp_path, "validate", note(tmp_path, "lyra", "check"))
    assert code == 0 and "--check: validation passed" in out, out
    code, out = report(suite, tmp_path, "publish", note(tmp_path, "lyra", "seed"))
    assert code == 0 and out.startswith("session: demo/lyra\n"), out
    assert "submitted  symposium-data:" in out, out
    skill.ok(tmp_path, "use", "demo", ADMIN)
    code, out = report(suite, tmp_path, "gate")
    assert (
        code == 0 and out.startswith(f"session: demo/{ADMIN}\n") and "ACCEPTED" in out
    ), out
    skill.ok(tmp_path, "use", "demo", "vega")
    code, out = report(suite, tmp_path, "sync")
    assert code == 0 and "+1: lyra_note_seed_v1" in out, out
    vega = suite.home / ".symposium" / "member" / "demo" / "vega"
    assert (vega / "record" / "lyra_note_seed_v1.json").exists()


def test_use_lists_switches_and_keeps_the_admins_commands_for_the_admin(
    server, skill, suite, tmp_path
):
    spec = community_file(tmp_path, server, "demo", ["lyra"])
    [invite] = skill.ok(tmp_path, "bootstrap", "--community-file", spec)["invite_files"]
    joined = skill.ok(tmp_path, "setup", "--invite-file", invite)
    assert joined["session"] == "demo/lyra"  # setup made lyra's session the current one
    assert skill.ok(tmp_path, "data", "changes", "--collection", "record")[
        "session"
    ] == ("demo/lyra")
    # any member reads the roster; changing it is the admin's, refused in lyra's session
    listed = skill.ok(tmp_path, "roster", "list")
    assert listed["session"] == "demo/lyra"
    assert [m["handle"] for m in listed["roster"]] == ["lyra"]
    code, out = skill(tmp_path, "roster", "add", "--handle", "vega")
    assert code == 1 and "/symposium use demo <the admin's handle>" in out["error"]
    code, out = skill(
        tmp_path, "use"
    )  # alone: every session, with the command for each
    assert code == 1 and sorted(s["use"] for s in out["sessions"]) == [
        f"/symposium use demo {ADMIN}",
        "/symposium use demo lyra",
    ]
    code, out = skill(tmp_path, "use", "demo", "nobody")
    assert code == 1 and "no session for nobody in demo" in out["error"]
    chosen = skill.ok(tmp_path, "use", "demo", ADMIN)
    assert chosen["role"] == "admin" and chosen["current"] is True
    roster = skill.ok(tmp_path, "roster", "list")
    assert [m["handle"] for m in roster["roster"]] == ["lyra"]
    assert roster["session"] == f"demo/{ADMIN}"


def test_a_command_without_a_context_names_setup_and_bootstrap(skill, tmp_path):
    code, out = skill(tmp_path, "roster", "list")
    assert code == 1
    assert "/symposium setup --invite-file" in out["error"]
    assert "/symposium bootstrap --community-file" in out["error"]


def test_bootstrap_reports_every_missing_field(skill, tmp_path):
    (tmp_path / "community.json").write_text("{}")
    code, out = skill(tmp_path, "bootstrap", "--community-file", "community.json")
    assert code == 1
    fields = sorted(p.split(":")[0] for p in out["problems"])
    assert fields == ["community", "data-server-url", "handles"]


def test_bootstrap_reports_every_invalid_field(server, skill, tmp_path):
    (tmp_path / "community.json").write_text(
        json.dumps(
            {
                "community": "not ok!",
                "handles": ["lyra", "bad handle", ADMIN],
                "data-server-url": server.url,
            }
        )
    )
    code, out = skill(tmp_path, "bootstrap", "--community-file", "community.json")
    assert code == 1
    problems = "\n".join(out["problems"])
    assert "'not ok!' is not a community name" in problems
    assert "'bad handle' is not a valid handle" in problems
    assert f"'{ADMIN}' is the server admin's handle" in problems
    assert "'lyra'" not in problems


def test_bootstrap_writes_invite_files_and_only_adds(server, skill, suite, tmp_path):
    spec = community_file(tmp_path, server, "demo", ["lyra", "vega"])
    first = skill.ok(tmp_path, "bootstrap", "--community-file", spec)
    assert first["created"] is True and first["added_to_roster"] == ["lyra", "vega"]
    session = admin_session(
        suite, "demo"
    )  # the admin's session: the invite files are there
    assert invite_files(session) == ["demo-lyra.invite", "demo-vega.invite"]
    assert sorted(Path(f).resolve() for f in first["invite_files"]) == sorted(
        p.resolve() for p in session.glob("*.invite")
    )
    for path in session.glob("*.invite"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert "invite" in json.loads(path.read_text())
    printed = json.dumps(first)
    for path in session.glob("*.invite"):
        assert (
            json.loads(path.read_text())["invite"] not in printed
        )  # secrets never printed

    # a member joins with its file, from any directory; setup twice is harmless
    lyra = session / "demo-lyra.invite"
    joined = skill.ok(tmp_path, "setup", "--invite-file", lyra)
    assert joined["registered"] is True and joined["handle"] == "lyra"
    again = skill.ok(tmp_path, "setup", "--invite-file", lyra)
    assert (
        again["registered"] is False and again["fingerprint"] == joined["fingerprint"]
    )
    assert (suite.home / ".symposium" / "member" / "demo" / "lyra" / "record").is_dir()

    # bootstrap again only adds, and writes the invites of those still waiting
    for path in session.glob("*.invite"):
        path.unlink()
    second = skill.ok(tmp_path, "bootstrap", "--community-file", spec)
    assert second["created"] is False and second["added_to_roster"] == []
    assert invite_files(session) == ["demo-vega.invite"]

    roster = skill.ok(tmp_path, "roster", "list")["roster"]
    assert [(m["handle"], m["registered"]) for m in roster] == [
        ("lyra", True),
        ("vega", False),
    ]


def test_one_handle_in_two_communities_gets_two_invite_files(
    server, skill, suite, tmp_path
):
    for community in ("demo", "other"):
        spec = community_file(tmp_path, server, community, ["lyra"])
        skill.ok(tmp_path, "bootstrap", "--community-file", spec)
    files = [
        admin_session(suite, "demo") / "demo-lyra.invite",
        admin_session(suite, "other") / "other-lyra.invite",
    ]
    contents = [json.loads(f.read_text()) for f in files]
    assert [c["community"] for c in contents] == ["demo", "other"]
    assert contents[0]["invite"] != contents[1]["invite"]


def test_bootstrap_refuses_a_server_bound_to_another_admin_key(
    server, skill, suite, tmp_path
):
    # another machine: its keystore holds a key it made for this server, never placed there
    other = Cli(skill.program, {**skill.env, "HOME": str(tmp_path / "other-home")})
    (tmp_path / "other-home").mkdir()
    config = other.ok(
        tmp_path, "admin-config", "--handle", ADMIN, "--data-server-url", server.url
    )
    assert (
        config["created"] is True
        and config["fingerprint"] != server.status()["fingerprint"]
    )
    spec = community_file(tmp_path, server, "demo", ["lyra"])
    code, out = other(tmp_path, "bootstrap", "--community-file", spec)
    assert (
        code == 1
        and "bound to" in out["error"]
        and config["fingerprint"] in out["error"]
    )
    assert "restart the server" in out["error"]


def test_setup_with_an_unusable_invite_file_is_refused(skill, tmp_path):
    (tmp_path / "bad.invite").write_text(json.dumps({"handle": "lyra"}))
    code, out = skill(tmp_path, "setup", "--invite-file", "bad.invite")
    assert code == 1 and "lacks" in out["error"]


def test_commands_that_keep_running_stream_their_output_and_end_with_their_agent(
    server, skill, suite, tmp_path
):
    skill.ok(
        tmp_path, "bootstrap", "--community-file", community_file(tmp_path, server)
    )
    gate_log, serve_log = tmp_path / "gate.log", tmp_path / "serve.log"
    gate = in_the_background(suite, tmp_path, gate_log, "gate", "--watch")
    serve = None
    try:
        assert until(gate_log, "watching inbox", 30), gate_log.read_text()
        code, out = report(suite, tmp_path, "publish", note(tmp_path, ADMIN, "kept"))
        assert code == 0, out
        # each decision reaches the agent as the gate prints it, while the gate keeps running
        assert until(gate_log, "ACCEPTED", 30), gate_log.read_text()
        serve = in_the_background(
            suite, tmp_path, serve_log, "serve", "--port", free_port()
        )
        assert until(serve_log, "build 1:", 30), serve_log.read_text()
    finally:
        for agent in (gate, serve):
            if agent is not None:
                agent.kill()  # the agent session ends abruptly
                agent.wait()
    for log in (gate_log, serve_log):
        assert until(log, "the agent session that started this has ended", 30), (
            log.read_text()
        )
        assert "Traceback" not in log.read_text()
    left = subprocess.run(
        ["pgrep", "-f", f"{REPO}/tools/(gate|serve).py"], capture_output=True, text=True
    )
    assert left.stdout == ""
