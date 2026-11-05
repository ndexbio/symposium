"""Invites: the server stores an invite's home and roles and applies them when the invitee
joins; the file carries a secret and nothing to tamper with. Single use, expiry, revocation,
re-issue, rebind, and the authority to create one."""

import pytest
from conftest import (
    EVERY,
    Owner,
    OwnerKey,
    community_with,
    create_community,
    init_admin,
    invite,
    psql,
    steward_of,
)
from harness import HTTP

MEMBER = [{"role": "community-member", "collections": EVERY}]
OBSERVER = [{"role": "community-observer", "collections": EVERY}]


@pytest.fixture
def demo(server):
    admin = init_admin(server)
    create_community(server, admin, "demo")
    return server, admin


def roles_of(owner):
    return HTTP.get(owner.url("/me"), headers=owner.headers()).json()["roles"]


def test_joining_applies_exactly_the_roles_the_server_stored(demo):
    server, admin = demo
    issued = invite(admin, "demo", "olive", roles=OBSERVER)
    assert issued.status_code == 201, issued.text
    body = issued.json()
    assert body["roles"] == OBSERVER and body["community"] == "demo"
    assert body["invite"].startswith("sdi_")
    olive = Owner(server, "olive")
    joined = olive.register(body["invite"])
    assert joined.status_code == 201, joined.text
    assert joined.json()["roles"] == OBSERVER
    assert roles_of(olive) == OBSERVER


def test_a_redemption_naming_roles_or_a_home_is_refused(demo):
    server, admin = demo
    secret = invite(admin, "demo", "olive", roles=OBSERVER).json()["invite"]
    olive = Owner(server, "olive")
    assert olive.register(secret, roles=MEMBER).status_code == 400
    assert olive.register(secret, community="other").status_code == 400
    joined = olive.register(secret)
    assert joined.status_code == 201 and joined.json()["roles"] == OBSERVER


def test_an_invite_works_once_for_its_own_handle(demo):
    server, admin = demo
    secret = invite(admin, "demo", "lyra").json()["invite"]
    assert Owner(server, "vega").register(secret).status_code == 403  # edited handle
    assert Owner(server, "lyra").register("sdi_" + "A" * 43).status_code == 403
    assert Owner(server, "lyra").register(secret).status_code == 201
    assert Owner(server, "lyra", OwnerKey()).register(secret).status_code == 403
    assert (
        psql(server, "SELECT count(secret) FROM invites WHERE handle = 'lyra'") == "0"
    )


def test_an_expired_or_replaced_invite_is_refused(demo):
    server, admin = demo
    first = invite(admin, "demo", "lyra").json()["invite"]
    second = invite(admin, "demo", "lyra").json()["invite"]
    assert (
        Owner(server, "lyra").register(first).status_code == 403
    )  # revoked by the second
    psql(server, "UPDATE invites SET expires = now() - interval '1 second'")
    assert Owner(server, "lyra").register(second).status_code == 403
    server.sweep()
    assert psql(server, "SELECT count(secret) FROM invites") == "0"


def test_pending_invites_are_listed_with_their_roles_until_used(demo):
    server, admin = demo
    invite(admin, "demo", "lyra")
    invite(admin, "demo", "olive", roles=OBSERVER)
    listed = HTTP.get(
        f"{server.url}/v1/invites",
        params={"community": "demo"},
        headers=admin.headers(),
    ).json()["invites"]
    handles = {i["handle"]: i for i in listed}
    assert set(handles) == {"lyra", "olive", "steward"}
    assert handles["olive"]["roles"] == OBSERVER and handles["olive"]["invite"]
    Owner(server, "lyra").register(handles["lyra"]["invite"])
    again = HTTP.get(
        f"{server.url}/v1/invites",
        params={"community": "demo"},
        headers=admin.headers(),
    ).json()["invites"]
    assert {i["handle"] for i in again} == {"olive", "steward"}


def test_a_missing_collection_value_is_refused(demo):
    _, admin = demo
    bare = invite(admin, "demo", "lyra", roles=[{"role": "community-member"}])
    assert bare.status_code == 400
    extra = invite(
        admin, "demo", "lyra", roles=[{"role": "gate-keeper", "collections": []}]
    )
    assert extra.status_code == 400


def test_creating_an_invite_takes_the_authority_to_assign_its_roles(server):
    admin, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    steward = steward_of(server)
    assert invite(lyra, "demo", "mallory").status_code == 403  # members
    assert invite(steward, "demo", "mallory").status_code == 201
    server_admin = [{"role": "server-admin", "collections": None}]
    assert steward.invite("ana", server_admin).status_code == 403  # delegate
    assert admin.invite("ana", server_admin).status_code == 201
    root = [{"role": "server-root", "collections": None}]
    assert admin.invite("eve", root).status_code == 403  # never assignable
    # a homed caller invites into its own community only
    create_community(server, admin, "other")
    assert invite(steward, "other", "mallory").status_code == 403


def test_rebind_retires_keys_and_only_the_fresh_invite_works(server):
    admin, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    old_session = lyra.session_key()
    user = admin.user_id("lyra", "demo")
    rebound = HTTP.post(f"{server.url}/v1/users/{user}/rebind", headers=admin.headers())
    assert rebound.status_code == 201, rebound.text
    assert rebound.json()["retired_keys"] == 1
    assert (
        HTTP.get(lyra.url("/me"), headers=lyra.headers(old_session)).status_code == 401
    )
    assert lyra.sign_in().status_code == 401
    fresh = Owner(server, "lyra", OwnerKey())
    assert fresh.register(rebound.json()["invite"]).status_code == 201
    assert roles_of(fresh) == MEMBER  # its roles are as they were


def test_a_ported_author_claims_its_handle_by_invite(demo):
    server, admin = demo
    psql(
        server,
        "INSERT INTO users (handle, home) VALUES ('author', 'demo'); "
        "INSERT INTO role_assignments (user_id, role_id, collections, created_by) "
        "SELECT id, 'community-member', '{*}', 'port' FROM users WHERE handle = 'author'",
    )
    secret = invite(admin, "demo", "author").json()["invite"]
    author = Owner(server, "author")
    assert author.register(secret).status_code == 201
    assert roles_of(author) == MEMBER
    assert invite(admin, "demo", "author").status_code == 409
