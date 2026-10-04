"""#20 stage 2: the CLI's admin side against a real data server: the admin key (R-D4), the
context (R-I3), communities, the roster and invites (R-D6), rebind-key and suspect-after."""

import json
import stat
from pathlib import Path

from suite import ADMIN, community_file, place_admin_key


def mode(path) -> int:
    return stat.S_IMODE(Path(path).stat().st_mode)


def test_admin_config_reuses_its_key_and_only_new_key_replaces_it(
    server, cli, tmp_path
):
    first = cli.ok(
        tmp_path, "admin-config", "--handle", ADMIN, "--data-server-url", server.url
    )
    assert first["created"] is False  # the session's key, reused
    assert first["fingerprint"] == server.status()["fingerprint"]
    assert mode(first["public_key_file"]) == 0o644
    assert any("docker cp" in step for step in first["steps"])
    assert "warning" not in first

    code, other = cli(
        tmp_path, "admin-config", "--handle", "someone", "--data-server-url", server.url
    )
    assert (
        code == 1 and f"'{ADMIN}'" in other["error"]
    )  # the admin handle never changes

    new = cli.ok(
        tmp_path,
        "admin-config",
        "--handle",
        ADMIN,
        "--data-server-url",
        server.url,
        "--new-key",
    )
    assert new["created"] is True and "rebinds" in new["warning"]
    assert new["fingerprint"] != first["fingerprint"]
    place_admin_key(server, Path(new["public_key_file"]), new["fingerprint"])

    # the CLI signs in with the new key; the rest of the session keeps it
    cli.ok(
        tmp_path, "context", "set", "--community-file", community_file(tmp_path, server)
    )
    assert cli.ok(tmp_path, "communities", "list") == {"communities": []}


def test_without_a_context_every_command_names_setup_and_bootstrap(cli, tmp_path):
    for args in (
        ("roster", "list"),
        ("invite", "list", "--out-dir", "x"),
        ("changes", "--collection", "files"),
    ):
        code, out = cli(tmp_path, *args)
        assert code == 1
        assert "/symposium setup --invite-file" in out["error"]
        assert "/symposium bootstrap --community" in out["error"]


def test_status_and_the_context(server, cli, tmp_path):
    status = cli.ok(tmp_path, "status", "--data-server-url", server.url)
    assert status["mode"] == "operational" and status["admin"] == ADMIN
    context = cli.ok(
        tmp_path, "context", "set", "--community-file", community_file(tmp_path, server)
    )
    assert (
        context["context"]["role"] == "admin" and context["context"]["handle"] == ADMIN
    )
    assert cli.ok(tmp_path, "context", "show") == context
    assert (
        cli.ok(tmp_path, "status")["server_id"] == status["server_id"]
    )  # from the context

    code, out = cli(tmp_path, "context", "set", "--community-file", "missing.json")
    assert code == 1 and "cannot read" in out["error"]


def test_communities_are_created_idempotently(server, cli, tmp_path):
    cli.ok(
        tmp_path, "context", "set", "--community-file", community_file(tmp_path, server)
    )
    assert (
        cli.ok(tmp_path, "communities", "create", "--name", "demo")["created"] is True
    )
    assert (
        cli.ok(tmp_path, "communities", "create", "--name", "demo")["created"] is False
    )
    code, out = cli(tmp_path, "communities", "create", "--name", "not-a-slug")
    assert code == 1 and out["status"] == 400
    names = [c["name"] for c in cli.ok(tmp_path, "communities", "list")["communities"]]
    assert names == ["demo"]


def test_the_roster_changes_one_handle_at_a_time(admin_dir, cli):
    assert cli.ok(admin_dir, "roster", "add", "--handle", "lyra")["added"] is True
    assert cli.ok(admin_dir, "roster", "add", "--handle", "lyra")["added"] is False
    cli.ok(admin_dir, "roster", "add", "--handle", "vega")
    roster = cli.ok(admin_dir, "roster", "list")["roster"]
    assert [m["handle"] for m in roster] == ["lyra", "vega"]
    assert roster[0]["registered"] is False

    code, out = cli(admin_dir, "roster", "add", "--handle", ADMIN)
    assert code == 1 and out["status"] == 400  # the admin is never a member
    cli.ok(admin_dir, "roster", "remove", "--handle", "vega")
    code, out = cli(admin_dir, "roster", "remove", "--handle", "vega")
    assert code == 1 and out["status"] == 404


def test_invites_are_files_and_never_printed(server, admin_dir, cli, tmp_path):
    cli.ok(admin_dir, "roster", "add", "--handle", "lyra")
    out = admin_dir / "lyra.invite"
    issued = cli.ok(admin_dir, "invite", "--handle", "lyra", "--out", out)
    assert set(issued) == {"community", "handle", "expires", "invite_file"}  # no secret
    content = json.loads(out.read_text())
    assert mode(out) == 0o600
    assert content["handle"] == "lyra" and content["community"] == "demo"
    assert content["data-server-url"] == server.url and content["invite"].startswith(
        "sdi_"
    )

    code, refused = cli(
        admin_dir, "invite", "--handle", "mallory", "--out", admin_dir / "m.invite"
    )
    assert code == 1 and refused["status"] == 403  # not on the roster

    # the invite file sets a member's context
    member = tmp_path / "lyra"
    member.mkdir()
    context = cli.ok(member, "context", "set", "--invite-file", out)["context"]
    assert context["role"] == "member" and context["handle"] == "lyra"
    assert "invite" not in context  # the secret stays in its file
    code, admin_only = cli(member, "roster", "list")
    assert code == 1 and "admin command" in admin_only["error"]


def test_pending_invites_are_written_one_file_per_community_and_handle(
    server, admin_dir, cli
):
    # one handle invited into two communities gets two files that do not overwrite each other
    other = admin_dir / "other"
    other.mkdir()
    cli.ok(
        other,
        "context",
        "set",
        "--community-file",
        community_file(other, server, "other"),
    )
    cli.ok(other, "communities", "create", "--name", "other")
    invites = admin_dir / "invites"
    for directory in (admin_dir, other):
        cli.ok(directory, "roster", "add", "--handle", "lyra")
        cli.ok(
            directory, "invite", "--handle", "lyra", "--out", directory / "first.invite"
        )
        listed = cli.ok(directory, "invite", "list", "--out-dir", invites)
        assert [i["handle"] for i in listed["invites"]] == ["lyra"]
        assert "invite" not in listed["invites"][0]
    files = sorted(p.name for p in invites.iterdir())
    assert files == ["demo-lyra.invite", "other-lyra.invite"]
    for path in invites.iterdir():
        assert mode(path) == 0o600
        assert json.loads(path.read_text())["community"] == path.name.split("-")[0]


def test_rebind_key_writes_a_fresh_invite_and_suspect_after_needs_a_member(
    admin_dir, cli
):
    cli.ok(admin_dir, "roster", "add", "--handle", "lyra")
    out = admin_dir / "lyra-rebound.invite"
    rebound = cli.ok(admin_dir, "rebind-key", "--handle", "lyra", "--out", out)
    assert rebound["retired_keys"] == 0 and mode(out) == 0o600  # lyra never registered
    assert json.loads(out.read_text())["invite"].startswith("sdi_")
    code, nobody = cli(
        admin_dir, "rebind-key", "--handle", "mallory", "--out", admin_dir / "m"
    )
    assert code == 1 and nobody["status"] == 404

    code, out = cli(
        admin_dir,
        "suspect-after",
        "--handle",
        "lyra",
        "--at",
        "2026-10-01T12:00:00+00:00",
    )
    assert code == 1 and out["status"] == 404  # not registered: no member to flag
    code, out = cli(
        admin_dir, "suspect-after", "--handle", "lyra", "--at", "2026-10-01T12:00:00"
    )
    assert code == 1 and out["status"] == 400 and "timezone" in out["error"]
