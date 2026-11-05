"""The CLI's administration against a real data server: root's key (R-D4), the context (R-I3),
communities with their first community admin, invites carrying access roles, `access`,
`assign`/`unassign`, users, rebind-key and suspect-after."""

import json
import stat
from pathlib import Path

from suite import ADMIN, community_file, enroll, place_admin_key


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
    assert any("--set-file adminKey.publicKey=" in step for step in first["steps"])
    assert "warning" not in first
    # root's server-wide context, here
    context = cli.ok(tmp_path, "context", "show")["context"]
    assert (context["handle"], context["home"], context["community"]) == (
        ADMIN,
        None,
        None,
    )

    code, other = cli(
        tmp_path, "admin-config", "--handle", "someone", "--data-server-url", server.url
    )
    assert code == 1 and ADMIN in other["error"]

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
    assert cli.ok(tmp_path, "communities", "list") == {"communities": []}


def test_without_a_context_every_command_names_setup(cli, tmp_path):
    for args in (
        ("roster", "list"),
        ("invite", "list", "--out-dir", "x"),
        ("changes", "--collection", "files"),
    ):
        code, out = cli(tmp_path, *args)
        assert code == 1
        assert "/symposium setup --invite-file" in out["error"]


def test_status_and_the_context(server, cli, tmp_path):
    status = cli.ok(tmp_path, "status", "--data-server-url", server.url)
    assert status["mode"] == "operational" and status["root"] == ADMIN
    context = cli.ok(
        tmp_path, "context", "set", "--community-file", community_file(tmp_path, server)
    )
    held = context["context"]
    assert (held["handle"], held["home"], held["community"]) == (ADMIN, None, "demo")
    assert cli.ok(tmp_path, "context", "show") == context
    assert cli.ok(tmp_path, "status")["server_id"] == status["server_id"]

    code, out = cli(tmp_path, "context", "set", "--community-file", "missing.json")
    assert code == 1 and "cannot read" in out["error"]


def test_a_community_is_created_with_its_first_admin_invite(server, cli, tmp_path):
    cli.ok(
        tmp_path, "context", "set", "--community-file", community_file(tmp_path, server)
    )
    invite = tmp_path / "steward.invite"
    made = cli.ok(
        tmp_path,
        "communities",
        "create",
        "--name",
        "demo",
        "--admin",
        "steward",
        "--out",
        invite,
    )
    assert made["created"] is True and made["admin_invite_file"] == str(invite)
    assert mode(invite) == 0o600 and "admin_invite" not in made
    again = cli.ok(
        tmp_path, "communities", "create", "--name", "demo", "--admin", "steward"
    )
    assert again["created"] is False and "admin_invite_file" not in again
    code, out = cli(
        tmp_path, "communities", "create", "--name", "not-a-slug", "--admin", "x"
    )
    assert code == 1 and out["status"] == 400
    names = [c["name"] for c in cli.ok(tmp_path, "communities", "list")["communities"]]
    assert names == ["demo"]
    # the admin joins with its invite and holds community-admin
    steward = tmp_path / "steward"
    steward.mkdir()
    cli.ok(steward, "context", "set", "--invite-file", invite)
    joined = cli.ok(steward, "owner", "register")
    assert joined["roles"] == [{"role": "community-admin", "collections": None}]
    access = cli.ok(steward, "access")
    assert access["context"]["community"] == "demo"
    assert {"gate", "members", "export"} <= set(access["context"]["grants"])
    assert len(access["access_roles"]) == 6
    cached = cli.ok(steward, "context", "show")["context"]["access"]
    assert cached["roles"] == access["roles"]


def test_invites_carry_access_and_are_files_never_printed(
    server, admin_dir, cli, tmp_path
):
    out = admin_dir / "lyra.invite"
    issued = cli.ok(
        admin_dir,
        "invite",
        "--handle",
        "lyra",
        "--access",
        "community-observer:*",
        "--out",
        out,
    )
    # a server on this machine's loopback: the CLI warns the invite works only here
    assert set(issued) - {"warning"} == {
        "community",
        "handle",
        "roles",
        "expires",
        "invite_file",
    }
    assert issued["roles"] == [{"role": "community-observer", "collections": ["*"]}]
    content = json.loads(out.read_text())
    assert mode(out) == 0o600 and "roles" not in content
    assert content["handle"] == "lyra" and content["community"] == "demo"
    assert content["data-server-url"] == server.url
    assert content["invite"].startswith("sdi_")

    for bad in ("community-member", "community-member:x:y:*", "nobody"):
        code, refused = cli(
            admin_dir, "invite", "--handle", "m", "--access", bad, "--out", "m.invite"
        )
        assert code == 1 and "error" in refused, bad
    code, refused = cli(
        admin_dir, "invite", "--handle", "m", "--access", "community-member"
    )
    assert (
        code == 1
        and "community-member:*" in refused["error"]
        or "--out" in (refused["error"])
    )

    member = tmp_path / "lyra"
    member.mkdir()
    context = cli.ok(member, "context", "set", "--invite-file", out)["context"]
    assert context["home"] == "demo" and context["handle"] == "lyra"
    assert "invite" not in context  # the secret stays in its file
    cli.ok(member, "owner", "register")
    code, refused = cli(
        member,
        "invite",
        "--handle",
        "vega",
        "--access",
        "community-member:*",
        "--out",
        "v",
    )
    assert code == 1 and refused["status"] == 403  # an observer holds no members


def test_pending_invites_are_written_one_file_per_community_and_handle(
    server, admin_dir, cli
):
    other = admin_dir / "other"
    other.mkdir()
    cli.ok(
        other,
        "context",
        "set",
        "--community-file",
        community_file(other, server, "other"),
    )
    cli.ok(other, "communities", "create", "--name", "other", "--admin", "boss")
    invites = admin_dir / "invites"
    for directory in (admin_dir, other):
        cli.ok(
            directory,
            "invite",
            "--handle",
            "lyra",
            "--access",
            "community-member:*",
            "--out",
            directory / "first.invite",
        )
        listed = cli.ok(directory, "invite", "list", "--out-dir", invites)
        assert "lyra" in [i["handle"] for i in listed["invites"]]
        assert all("invite" not in i for i in listed["invites"])
    files = sorted(p.name for p in invites.iterdir())
    assert files == [
        "demo-lyra.invite",
        "demo-steward.invite",
        "other-boss.invite",
        "other-lyra.invite",
    ]
    for path in invites.iterdir():
        assert mode(path) == 0o600
        assert json.loads(path.read_text())["community"] == path.name.split("-")[0]


def test_assign_unassign_and_users(admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra", "community-observer:files")
    cli.ok(admin_dir, "collection", "create", "--name", "c1")
    cli.ok(
        admin_dir,
        "assign",
        "--handle",
        "lyra",
        "--access",
        "community-observer:c1",
    )
    held = cli.ok(lyra, "access")["roles"]
    assert [(r["role"], sorted(r["collections"])) for r in held] == [
        ("community-observer", ["c1", "files"])
    ]
    cli.ok(
        admin_dir,
        "unassign",
        "--handle",
        "lyra",
        "--access",
        "community-observer:files",
    )
    cli.ok(admin_dir, "assign", "--handle", "lyra", "--access", "community-member:*")
    cli.ok(admin_dir, "unassign", "--handle", "lyra", "--access", "community-observer")
    held = cli.ok(lyra, "access")["roles"]
    assert held == [{"role": "community-member", "collections": ["*"]}]

    users = cli.ok(admin_dir, "users", "list")["users"]
    assert {u["handle"] for u in users} == {"lyra"}  # steward has not joined yet
    removed = cli.ok(admin_dir, "users", "remove", "--handle", "lyra")
    assert removed["removed"]
    code, out = cli(lyra, "roster", "list")
    assert code == 1 and out["status"] == 401 and "removed from demo" in out["error"]
    roster = cli.ok(admin_dir, "roster", "list")
    assert roster["roster"][0]["removed"] and ADMIN in roster["server_users"]


def test_a_server_admin_joins_by_invite_and_works_in_any_community(
    admin_dir, cli, tmp_path
):
    # ana's own machine: a HOME of its own
    home = tmp_path / "ana-home"
    env = {**cli.env, "HOME": str(home)}
    invite = tmp_path / "ana.invite"
    issued = cli.ok(
        admin_dir,
        "invite",
        "--handle",
        "ana",
        "--access",
        "server-admin",
        "--out",
        invite,
    )
    assert issued["community"] is None
    ana = tmp_path / "ana"
    ana.mkdir()
    code, set_ = cli(ana, "context", "set", "--invite-file", invite, env=env)
    context = set_["context"]
    assert context["home"] is None and context["community"] is None
    assert cli(ana, "owner", "register", env=env)[0] == 0
    code, access = cli(ana, "access", env=env)
    assert code == 0, access
    assert access["context"]["community"] is None
    assert "communities" in access["context"]["grants"]
    assert "delegate" not in access["context"]["grants"]
    code, refused = cli(
        ana,
        "invite",
        "--handle",
        "ben",
        "--access",
        "server-admin",
        "--out",
        "b",
        env=env,
    )
    assert code == 1 and refused["status"] == 403
    users = cli.ok(admin_dir, "users", "list", "--server")["users"]
    assert {u["handle"] for u in users} == {ADMIN, "ana"}


def test_rebind_key_and_suspect_after(admin_dir, cli):
    enroll(cli, admin_dir, "lyra")
    out = admin_dir / "lyra-rebound.invite"
    rebound = cli.ok(admin_dir, "rebind-key", "--handle", "lyra", "--out", out)
    assert rebound["retired_keys"] == 1 and mode(out) == 0o600
    assert json.loads(out.read_text())["invite"].startswith("sdi_")
    code, nobody = cli(
        admin_dir, "rebind-key", "--handle", "mallory", "--out", admin_dir / "m"
    )
    assert code == 1 and nobody["status"] == 404
    flagged = cli.ok(
        admin_dir,
        "suspect-after",
        "--handle",
        "lyra",
        "--at",
        "2026-10-01T12:00:00+00:00",
    )
    assert flagged["suspect_after"].startswith("2026-10-01T12:00:00")
    code, out = cli(
        admin_dir, "suspect-after", "--handle", "lyra", "--at", "2026-10-01T12:00:00"
    )
    assert code == 1 and out["status"] == 400 and "timezone" in out["error"]
