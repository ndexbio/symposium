"""M5: Symposium parity: the change feed, find, metadata query, hash lookup, promote, verify,
and export/import with identity reconciliation."""

import hashlib
import json
import subprocess
from datetime import datetime

import httpx
import pytest
from conftest import (
    Owner,
    assert_consistent,
    community_with,
    init_admin,
    psql,
    set_roster,
)


@pytest.fixture
def demo(server):
    admin, owners = community_with(server)
    return server, admin, owners


def changes(server, headers, collection, since=0, limit=100, community="demo"):
    return httpx.get(
        f"{server.url}/v1/c/{community}/{collection}/changes",
        params={"since": since, "limit": limit},
        headers=headers,
    )


def every_change(server, headers, collection, limit=3, community="demo") -> list:
    items, since = [], 0
    while True:
        page = changes(server, headers, collection, since, limit, community)
        assert page.status_code == 200, page.text
        body = page.json()
        items += body["items"]
        since = body["next_since"]
        if not body["more"]:
            return items


def query(server, headers, collection, contains, since=0, limit=100):
    return httpx.post(
        f"{server.url}/v1/c/demo/{collection}/query",
        json={"contains": contains, "since": since, "limit": limit},
        headers=headers,
    )


def promote(admin, file_id, n, collection="record", **body):
    return httpx.post(
        f"{admin.server.url}/v1/files/{file_id}/v/{n}/promote",
        json={"collection": collection, **body},
        headers=admin.headers(),
    )


def verify(owner, cite, **params):
    return httpx.get(
        f"{owner.server.url}/v1/verify",
        params={"cite": cite, **params},
        headers=owner.headers(),
    )


def submission(name="goal", created=None) -> bytes:
    return json.dumps({"artifact": {"name": name, "created": created}}).encode()


def test_changes_pages_through_every_version_once_in_seq_order(demo):
    server, admin, owners = demo
    lyra = owners["lyra"]
    ids = [
        lyra.put("demo", "files", f"f{i}.csv", f"row {i}".encode()).json()["file_id"]
        for i in range(4)
    ]
    assert lyra.version(ids[0], metadata={"note": "relabelled"}).status_code == 201
    assert lyra.delete(ids[1]).status_code == 200

    items = every_change(server, lyra.headers(), "files", limit=3)
    assert [i["seq"] for i in items] == list(range(1, 7))
    assert [i["citation"] for i in items][-2:] == [
        f"symposium-data:{ids[0]}@v2",
        f"symposium-data:{ids[1]}@v2",
    ]
    assert items[4]["metadata"] == {"note": "relabelled"} and items[5]["deleted"]

    tail = changes(server, lyra.headers(), "files", since=6).json()
    assert tail == {"items": [], "next_since": 6, "more": False}
    assert changes(server, {}, "files").status_code == 401
    assert changes(server, lyra.headers(), "files", limit=1001).status_code == 422
    assert changes(server, lyra.headers(), "nowhere").status_code == 404


def test_a_member_lists_only_their_own_inbox_entries(demo):
    server, admin, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    mine = lyra.put("demo", "inbox", "lyra.json", submission()).json()["file_id"]
    vega.put("demo", "inbox", "vega.json", submission())
    reply = admin.put(
        "demo", "inbox", "reply.json", b"{}", metadata={"recipients": ["lyra"]}
    ).json()["file_id"]

    seen = every_change(server, lyra.headers(), "inbox", limit=2)
    assert {i["file_id"] for i in seen} == {mine, reply}
    assert len(every_change(server, admin.headers(), "inbox")) == 3


def test_find_and_query_by_metadata(demo):
    server, admin, owners = demo
    lyra = owners["lyra"]
    for i in range(3):
        lyra.put(
            "demo", "files", f"a{i}.json", b"{}", metadata={"kind": "Analysis", "i": i}
        )
    data = lyra.put("demo", "files", "d.json", b"[]", metadata={"kind": "Data"})
    gone = lyra.put("demo", "files", "gone.json", b"{}").json()["file_id"]
    lyra.delete(gone)

    found = query(server, lyra.headers(), "files", {"kind": "Analysis"}, limit=2)
    assert found.status_code == 200 and found.json()["more"]
    rest = query(
        server,
        lyra.headers(),
        "files",
        {"kind": "Analysis"},
        since=found.json()["next_since"],
        limit=2,
    ).json()
    names = [i["name"] for i in found.json()["items"] + rest["items"]]
    assert names == ["a0.json", "a1.json", "a2.json"] and not rest["more"]
    assert query(server, lyra.headers(), "files", ["kind"]).status_code == 422

    url = f"{server.url}/v1/c/demo/files/find"
    hit = httpx.get(url, params={"name": "d.json"}, headers=lyra.headers())
    assert hit.status_code == 200
    assert hit.json()["file_id"] == data.json()["file_id"]
    assert hit.headers["etag"] == '"v1"'
    deleted = httpx.get(url, params={"name": "gone.json"}, headers=lyra.headers())
    assert deleted.json()["file_deleted"]  # a deleted file still holds its name
    missing = httpx.get(url, params={"name": "nope"}, headers=lyra.headers())
    assert missing.status_code == 404


def test_hash_lookup_finds_every_readable_copy(demo):
    server, admin, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    content = b"the same bytes"
    sha = hashlib.sha256(content).hexdigest()
    lyra.put("demo", "files", "one.csv", content)
    vega.put("demo", "files", "two.csv", content)
    set_roster(server, admin, "other", ["bob"])
    bob = Owner(server, "bob")
    assert bob.register("other").status_code == 201
    bob.put("other", "files", "three.csv", content)

    url = f"{server.url}/v1/sha256/{sha}"
    seen = httpx.get(url, headers=lyra.headers()).json()["items"]
    assert sorted(i["name"] for i in seen) == ["one.csv", "two.csv"]
    assert len(httpx.get(url, headers=admin.headers()).json()["items"]) == 3
    bad = httpx.get(f"{server.url}/v1/sha256/{sha.upper()}", headers=lyra.headers())
    assert bad.status_code == 400


def test_promote_stamps_the_server_clock_into_the_record(demo):
    server, admin, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    source = lyra.put(
        "demo",
        "inbox",
        "goal.json",
        submission(),
        metadata={"symposium_submission": True, "kind": "ResearchGoal"},
        content_type="application/json",
    ).json()

    promoted = promote(
        admin,
        source["file_id"],
        1,
        name="ResearchGoal_goal.json",
        metadata={"accepted": True},
        stamp_json_pointer="/artifact/created",
    )
    assert promoted.status_code == 201, promoted.text
    record = promoted.json()
    assert record["collection"] == "record" and record["version"] == 1
    assert record["name"] == "ResearchGoal_goal.json"
    assert record["metadata"] == {
        "symposium_submission": True,
        "kind": "ResearchGoal",
        "accepted": True,
    }
    assert record["content_type"] == "application/json"

    body = vega.get(record["file_id"])  # members read the record with their own token
    assert body.status_code == 200
    assert json.loads(body.content)["artifact"]["created"] == record["created"]
    assert hashlib.sha256(body.content).hexdigest() == record["sha256"]
    assert (
        body.content
        == json.dumps(
            {"artifact": {"name": "goal", "created": record["created"]}}
        ).encode()
    )

    plain = promote(admin, source["file_id"], 1, name="copy.json")
    assert plain.status_code == 201
    assert plain.json()["sha256"] == source["sha256"]  # no stamp: the payload is reused
    assert_consistent(server)


def test_a_failing_promote_leaves_nothing_behind(make_server):
    content = submission()
    # the quota admits the submission but not its stamped copy, so the promote fails
    # inside its commit transaction, after the stamped bytes were written
    # (stamping replaces null with a 34-character instant, adding 30 bytes)
    server = make_server(SYMPOSIUM_DATA_QUOTA_BYTES=str(len(content) + 20))
    admin, owners = community_with(server)
    lyra = owners["lyra"]
    fid = lyra.put("demo", "inbox", "goal.json", content).json()["file_id"]
    text = lyra.put("demo", "inbox", "note.txt", b"plain").json()["file_id"]
    gone = lyra.put("demo", "inbox", "gone.json", b"{}").json()["file_id"]
    lyra.delete(gone)
    pointer = {"stamp_json_pointer": "/artifact/created"}

    assert promote(lyra, fid, 1, **pointer).status_code == 403
    assert promote(admin, fid, 1, **pointer).status_code == 413
    assert promote(admin, fid, 1, stamp_json_pointer="/missing/x").status_code == 422
    assert promote(admin, text, 1, **pointer).status_code == 422
    assert promote(admin, gone, 2).status_code == 409
    assert promote(admin, fid, 1, collection="nowhere").status_code == 404
    assert promote(admin, fid, 1).status_code == 201
    assert promote(admin, fid, 1).status_code == 409  # the name is taken
    server.admin("purge", "--cite", f"symposium-data:{text}@v1")
    assert promote(admin, text, 1).status_code == 410

    record = every_change(server, admin.headers(), "record")
    assert [i["name"] for i in record] == ["goal.json"]
    assert_consistent(server)


def test_verify_checks_existence_hash_and_strict_ordering(demo):
    server, admin, owners = demo
    lyra = owners["lyra"]
    data = lyra.put("demo", "files", "table.csv", b"a,b\n1,2\n").json()
    goal = lyra.put("demo", "inbox", "goal.json", submission()).json()
    record = promote(
        admin, goal["file_id"], 1, stamp_json_pointer="/artifact/created"
    ).json()
    cite = data["citation"]

    ok = verify(admin, cite, before=record["created"], sha256=data["sha256"]).json()
    assert ok["ok"] and ok["exists"] and ok["created"] == data["created"]
    wrong = verify(admin, cite, sha256="0" * 64).json()
    assert not wrong["ok"] and wrong["reason"] == "sha256 does not match"
    late = verify(admin, cite, before=data["created"]).json()
    assert not late["ok"] and "not strictly earlier" in late["reason"]

    set_roster(server, admin, "other", ["bob"])
    bob = Owner(server, "bob")
    bob.register("other")
    hidden = verify(bob, cite).json()
    unknown = verify(bob, "symposium-data:00000000-0000-0000-0000-000000000000@v1")
    assert hidden == unknown.json() and not hidden["exists"]
    assert not verify(admin, "ndex:abc").json()["exists"]
    assert verify(admin, cite, before="yesterday").status_code == 400
    anonymous = httpx.get(f"{server.url}/v1/verify", params={"cite": cite})
    assert anonymous.status_code == 401

    server.admin("purge", "--cite", cite)
    purged = verify(admin, cite).json()
    assert purged["exists"] and not purged["ok"]
    assert purged["reason"] == "content purged"


# ── export and import ───────────────────────────────────────────────────────────────────────
def export(server, community, path):
    with open(path, "wb") as out:
        result = subprocess.run(
            ["docker", "exec", server.name, "data-admin", "export"]
            + ["--community", community],
            stdout=out,
            stderr=subprocess.PIPE,
            text=False,
            timeout=600,
        )
    assert result.returncode == 0, result.stderr.decode()
    return path


def import_(server, path):
    with open(path, "rb") as source:
        result = subprocess.run(
            ["docker", "exec", "-i", server.name, "data-admin", "import"],
            stdin=source,
            capture_output=True,
            timeout=600,
        )
    lines = result.stdout.decode().splitlines()
    return result.returncode, [json.loads(line) for line in lines if line]


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def comparable(items):
    keep = ("file_id", "version", "sha256", "created", "seq", "metadata", "deleted")
    return [{k: i[k] for k in (*keep, "purged", "created_by", "key_id")} for i in items]


def test_export_import_round_trip_preserves_the_community(make_server, tmp_path):
    source = make_server()
    admin, owners = community_with(source)
    lyra, vega = owners["lyra"], owners["vega"]
    fid = lyra.put("demo", "files", "data.csv", b"1,2,3").json()["file_id"]
    lyra.version(fid, b"1,2,3,4")
    lyra.delete(fid, reason="superseded")
    purged = lyra.put("demo", "files", "secret.csv", b"remove me").json()["citation"]
    source.admin("purge", "--cite", purged)
    httpx.post(
        f"{source.url}/v1/c/demo/collections",
        json={"name": "project"},
        headers=lyra.headers(),
    )
    httpx.put(
        f"{source.url}/v1/c/demo/project/grants",
        json={"handle": "vega", "perm": "read"},
        headers=lyra.headers(),
    )
    shared = lyra.put("demo", "project", "shared.csv", b"for vega").json()["file_id"]
    key = httpx.post(
        f"{source.url}/v1/c/demo/project/keys",
        json={"label": "reviewer"},
        headers=lyra.headers(),
    ).json()["key"]
    goal = lyra.put("demo", "inbox", "goal.json", submission()).json()["file_id"]
    promote(admin, goal, 1, stamp_json_pointer="/artifact/created")
    before = {
        c: comparable(every_change(source, admin.headers(), c))
        for c in ("files", "inbox", "record", "project")
    }
    archive = export(source, "demo", tmp_path / "demo.tar")

    target = make_server()
    target_admin = init_admin(target)  # the same handle, this server's own key
    truncated = tmp_path / "truncated.tar"
    truncated.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
    code, _ = import_(target, truncated)
    assert code == 1
    assert psql(target, "SELECT count(*) FROM collections") == "0"
    assert_consistent(target)

    code, report = import_(target, archive)
    assert code == 0, report
    results = {r["handle"]: r["result"] for r in report if "handle" in r}
    assert results == {
        "demo-admin": "admin: this server's keys kept",
        "lyra": "created",
        "vega": "created",
        "rigel": "created",
    }
    after = {
        c: comparable(every_change(target, target_admin.headers(), c)) for c in before
    }
    assert after == before

    # members sign in with the keys they already hold; the source admin's key does not
    lyra2 = Owner(target, "lyra", key=lyra.key)
    vega2 = Owner(target, "vega", key=vega.key)
    assert lyra2.get(fid, 2).content == b"1,2,3,4"
    assert vega2.get(shared).content == b"for vega"  # the grant survived
    assert (
        Owner(target, "demo-admin", key=admin.key).token_response().status_code == 401
    )
    read = httpx.get(
        f"{target.url}/v1/files/{shared}/v/1",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert read.content == b"for vega"  # the read key survived
    file_id = purged.split(":")[1].split("@")[0]
    assert lyra2.get(file_id, 1).status_code == 410

    # the collection clock continues where the source left off
    last = before["files"][-1]
    new = lyra2.put("demo", "files", "next.csv", b"after the move").json()
    assert new["seq"] == last["seq"] + 1
    assert instant(new["created"]) > instant(last["created"])

    code, report = import_(target, archive)
    assert code == 2 and "already exists" in report[0]["error"]
    assert_consistent(target)


def test_import_reconciles_handles_and_refuses_what_cannot_be(make_server, tmp_path):
    source = make_server()
    admin, owners = community_with(source, members=("lyra", "vega"))
    lyra = owners["lyra"]
    fid = lyra.put("demo", "files", "data.csv", b"lyra's data").json()["file_id"]
    archive = export(source, "demo", tmp_path / "demo.tar")
    old_kid = psql(source, "SELECT key_id FROM versions LIMIT 1")

    # lyra already holds a different key on the target, through another community
    target = make_server()
    target_admin = init_admin(target)
    set_roster(target, target_admin, "other", ["lyra"])
    lyra_here = Owner(target, "lyra")
    assert lyra_here.register("other").status_code == 201
    code, report = import_(target, archive)
    assert code == 0, report
    results = {r["handle"]: r["result"] for r in report if "handle" in r}
    assert results["lyra"] == "keys merged" and results["vega"] == "created"
    assert lyra_here.token_response().status_code == 200  # this server's key wins
    assert Owner(target, "lyra", key=lyra.key).token_response().status_code == 401
    assert lyra_here.get(fid).content == b"lyra's data"
    retired = psql(
        target,
        f"SELECT active FROM owner_keys WHERE kid = '{old_kid}' AND handle = 'lyra'",
    )
    assert retired == "f"  # every imported key_id still resolves

    # one key cannot belong to two handles
    clash = make_server()
    clash_admin = init_admin(clash)
    set_roster(clash, clash_admin, "other", ["mallory"])
    assert Owner(clash, "mallory", key=lyra.key).register("other").status_code == 201
    code, report = import_(clash, archive)
    assert code == 2 and "belongs to 'mallory'" in report[0]["error"]
    assert (
        psql(clash, "SELECT count(*) FROM collections WHERE community = 'demo'") == "0"
    )
    assert_consistent(clash)

    # the admin handle must match
    elsewhere = make_server()
    init_admin(elsewhere, handle="other-admin")
    code, report = import_(elsewhere, archive)
    assert code == 2 and "initialize with the same admin handle" in report[0]["error"]
