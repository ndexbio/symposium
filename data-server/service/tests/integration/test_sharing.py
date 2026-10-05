"""Sharing: member-owned collections, grants, public collections, read keys for
non-members, inbox privacy, and per-community isolation."""

import httpx
import pytest
from conftest import Owner, community_with, enroll, psql, set_roster


@pytest.fixture
def demo(server):
    admin, owners = community_with(server)
    return server, admin, owners


def with_key(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def create_collection(owner, name, community="demo"):
    return httpx.post(
        f"{owner.server.url}/v1/{community}/collections",
        json={"name": name},
        headers=owner.headers(),
    )


def grant(owner, collection, handle, perm, granted=True):
    return httpx.put(
        f"{owner.server.url}/v1/demo/collections/{collection}/grants",
        json={"handle": handle, "perm": perm, "granted": granted},
        headers=owner.headers(),
    )


def mint(owner, collection, label="reviewer", file_id=None, community="demo"):
    body = {"label": label}
    if file_id:
        body["file_id"] = file_id
    return httpx.post(
        f"{owner.server.url}/v1/{community}/collections/{collection}/keys",
        json=body,
        headers=owner.headers(),
    )


def read(server, file_id, headers=None, ref=1, community="demo"):
    return httpx.get(
        f"{server.url}/v1/{community}/files/{file_id}/v/{ref}", headers=headers or {}
    )


def test_a_member_creates_and_owns_a_collection(demo):
    server, _, owners = demo
    created = create_collection(owners["lyra"], "lyra-project")
    assert created.status_code == 201, created.text
    assert created.json()["owner"] == "lyra"
    assert create_collection(owners["vega"], "lyra-project").status_code == 409
    assert create_collection(owners["vega"], "bad/name").status_code == 422

    fid = owners["lyra"].put("demo", "lyra-project", "a.csv", b"x").json()["file_id"]
    assert owners["lyra"].get(fid).status_code == 200
    assert owners["vega"].get(fid).status_code == 403  # not shared yet
    assert owners["vega"].put("demo", "lyra-project", "b.csv", b"y").status_code == 403


def test_only_the_owner_grants_and_grants_reach_roster_members_only(demo):
    server, _, owners = demo
    lyra, vega, rigel = owners["lyra"], owners["vega"], owners["rigel"]
    create_collection(lyra, "shared")
    assert grant(vega, "shared", "rigel", "write").status_code == 403  # not the owner
    assert (
        grant(lyra, "shared", "mallory", "write").status_code == 403
    )  # not on the roster
    assert grant(lyra, "shared", "vega", "write").status_code == 200
    assert grant(lyra, "shared", "vega", "read").status_code == 200

    fid = vega.put("demo", "shared", "vega.csv", b"from vega").json()["file_id"]
    assert vega.get(fid).content == b"from vega"
    assert rigel.put("demo", "shared", "rigel.csv", b"no").status_code == 403
    assert rigel.get(fid).status_code == 403
    # the owner may read anything in their collection, but still not change vega's file
    assert lyra.get(fid).status_code == 200
    assert lyra.version(fid, data=b"overwrite").status_code == 403

    assert grant(lyra, "shared", "vega", "write", granted=False).status_code == 200
    assert vega.put("demo", "shared", "again.csv", b"no").status_code == 403


def test_a_collection_read_key_reads_only_within_its_scope(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    create_collection(lyra, "release")
    inside = lyra.put("demo", "release", "result.csv", b"shared result").json()[
        "file_id"
    ]
    outside = lyra.put("demo", "files", "private.csv", b"not shared").json()["file_id"]

    minted = mint(lyra, "release")
    assert minted.status_code == 201, minted.text
    key = minted.json()["key"]
    assert key.startswith("sdr_")

    assert read(server, inside, with_key(key)).content == b"shared result"
    assert read(server, outside, with_key(key)).status_code == 403
    assert read(server, inside).status_code == 401  # no credential at all
    stat = httpx.get(
        f"{server.url}/v1/demo/files/{inside}/v/1/stat", headers=with_key(key)
    )
    assert stat.status_code == 200

    # a read key never writes, and never acts as an identity
    write = httpx.put(
        f"{server.url}/v1/demo/collections/release/files/x.csv",
        content=b"x",
        headers=with_key(key),
    )
    assert write.status_code == 403
    assert (
        httpx.get(f"{server.url}/v1/demo/whoami", headers=with_key(key)).status_code
        == 403
    )

    listed = httpx.get(
        f"{server.url}/v1/demo/collections/release/keys", headers=lyra.headers()
    ).json()
    assert [k["label"] for k in listed["keys"]] == ["reviewer"]
    assert "key" not in listed["keys"][0]
    assert listed["keys"][0]["uses"] == 2 and listed["keys"][0]["last_used"]


def test_a_revoked_key_is_refused_on_the_next_request(demo):
    server, _, owners = demo
    lyra, rigel = owners["lyra"], owners["rigel"]
    create_collection(lyra, "revocable")
    fid = lyra.put("demo", "revocable", "f.csv", b"x").json()["file_id"]
    minted = mint(lyra, "revocable").json()
    assert read(server, fid, with_key(minted["key"])).status_code == 200

    url = f"{server.url}/v1/demo/keys/{minted['id']}"
    assert httpx.delete(url, headers=rigel.headers()).status_code == 403
    revoked = httpx.delete(url, headers=lyra.headers())
    assert revoked.status_code == 200 and revoked.json()["revoked"]
    assert read(server, fid, with_key(minted["key"])).status_code == 401


def test_an_expired_key_is_refused(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    create_collection(lyra, "dated")
    fid = lyra.put("demo", "dated", "f.csv", b"x").json()["file_id"]
    key = mint(lyra, "dated").json()
    psql(
        server,
        f"UPDATE read_keys SET expires = now() - interval '1 second' WHERE id = '{key['id']}'",
    )
    assert read(server, fid, with_key(key["key"])).status_code == 401
    assert read(server, fid, with_key("sdr_forged")).status_code == 401


def test_a_file_creator_keys_their_own_file_only(demo):
    server, admin, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    mine = lyra.put("demo", "files", "mine.csv", b"lyra data").json()["file_id"]
    theirs = vega.put("demo", "files", "theirs.csv", b"vega data").json()["file_id"]

    assert mint(lyra, "files").status_code == 403  # files is admin-owned
    assert mint(lyra, "files", file_id=theirs).status_code == 403
    key = mint(lyra, "files", file_id=mine)
    assert key.status_code == 201, key.text
    key = key.json()["key"]
    assert read(server, mine, with_key(key)).content == b"lyra data"
    assert read(server, theirs, with_key(key)).status_code == 403

    # the admin owns `files` and may key any file in it, or the whole collection
    assert mint(admin, "files", file_id=theirs).status_code == 201
    assert mint(admin, "files").status_code == 201

    # the creator sees only their own keys; the owner sees all of them
    mine_listed = httpx.get(
        f"{server.url}/v1/demo/collections/files/keys", headers=lyra.headers()
    )
    assert {k["created_by"] for k in mine_listed.json()["keys"]} == {"lyra"}
    all_listed = httpx.get(
        f"{server.url}/v1/demo/collections/files/keys", headers=admin.headers()
    )
    assert len(all_listed.json()["keys"]) == 3


def test_inbox_is_never_exposed(demo):
    server, admin, owners = demo
    fid = (
        owners["lyra"].put("demo", "inbox", "submission.json", b"{}").json()["file_id"]
    )
    public = httpx.put(
        f"{server.url}/v1/demo/collections/inbox/public",
        json={"public": True},
        headers=admin.headers(),
    )
    assert public.status_code == 403
    assert mint(admin, "inbox").status_code == 403
    assert mint(admin, "inbox", file_id=fid).status_code == 403
    assert read(server, fid).status_code == 401


def test_a_public_collection_reads_anonymously(demo):
    server, admin, owners = demo
    lyra = owners["lyra"]
    create_collection(lyra, "open-data")
    fid = lyra.put("demo", "open-data", "table.csv", b"public table").json()["file_id"]
    assert read(server, fid).status_code == 401

    url = f"{server.url}/v1/demo/collections/open-data/public"
    assert (
        httpx.put(
            url, json={"public": True}, headers=owners["vega"].headers()
        ).status_code
        == 403
    )
    assert (
        httpx.put(url, json={"public": True}, headers=lyra.headers()).status_code == 200
    )
    assert read(server, fid).content == b"public table"
    assert owners["rigel"].get(fid).status_code == 200  # members read it too

    assert (
        httpx.put(url, json={"public": False}, headers=lyra.headers()).status_code
        == 200
    )
    assert read(server, fid).status_code == 401


def test_communities_are_isolated(demo):
    server, admin, owners = demo
    set_roster(server, admin, "other", ["bob"])
    bob = Owner(server, "bob")
    assert enroll(admin, bob, "other").status_code == 201
    other_file = bob.put("other", "files", "b.csv", b"other community").json()[
        "file_id"
    ]
    demo_file = (
        owners["lyra"]
        .put("demo", "files", "d.csv", b"demo community")
        .json()["file_id"]
    )

    # a file id from another community is not found in yours
    assert owners["lyra"].get(other_file).status_code == 404
    assert bob.get(demo_file).status_code == 404
    # a member's token is valid only in its own community
    assert create_collection(bob, "sneaky", community="demo").status_code == 401
    # so is a read key
    demo_key = mint(admin, "files").json()["key"]
    assert read(server, demo_file, with_key(demo_key)).status_code == 200
    assert read(server, other_file, with_key(demo_key)).status_code == 404
    other_read = read(server, other_file, with_key(demo_key), community="other")
    assert other_read.status_code == 401


def test_removing_an_owner_from_the_roster_ends_their_control(demo):
    server, admin, owners = demo
    lyra = owners["lyra"]
    create_collection(lyra, "orphaned")
    set_roster(server, admin, "demo", ["vega", "rigel"])
    assert grant(lyra, "orphaned", "vega", "read").status_code == 403
    assert mint(lyra, "orphaned").status_code == 403
    assert mint(admin, "orphaned").status_code == 201  # the admin still manages it
