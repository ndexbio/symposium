"""Role assignments: who may assign and unassign what, how collection
values merge and shrink, what a key may carry and who may change it, and the last `members`
holder. Every change applies on the next request."""

import threading

from conftest import (
    EVERY,
    Owner,
    community_with,
    create_community,
    enroll,
    file_headers,
    init_root,
    steward_of,
)
from harness import HTTP


def roles(owner, handle, community="demo"):
    r = HTTP.get(
        owner.principal_url(handle, community) + "/roles", headers=owner.headers()
    )
    assert r.status_code == 200, r.text
    return {a["role"]: a["collections"] for a in r.json()["roles"]}


def make_collection(owner, name, community="demo"):
    r = HTTP.post(
        f"{owner.server.url}/v1/communities/{community}/collections",
        json={"name": name},
        headers=owner.headers(),
    )
    assert r.status_code == 201, r.text


def test_each_role_is_assigned_only_by_its_authority(server):
    root, owners = community_with(server, members=("lyra", "olive"))
    lyra = owners["lyra"]
    steward = steward_of(server)
    bob = Owner(server, "bob")
    enroll(steward, bob, "demo", roles=[{"role": "gate-keeper", "collections": None}])
    make_collection(lyra, "mine")

    # community-member: members, whatever the collection value
    for value in (EVERY, [], ["mine"]):
        assert (
            lyra.assign("community-member", value, "olive", "demo").status_code == 403
        )
    assert steward.assign(
        "community-member", ["files"], "olive", "demo"
    ).status_code in (200, 201)
    # community-observer by name: manage on each collection, so an owner shares its own
    assert lyra.assign("community-observer", ["mine"], "olive", "demo").status_code in (
        200,
        201,
    )
    assert (
        lyra.assign("community-observer", ["files"], "olive", "demo").status_code == 403
    )
    assert lyra.assign("community-observer", EVERY, "olive", "demo").status_code == 403
    # administrative community roles: members
    assert bob.assign("community-admin", None, "olive", "demo").status_code == 403
    assert lyra.assign("gate-keeper", None, "olive", "demo").status_code == 403
    assert steward.assign("gate-keeper", None, "olive", "demo").status_code in (
        200,
        201,
    )
    # server roles: delegate; server-root never
    ana = Owner(server, "ana", community=None)
    ana.home = None
    joined = root.invite("ana", [{"role": "server-admin", "collections": None}])
    assert ana.register(joined.json()["invite"]).status_code == 201
    assert ana.assign("server-admin", None, "ana").status_code == 403
    assert (
        steward.assign("server-admin", None, "ana").status_code == 404
    )  # not in its home
    assert root.assign("server-admin", None, "lyra", "demo").status_code == 400
    assert root.assign("server-root", None, "ana").status_code == 403
    assert root.assign("community-member", EVERY, "ana").status_code == 400
    # a user of another community is out of reach
    create_community(server, root, "other")
    outsider = Owner(server, "x", community="other")
    enroll(root.at("other"), outsider, "other")
    assert steward.assign("community-observer", EVERY, "x", "other").status_code == 403


def test_collection_values_merge_and_shrink(server):
    root, owners = community_with(server, members=("lyra", "olive"))
    lyra = owners["lyra"]
    for name in ("c1", "c2", "c3"):
        make_collection(lyra, name)
    for names in (["c1"], ["c2", "c3"]):
        assert lyra.assign(
            "community-observer", names, "olive", "demo"
        ).status_code in (200, 201)
    assert roles(root, "olive")["community-observer"] == ["c1", "c2", "c3"]
    assert (
        lyra.unassign("community-observer", ["c2"], "olive", "demo").status_code == 200
    )
    assert roles(root, "olive")["community-observer"] == ["c1", "c3"]
    # `*` absorbs names, and names leave `*` as it is
    assert root.assign("community-observer", EVERY, "olive", "demo").status_code in (
        200,
        201,
    )
    assert root.assign("community-observer", ["c1"], "olive", "demo").status_code in (
        200,
        201,
    )
    assert roles(root, "olive")["community-observer"] == EVERY


def test_removing_names_takes_the_authority_to_assign_each(server):
    root, owners = community_with(server, members=("lyra", "mia", "olive"))
    lyra, mia = owners["lyra"], owners["mia"]
    make_collection(lyra, "c2")
    make_collection(mia, "c1")
    mia.assign("community-observer", ["c1"], "olive", "demo")
    lyra.assign("community-observer", ["c2"], "olive", "demo")
    assert (
        lyra.unassign("community-observer", ["c1"], "olive", "demo").status_code == 403
    )
    assert lyra.unassign("community-observer", None, "olive", "demo").status_code == 403
    assert (
        lyra.unassign("community-observer", ["c2"], "olive", "demo").status_code == 200
    )
    assert roles(root, "olive")["community-observer"] == ["c1"]
    assert root.unassign("community-observer", None, "olive", "demo").status_code == 200
    assert "community-observer" not in roles(root, "olive")


def test_changes_apply_on_the_next_request(server):
    root, owners = community_with(server, members=("lyra", "olive"))
    lyra, olive = owners["lyra"], owners["olive"]
    make_collection(lyra, "c2")
    fid = lyra.put("demo", "c2", "a.csv", b"x").json()["file_id"]
    root.unassign("community-member", None, "olive", "demo")
    olive._session = None
    assert olive.get(fid).status_code == 403
    lyra.assign("community-observer", ["c2"], "olive", "demo")
    assert olive.get(fid).status_code == 200  # the same session, the next request
    lyra.unassign("community-observer", ["c2"], "olive", "demo")
    assert olive.get(fid).status_code == 403


def test_only_the_issuer_or_a_members_holder_changes_a_key(server):
    root, owners = community_with(server, members=("lyra", "vega"))
    lyra, vega = owners["lyra"], owners["vega"]
    steward = steward_of(server)
    make_collection(vega, "theirs")
    key = lyra.issue(
        "script", roles=[{"role": "community-member", "collections": ["files"]}]
    )
    assert (
        vega.assign("community-member", ["theirs"], api_key_id=key["id"]).status_code
        == 403
    )
    assert (
        vega.unassign("community-member", None, api_key_id=key["id"]).status_code == 403
    )
    revoked = HTTP.delete(lyra.url(f"/api-keys/{key['id']}"), headers=vega.headers())
    assert revoked.status_code == 403
    assert (
        lyra.assign("community-member", ["c9"], api_key_id=key["id"]).status_code == 404
    )
    assert lyra.assign(
        "community-member", ["theirs"], api_key_id=key["id"]
    ).status_code in (200, 201)
    # a members holder changes it, never beyond the issuer's grants
    assert steward.assign(
        "community-observer", EVERY, api_key_id=key["id"]
    ).status_code in (200, 201)
    root.unassign("community-member", None, "lyra", "demo")
    root.assign("community-observer", ["files"], "lyra", "demo")
    assert (
        steward.assign("community-member", EVERY, api_key_id=key["id"]).status_code
        == 403
    )


def test_a_key_carries_only_what_its_issuer_holds(server):
    _, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    steward = steward_of(server)
    admin_role = [{"role": "community-admin", "collections": None}]
    assert lyra.issue_request("a", admin_role).status_code == 403
    assert steward.issue_request("a", admin_role).status_code == 403
    gate = [{"role": "gate-keeper", "collections": None}]
    assert steward.issue_request("a", gate).status_code == 403
    member = [{"role": "community-member", "collections": EVERY}]
    assert lyra.issue_request("b", member, non_member=True).status_code == 403
    observer_all = [{"role": "community-observer", "collections": EVERY}]
    assert lyra.issue_request("c", observer_all, non_member=True).status_code == 403
    assert steward.issue_request("c", observer_all, non_member=True).status_code == 201
    assert lyra.issue_request("d", observer_all).status_code == 201  # a member key
    assert lyra.issue_request("e", []).status_code == 422  # roles are required


def test_the_last_members_holder_stays(server):
    root = init_root(server)
    steward = steward_of(server)
    assert (
        steward.unassign("community-admin", None, "steward", "demo").status_code == 409
    )
    removed = HTTP.delete(
        root.user_url("steward", "demo"),
        headers=root.headers(),
    )
    assert removed.status_code == 409
    second = Owner(server, "mia")
    enroll(
        steward,
        second,
        "demo",
        roles=[{"role": "community-admin", "collections": None}],
    )
    assert (
        steward.unassign("community-admin", None, "steward", "demo").status_code == 200
    )
    assert second.unassign("community-admin", None, "mia", "demo").status_code == 409


def test_two_concurrent_demotions_of_the_last_two_admins_leave_one(server):
    steward = steward_of(server)
    mia = Owner(server, "mia")
    enroll(
        steward, mia, "demo", roles=[{"role": "community-admin", "collections": None}]
    )
    results = []
    barrier = threading.Barrier(2)

    def demote(who, handle):
        barrier.wait()
        results.append(
            who.unassign("community-admin", None, handle, "demo").status_code
        )

    threads = [
        threading.Thread(target=demote, args=(steward, "mia")),
        threading.Thread(target=demote, args=(mia, "steward")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # one demotion wins; the other is refused, as the last holder (409) or, once demoted,
    # as lacking members (403)
    assert sorted(results)[0] == 200 and sorted(results)[1] in (403, 409)
    roster = HTTP.get(steward.url("/users"), headers=init_root(server).headers()).json()
    community_admins = [
        r["handle"]
        for r in roster["users"]
        if any(a["role"] == "community-admin" for a in r["roles"])
    ]
    assert len(community_admins) == 1


def test_narrowing_the_issuer_narrows_its_keys_on_the_next_request(server):
    root, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    key = lyra.issue(
        "script", roles=[{"role": "community-member", "collections": EVERY}]
    )
    bearer = {"Authorization": f"Bearer {key['key']}"}
    made = HTTP.post(
        root.url("/collections"), json={"name": "lab"}, headers=root.headers()
    )
    assert made.status_code == 201, made.text
    lab = lyra.url("/collections/lab/changes")
    assert HTTP.get(lab, headers=bearer).status_code == 200
    root.unassign("community-member", None, "lyra", "demo")
    root.assign("community-member", ["files"], "lyra", "demo")
    assert HTTP.get(lab, headers=bearer).status_code == 403
    files = lyra.url("/collections/files/changes")
    assert HTTP.get(files, headers=bearer).status_code == 200
    root.unassign("community-member", None, "lyra", "demo")
    root.assign("community-observer", EVERY, "lyra", "demo")
    put = HTTP.put(
        lyra.url("/collections/files/files/x.csv"),
        content=b"x",
        headers={**bearer, **file_headers(b"x")},
    )
    assert (
        put.status_code == 403
    )  # the issuer writes nothing now, and neither does its key
