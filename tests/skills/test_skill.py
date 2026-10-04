"""#20 stage 4: the `symposium` skill as people use it (R-I7): `/symposium bootstrap` (admins)
and `/symposium setup` (members) over the CLI, the context they set, and what the skill says
when something is missing."""

import json
import os
import stat
from pathlib import Path

from suite import ADMIN, Cli, community_file


def invite_files(directory: Path) -> list:
    return sorted(p.name for p in directory.glob("*.invite"))


def test_without_the_cli_on_path_the_skill_names_the_install_step(
    skill, tmp_path, suite
):
    env = {**skill.env, "PATH": os.environ.get("PATH", "")}
    code, out = skill(tmp_path, "bootstrap", "--community", "community.json", env=env)
    assert code == 1 and "make deploy-local" in out["error"] and "PATH" in out["error"]


def test_usage_and_an_unknown_command(skill, tmp_path):
    usage = skill.ok(tmp_path, "--help")
    assert usage["usage"].startswith("/symposium <setup|bootstrap|port|admin-config")
    code, out = skill(
        tmp_path, "publish"
    )  # a workflow command: not part of the skill yet
    assert code == 1 and "unknown command" in out["error"]


def test_a_command_without_a_context_names_setup_and_bootstrap(skill, tmp_path):
    code, out = skill(tmp_path, "roster", "list")
    assert code == 1
    assert "/symposium setup --invite-file" in out["error"]
    assert "/symposium bootstrap --community" in out["error"]


def test_bootstrap_reports_every_missing_field(skill, tmp_path):
    (tmp_path / "community.json").write_text("{}")
    code, out = skill(tmp_path, "bootstrap", "--community", "community.json")
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
    code, out = skill(tmp_path, "bootstrap", "--community", "community.json")
    assert code == 1
    problems = "\n".join(out["problems"])
    assert "'not ok!' is not a community name" in problems
    assert "'bad handle' is not a valid handle" in problems
    assert f"'{ADMIN}' is the server admin's handle" in problems
    assert "'lyra'" not in problems


def test_bootstrap_writes_invite_files_and_only_adds(server, skill, tmp_path):
    spec = community_file(tmp_path, server, "demo", ["lyra", "vega"])
    first = skill.ok(tmp_path, "bootstrap", "--community", spec)
    assert first["created"] is True and first["added_to_roster"] == ["lyra", "vega"]
    assert invite_files(tmp_path) == ["demo-lyra.invite", "demo-vega.invite"]
    for path in tmp_path.glob("*.invite"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert "invite" in json.loads(path.read_text())
    printed = json.dumps(first)
    for path in tmp_path.glob("*.invite"):
        assert (
            json.loads(path.read_text())["invite"] not in printed
        )  # secrets never printed

    # a member joins with its file, in its own directory; setup twice is harmless
    lyra = tmp_path / "lyra"
    lyra.mkdir()
    joined = skill.ok(lyra, "setup", "--invite-file", tmp_path / "demo-lyra.invite")
    assert joined["registered"] is True and joined["handle"] == "lyra"
    again = skill.ok(lyra, "setup", "--invite-file", tmp_path / "demo-lyra.invite")
    assert (
        again["registered"] is False and again["fingerprint"] == joined["fingerprint"]
    )

    # bootstrap again only adds, and writes the invites of those still waiting
    for path in tmp_path.glob("*.invite"):
        path.unlink()
    second = skill.ok(tmp_path, "bootstrap", "--community", spec)
    assert second["created"] is False and second["added_to_roster"] == []
    assert invite_files(tmp_path) == ["demo-vega.invite"]

    roster = skill.ok(tmp_path, "roster", "list")["roster"]
    assert [(m["handle"], m["registered"]) for m in roster] == [
        ("lyra", True),
        ("vega", False),
    ]


def test_one_handle_in_two_communities_gets_two_invite_files(server, skill, tmp_path):
    for community in ("demo", "other"):
        spec = community_file(tmp_path, server, community, ["lyra"])
        skill.ok(tmp_path, "bootstrap", "--community", spec)
    assert invite_files(tmp_path) == ["demo-lyra.invite", "other-lyra.invite"]
    contents = [json.loads((tmp_path / f).read_text()) for f in invite_files(tmp_path)]
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
    code, out = other(tmp_path, "bootstrap", "--community", spec)
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
