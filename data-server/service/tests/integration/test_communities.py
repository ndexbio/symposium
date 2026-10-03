"""Post-M6 stage 1: communities as tenants (R-G8): explicit creation, slug names that are unique
ignoring case, identity per community, and the server-wide admin."""

import httpx
import pytest
from conftest import Owner, create_community, init_admin, set_roster


@pytest.fixture
def admin(server):
    return init_admin(server)


def create(server, admin, name):
    return httpx.post(
        f"{server.url}/v1/communities", json={"name": name}, headers=admin.headers()
    )


def test_the_admin_creates_communities_idempotently(server, admin):
    first = create(server, admin, "comm1")
    assert first.status_code == 201 and first.json() == {
        "name": "comm1",
        "created": True,
    }
    again = create(server, admin, "comm1")
    assert again.status_code == 200 and again.json()["created"] is False
    create(server, admin, "Comm2")

    listed = httpx.get(f"{server.url}/v1/communities", headers=admin.headers()).json()
    assert [c["name"] for c in listed["communities"]] == ["comm1", "Comm2"]
    # the default collections exist from the start, owned by the admin
    for collection in ("inbox", "files", "record"):
        r = httpx.get(
            f"{server.url}/v1/comm1/collections/{collection}/changes",
            headers=admin.headers(),
        )
        assert r.status_code == 200, r.text

    assert (
        httpx.post(f"{server.url}/v1/communities", json={"name": "x"}).status_code
        == 401
    )
    set_roster(server, admin, "comm1", ["lyra"])
    lyra = Owner(server, "lyra")
    assert lyra.register("comm1").status_code == 201
    assert (
        httpx.post(
            f"{server.url}/v1/communities",
            json={"name": "mine"},
            headers=lyra.headers(),
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "name",
    [
        "x" * 21,
        "my comm",
        "my-comm",
        "comm.1",
        "",
        "status",
        "STATUS",
        "Communities",
        "admin",
    ],
)
def test_community_names_must_be_slugs_and_not_reserved(server, admin, name):
    assert create(server, admin, name).status_code == 400


def test_names_are_unique_and_matched_ignoring_case(server, admin):
    assert create(server, admin, "x" * 20).status_code == 201  # the longest slug
    assert create(server, admin, "Comm1").status_code == 201
    clash = create(server, admin, "comm1")
    assert clash.status_code == 400 and "already exists" in clash.json()["detail"]

    set_roster(server, admin, "Comm1", ["lyra"])
    lyra = Owner(server, "lyra", community="COMM1")  # any case reaches Comm1
    assert lyra.register("COMM1").status_code == 201
    me = httpx.get(lyra.url("/whoami"), headers=lyra.headers()).json()
    assert me["community"] == "Comm1"

    for path in ("my-comm", "x" * 21, "nowhere"):
        r = httpx.get(f"{server.url}/v1/{path}/whoami", headers=admin.headers())
        assert r.status_code == 404, path


def test_one_handle_is_an_independent_identity_in_each_community(server, admin):
    set_roster(server, admin, "comm1", ["lyra"])
    set_roster(server, admin, "comm2", ["lyra"])
    lyra1 = Owner(server, "lyra")
    lyra2 = Owner(server, "lyra")  # another key: a different person, perhaps
    assert lyra1.register("comm1").status_code == 201
    assert lyra2.register("comm2").status_code == 201

    # each key signs in only to its own community, and each token works only there
    assert Owner(server, "lyra", lyra1.key, "comm2").token_response().status_code == 401
    assert Owner(server, "lyra", lyra2.key, "comm1").token_response().status_code == 401
    wrong = httpx.get(f"{server.url}/v1/comm2/whoami", headers=lyra1.headers())
    assert wrong.status_code == 401

    fid = lyra1.put("comm1", "files", "a.csv", b"comm1 data").json()["file_id"]
    assert lyra2.get(fid).status_code == 404  # not a file of comm2


def test_the_admin_is_server_wide_and_never_a_member(server, admin):
    create_community(server, admin, "comm1")
    create_community(server, admin, "comm2")
    for community in ("comm1", "comm2"):
        me = httpx.get(
            f"{server.url}/v1/{community}/whoami", headers=admin.headers()
        ).json()
        assert me["admin"] is True and me["community"] == community

    refused = httpx.put(
        f"{server.url}/v1/comm1/roster",
        json={"handles": ["lyra", "demo-admin"]},
        headers=admin.headers(),
    )
    assert refused.status_code == 400 and "admin's handle" in refused.json()["detail"]


def test_the_admins_own_writes_are_exempt_from_quota(make_server):
    server = make_server(SYMPOSIUM_DATA_QUOTA_BYTES="10")
    admin = init_admin(server)
    set_roster(server, admin, "comm1", ["lyra"])
    lyra = Owner(server, "lyra")
    lyra.register("comm1")
    assert lyra.put("comm1", "files", "big.bin", b"x" * 100).status_code == 413
    assert (
        admin.at("comm1").put("comm1", "files", "big.bin", b"x" * 100).status_code
        == 201
    )
