"""Communities as tenants (R-G8): explicit creation with a first community admin, slug names
that are unique ignoring case, users homed in one community each, and server-level users that
work in every community."""

import pytest
from conftest import (
    Owner,
    create_community,
    enroll,
    init_admin,
    set_quota,
)
from harness import HTTP


@pytest.fixture
def admin(server):
    return init_admin(server)


def create(server, admin, name, steward="steward"):
    return HTTP.post(
        f"{server.url}/v1/communities",
        json={"name": name, "admin": steward},
        headers=admin.headers(),
    )


def test_a_server_admin_creates_communities_idempotently(server, admin):
    first = create(server, admin, "comm1")
    assert first.status_code == 201 and first.json()["created"] is True
    invite = first.json()["admin_invite"]
    assert invite["handle"] == "steward" and invite["community"] == "comm1"
    assert invite["roles"] == [{"role": "community-admin", "collections": None}]
    again = create(server, admin, "comm1")
    assert again.status_code == 200 and again.json() == {
        "name": "comm1",
        "created": False,
    }
    create(server, admin, "Comm2")

    listed = HTTP.get(f"{server.url}/v1/communities", headers=admin.headers()).json()
    assert [c["name"] for c in listed["communities"]] == ["comm1", "Comm2"]
    # the default collections exist from the start
    for collection in ("inbox", "files", "record"):
        r = HTTP.get(
            f"{server.url}/v1/communities/comm1/collections/{collection}/changes",
            headers=admin.headers(),
        )
        assert r.status_code == 200, r.text

    no_admin = HTTP.post(
        f"{server.url}/v1/communities", json={"name": "x"}, headers=admin.headers()
    )
    assert no_admin.status_code == 422
    assert (
        HTTP.post(f"{server.url}/v1/communities", json={"name": "x", "admin": "a"})
    ).status_code == 401
    lyra = Owner(server, "lyra", community="comm1")
    assert enroll(admin.at("comm1"), lyra, "comm1").status_code == 201
    mine = HTTP.post(
        f"{server.url}/v1/communities",
        json={"name": "mine", "admin": "lyra"},
        headers=lyra.headers(),
    )
    assert mine.status_code == 403


@pytest.mark.parametrize(
    "name",
    [
        "x" * 21,
        "my comm",
        "my-comm",
        "comm.1",
        "",
    ],
)
def test_community_names_must_be_slugs(server, admin, name):
    assert create(server, admin, name).status_code == 400


def test_any_slug_names_a_community_route_words_included(server, admin):
    """No server-wide route shares a community's path segment, so every slug is free."""
    for name in ("status", "users", "invites"):
        assert create(server, admin, name).status_code == 201, name
    assert HTTP.get(f"{server.url}/v1/status").json()["mode"] == "operational"


def test_names_are_unique_and_matched_ignoring_case(server, admin):
    assert create(server, admin, "x" * 20).status_code == 201  # the longest slug
    assert create(server, admin, "Comm1").status_code == 201
    clash = create(server, admin, "comm1")
    assert clash.status_code == 400 and "already exists" in clash.json()["detail"]

    lyra = Owner(server, "lyra", community="Comm1")
    assert enroll(admin.at("Comm1"), lyra, "Comm1").status_code == 201
    lyra.community = "COMM1"  # any case reaches Comm1
    me = HTTP.get(lyra.server.url + "/v1/me", headers=lyra.headers()).json()
    assert me["community"] == "Comm1"

    for path in ("my-comm", "x" * 21, "nowhere"):
        r = HTTP.get(f"{server.url}/v1/{path}/me", headers=admin.headers())
        assert r.status_code == 404, path


def test_one_handle_is_an_independent_user_in_each_community(server, admin):
    create_community(server, admin, "comm1")
    create_community(server, admin, "comm2")
    lyra1 = Owner(server, "lyra", community="comm1")
    lyra2 = Owner(server, "lyra", community="comm2")  # another key: a different person
    assert enroll(admin.at("comm1"), lyra1, "comm1").status_code == 201
    assert enroll(admin.at("comm2"), lyra2, "comm2").status_code == 201

    # each key signs in only to its own community, and each session works only there
    assert Owner(server, "lyra", lyra1.key, "comm2").sign_in().status_code == 401
    assert Owner(server, "lyra", lyra2.key, "comm1").sign_in().status_code == 401
    wrong = HTTP.get(
        f"{server.url}/v1/communities/comm2/collections", headers=lyra1.headers()
    )
    assert wrong.status_code == 403 and "belongs to comm1" in wrong.json()["detail"]
    me = HTTP.get(f"{server.url}/v1/me", headers=lyra1.headers()).json()
    assert me["community"] == "comm1"  # the caller's own community

    fid = lyra1.put("comm1", "files", "a.csv", b"comm1 data").json()["file_id"]
    lyra2.community = "comm2"
    assert lyra2.get(fid).status_code == 404  # not a file of comm2


def test_a_server_level_user_works_in_every_community_and_on_no_roster(server, admin):
    create_community(server, admin, "comm1")
    create_community(server, admin, "comm2")
    me = HTTP.get(f"{server.url}/v1/me", headers=admin.headers()).json()
    assert me["community"] is None and me["context"]["community"] is None
    assert {"communities", "delegate"} <= set(me["context"]["grants"])
    for community in ("comm1", "comm2"):
        roster = HTTP.get(
            f"{server.url}/v1/communities/{community}/users", headers=admin.headers()
        ).json()
        assert roster["server_users"] == ["demo-admin"]
        assert "demo-admin" not in [r["handle"] for r in roster["users"]]
    clash = admin.invite(
        "demo-admin",
        [{"role": "community-member", "collections": ["*"]}],
        community="comm1",
    )
    assert clash.status_code == 409 and "server-level" in clash.json()["detail"]


def test_a_holder_of_communities_writes_without_quota(server, admin):
    set_quota(server, 10)
    create_community(server, admin, "comm1")
    lyra = Owner(server, "lyra", community="comm1")
    enroll(admin.at("comm1"), lyra, "comm1")
    assert lyra.put("comm1", "files", "big.bin", b"x" * 100).status_code == 413
    assert (
        admin.at("comm1").put("comm1", "files", "big.bin", b"x" * 100).status_code
        == 201
    )
