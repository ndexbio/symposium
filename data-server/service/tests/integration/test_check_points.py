"""The two check points of every request: the operation's grants at the route, then each
collection at the handler. Collection lists, the owner allowance (sessions only), public collections and anonymous reads, and the status codes."""

from conftest import (
    EVERY,
    community_with,
    create_community,
    enroll,
    init_admin,
)
from conftest import Owner as User
from harness import HTTP

SUBMISSION = {"symposium_submission": True}


def bearer(key) -> dict:
    return {"Authorization": f"Bearer {key['key']}"}


def collection(owner, name, community="demo"):
    r = HTTP.post(
        f"{owner.server.url}/v1/communities/{community}/collections",
        json={"name": name},
        headers=owner.headers(),
    )
    assert r.status_code == 201, r.text


def test_a_collection_limited_key_reads_its_collections_only(server):
    root, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    for name in ("c1", "c2", "c3"):
        collection(lyra, name)
    files = {
        n: lyra.put("demo", n, "a.csv", n.encode()).json()["file_id"]
        for n in ("c1", "c2")
    }
    lyra.put("demo", "inbox", "sub.json", b"{}", SUBMISSION)
    key = lyra.issue(
        "app",
        roles=[{"role": "community-observer", "collections": ["c2", "c3"]}],
        non_member=True,
    )
    url = f"{server.url}/v1/communities/demo"
    ok = HTTP.get(f"{url}/collections/c2/changes", headers=bearer(key))
    assert ok.status_code == 200 and len(ok.json()["items"]) == 1
    assert (
        HTTP.get(
            f"{url}/files/{files['c2']}/versions/latest", headers=bearer(key)
        ).status_code
        == 200
    )
    for refused in (
        f"{url}/collections/c1/changes",
        f"{url}/files/{files['c1']}/versions/latest",
        f"{url}/collections/record/changes",
        f"{url}/collections/inbox/changes",
        f"{url}/artifacts",
    ):
        assert HTTP.get(refused, headers=bearer(key)).status_code == 403, refused
    listed = HTTP.get(f"{url}/collections", headers=bearer(key)).json()["collections"]
    assert [c["name"] for c in listed] == ["c2", "c3"]
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        HTTP.get(
            f"{url}/files/{missing}/versions/latest", headers=bearer(key)
        ).status_code
        == 404
    )
    create_community(server, root, "other")
    other = HTTP.get(
        f"{server.url}/v1/communities/other/collections/c2/changes", headers=bearer(key)
    )
    assert other.status_code in (403, 404)
    write = HTTP.put(
        f"{url}/collections/c2/files/b.csv", content=b"x", headers=bearer(key)
    )
    assert write.status_code == 403
    assert (
        lyra.unassign("community-observer", ["c2"], api_key_id=key["id"]).status_code
        == 200
    )
    assert (
        HTTP.get(f"{url}/collections/c2/changes", headers=bearer(key)).status_code
        == 403
    )
    assert (
        HTTP.delete(f"{url}/api-keys/{key['id']}", headers=lyra.headers()).status_code
        == 200
    )
    assert (
        HTTP.get(f"{url}/collections/c3/changes", headers=bearer(key)).status_code
        == 401
    )
    reissued = lyra.issue_request(
        "app2",
        [{"role": "community-observer", "collections": ["files"]}],
        non_member=True,
    )
    assert reissued.status_code == 403  # files is not lyra's to share


def test_issued_keys_get_no_owner_allowance_and_sessions_do(server):
    _, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    collection(lyra, "mine")
    script = lyra.issue(
        "uploader", roles=[{"role": "community-member", "collections": ["files"]}]
    )
    up = HTTP.put(
        f"{server.url}/v1/communities/demo/collections/files/files/a.csv",
        content=b"x",
        headers={**bearer(script), "If-None-Match": "*", "Repr-Digest": _digest(b"x")},
    )
    assert up.status_code == 201, up.text
    mine = HTTP.put(
        f"{server.url}/v1/communities/demo/collections/mine/files/a.csv",
        content=b"x",
        headers={**bearer(script), "If-None-Match": "*", "Repr-Digest": _digest(b"x")},
    )
    assert mine.status_code == 403
    # the same user, signed in and narrowed to nothing by list, still reaches what it owns
    root = init_admin(server)
    root.unassign("community-member", None, "lyra", "demo")
    root.assign("community-member", [], "lyra", "demo")
    lyra._session = None
    assert lyra.put("demo", "mine", "b.csv", b"y").status_code == 201
    assert lyra.put("demo", "files", "c.csv", b"z").status_code == 403


def test_public_collections_answer_without_a_key(server):
    _, owners = community_with(server, members=("lyra", "olive"))
    lyra, olive = owners["lyra"], owners["olive"]
    collection(lyra, "open")
    fid = lyra.put("demo", "open", "a.csv", b"x").json()["file_id"]
    url = f"{server.url}/v1/communities/demo"
    assert HTTP.get(f"{url}/files/{fid}/versions/latest").status_code == 401
    made = HTTP.patch(
        f"{url}/collections/open", json={"public": True}, headers=olive.headers()
    )
    assert made.status_code == 403  # manage: the owner's
    made = HTTP.patch(
        f"{url}/collections/open", json={"public": True}, headers=lyra.headers()
    )
    assert made.status_code == 200
    assert HTTP.get(f"{url}/files/{fid}/versions/latest").status_code == 200
    assert (
        HTTP.put(f"{url}/collections/open/files/b.csv", content=b"x").status_code == 401
    )


def test_creating_a_collection_takes_write_with_any_value(server):
    root, owners = community_with(server, members=("lyra", "mia"))
    for handle, value in (("lyra", ["files"]), ("mia", [])):
        root.unassign("community-member", None, handle, "demo")
        root.assign("community-member", value, handle, "demo")
        owner = owners[handle]
        owner._session = None
        made = HTTP.post(
            owner.url("/collections"),
            json={"name": f"{handle}s"},
            headers=owner.headers(),
        )
        assert made.status_code == 201, made.text
        # the creator owns it: read, write and manage through the owner allowance
        assert owner.put("demo", f"{handle}s", "a.csv", b"x").status_code == 201
        public = HTTP.patch(
            owner.url(f"/collections/{handle}s"),
            json={"public": False},
            headers=owner.headers(),
        )
        assert public.status_code == 200
    assert owners["mia"].put("demo", "lyras", "b.csv", b"x").status_code == 403
    observer = User(server, "olive")
    enroll(
        root,
        observer,
        "demo",
        roles=[{"role": "community-observer", "collections": EVERY}],
    )
    refused = HTTP.post(
        observer.url("/collections"), json={"name": "x"}, headers=observer.headers()
    )
    assert refused.status_code == 403
    app = owners["lyra"].issue(
        "app",
        roles=[{"role": "community-observer", "collections": ["lyras"]}],
        non_member=True,
    )
    by_app = HTTP.post(
        observer.url("/collections"),
        json={"name": "y"},
        headers={"Authorization": f"Bearer {app['key']}"},
    )
    assert by_app.status_code == 403


def _digest(data: bytes) -> str:
    import base64
    import hashlib

    return "sha-256=:" + base64.b64encode(hashlib.sha256(data).digest()).decode() + ":"
