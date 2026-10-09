"""Every admin operation is an admin-only route (R-D7). Without a token each
answers 401; a member's token or a read key gets 403."""

import httpx
from conftest import community_with

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
    httpx.post(
        f"{server.url}/v1/demo/collections",
        json={"name": "project"},
        headers=lyra.headers(),
    )
    read_key = httpx.post(
        f"{server.url}/v1/demo/collections/project/keys",
        json={"label": "reviewer"},
        headers=lyra.headers(),
    ).json()["key"]

    callers = {
        "no token": ({}, 401),
        "a member": (lyra.headers(), 403),
        "a read key": ({"Authorization": f"Bearer {read_key}"}, 403),
    }
    for method, path, body in ROUTES:
        url = server.url + path.format(file_id=file_id)
        for who, (headers, expected) in callers.items():
            r = httpx.request(method, url, json=body, headers=headers)
            assert r.status_code == expected, (method, path, who, r.text)

    # nothing changed: the roster, the file and the community list are as they were
    roster = httpx.get(f"{server.url}/v1/demo/roster", headers=admin.headers()).json()
    assert [m["handle"] for m in roster["roster"]] == ["lyra"]
    assert lyra.get(file_id).content == b"1,2"
