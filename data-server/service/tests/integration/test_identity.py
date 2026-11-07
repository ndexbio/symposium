"""Identity: joining with an invite and a proof of possession, signing in, sessions, key rotation
and suspicion. Every user signs in the same way; its home says where."""

import pytest
from conftest import (
    EVERY,
    Owner,
    OwnerKey,
    community_with,
    create_community,
    enroll,
    init_root,
    invite,
    psql,
)
from harness import HTTP


@pytest.fixture
def community(server):
    root = init_root(server)
    create_community(server, root, "demo")
    return server, root


def me(owner, headers=None):
    return HTTP.get(
        owner.server.url + "/v1/me",
        headers=owner.headers() if headers is None else headers,
    )


def test_joining_requires_proof_of_possession(community):
    server, root = community
    lyra = Owner(server, "lyra")
    secret = invite(root, "demo", "lyra").json()["invite"]
    nonce = lyra.challenge()
    body = {
        "handle": "lyra",
        "public_jwk": lyra.key.jwk,
        "nonce": nonce,
        "signature": OwnerKey().sign(nonce),
        "invite": secret,
    }
    assert HTTP.post(server.url + "/v1/registrations", json=body).status_code == 401
    # the challenge was spent by the failed attempt; replaying it with a good signature fails
    body["signature"] = lyra.key.sign(nonce)
    assert HTTP.post(server.url + "/v1/registrations", json=body).status_code == 401
    # the invite was not spent: a fresh challenge joins
    assert lyra.register(secret).status_code == 201


def test_sign_in_needs_the_registered_key_and_a_fresh_challenge(community):
    server, root = community
    lyra = Owner(server, "lyra")
    enroll(root, lyra, "demo")

    assert lyra.sign_in(key=OwnerKey()).status_code == 401
    nonce = lyra.challenge()
    body = {
        "handle": "lyra",
        "community": "demo",
        "nonce": nonce,
        "signature": lyra.key.sign(nonce),
    }
    signed_in = HTTP.post(server.url + "/v1/sessions", json=body)
    assert signed_in.status_code == 200
    session = signed_in.json()
    assert session["key"].startswith("sak_") and len(session["key"]) == 47
    assert session["expires"] and session["kid"]
    assert signed_in.headers["cache-control"] == "no-store"
    assert HTTP.post(server.url + "/v1/sessions", json=body).status_code == 401

    mine = me(lyra, lyra.headers(session["key"])).json()
    assert mine["handle"] == "lyra" and mine["community"] == "demo"
    assert (mine["kind"], mine["kid"]) == ("session", session["kid"])
    assert mine["roles"] == [{"role": "community-member", "collections": EVERY}]
    assert mine["context"]["community"] == "demo" and mine["context"]["via_session"]
    assert mine["context"]["grants"] == {
        "manage": [],
        "publish": None,
        "read": EVERY,
        "write": EVERY,
    }

    assert me(lyra, {}).status_code == 401
    for bad in ("not-a-key", "sak_" + "A" * 43, "eyJhbGciOiJFZERTQSJ9.e30.x"):
        assert me(lyra, {"Authorization": f"Bearer {bad}"}).status_code == 401, bad


def test_a_session_ends_when_it_expires(community):
    server, root = community
    lyra = Owner(server, "lyra")
    enroll(root, lyra, "demo")
    session = lyra.session_key()
    assert me(lyra, lyra.headers(session)).status_code == 200
    lyras = "kind = 'session' AND handle = 'lyra'"
    psql(
        server,
        f"UPDATE api_keys SET expires = now() - interval '1 second' WHERE {lyras}",
    )
    assert me(lyra, lyra.headers(session)).status_code == 401
    assert psql(server, f"SELECT count(*) FROM api_keys WHERE {lyras}") != "0"
    server.sweep()  # the janitor deletes ended sessions
    assert psql(server, f"SELECT count(*) FROM api_keys WHERE {lyras}") == "0"


def test_key_rotation_retires_the_old_key(community):
    server, root = community
    lyra = Owner(server, "lyra")
    enroll(root, lyra, "demo")
    old_session = lyra.session_key()

    new_key = OwnerKey()
    nonce = lyra.challenge()
    rotate = {
        "public_jwk": new_key.jwk,
        "nonce": nonce,
        "signature": new_key.sign(nonce),
    }
    r = HTTP.post(
        server.url + "/v1/me/keys", json=rotate, headers=lyra.headers(old_session)
    )
    assert r.status_code == 200, r.text  # the key is replaced

    # the old key's sessions end with it, and it cannot sign in again
    assert me(lyra, lyra.headers(old_session)).status_code == 401
    assert lyra.sign_in().status_code == 401
    rotated = Owner(server, "lyra", key=new_key)
    assert me(rotated).status_code == 200
    # an issued key cannot rotate a user's key
    issued = rotated.issue("notebook")
    nonce = rotated.challenge()
    other = OwnerKey()
    r = HTTP.post(
        server.url + "/v1/me/keys",
        json={"public_jwk": other.jwk, "nonce": nonce, "signature": other.sign(nonce)},
        headers=rotated.headers(issued["key"]),
    )
    assert r.status_code == 403


def test_suspect_after_is_recorded_and_reported(server):
    root, owners = community_with(server, members=("lyra",))
    lyra = owners["lyra"]
    user = root.user_url("lyra", "demo")
    at = "2026-10-01T12:00:00+00:00"
    flagged = HTTP.patch(
        user,
        json={"suspect_after": at},
        headers=root.headers(),
    )
    assert flagged.status_code == 200, flagged.text
    assert flagged.json()["suspect_after"].startswith("2026-10-01T12:00:00")
    assert me(lyra).json()["suspect_after"].startswith("2026-10-01T12:00:00")
    naive = HTTP.patch(
        user,
        json={"suspect_after": "2026-10-01T12:00:00"},
        headers=root.headers(),
    )
    assert naive.status_code == 400
    refused = HTTP.patch(
        user,
        json={"suspect_after": at},
        headers=lyra.headers(),
    )
    assert refused.status_code == 403


def test_a_server_level_user_signs_in_without_a_community(community):
    server, root = community
    session = root.sign_in()
    assert session.status_code == 200
    as_member = Owner(server, root.handle, key=root.key, community="demo")
    assert as_member.sign_in().status_code == 401  # no such user homed in demo
