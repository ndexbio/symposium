"""Server-level users and removal: root delegates server admins, removed users
become permanent tombstones whose handles never return and whose record keeps their name, and
a rebind of root's key file leaves every other user's keys alone."""

from conftest import (
    EVERY,
    Owner,
    ServerUser,
    community_with,
    enroll,
    init_root,
    invite,
    psql,
    steward_of,
)
from harness import HTTP

SERVER_ADMIN = [{"role": "server-admin", "collections": None}]


def delegate(server, handle="ana") -> ServerUser:
    root = init_root(server)
    issued = root.invite(handle, SERVER_ADMIN)
    assert issued.status_code == 201, issued.text
    assert issued.json()["community"] is None
    user = ServerUser(server, handle)
    assert user.register(issued.json()["invite"]).status_code == 201
    return user


def test_root_delegates_server_admins_who_cannot_delegate(server):
    root = init_root(server)
    ana, ben = delegate(server, "ana"), delegate(server, "ben")
    me = HTTP.get(f"{server.url}/v1/me", headers=ana.headers())
    assert me.status_code == 200 and me.json()["community"] is None  # server-wide
    assert me.json().get("position") is None  # no record to report a position in
    users = HTTP.get(f"{server.url}/v1/users", headers=root.headers()).json()["users"]
    assert {u["handle"]: [r["role"] for r in u["roles"]] for u in users} == {
        "demo-admin": ["server-root"],
        "ana": ["server-admin"],
        "ben": ["server-admin"],
    }
    assert ben.invite("eve", SERVER_ADMIN).status_code == 403
    assert HTTP.get(f"{server.url}/v1/users", headers=ben.headers()).status_code == 403
    # a server admin creates communities and runs them
    created = HTTP.post(
        f"{server.url}/v1/communities",
        json={"name": "demo", "admin": "steward"},
        headers=ana.headers(),
    )
    assert created.status_code == 201, created.text
    assert invite(ana, "demo", "lyra").status_code == 201
    app = ana.at("demo").issue(
        "app",
        roles=[{"role": "community-observer", "collections": EVERY}],
        non_member=True,
    )
    app_headers = {"Authorization": f"Bearer {app['key']}"}
    record = f"{server.url}/v1/communities/demo/collections/record/changes"
    assert HTTP.get(record, headers=app_headers).status_code == 200
    # root is not removed through the API; ana is, by root alone
    root_url = root.user_url("demo-admin")
    assert HTTP.delete(root_url, headers=root.headers()).status_code == 409
    ana_url = root.user_url("ana")
    assert HTTP.delete(ana_url, headers=ben.headers()).status_code == 403
    assert HTTP.delete(ana_url, headers=root.headers()).status_code == 200
    gone = HTTP.get(ana_url, headers=root.headers())
    assert gone.status_code == 200 and gone.json()["removed"]  # its tombstone answers
    assert HTTP.get(f"{server.url}/v1/me", headers=ana.headers()).status_code == 401
    signed = ana.sign_in()
    assert signed.status_code == 401 and "removed" in signed.json()["detail"]
    assert (
        HTTP.get(record, headers=app_headers).status_code == 401
    )  # its keys are deleted
    assert HTTP.get(f"{server.url}/v1/me", headers=ben.headers()).status_code == 200


def test_a_handle_is_server_level_or_in_communities_never_both(server):
    community_with(server, members=("lyra",))
    root = init_root(server)
    clash = root.invite("lyra", SERVER_ADMIN)
    assert clash.status_code == 409 and "demo" in clash.json()["detail"]


def test_a_removed_member_is_a_permanent_tombstone(server):
    root, owners = community_with(server, members=("lyra", "olive"))
    lyra = owners["lyra"]
    steward = steward_of(server)
    own = HTTP.post(
        lyra.url("/collections"), json={"name": "mine"}, headers=lyra.headers()
    )
    assert own.status_code == 201
    shared = lyra.put("demo", "mine", "a.csv", b"x").json()["file_id"]
    lyra.assign("community-observer", ["mine"], "olive", "demo")
    published = lyra.put("demo", "files", "data.csv", b"lyra's").json()
    member_key = lyra.issue("script")
    app_key = steward.issue(
        "app",
        roles=[{"role": "community-observer", "collections": EVERY}],
        non_member=True,
    )
    lyra_app = HTTP.post(
        lyra.url("/api-keys"),
        json={
            "label": "mine-app",
            "non_member": True,
            "roles": [{"role": "community-observer", "collections": ["mine"]}],
        },
        headers=lyra.headers(),
    )
    assert lyra_app.status_code == 201, lyra_app.text
    gate_keeper = Owner(server, "bob")
    enroll(
        steward,
        gate_keeper,
        "demo",
        roles=[{"role": "gate-keeper", "collections": None}],
    )
    lyra_id = psql(server, "SELECT id FROM users WHERE handle = 'lyra'")
    url = root.user_url("lyra", "demo")
    assert HTTP.delete(url, headers=gate_keeper.headers()).status_code == 403
    assert HTTP.delete(url, headers=owners["olive"].headers()).status_code == 403
    removed = HTTP.delete(url, headers=steward.headers())
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed"] and removed.json()["roles"] == []

    # everything it signed in with or issued is gone
    signed = lyra.sign_in()
    assert signed.status_code == 401 and "removed from demo" in signed.json()["detail"]
    for issued in (member_key, lyra_app.json()):
        by_key = {"Authorization": f"Bearer {issued['key']}"}
        assert HTTP.get(lyra.server.url + "/v1/me", headers=by_key).status_code == 401
    listed = HTTP.get(steward.url("/api-keys"), headers=steward.headers()).json()[
        "items"
    ]
    assert [k["label"] for k in listed] == ["app"]
    assert (
        HTTP.get(
            steward.server.url + "/v1/me",
            headers={"Authorization": f"Bearer {app_key['key']}"},
        ).status_code
        == 200
    )

    # it stays: on the roster, marked removed; its work under its handle; its collection
    roster = HTTP.get(steward.url("/users"), headers=steward.headers()).json()["users"]
    assert {r["handle"]: bool(r["removed"]) for r in roster}["lyra"] is True
    assert steward.stat(published["file_id"]).json()["created_by"] == "lyra"
    assert owners["olive"].get(shared).status_code == 200
    assert steward.get(shared).status_code == 200
    member = HTTP.get(steward.url("/members/lyra"), headers=steward.headers()).json()
    assert member["removed"]

    # and its handle never returns
    again = invite(steward, "demo", "lyra")
    assert again.status_code == 409 and "removed member" in again.json()["detail"]
    assert psql(server, "SELECT count(*) FROM users WHERE handle = 'lyra'") == "1"
    deleted = psql(server, f"DELETE FROM users WHERE id = '{lyra_id}'")
    assert deleted == ""  # refused by the foreign keys: the row stays
    assert psql(server, "SELECT count(*) FROM users WHERE handle = 'lyra'") == "1"
    duplicate = psql(
        server, "INSERT INTO users (handle, home) VALUES ('lyra', 'demo') RETURNING id"
    )
    assert duplicate == ""
    assert psql(server, "SELECT count(*) FROM users WHERE handle = 'lyra'") == "1"


def test_a_root_rebind_leaves_every_other_users_keys(server):
    ana = delegate(server)
    _, owners = community_with(server, members=("lyra",))
    status = server.status()
    assert status["root"] == "demo-admin"
    # the root's key file is rebound to the same key at restart: nothing else changes
    server.restarted()
    assert ana.sign_in().status_code == 200
    assert owners["lyra"].sign_in().status_code == 200
