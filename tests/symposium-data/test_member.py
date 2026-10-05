"""The CLI's member side against a real data server, with every setup step done through
the CLI's own admin commands: registration (R-D1, R-D5), files and versions (R-A, R-B),
collections and read keys (R-E), lookups, verify and promote (R-G), and what rebind-key and
suspect-after do to a registered member."""

import hashlib
import json
import stat
from pathlib import Path

from suite import enroll


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
    assert me["handle"] == "lyra" and me["community"] == "demo" and me["admin"] is False
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
        lyra, "collection", "grant-write", "--collection", "project", "--handle", "vega"
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
        vega, "collection", "grant-write", "--collection", "project", "--handle", "lyra"
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


def test_read_keys_are_files_and_read_with_no_context(admin_dir, cli, tmp_path):
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
    key_file = lyra / "reviewer.key"
    minted = cli.ok(
        lyra,
        "keys",
        "mint",
        "--collection",
        "project",
        "--label",
        "reviewer",
        "--out",
        key_file,
        "--hours",
        24,
    )
    assert "key" not in minted and minted["expires"] is not None  # never printed
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    content = json.loads(key_file.read_text())
    assert content["key"].startswith("sdr_") and content["community"] == "demo"
    listed = cli.ok(lyra, "keys", "list", "--collection", "project")["keys"]
    assert [k["label"] for k in listed] == ["reviewer"] and "key" not in listed[0]

    outsider = tmp_path / "outsider"  # no context at all
    outsider.mkdir()
    read = cli.ok(
        outsider,
        "get",
        put["citation"],
        "--out",
        outsider / "r.txt",
        "--read-key-file",
        key_file,
    )
    assert (outsider / "r.txt").read_bytes() == b"for a reviewer" and read[
        "sha256"
    ] == put["sha256"]

    cli.ok(lyra, "keys", "revoke", minted["id"])
    code, out = cli(
        outsider,
        "get",
        put["citation"],
        "--out",
        outsider / "again.txt",
        "--read-key-file",
        key_file,
    )
    assert code == 1 and out["status"] == 401  # refused from the very next request


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
