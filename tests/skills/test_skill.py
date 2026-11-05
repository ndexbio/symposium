"""The `symposium` skill as people use it (R-I7): `/symposium bootstrap` (server admins) and
`/symposium setup` (anyone invited) over the CLI, the sessions they make under `~/.symposium/`,
what the skill says when something is missing or a grant is not held; and the workflow
commands (`publish`, `validate`, `sync`, `gate`, `serve`) through the skill, run from any
directory."""

import json
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path

import httpx
from harness import HTTP, MAX_WAIT, Output
from skills.test_workflow import note, tool
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
        timeout=MAX_WAIT,
    )
    return result.returncode, result.stdout + result.stderr


# a stand-in agent: a process that starts the command's shell and runs until it is ended; the
# shell, the skill and its tool all write to the agent's output, as a background command does
STAND_IN_AGENT = (
    "import subprocess, sys, threading; subprocess.Popen(['sh', '-c', sys.argv[1]]); "
    "threading.Event().wait()"
)


def in_the_background(suite, cwd: Path, *args) -> tuple[subprocess.Popen, Output]:
    """A command an agent runs in the background. -> (the agent, the command's output). The
    output ends only once every process writing to it has exited."""
    command = shlex.join([sys.executable, str(SKILL), *map(str, args)])
    agent = subprocess.Popen(
        [sys.executable, "-c", STAND_IN_AGENT, f"{command} 2>&1"],
        cwd=cwd,
        env={**suite.env, "SYMPOSIUM_POLL": "1"},
        stdout=subprocess.PIPE,
        text=True,
    )
    return agent, Output(agent.stdout)


def poll(probe, message: str):
    """Poll every 0.2 s until `probe` returns something truthy. -> that value."""
    deadline = time.monotonic() + MAX_WAIT
    while True:
        value = probe()
        if value:
            return value
        assert time.monotonic() < deadline, message
        time.sleep(0.2)


def built(port) -> bool:
    """`serve` answers on its port and has finished its first build (its `/__build` state)."""
    try:
        state = HTTP.get(f"http://127.0.0.1:{port}/__build").json()
    except (httpx.HTTPError, ValueError):
        return False
    return state.get("build", 0) >= 1


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
        "/symposium <setup|admin-config|bootstrap|use-community|use|access|publish"
    )
    code, out = skill(tmp_path, "frobnicate")
    assert code == 1 and "unknown command 'frobnicate'" in out["error"]


def test_a_workflow_command_without_a_session_names_setup_and_admin_config(
    suite, tmp_path
):
    for command in (["publish", "a.json"], ["validate", "a.json"], ["sync"], ["gate"]):
        code, out = report(suite, tmp_path, *command)
        assert code == 1, (command, out)
        assert "/symposium setup --invite-file" in out, (command, out)
        assert "/symposium admin-config" in out, (command, out)
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
    # four sessions on one machine, root's, the community admin's and two members': `use`
    # switches between them
    skill.ok(tmp_path, "use", "demo", "lyra")
    code, out = report(suite, tmp_path, "validate", note(tmp_path, "lyra", "check"))
    assert code == 0 and "--check: validation passed" in out, out
    code, out = report(suite, tmp_path, "publish", note(tmp_path, "lyra", "seed"))
    assert code == 0 and out.startswith("session: demo/lyra\n"), out
    assert "submitted  symposium-data:" in out, out
    skill.ok(tmp_path, "use", "demo", "steward")
    code, out = report(suite, tmp_path, "gate")
    assert (
        code == 0 and out.startswith("session: demo/steward\n") and "ACCEPTED" in out
    ), out
    skill.ok(tmp_path, "use", "demo", "vega")
    code, out = report(suite, tmp_path, "sync")
    assert code == 0 and "+1: lyra_note_seed_v1" in out, out
    vega = suite.home / ".symposium" / "member" / "demo" / "vega"
    assert (vega / "record" / "lyra_note_seed_v1.json").exists()


def test_use_lists_switches_and_refuses_what_a_session_does_not_hold(
    server, skill, suite, tmp_path
):
    spec = community_file(tmp_path, server, "demo", ["lyra"])
    invites = skill.ok(tmp_path, "bootstrap", "--community-file", spec)["invite_files"]
    [invite] = [i for i in invites if i.endswith("demo-lyra.invite")]
    joined = skill.ok(tmp_path, "setup", "--invite-file", invite)
    assert joined["session"] == "demo/lyra"  # setup made lyra's session the current one
    assert joined["roles"] == [{"role": "community-member", "collections": ["*"]}]
    assert skill.ok(tmp_path, "data", "changes", "--collection", "record")[
        "session"
    ] == ("demo/lyra")
    # any member reads the roster; inviting takes `members`, refused in lyra's session
    listed = skill.ok(tmp_path, "roster", "list")
    assert listed["session"] == "demo/lyra"
    assert [m["handle"] for m in listed["roster"]] == ["lyra"]
    code, out = skill(
        tmp_path, "invite", "--handle", "vega", "--access", "community-member:*"
    )
    assert code == 1 and "`members` or `delegate`" in out["error"]
    assert [s["use"] for s in out["sessions"]] == [f"/symposium use demo {ADMIN}"]
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
    assert chosen["server_level"] is True and chosen["current"] is True
    roster = skill.ok(tmp_path, "roster", "list")
    assert [m["handle"] for m in roster["roster"]] == ["lyra"]
    assert roster["session"] == f"demo/{ADMIN}"
    access = skill.ok(tmp_path, "access")
    assert [r["role"] for r in access["roles"]] == ["server-root"]


def test_a_command_without_a_session_names_setup_and_admin_config(skill, tmp_path):
    code, out = skill(tmp_path, "roster", "list")
    assert code == 1
    assert "/symposium setup --invite-file" in out["error"]
    assert "/symposium admin-config" in out["error"]


def test_bootstrap_reports_every_missing_field(skill, tmp_path):
    (tmp_path / "community.json").write_text("{}")
    code, out = skill(tmp_path, "bootstrap", "--community-file", "community.json")
    assert code == 1
    fields = sorted(p.split(":")[0] for p in out["problems"])
    assert fields == ["admin", "community", "data-server-url"]


def test_bootstrap_reports_every_invalid_field(server, skill, tmp_path):
    (tmp_path / "community.json").write_text(
        json.dumps(
            {
                "community": "not ok!",
                "admin": "bad admin!",
                "handles": ["lyra", "bad handle"],
                "data-server-url": server.url,
            }
        )
    )
    code, out = skill(tmp_path, "bootstrap", "--community-file", "community.json")
    assert code == 1
    problems = "\n".join(out["problems"])
    assert "'not ok!' is not a community name" in problems
    assert "'bad handle' is not a valid handle" in problems
    assert "admin: 'bad admin!' is not a valid handle" in problems
    assert "'lyra'" not in problems


def test_bootstrap_writes_invite_files_and_only_adds(server, skill, suite, tmp_path):
    spec = community_file(tmp_path, server, "demo", ["lyra", "vega"])
    first = skill.ok(tmp_path, "bootstrap", "--community-file", spec)
    assert first["created"] is True and first["invited"] == ["lyra", "vega"]
    assert first["admin"] == "steward"
    session = admin_session(suite, "demo")  # the server admin's session holds the files
    assert invite_files(session) == [
        "demo-lyra.invite",
        "demo-steward.invite",
        "demo-vega.invite",
    ]
    assert sorted(Path(f).resolve() for f in first["invite_files"]) == sorted(
        p.resolve() for p in session.glob("*.invite")
    )
    printed = json.dumps(first)
    for path in session.glob("*.invite"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        content = json.loads(path.read_text())
        assert "roles" not in content  # the server holds the roles
        assert content["invite"] not in printed  # secrets never printed

    # a member joins with its file, from any directory; setup twice is harmless
    lyra = session / "demo-lyra.invite"
    joined = skill.ok(tmp_path, "setup", "--invite-file", lyra)
    assert joined["registered"] is True and joined["handle"] == "lyra"
    again = skill.ok(tmp_path, "setup", "--invite-file", lyra)
    assert (
        again["registered"] is False and again["fingerprint"] == joined["fingerprint"]
    )
    assert (suite.home / ".symposium" / "member" / "demo" / "lyra" / "record").is_dir()
    # the community admin joins with its own file and holds community-admin
    steward = skill.ok(
        tmp_path, "setup", "--invite-file", session / "demo-steward.invite"
    )
    assert steward["roles"] == [{"role": "community-admin", "collections": None}]

    # bootstrap again invites nobody twice, and writes the invites still waiting
    for path in session.glob("*.invite"):
        path.unlink()
    skill.ok(tmp_path, "use", "demo", ADMIN)
    second = skill.ok(tmp_path, "bootstrap", "--community-file", spec)
    assert second["created"] is False and second["invited"] == []
    assert invite_files(session) == ["demo-vega.invite"]

    roster = skill.ok(tmp_path, "roster", "list")["roster"]
    assert [(m["handle"], m["registered"]) for m in roster] == [
        ("lyra", True),
        ("steward", True),
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


def test_bootstrap_takes_a_key_the_server_knows(server, skill, suite, tmp_path):
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
    assert code == 1 and out["status"] == 401


def test_setup_with_an_unusable_invite_file_is_refused(skill, tmp_path):
    (tmp_path / "bad.invite").write_text(json.dumps({"handle": "lyra"}))
    code, out = skill(tmp_path, "setup", "--invite-file", "bad.invite")
    assert code == 1 and "lacks" in out["error"]


def test_commands_that_keep_running_stream_their_output_and_end_with_their_agent(
    server, skill, cli, suite, tmp_path
):
    spec = community_file(tmp_path, server, "demo", ["lyra"])
    invites = skill.ok(tmp_path, "bootstrap", "--community-file", spec)["invite_files"]
    # the machine's only session, root's for demo, runs the gate in the background
    gate, gate_out = in_the_background(suite, tmp_path, "gate", "--watch")
    serve = None
    try:
        # lyra works on a machine of its own: no second session on this one
        [invite] = [i for i in invites if i.endswith("demo-lyra.invite")]
        lyra = tmp_path / "lyra"
        lyra.mkdir()
        cli.ok(lyra, "context", "set", "--invite-file", invite)
        cli.ok(lyra, "owner", "register")
        code, out = tool(suite, lyra, "publish.py", note(lyra, "lyra", "kept"))
        assert code == 0, out
        # each decision reaches the agent as the gate prints it, while the gate keeps running
        gate_out.wait_for("ACCEPTED")
        assert "stopped" not in gate_out.text()
        record = skill.ok(
            tmp_path, "data", "changes", "--collection", "record", "--all"
        )
        assert [i["name"] for i in record["items"]] == ["lyra_note_kept_v1"]
        serve, serve_out = in_the_background(suite, tmp_path, "serve", "--port", 0)
        port = re.search(r"localhost:(\d+)", serve_out.wait_for("serving")).group(1)
        poll(lambda: built(port), "serve never built the record")
        assert "build 1:" in serve_out.text()
    finally:
        for agent in (gate, serve):
            if agent is not None:
                agent.kill()  # the agent session ends abruptly
                agent.wait()
    # each tool notices its agent session ended, says so, and exits: its output ends only once
    # the tool and the skill around it have both exited, the skill's last line written
    for output in (gate_out, serve_out):
        out = output.end()
        assert "the agent session that started this has ended" in out, out
        assert "Traceback" not in out


def test_keys_sharing_and_public_collections_through_the_skill(
    server, skill, suite, tmp_path
):
    """The skill's key commands and its sharing commands reach the CLI in the session that
    runs them: a member issues a non-member key reading its own collection, shares and opens
    collections, and revokes the key; root's session issues one of its own."""
    spec = community_file(tmp_path, server, "demo", ["lyra"])
    invites = skill.ok(tmp_path, "bootstrap", "--community-file", spec)["invite_files"]
    [invite] = [i for i in invites if i.endswith("demo-lyra.invite")]
    skill.ok(tmp_path, "setup", "--invite-file", invite)  # lyra's session is current
    api = f"{server.url}/v1/demo"

    (tmp_path / "scores.csv").write_bytes(b"gene,score\nBST2,0.06\n")
    skill.ok(tmp_path, "data", "collection", "create", "--name", "test_collection")
    private = skill.ok(
        tmp_path,
        "data",
        "put",
        "scores.csv",
        "--collection",
        "test_collection",
        "--name",
        "scores.csv",
    )
    issued = skill.ok(
        tmp_path,
        "gen-api-key",
        "dashboard",
        "--non-member",
        "--access",
        "community-observer:test_collection",
    )
    assert issued["session"] == "demo/lyra" and issued["member_key"] is False
    key = json.loads(Path(issued["key_file"]).read_text())["key"]
    bearer = {"Authorization": f"Bearer {key}"}
    content = f"{api}/files/{private['file_id']}/v/latest"
    assert HTTP.get(content, headers=bearer).content == b"gene,score\nBST2,0.06\n"
    assert HTTP.get(content).status_code == 401  # private: no key, no read
    narrowed = skill.ok(
        tmp_path,
        "unassign",
        "--api-key",
        issued["id"],
        "--access",
        "community-observer:test_collection",
    )
    assert narrowed["session"] == "demo/lyra"
    assert HTTP.get(content, headers=bearer).status_code in (401, 403)

    (tmp_path / "summary.csv").write_bytes(b"genes,1\n")
    skill.ok(
        tmp_path, "data", "collection", "create", "--name", "test_collection_public"
    )
    public = skill.ok(
        tmp_path,
        "data",
        "put",
        "summary.csv",
        "--collection",
        "test_collection_public",
        "--name",
        "summary.csv",
    )
    opened = skill.ok(
        tmp_path,
        "data",
        "collection",
        "set-public",
        "--collection",
        "test_collection_public",
        "--public",
    )
    assert opened["public"] is True
    collections = skill.ok(tmp_path, "data", "collection", "list")["collections"]
    owned = {c["name"]: c["public"] for c in collections if c["owner"] == "lyra"}
    assert owned == {"test_collection": False, "test_collection_public": True}
    listed = HTTP.get(f"{api}/collections/test_collection_public/changes").json()
    assert [i["name"] for i in listed["items"]] == ["summary.csv"]
    read = HTTP.get(f"{api}/files/{public['file_id']}/v/latest")
    assert read.status_code == 200 and read.content == b"genes,1\n"

    mine = skill.ok(tmp_path, "list-api-keys")
    assert [k["id"] for k in mine["keys"]] == [issued["id"]]
    skill.ok(tmp_path, "revoke-api-key", issued["id"])
    assert HTTP.get(content, headers=bearer).status_code == 401
    assert skill.ok(tmp_path, "list-api-keys")["keys"] == []

    skill.ok(tmp_path, "use", "demo", ADMIN)
    roots = skill.ok(
        tmp_path,
        "gen-api-key",
        "kiosk",
        "--non-member",
        "--access",
        "community-observer:*",
    )
    assert roots["session"] == f"demo/{ADMIN}" and roots["member_key"] is False
    skill.ok(tmp_path, "revoke-api-key", roots["id"])
