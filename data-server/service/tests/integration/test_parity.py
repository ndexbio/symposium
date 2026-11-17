"""Symposium parity: the change feed, find, metadata query, hash lookup, promote, verify,
and export/import."""

import hashlib
import io
import json
import tarfile
from datetime import datetime

import pytest
from conftest import (
    Owner,
    assert_consistent,
    community_with,
    create_community,
    enroll,
    psql,
    purge,
)
from harness import HTTP

SUBMITTED = {"symposium_submission": True}


@pytest.fixture
def demo(server):
    root, owners = community_with(server)
    return server, root, owners


def changes(server, headers, collection, since=0, limit=100, community="demo"):
    return HTTP.get(
        f"{server.url}/v1/communities/{community}/collections/{collection}/changes",
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
    return HTTP.post(
        f"{server.url}/v1/communities/demo/collections/{collection}/files/search",
        json={"contains": contains, "since": since, "limit": limit},
        headers=headers,
    )


def promote(caller, file_id, n, collection="record", **body):
    return HTTP.post(
        caller.url(f"/collections/{collection}/files"),
        json={"from": f"symposium-data:{file_id}@v{n}", **body},
        headers=caller.headers(),
    )


def verification_url(owner, cite: str) -> str:
    """Where a citation `symposium-data:<file id>@v<n>` is verified: under the version it
    names."""
    file_id, _, n = cite.removeprefix("symposium-data:").partition("@v")
    return owner.url(f"/files/{file_id}/versions/{n}/verification")


def verify(owner, cite, **params):
    return HTTP.get(
        verification_url(owner, cite), params=params, headers=owner.headers()
    )


def submission(name="goal", created=None) -> bytes:
    return json.dumps({"artifact": {"name": name, "created": created}}).encode()


def test_changes_pages_through_every_version_once_in_seq_order(demo):
    server, root, owners = demo
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
    server, root, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    mine = lyra.put("demo", "inbox", "lyra.json", submission(), SUBMITTED).json()[
        "file_id"
    ]
    vega.put("demo", "inbox", "vega.json", submission(), SUBMITTED)
    reply = root.put(
        "demo",
        "inbox",
        "reply.json",
        b"{}",
        metadata={"symposium_reply": True, "recipients": ["lyra"]},
    ).json()["file_id"]

    seen = every_change(server, lyra.headers(), "inbox", limit=2)
    assert {i["file_id"] for i in seen} == {mine, reply}
    assert len(every_change(server, root.headers(), "inbox")) == 3


def test_find_and_query_by_metadata(demo):
    server, root, owners = demo
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

    url = f"{server.url}/v1/communities/demo/collections/files/files"
    hit = HTTP.get(url, params={"name": "d.json"}, headers=lyra.headers())
    assert hit.status_code == 200
    [found] = hit.json()["items"]
    assert found["file_id"] == data.json()["file_id"] and found["version"] == 1
    deleted = HTTP.get(url, params={"name": "gone.json"}, headers=lyra.headers())
    assert deleted.json()["items"][0]["file_deleted"]  # a deleted file holds its name
    missing = HTTP.get(url, params={"name": "nope"}, headers=lyra.headers())
    assert missing.status_code == 200 and missing.json()["items"] == []
    # without a name: every file, by name, paged
    first = HTTP.get(url, params={"limit": 1}, headers=lyra.headers()).json()
    assert len(first["items"]) == 1 and first["next"]
    names, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = HTTP.get(url, params=params, headers=lyra.headers()).json()
        names += [i["name"] for i in page["items"]]
        cursor = page["next"]
        if not cursor:
            break
    assert names == sorted(names) and "d.json" in names


def test_hash_lookup_finds_every_readable_copy(demo):
    server, root, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    content = b"the same bytes"
    sha = hashlib.sha256(content).hexdigest()
    lyra.put("demo", "files", "one.csv", content)
    vega.put("demo", "files", "two.csv", content)
    create_community(server, root, "other")
    bob = Owner(server, "bob", community="other")
    assert enroll(root.at("other"), bob, "other").status_code == 201
    bob.put("other", "files", "three.csv", content)

    url = f"{server.url}/v1/communities/demo/versions?sha256={sha}"
    seen = HTTP.get(url, headers=lyra.headers()).json()["items"]
    assert sorted(i["name"] for i in seen) == ["one.csv", "two.csv"]
    # hash lookup stays inside its community, even for root
    assert len(HTTP.get(url, headers=root.headers()).json()["items"]) == 2
    elsewhere = HTTP.get(
        f"{server.url}/v1/communities/other/versions?sha256={sha}",
        headers=bob.headers(),
    )
    assert [i["name"] for i in elsewhere.json()["items"]] == ["three.csv"]
    # content is deduplicated within a community, never across: one payload each
    stored = psql(server, f"SELECT count(*) FROM payloads WHERE sha256 = '{sha}'")
    assert stored == "2"
    bad = HTTP.get(
        f"{server.url}/v1/communities/demo/versions?sha256={sha.upper()}",
        headers=lyra.headers(),
    )
    assert bad.status_code == 400


def test_promote_stamps_the_server_clock_into_the_record(demo):
    server, root, owners = demo
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
        root,
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
    # credited to its submitter
    assert record["created_by"] == "lyra" and record["key_id"] is None
    assert promote(lyra, source["file_id"], 1, name="mine.json").status_code == 403

    body = vega.get(record["file_id"])  # members read the record with their own key
    assert body.status_code == 200
    assert json.loads(body.content)["artifact"]["created"] == record["created"]
    assert hashlib.sha256(body.content).hexdigest() == record["sha256"]
    assert (
        body.content
        == json.dumps(
            {"artifact": {"name": "goal", "created": record["created"]}}
        ).encode()
    )

    plain = promote(root, source["file_id"], 1, name="copy.json")
    assert plain.status_code == 201
    assert plain.json()["sha256"] == source["sha256"]  # no stamp: the payload is reused
    assert_consistent(server)


def test_a_failing_promote_leaves_nothing_behind(demo):
    content = submission()
    server, root, owners = demo
    lyra = owners["lyra"]
    fid = lyra.put("demo", "inbox", "goal.json", content, SUBMITTED).json()["file_id"]
    text = lyra.put("demo", "inbox", "note.txt", b"plain", SUBMITTED).json()["file_id"]
    # inbox items never change, so the tombstone to refuse is a file's
    gone = lyra.put("demo", "files", "gone.json", b"{}").json()["file_id"]
    assert lyra.delete(gone).status_code == 200
    pointer = {"stamp_json_pointer": "/artifact/created"}

    assert promote(lyra, fid, 1, **pointer).status_code == 403
    # an upload still in progress holds the target name: the stamped promote fails inside
    # its commit transaction, after its pending payload was recorded, and leaves nothing
    psql(
        server,
        "INSERT INTO files (id, community, collection, name, state, reserved_by, reserved_at) "
        "VALUES (gen_random_uuid(), 'demo', 'record', 'goal.json', 'reserved', 'vega', "
        "now())",
    )
    assert promote(root, fid, 1, **pointer).status_code == 409
    assert psql(server, "SELECT count(*) FROM payloads WHERE state = 'pending'") == "0"
    psql(server, "DELETE FROM files WHERE state = 'reserved'")
    assert promote(root, fid, 1, stamp_json_pointer="/missing/x").status_code == 422
    assert promote(root, text, 1, **pointer).status_code == 422
    assert promote(root, gone, 2).status_code == 409
    assert promote(root, fid, 1, collection="nowhere").status_code == 404
    assert promote(root, fid, 1).status_code == 201
    assert promote(root, fid, 1).status_code == 409  # the name is taken
    assert purge(root, text, 1).status_code == 200
    assert promote(root, text, 1).status_code == 410

    record = every_change(server, root.headers(), "record")
    assert [i["name"] for i in record] == ["goal.json"]
    assert_consistent(server)


def test_verify_checks_existence_hash_and_strict_ordering(demo):
    server, root, owners = demo
    lyra = owners["lyra"]
    data = lyra.put("demo", "files", "table.csv", b"a,b\n1,2\n").json()
    goal = lyra.put("demo", "inbox", "goal.json", submission(), SUBMITTED).json()
    record = promote(
        root, goal["file_id"], 1, stamp_json_pointer="/artifact/created"
    ).json()
    cite = data["citation"]

    ok = verify(root, cite, before=record["created"], sha256=data["sha256"]).json()
    assert ok["ok"] and ok["exists"] and ok["created"] == data["created"]
    wrong = verify(root, cite, sha256="0" * 64).json()
    assert not wrong["ok"] and wrong["reason"] == "sha256 does not match"
    late = verify(root, cite, before=data["created"]).json()
    assert not late["ok"] and "not strictly earlier" in late["reason"]

    create_community(server, root, "other")
    bob = Owner(server, "bob", community="other")
    enroll(root.at("other"), bob, "other")
    hidden = verify(bob, cite).json()
    unknown = verify(bob, "symposium-data:00000000-0000-0000-0000-000000000000@v1")
    assert hidden == unknown.json() and not hidden["exists"]
    assert verify(root, cite, before="yesterday").status_code == 400
    # a caller with no key verifies only what it may read: here, nothing
    anonymous = HTTP.get(verification_url(root, cite))
    assert anonymous.status_code == 200 and anonymous.json() == unknown.json()

    assert purge(root, data["file_id"], 1).status_code == 200
    purged = verify(root, cite).json()
    assert purged["exists"] and not purged["ok"]
    assert purged["reason"] == "content purged"


# ── export and import ───────────────────────────────────────────────────────────────────────
def export(caller, community, path):
    """Stream the community's export through the route into `path`."""
    url = f"{caller.server.url}/v1/communities/{community}/archive"
    with HTTP.stream("GET", url, headers=caller.headers()) as r:
        assert r.status_code == 200, r.read()
        with open(path, "wb") as out:
            for chunk in r.iter_bytes():
                out.write(chunk)
    return path


def import_(caller, path):
    """Upload an export through the route. -> the response."""
    with open(path, "rb") as source:
        return HTTP.post(
            f"{caller.server.url}/v1/communities",
            content=source.read(),
            headers={**caller.headers(), "Content-Type": "application/x-tar"},
        )


def rewritten(path, out, *replacements):
    """A copy of an export with text replaced in its rows (not its payloads), as if it came
    from another server."""
    with tarfile.open(path) as src, tarfile.open(out, "w") as dst:
        for member in src.getmembers():
            data = src.extractfile(member).read()
            if not member.name.startswith("payloads/"):
                text = data.decode()
                for old, new in replacements:
                    text = text.replace(old, new)
                data = text.encode()
                member.size = len(data)
            dst.addfile(member, io.BytesIO(data))
    return out


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def comparable(items):
    keep = ("file_id", "version", "sha256", "created", "seq", "metadata", "deleted")
    return [{k: i[k] for k in (*keep, "purged", "created_by", "key_id")} for i in items]


def test_export_import_round_trip_preserves_the_community(server, tmp_path):
    # export, empty the server, import: the one session server plays source and target
    source = target = server
    root, owners = community_with(source)
    lyra, vega = owners["lyra"], owners["vega"]
    fid = lyra.put("demo", "files", "data.csv", b"1,2,3").json()["file_id"]
    lyra.version(fid, b"1,2,3,4")
    lyra.delete(fid, reason="superseded")
    secret = lyra.put("demo", "files", "secret.csv", b"remove me").json()
    purged = secret["citation"]
    assert purge(root, secret["file_id"], 1).status_code == 200
    HTTP.post(
        f"{source.url}/v1/communities/demo/collections",
        json={"name": "project"},
        headers=lyra.headers(),
    )
    # vega is narrowed to `files`, then given read on the project lyra owns
    assert root.unassign("community-member", None, "vega", "demo").status_code == 200
    assert root.assign("community-member", ["files"], "vega", "demo").status_code in (
        200,
        201,
    )
    rigel = owners["rigel"]
    shared_to = lyra.assign("community-observer", ["project"], "vega", "demo")
    assert shared_to.status_code == 200, shared_to.text
    shared = lyra.put("demo", "project", "shared.csv", b"for vega").json()["file_id"]
    app = lyra.issue(
        "dashboard",
        roles=[{"role": "community-observer", "collections": ["project"]}],
        non_member=True,
    )
    removed = HTTP.delete(root.user_url("rigel", "demo"), headers=root.headers())
    assert removed.status_code == 200, removed.text
    goal = lyra.put("demo", "inbox", "goal.json", submission(), SUBMITTED).json()[
        "file_id"
    ]
    promote(root, goal, 1, stamp_json_pointer="/artifact/created")
    before = {
        c: comparable(every_change(source, root.headers(), c))
        for c in ("files", "inbox", "record", "project")
    }
    archive = export(root, "demo", tmp_path / "demo.tar")

    target.reset()
    truncated = tmp_path / "truncated.tar"
    truncated.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
    assert import_(root, truncated).status_code == 400
    assert psql(target, "SELECT count(*) FROM collections") == "0"
    assert_consistent(target)

    imported = import_(root, archive)
    assert imported.status_code == 201, imported.text
    results = {r["handle"]: r["result"] for r in imported.json()["handles"]}
    assert results == {
        "lyra": "created",
        "vega": "created",
        "rigel": "created",
    }
    after = {c: comparable(every_change(target, root.headers(), c)) for c in before}
    assert after == before

    # members sign in with the keys they already hold, with their roles
    lyra2 = Owner(target, "lyra", key=lyra.key)
    vega2 = Owner(target, "vega", key=vega.key)
    assert lyra2.get(fid, 2).content == b"1,2,3,4"
    assert vega2.get(shared).content == b"for vega"  # the share survived
    # the removed member came along as a tombstone: listed, and unable to sign in
    roster = HTTP.get(
        f"{target.url}/v1/communities/demo/users", headers=lyra2.headers()
    ).json()
    assert {r["handle"]: bool(r["removed"]) for r in roster["users"]}["rigel"] is True
    assert Owner(target, "rigel", key=rigel.key).sign_in().status_code == 401
    # API keys stay on the server that issued them, and so do their roles
    read = HTTP.get(
        f"{target.url}/v1/communities/demo/files/{shared}/versions/1",
        headers={"Authorization": f"Bearer {app['key']}"},
    )
    assert read.status_code == 401
    assert (
        psql(
            target, "SELECT count(*) FROM role_assignments WHERE api_key_id IS NOT NULL"
        )
        == "0"
    )
    file_id = purged.split(":")[1].split("@")[0]
    assert lyra2.get(file_id, 1).status_code == 410

    # the collection clock continues where the source left off
    last = before["files"][-1]
    new = lyra2.put("demo", "files", "next.csv", b"after the move").json()
    assert new["seq"] == last["seq"] + 1
    assert instant(new["created"]) > instant(last["created"])

    again = import_(root, archive)
    assert again.status_code == 409 and "already exists" in again.json()["detail"]
    assert import_(lyra2, archive).status_code == 403  # takes `communities`
    assert_consistent(target)


def test_imported_identities_are_per_community(server, tmp_path):
    source = target = server
    root, owners = community_with(source, members=("lyra", "vega"))
    lyra = owners["lyra"]
    fid = lyra.put("demo", "files", "data.csv", b"lyra's data").json()["file_id"]
    archive = export(root, "demo", tmp_path / "demo.tar")

    # emptied, the server then has a lyra, with another key, in another community
    target.reset()
    create_community(target, root, "other")
    lyra_other = Owner(target, "lyra", community="other")
    assert enroll(root.at("other"), lyra_other, "other").status_code == 201
    imported = import_(root, archive)
    assert imported.status_code == 201, imported.text
    results = {r["handle"]: r["result"] for r in imported.json()["handles"]}
    assert results == {
        "lyra": "created",
        "vega": "created",
    }
    # two independent identities: each signs in with its own key, in its own community
    lyra_demo = Owner(target, "lyra", key=lyra.key)
    assert lyra_demo.get(fid).content == b"lyra's data"
    assert lyra_other.sign_in().status_code == 200
    assert (
        Owner(target, "lyra", key=lyra.key, community="other").sign_in().status_code
        == 401
    )
    assert Owner(target, "lyra", key=lyra_other.key).sign_in().status_code == 401


def test_an_export_from_another_server_is_owned_by_this_root(server, tmp_path):
    root, owners = community_with(server, members=("lyra",))
    goal = (
        owners["lyra"].put("demo", "inbox", "goal.json", submission(), SUBMITTED).json()
    )
    promote(root, goal["file_id"], 1, stamp_json_pointer="/artifact/created")
    archive = export(root, "demo", tmp_path / "demo.tar")
    server.reset()

    # the same community, exported from a server whose root has another handle
    elsewhere = rewritten(
        archive, tmp_path / "elsewhere.tar", ('"demo-admin"', '"old-admin"')
    )
    imported = import_(root, elsewhere)
    assert imported.status_code == 201, imported.text
    owners_now = psql(
        server,
        "SELECT DISTINCT u.handle FROM collections c JOIN users u ON u.id = c.owner",
    )
    assert owners_now == "demo-admin"  # what the source's root owned is this root's

    # a member whose handle is a server-level user's here cannot be imported
    server.reset()
    collision = rewritten(
        archive,
        tmp_path / "collision.tar",
        ('"demo-admin"', '"old-admin"'),
        ('"lyra"', '"demo-admin"'),
    )
    refused = import_(root, collision)
    assert refused.status_code == 409 and "handle collision" in refused.json()["detail"]
    assert psql(server, "SELECT count(*) FROM communities") == "0"
    assert_consistent(server)
