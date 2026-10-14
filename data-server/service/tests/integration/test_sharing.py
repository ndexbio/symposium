"""Sharing: member-owned collections, grants to Members and to non-member API keys, public
collections, inbox privacy, the life of an issued key, and per-community isolation. A file has
its collection's access; `test_access_matrix.py` asserts every caller against every operation."""

import pytest
from conftest import Owner, community_with, enroll, psql, set_roster
from harness import HTTP


@pytest.fixture
def demo(server):
    admin, owners = community_with(server)
    return server, admin, owners


def with_key(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def create_collection(owner, name, community="demo"):
    return HTTP.post(
        f"{owner.server.url}/v1/{community}/collections",
        json={"name": name},
        headers=owner.headers(),
    )


def grant(owner, collection, perm, granted=True, *, handle=None, api_key_id=None):
    body = {"perm": perm, "granted": granted}
    if handle is not None:
        body["handle"] = handle
    if api_key_id is not None:
        body["api_key_id"] = api_key_id
    return HTTP.put(
        f"{owner.server.url}/v1/demo/collections/{collection}/grants",
        json=body,
        headers=owner.headers(),
    )


def set_public(owner, collection, public, headers=None):
    return HTTP.put(
        f"{owner.server.url}/v1/demo/collections/{collection}/public",
        json={"public": public},
        headers=owner.headers() if headers is None else headers,
    )


def read(server, file_id, headers=None, ref=1, community="demo"):
    return HTTP.get(
        f"{server.url}/v1/{community}/files/{file_id}/v/{ref}", headers=headers or {}
    )


def file_count(server, collection) -> str:
    return psql(
        server,
        f"SELECT count(*) FROM files WHERE community = 'demo' AND collection = '{collection}'",
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
    assert grant(vega, "shared", "write", handle="rigel").status_code == 403
    assert grant(lyra, "shared", "write", handle="mallory").status_code == 403
    assert grant(lyra, "shared", "write", handle="vega").status_code == 200
    assert grant(lyra, "shared", "read", handle="vega").status_code == 200
    # a Member granted write is still not the owner: it cannot grant on
    assert grant(vega, "shared", "read", handle="rigel").status_code == 403

    fid = vega.put("demo", "shared", "vega.csv", b"from vega").json()["file_id"]
    assert vega.get(fid).content == b"from vega"
    assert rigel.put("demo", "shared", "rigel.csv", b"no").status_code == 403
    assert rigel.get(fid).status_code == 403
    # the owner may read anything in their collection, but still not change vega's file
    assert lyra.get(fid).status_code == 200
    assert lyra.version(fid, data=b"overwrite").status_code == 403

    assert grant(lyra, "shared", "write", False, handle="vega").status_code == 200
    assert vega.put("demo", "shared", "again.csv", b"no").status_code == 403
    assert grant(lyra, "shared", "read", False, handle="vega").status_code == 200
    assert vega.get(fid).status_code == 403  # withdrawn on the very next request


def test_a_non_member_key_reads_only_the_collections_it_is_granted(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    create_collection(lyra, "release")
    inside = lyra.put("demo", "release", "result.csv", b"shared result").json()
    outside = lyra.put("demo", "files", "private.csv", b"not shared").json()

    app = lyra.issue("dashboard", role="non-member")
    assert app["role"] == "non-member" and app["handle"] is None
    assert app["key"].startswith("sak_")
    key = with_key(app["key"])
    assert (
        read(server, inside["file_id"], key).status_code == 403
    )  # nothing granted yet

    assert grant(lyra, "release", "read", api_key_id=app["id"]).status_code == 200
    assert read(server, inside["file_id"], key).content == b"shared result"
    assert read(server, outside["file_id"], key).status_code == 403
    assert read(server, inside["file_id"]).status_code == 401  # no key at all
    stat = HTTP.get(
        f"{server.url}/v1/demo/files/{inside['file_id']}/v/1/stat", headers=key
    )
    assert stat.status_code == 200
    listed = HTTP.get(
        f"{server.url}/v1/demo/collections/release/changes", headers=key
    ).json()
    assert [i["file_id"] for i in listed["items"]] == [inside["file_id"]]

    # a non-member key never writes and acts as no Member
    write = HTTP.put(
        f"{server.url}/v1/demo/collections/release/files/x.csv",
        content=b"x",
        headers=key,
    )
    assert write.status_code == 403
    assert file_count(server, "release") == "1"
    me = HTTP.get(f"{server.url}/v1/demo/me", headers=key).json()
    assert (me["role"], me["handle"], me["kind"]) == ("non-member", None, "issued")
    assert me["grants"] == [{"collection": "release", "perm": "read"}]

    # withdrawn, it reads nothing from the very next request
    assert (
        grant(lyra, "release", "read", False, api_key_id=app["id"]).status_code == 200
    )
    assert read(server, inside["file_id"], key).status_code == 403


def test_a_non_member_key_is_granted_read_only(demo):
    server, admin, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    create_collection(lyra, "release")
    app = lyra.issue("dashboard", role="non-member")
    refused = grant(lyra, "release", "write", api_key_id=app["id"])
    assert refused.status_code == 400 and "read only" in refused.json()["detail"]
    assert (
        psql(server, "SELECT count(*) FROM grants WHERE api_key_id IS NOT NULL") == "0"
    )

    member_key = lyra.issue("notebook")
    refused = grant(lyra, "release", "read", api_key_id=member_key["id"])
    assert refused.status_code == 400  # a member key reads with its Member's grants

    revoked = vega.issue("old app", role="non-member")
    HTTP.delete(vega.url(f"/api-keys/{revoked['id']}"), headers=vega.headers())
    assert grant(lyra, "release", "read", api_key_id=revoked["id"]).status_code == 400

    set_roster(server, admin, "other", ["bob"])
    bob = Owner(server, "bob")
    enroll(admin, bob, "other")
    elsewhere = HTTP.post(
        bob.url("/api-keys"),
        json={"label": "other app", "role": "non-member"},
        headers=bob.headers(),
    ).json()
    assert grant(lyra, "release", "read", api_key_id=elsewhere["id"]).status_code == 400

    both = HTTP.put(
        f"{server.url}/v1/demo/collections/release/grants",
        json={"handle": "vega", "api_key_id": app["id"], "perm": "read"},
        headers=lyra.headers(),
    )
    assert both.status_code == 400


def test_changing_access_takes_a_session_key(demo):
    server, _, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    create_collection(lyra, "release")
    member_key = with_key(lyra.issue("notebook")["key"])
    app = lyra.issue("dashboard", role="non-member")
    for headers in (member_key, with_key(app["key"])):
        assert set_public(lyra, "release", True, headers).status_code == 403
        r = HTTP.put(
            f"{server.url}/v1/demo/collections/release/grants",
            json={"handle": "vega", "perm": "read"},
            headers=headers,
        )
        assert r.status_code == 403
        r = HTTP.post(lyra.url("/api-keys"), json={"label": "more"}, headers=headers)
        assert r.status_code == 403
    # vega gained nothing, and no key was issued
    assert psql(server, "SELECT count(*) FROM api_keys WHERE kind = 'issued'") == "2"
    fid = lyra.put("demo", "release", "a.csv", b"x").json()["file_id"]
    assert vega.get(fid).status_code == 403


def test_a_revoked_or_expired_key_is_refused_on_the_next_request(demo):
    server, admin, owners = demo
    lyra, rigel = owners["lyra"], owners["rigel"]
    create_collection(lyra, "revocable")
    fid = lyra.put("demo", "revocable", "f.csv", b"x").json()["file_id"]
    apps = [lyra.issue(f"app {n}", role="non-member") for n in range(3)]
    for app in apps:
        assert grant(lyra, "revocable", "read", api_key_id=app["id"]).status_code == 200
        assert read(server, fid, with_key(app["key"])).status_code == 200

    # another Member cannot revoke it; its issuer can, and so can the admin
    url = lyra.url(f"/api-keys/{apps[0]['id']}")
    assert HTTP.delete(url, headers=rigel.headers()).status_code == 404
    revoked = HTTP.delete(url, headers=lyra.headers())
    assert revoked.status_code == 200 and revoked.json()["revoked"]
    assert read(server, fid, with_key(apps[0]["key"])).status_code == 401
    by_admin = HTTP.delete(
        lyra.url(f"/api-keys/{apps[1]['id']}"), headers=admin.headers()
    )
    assert by_admin.status_code == 200
    assert read(server, fid, with_key(apps[1]["key"])).status_code == 401

    psql(
        server,
        f"UPDATE api_keys SET expires = now() - interval '1 second' WHERE id = '{apps[2]['id']}'",
    )
    assert read(server, fid, with_key(apps[2]["key"])).status_code == 401
    assert read(server, fid, with_key("sak_" + "A" * 43)).status_code == 401


def test_an_issuer_leaving_the_roster_revokes_every_key_it_made(demo):
    server, admin, owners = demo
    lyra = owners["lyra"]
    create_collection(lyra, "orphaned")
    fid = lyra.put("demo", "orphaned", "f.csv", b"x").json()["file_id"]
    session = lyra.headers()
    member_key = with_key(lyra.issue("notebook")["key"])
    app = lyra.issue("dashboard", role="non-member")
    grant(lyra, "orphaned", "read", api_key_id=app["id"])
    assert read(server, fid, with_key(app["key"])).status_code == 200

    removed = set_roster(server, admin, "demo", ["vega", "rigel"])
    assert removed["removed"] == ["lyra"]
    for headers in (session, member_key, with_key(app["key"])):
        assert read(server, fid, headers).status_code == 401
    # control of the collection passes to the admin, who manages it still
    assert grant(admin, "orphaned", "read", handle="vega").status_code == 200
    assert owners["vega"].get(fid).status_code == 200


def test_inbox_is_never_exposed(demo):
    server, admin, owners = demo
    fid = (
        owners["lyra"].put("demo", "inbox", "submission.json", b"{}").json()["file_id"]
    )
    assert set_public(admin, "inbox", True).status_code == 403
    assert read(server, fid).status_code == 401
    assert owners["vega"].get(fid).status_code == 403  # a submission is its submitter's
    # inbox's owner, the admin, may still grant a key read on it, as on any collection
    app = admin.issue("dashboard", role="non-member")
    assert read(server, fid, with_key(app["key"])).status_code == 403
    assert grant(admin, "inbox", "read", api_key_id=app["id"]).status_code == 200
    assert read(server, fid, with_key(app["key"])).status_code == 200
    assert read(server, fid).status_code == 401


def test_a_public_collection_opens_reads_only(demo):
    server, admin, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    create_collection(lyra, "open-data")
    fid = lyra.put("demo", "open-data", "table.csv", b"public table").json()["file_id"]
    app = with_key(lyra.issue("dashboard", role="non-member")["key"])
    changes = f"{server.url}/v1/demo/collections/open-data/changes"
    assert read(server, fid).status_code == 401
    assert read(server, fid, app).status_code == 403
    assert HTTP.get(changes).status_code == 401

    assert set_public(lyra, "open-data", True, vega.headers()).status_code == 403
    assert set_public(lyra, "open-data", True).status_code == 200
    assert read(server, fid).content == b"public table"
    assert read(server, fid, app).content == b"public table"
    assert owners["rigel"].get(fid).status_code == 200  # members read it too
    assert [i["file_id"] for i in HTTP.get(changes).json()["items"]] == [fid]

    # public opens reads only: nobody without write access adds or changes a file
    anonymous = HTTP.put(
        f"{server.url}/v1/demo/collections/open-data/files/x.csv", content=b"x"
    )
    assert anonymous.status_code == 401
    assert vega.put("demo", "open-data", "x.csv", b"x").status_code == 403
    assert vega.version(fid, data=b"changed").status_code == 403
    assert vega.delete(fid).status_code == 403
    assert HTTP.delete(f"{server.url}/v1/demo/files/{fid}").status_code == 401
    assert file_count(server, "open-data") == "1"
    assert lyra.get(fid).content == b"public table"

    assert set_public(lyra, "open-data", False).status_code == 200
    assert read(server, fid).status_code == 401
    assert read(server, fid, app).status_code == 403
    assert HTTP.get(changes).status_code == 401


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
    # a key is valid only in its own community
    assert create_collection(bob, "sneaky", community="demo").status_code == 403
    app = admin.issue("dashboard", role="non-member")
    assert grant(admin, "files", "read", api_key_id=app["id"]).status_code == 200
    assert read(server, demo_file, with_key(app["key"])).status_code == 200
    assert read(server, other_file, with_key(app["key"])).status_code == 404
    other_read = read(server, other_file, with_key(app["key"]), community="other")
    assert other_read.status_code == 403
    # and so is public: a public collection elsewhere reads only through its own path
    bob_open = HTTP.post(
        bob.url("/collections"), json={"name": "open"}, headers=bob.headers()
    )
    assert bob_open.status_code == 201
    opened = HTTP.put(
        bob.url("/collections/open/public"),
        json={"public": True},
        headers=bob.headers(),
    )
    assert opened.status_code == 200
    public_file = bob.put("other", "open", "p.csv", b"public").json()["file_id"]
    assert read(server, public_file, community="other").content == b"public"
    assert read(server, public_file, community="demo").status_code == 404
