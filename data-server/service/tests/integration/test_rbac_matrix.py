"""Every role against every kind of operation: each of the six roles, the collection values
`*`, `[]` and names, a user of another community, a server-level user, a member key and a
non-member key, on a collection owned by one of them. Each cell is the status the operation
answers; a refusal is 403, and a caller without a key gets 401."""

import itertools

from conftest import (
    EVERY,
    Admin,
    Owner,
    community_with,
    create_community,
    enroll,
    file_headers,
    steward_of,
)
from harness import HTTP

SERVER_ADMIN = [{"role": "server-admin", "collections": None}]
GATE_KEEPER = [{"role": "gate-keeper", "collections": None}]
UNIQUE = itertools.count()

# the status of each operation when allowed; a refused one answers 403
OPERATIONS = {
    "read c1": 200,
    "write c1": 201,
    "manage c1": 200,
    "read record": 200,
    "create collection": 201,
    "submit": 201,
    "list users": 200,
    "export": 200,
    "list communities": 200,
}

# who may do what: lyra owns c1
ALLOWED = {
    "root": {"read c1", "write c1", "manage c1", "read record", "create collection",
             "list users", "export", "list communities"},
    "server-admin": {"read c1", "write c1", "manage c1", "read record", "create collection",
                     "list users", "export", "list communities"},
    "community-admin": {"read c1", "write c1", "manage c1", "read record",
                        "create collection", "list users", "export"},
    "gate-keeper": {"read c1", "read record"},
    "member * (owner)": {"read c1", "write c1", "manage c1", "read record",
                         "create collection", "submit"},
    "member []": {"create collection", "submit"},
    "member [c1]": {"read c1", "write c1", "create collection", "submit"},
    "observer *": {"read c1", "read record"},
    "observer [c1]": {"read c1"},
    "member of another community": set(),
    "member key [c1]": {"read c1", "write c1", "create collection", "submit"},
    "non-member key [c1]": {"read c1"},
}  # fmt: skip


def operate(name: str, headers: dict, url: str, fid: str) -> int:
    n = next(UNIQUE)
    demo = f"{url}/v1/demo"
    if name == "read c1":
        return HTTP.get(f"{demo}/files/{fid}/v/latest", headers=headers).status_code
    if name == "write c1":
        return HTTP.put(
            f"{demo}/collections/c1/files/f{n}.csv",
            content=b"x",
            headers={**headers, **file_headers(b"x")},
        ).status_code
    if name == "manage c1":
        return HTTP.put(
            f"{demo}/collections/c1/public", json={"public": False}, headers=headers
        ).status_code
    if name == "read record":
        return HTTP.get(f"{demo}/artifacts", headers=headers).status_code
    if name == "create collection":
        return HTTP.post(
            f"{demo}/collections", json={"name": f"n{n}"}, headers=headers
        ).status_code
    if name == "submit":
        return HTTP.put(
            f"{demo}/collections/inbox/files/s{n}@1",
            content=b"{}",
            headers={**headers, **file_headers(b"{}", {"symposium_submission": True})},
        ).status_code
    if name == "list users":
        return HTTP.get(
            f"{url}/v1/users", params={"community": "demo"}, headers=headers
        ).status_code
    if name == "export":
        return HTTP.get(f"{demo}/export", headers=headers).status_code
    if name == "list communities":
        return HTTP.get(f"{url}/v1/communities", headers=headers).status_code
    raise AssertionError(name)


def as_member(root, server, handle, roles, community="demo") -> Owner:
    owner = Owner(server, handle, community=community)
    r = enroll(root.at(community), owner, community, roles=roles)
    assert r.status_code == 201, r.text
    return owner


def bearer(key: dict) -> dict:
    return {"Authorization": f"Bearer {key['key']}"}


def world(server) -> tuple[dict, str]:
    root, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    steward = steward_of(server)
    made = HTTP.post(
        lyra.url("/collections"), json={"name": "c1"}, headers=lyra.headers()
    )
    assert made.status_code == 201, made.text
    fid = lyra.put("demo", "c1", "a.csv", b"lyra's").json()["file_id"]
    issued = root.invite("ana", SERVER_ADMIN)
    ana = Admin(server, "ana")
    assert ana.register(issued.json()["invite"]).status_code == 201
    create_community(server, root, "other")

    def member(value):
        return [{"role": "community-member", "collections": value}]

    def observer(value):
        return [{"role": "community-observer", "collections": value}]

    actors = {
        "root": root.headers(),
        "server-admin": ana.headers(),
        "community-admin": steward.headers(),
        "gate-keeper": as_member(root, server, "bob", GATE_KEEPER).headers(),
        "member * (owner)": lyra.headers(),
        "member []": as_member(root, server, "mia", member([])).headers(),
        "member [c1]": as_member(root, server, "nova", member(["c1"])).headers(),
        "observer *": as_member(root, server, "olive", observer(EVERY)).headers(),
        "observer [c1]": as_member(root, server, "orion", observer(["c1"])).headers(),
        "member of another community": as_member(
            root, server, "x", member(EVERY), community="other"
        ).headers(),
        "member key [c1]": bearer(lyra.issue("script", roles=member(["c1"]))),
        "non-member key [c1]": bearer(
            lyra.issue("app", roles=observer(["c1"]), non_member=True)
        ),
    }
    return actors, fid


def test_every_role_gets_exactly_the_access_its_grants_give(server):
    actors, fid = world(server)
    assert set(actors) == set(ALLOWED)
    wrong = []
    for actor, headers in actors.items():
        for operation, allowed_status in OPERATIONS.items():
            expected = allowed_status if operation in ALLOWED[actor] else 403
            got = operate(operation, headers, server.url, fid)
            if got != expected:
                wrong.append(f"{actor} / {operation}: {got}, expected {expected}")
    assert not wrong, "\n".join(wrong)


def test_a_caller_without_a_key_reaches_nothing_private(server):
    _, fid = world(server)
    for operation in OPERATIONS:
        assert operate(operation, {}, server.url, fid) == 401, operation


def test_the_roster_names_every_known_handle_to_any_principal(server):
    root, owners = community_with(server, members=("lyra", "vega"))
    issued = root.invite("ana", SERVER_ADMIN)
    assert Admin(server, "ana").register(issued.json()["invite"]).status_code == 201
    observer = as_member(
        root, server, "olive", [{"role": "community-observer", "collections": EVERY}]
    )
    app = owners["lyra"].issue(
        "app",
        roles=[{"role": "community-observer", "collections": EVERY}],
    )
    vega = root.user_id("vega", "demo")
    steward = steward_of(server)
    assert (
        HTTP.delete(
            f"{server.url}/v1/users/{vega}", headers=steward.headers()
        ).status_code
        == 200
    )
    for headers in (observer.headers(), bearer(app)):
        r = HTTP.get(f"{server.url}/v1/demo/roster", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        homed = {e["handle"]: bool(e["removed"]) for e in body["roster"]}
        assert homed["lyra"] is False and homed["vega"] is True
        assert {"olive", "steward"} <= set(homed)
        assert set(body["server_users"]) == {"demo-admin", "ana"}
