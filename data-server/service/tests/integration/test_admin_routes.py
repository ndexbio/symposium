"""Every admin operation is an admin-only route (R-D7). Without a key each answers 401; a
Member's session or issued key, a non-member key, and an admin key that is not the admin's
session all get 403."""

from conftest import community_with
from harness import HTTP

ROUTES = [
    ("POST", "/v1/communities", {"name": "other"}),
    ("GET", "/v1/communities", None),
    ("POST", "/v1/communities/import", None),
    ("POST", "/v1/demo/roster/vega", None),
    ("DELETE", "/v1/demo/roster/lyra", None),
    ("POST", "/v1/demo/invites", {"handle": "lyra"}),
    ("GET", "/v1/demo/invites", None),
    ("POST", "/v1/demo/owners/lyra/rebind", None),
    ("PUT", "/v1/demo/owners/lyra/suspect-after", {"at": "2026-10-01T12:00:00+00:00"}),
    ("POST", "/v1/demo/files/{file_id}/v/1/purge", None),
    ("GET", "/v1/demo/export", None),
]


def test_every_admin_route_refuses_everyone_but_the_admin(server):
    admin, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    file_id = lyra.put("demo", "files", "data.csv", b"1,2").json()["file_id"]
    HTTP.post(
        f"{server.url}/v1/demo/collections",
        json={"name": "project"},
        headers=lyra.headers(),
    )
    member_key = lyra.issue("notebook")["key"]
    app_key = lyra.issue("dashboard", role="non-member")["key"]
    admins_app_key = admin.issue("admin's app", role="non-member")["key"]

    callers = {
        "no key": ({}, 401),
        "a member's session": (lyra.headers(), 403),
        "a member key": ({"Authorization": f"Bearer {member_key}"}, 403),
        "a non-member key": ({"Authorization": f"Bearer {app_key}"}, 403),
        "a key the admin issued": ({"Authorization": f"Bearer {admins_app_key}"}, 403),
    }
    for method, path, body in ROUTES:
        url = server.url + path.format(file_id=file_id)
        for who, (headers, expected) in callers.items():
            r = HTTP.request(method, url, json=body, headers=headers)
            assert r.status_code == expected, (method, path, who, r.text)

    # nothing changed: the roster, the file and the community list are as they were
    roster = HTTP.get(f"{server.url}/v1/demo/roster", headers=admin.headers()).json()
    assert [m["handle"] for m in roster["roster"]] == ["lyra"]
    assert lyra.get(file_id).content == b"1,2"
