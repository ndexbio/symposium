"""The CLI's member side against a real data server, with every setup step done through
the CLI's own admin commands: registration (R-D1, R-D5), files and versions (R-A, R-B),
collections, grants and API keys (R-E), lookups, verify and promote (R-G), and what
rebind-key and suspect-after do to a registered member."""

import hashlib
import json
import stat
from pathlib import Path

from suite import ADMIN, enroll


def write(directory: Path, name: str, content: bytes) -> Path:
    path = directory / name
    path.write_bytes(content)
    return path


def test_registration_by_invite_file_is_idempotent(admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    again = cli.ok(lyra, "owner", "register")
    assert (
        again["registered"] is False
    )  # already registered with this key: nothing changes
    me = cli.ok(lyra, "owner", "whoami")
    assert me["handle"] == "lyra" and me["community"] == "demo"
    assert (me["role"], me["kind"]) == ("member", "session")
    assert {"collection": "files", "perm": "write"} in me["grants"]
    pubkey = cli.ok(lyra, "owner", "pubkey")
    assert pubkey["fingerprint"] == me["kid"] == again["fingerprint"]
    roster = cli.ok(admin_dir, "roster", "list")["roster"]
    assert roster == [{"handle": "lyra", "registered": True, "invite_expires": None}]
    assert cli.ok(lyra, "roster", "list")["roster"] == roster  # any member reads it too


def test_a_member_context_cannot_run_admin_commands_nor_an_admin_member_ones(
    admin_dir, cli
):
    lyra = enroll(cli, admin_dir, "lyra")
    code, out = cli(lyra, "communities", "list")
    assert code == 1 and "admin command" in out["error"]
    code, out = cli(admin_dir, "owner", "register")
    assert code == 1 and "member's command" in out["error"]


def test_files_and_versions(admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    v1 = cli.ok(
        lyra,
        "put",
        write(lyra, "data.csv", b"gene,score\nBST2,0.91\n"),
        "--collection",
        "files",
        "--name",
        "data.csv",
        "--metadata",
        '{"kind": "table"}',
        "--content-type",
        "text/csv",
    )
    fid = v1["file_id"]
    assert (
        v1["version"] == 1
        and v1["sha256"] == hashlib.sha256(b"gene,score\nBST2,0.91\n").hexdigest()
    )

    v2 = cli.ok(lyra, "version", fid, write(lyra, "v2.csv", b"gene,score\n"))
    assert v2["version"] == 2 and v2["metadata"] == {"kind": "table"}  # content only
    v3 = cli.ok(lyra, "version", fid, "--metadata", '{"kind": "summary"}')
    assert v3["sha256"] == v2["sha256"]  # metadata only: the content is reused
    code, stale = cli(lyra, "version", fid, "--metadata", "{}", "--if-match", 1)
    assert code == 1 and stale["status"] == 412

    got = cli.ok(lyra, "get", fid, "--out", lyra / "latest.csv", "--version", 2)
    assert (lyra / "latest.csv").read_bytes() == b"gene,score\n" and got[
        "version"
    ] == "2"
    assert cli.ok(lyra, "stat", v1["citation"])["metadata"] == {"kind": "table"}
    assert [v["version"] for v in cli.ok(lyra, "versions", fid)["versions"]] == [
        1,
        2,
        3,
    ]

    deleted = cli.ok(lyra, "delete", fid, "--reason", "superseded")
    assert deleted["deleted"] is True
    assert cli.ok(lyra, "stat", fid, "--version", deleted["version"])["deleted"] is True
    code, bad = cli(lyra, "version", fid)
    assert code == 1 and "a version needs" in bad["error"]
    code, bad = cli(
        lyra,
        "put",
        lyra / "data.csv",
        "--collection",
        "files",
        "--name",
        "x",
        "--metadata",
        "[1]",
    )
    assert code == 1 and "JSON object" in bad["error"]


def test_collections_sharing_and_lookups(admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    vega = enroll(cli, admin_dir, "vega")
    assert (
        cli.ok(lyra, "collection", "create", "--name", "project")["name"] == "project"
    )
    code, out = cli(
        vega,
        "put",
        write(vega, "a.txt", b"a"),
        "--collection",
        "project",
        "--name",
        "a.txt",
    )
    assert code == 1 and out["status"] == 403  # not granted yet
    cli.ok(
        lyra,
        "collection",
        "grant",
        "--collection",
        "project",
        "--handle",
        "vega",
        "--perm",
        "write",
    )
    shared = cli.ok(
        vega,
        "put",
        vega / "a.txt",
        "--collection",
        "project",
        "--name",
        "a.txt",
        "--metadata",
        '{"tag": "x"}',
    )
    code, out = cli(
        vega,
        "collection",
        "grant",
        "--collection",
        "project",
        "--handle",
        "lyra",
        "--perm",
        "write",
    )
    assert code == 1 and out["status"] == 403  # only the owner grants
    assert (
        cli.ok(lyra, "collection", "set-public", "--collection", "project", "--public")[
            "public"
        ]
        is True
    )
    code, out = cli(
        lyra, "collection", "set-public", "--collection", "inbox", "--public"
    )
    assert code == 1 and out["status"] == 403  # inbox is never public

    found = cli.ok(lyra, "find", "name", "--collection", "project", "--name", "a.txt")
    assert found["file_id"] == shared["file_id"]
    by_hash = cli.ok(lyra, "find", "hash", "--sha256", shared["sha256"])
    assert [i["citation"] for i in by_hash["items"]] == [shared["citation"]]
    meta = cli.ok(
        lyra, "find", "meta", "--collection", "project", "--contains", '{"tag": "x"}'
    )
    assert [i["citation"] for i in meta["items"]] == [shared["citation"]]

    ok = cli.ok(
        lyra, "verify", "--cite", shared["citation"], "--sha256", shared["sha256"]
    )
    assert ok["ok"] is True
    late = cli.ok(
        lyra, "verify", "--cite", shared["citation"], "--before", shared["created"]
    )
    assert late["ok"] is False and "not strictly earlier" in late["reason"]


def test_an_application_key_reads_what_it_is_granted_with_no_context(
    admin_dir, cli, tmp_path
):
    lyra = enroll(cli, admin_dir, "lyra")
    cli.ok(lyra, "collection", "create", "--name", "project")
    put = cli.ok(
        lyra,
        "put",
        write(lyra, "r.txt", b"for a reviewer"),
        "--collection",
        "project",
        "--name",
        "r.txt",
    )
    issued = cli.ok(
        lyra, "gen-api-key", "reviewer", "--non-member", "--expires-days", 1
    )
    assert "key" not in issued and issued["expires"] is not None  # never printed
    assert (issued["role"], issued["handle"]) == ("non-member", None)
    key_file = Path(issued["key_file"])
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    content = json.loads(key_file.read_text())
    assert content["key"].startswith("sak_") and content["community"] == "demo"
    assert content["api"].endswith("/v1")
    listed = cli.ok(lyra, "list-api-keys")["keys"]
    assert [k["label"] for k in listed] == ["reviewer"] and "key" not in listed[0]

    outsider = tmp_path / "outsider"  # no context at all
    outsider.mkdir()

    def read(name):
        return cli(
            outsider,
            "get",
            put["citation"],
            "--out",
            outsider / name,
            "--api-key-file",
            key_file,
        )

    code, out = read("before.txt")
    assert code == 1 and out["status"] == 403  # issued, but granted nothing yet

    code, out = cli(
        lyra,
        "collection",
        "grant",
        "--collection",
        "project",
        "--api-key",
        issued["id"],
        "--perm",
        "write",
    )
    assert code == 1 and out["status"] == 400  # a non-member key is granted read only
    granted = cli.ok(
        lyra,
        "collection",
        "grant",
        "--collection",
        "project",
        "--api-key",
        issued["id"],
        "--perm",
        "read",
    )
    assert granted["api_key_id"] == issued["id"] and granted["granted"] is True
    code, read_out = read("r.txt")
    assert code == 0, read_out
    assert (outsider / "r.txt").read_bytes() == b"for a reviewer"
    assert read_out["sha256"] == put["sha256"]

    cli.ok(lyra, "revoke-api-key", issued["id"])
    code, out = read("again.txt")
    assert code == 1 and out["status"] == 401  # refused from the very next request


def test_a_public_collection_is_read_by_an_ungranted_key(admin_dir, cli, tmp_path):
    lyra = enroll(cli, admin_dir, "lyra")
    cli.ok(lyra, "collection", "create", "--name", "open")
    put = cli.ok(
        lyra,
        "put",
        write(lyra, "o.txt", b"for anyone"),
        "--collection",
        "open",
        "--name",
        "o.txt",
    )
    issued = cli.ok(lyra, "gen-api-key", "anyone", "--non-member")
    outsider = tmp_path / "outsider"
    outsider.mkdir()

    def read(name):
        return cli(
            outsider,
            "get",
            put["citation"],
            "--out",
            outsider / name,
            "--api-key-file",
            issued["key_file"],
        )

    assert read("private.txt")[1]["status"] == 403
    cli.ok(lyra, "collection", "set-public", "--collection", "open", "--public")
    listed = cli.ok(lyra, "collection", "list")["collections"]
    opened = next(c for c in listed if c["name"] == "open")
    assert (opened["owner"], opened["public"]) == ("lyra", True)
    assert opened["access"] == ["read", "write", "manage"]
    code, out = read("public.txt")
    assert code == 0, out
    assert (outsider / "public.txt").read_bytes() == b"for anyone"
    cli.ok(lyra, "collection", "set-public", "--collection", "open", "--private")
    assert read("private-again.txt")[1]["status"] == 403


def test_a_member_submission_is_promoted_by_the_admin(admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    goal = json.dumps({"artifact": {"name": "goal", "created": None}}).encode()
    submitted = cli.ok(
        lyra,
        "put",
        write(lyra, "goal.json", goal),
        "--collection",
        "inbox",
        "--name",
        "goal-1.json",
        "--content-type",
        "application/json",
    )
    code, out = cli(lyra, "promote", submitted["citation"], "--collection", "record")
    assert code == 1 and "admin command" in out["error"]

    promoted = cli.ok(
        admin_dir,
        "promote",
        submitted["citation"],
        "--collection",
        "record",
        "--name",
        "goal.json",
        "--stamp-json-pointer",
        "/artifact/created",
    )
    assert promoted["created_by"] == "lyra"  # credited to the submitter
    record = cli.ok(admin_dir, "changes", "--collection", "record")["items"]
    assert [i["name"] for i in record] == ["goal.json"]
    stamped = cli.ok(
        admin_dir, "get", promoted["citation"], "--out", admin_dir / "goal.json"
    )
    assert (
        json.loads((admin_dir / "goal.json").read_text())["artifact"]["created"]
        == promoted["created"]
    )
    assert stamped["citation"] == promoted["citation"]


def test_a_rotated_key_replaces_the_old_one(admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    before = cli.ok(lyra, "owner", "pubkey")["fingerprint"]
    rotated = cli.ok(lyra, "owner", "rotate")
    assert rotated["fingerprint"] != before
    assert cli.ok(lyra, "owner", "whoami")["kid"] == rotated["fingerprint"]


def test_after_rebind_key_the_old_key_is_refused_and_the_fresh_invite_registers(
    admin_dir, cli
):
    lyra = enroll(cli, admin_dir, "lyra")
    old = cli.ok(lyra, "owner", "pubkey")["fingerprint"]
    fresh = admin_dir / "lyra-fresh.invite"
    assert (
        cli.ok(admin_dir, "rebind-key", "--handle", "lyra", "--out", fresh)[
            "retired_keys"
        ]
        == 1
    )
    code, out = cli(lyra, "owner", "whoami")
    assert code == 1 and out["status"] == 401  # the old key is retired

    cli.ok(lyra, "context", "set", "--invite-file", fresh)
    registered = cli.ok(lyra, "owner", "register")
    assert (
        registered["registered"] is True and registered["fingerprint"] != old
    )  # a new key
    assert cli.ok(lyra, "owner", "whoami")["kid"] == registered["fingerprint"]


def test_after_suspect_after_a_members_writes_are_flagged(admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    early = cli.ok(
        lyra,
        "put",
        write(lyra, "early.txt", b"before"),
        "--collection",
        "files",
        "--name",
        "early.txt",
    )
    flagged = cli.ok(
        admin_dir, "suspect-after", "--handle", "lyra", "--at", early["created"]
    )
    assert flagged["handle"] == "lyra"
    late = cli.ok(
        lyra,
        "put",
        write(lyra, "late.txt", b"after"),
        "--collection",
        "files",
        "--name",
        "late.txt",
    )
    assert late["suspect"] is True
    assert cli.ok(lyra, "stat", early["citation"])["suspect"] is False
    assert cli.ok(lyra, "owner", "whoami")["suspect_after"].startswith(
        early["created"][:19]
    )


def test_changes_all_pages_through_the_whole_feed(admin_dir, cli):
    lyra = enroll(cli, admin_dir, "lyra")
    for i in range(3):
        cli.ok(
            lyra,
            "put",
            write(lyra, f"f{i}.txt", b"x%d" % i),
            "--collection",
            "files",
            "--name",
            f"f{i}.txt",
        )
    page = cli.ok(lyra, "changes", "--collection", "files", "--limit", 2)
    assert len(page["items"]) == 2 and page["more"] is True
    whole = cli.ok(lyra, "changes", "--collection", "files", "--limit", 2, "--all")
    assert [i["name"] for i in whole["items"]] == ["f0.txt", "f1.txt", "f2.txt"]
    assert whole["more"] is False and whole["next_since"] == whole["items"][-1]["seq"]
    later = cli.ok(
        lyra,
        "changes",
        "--collection",
        "files",
        "--since",
        whole["next_since"],
        "--all",
    )
    assert later["items"] == []


def test_a_member_grants_another_member_read_and_withdraws_it(admin_dir, cli, tmp_path):
    lyra = enroll(cli, admin_dir, "lyra")
    vega = enroll(cli, admin_dir, "vega")
    cli.ok(lyra, "collection", "create", "--name", "shared")
    put = cli.ok(
        lyra,
        "put",
        write(lyra, "s.txt", b"for vega"),
        "--collection",
        "shared",
        "--name",
        "s.txt",
    )

    def read(name):
        return cli(vega, "get", put["citation"], "--out", tmp_path / name)

    grant = ["collection", "grant", "--collection", "shared", "--handle", "vega"]
    assert read("before.txt")[1]["status"] == 403
    granted = cli.ok(lyra, *grant, "--perm", "read")
    assert (granted["handle"], granted["perm"], granted["granted"]) == (
        "vega",
        "read",
        True,
    )
    code, out = read("granted.txt")
    assert code == 0, out
    assert (tmp_path / "granted.txt").read_bytes() == b"for vega"
    withdrawn = cli.ok(lyra, *grant, "--perm", "read", "--revoke")
    assert withdrawn["granted"] is False
    assert read("withdrawn.txt")[1]["status"] == 403  # from the very next request


def test_the_admin_revokes_a_members_non_member_issued_key(admin_dir, cli, tmp_path):
    lyra = enroll(cli, admin_dir, "lyra")
    issued = cli.ok(lyra, "gen-api-key", "dashboard", "--non-member")
    seen = {k["id"]: k for k in cli.ok(admin_dir, "list-api-keys")["keys"]}
    assert seen[issued["id"]]["role"] == "non-member"
    revoked = cli.ok(admin_dir, "revoke-api-key", issued["id"])
    assert revoked["revoked"] is not None and revoked["revoked_by"] == ADMIN
    mine = {k["id"]: k for k in cli.ok(lyra, "list-api-keys")["keys"]}
    assert mine[issued["id"]]["revoked"] is not None
    code, out = cli(
        tmp_path,
        "get",
        "symposium-data:00000000-0000-0000-0000-000000000000@v1",
        "--out",
        tmp_path / "x",
        "--api-key-file",
        issued["key_file"],
    )
    assert code == 1 and out["status"] == 401  # revoked: refused from the next request


def test_a_purged_version_reports_410_with_its_metadata(admin_dir, cli, tmp_path):
    lyra = enroll(cli, admin_dir, "lyra")
    put = cli.ok(
        lyra,
        "put",
        write(lyra, "p.txt", b"to purge"),
        "--collection",
        "files",
        "--name",
        "p.txt",
    )
    cli.ok(admin_dir, "purge", "--cite", put["citation"])
    code, out = cli(lyra, "get", put["citation"], "--out", tmp_path / "gone.txt")
    assert code == 1 and out["status"] == 410
    assert out["error"] == "the version's content was purged"
    assert (out["citation"], out["file_id"], out["purged"]) == (
        put["citation"],
        put["file_id"],
        True,
    )
    assert "code" not in out and "detail" not in out
    assert not (tmp_path / "gone.txt").exists()
