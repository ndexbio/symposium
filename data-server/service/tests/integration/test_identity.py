"""Identity: registration, sign-in and session keys, the roster, invites, rotation, rebind and
suspicion."""

import pytest
from conftest import Owner, OwnerKey, enroll, init_admin, invite, psql, set_roster
from harness import HTTP


@pytest.fixture
def community(server):
    """An initialized server with lyra, vega and rigel on the demo roster."""
    admin = init_admin(server)
    set_roster(server, admin, "demo", ["lyra", "vega", "rigel"])
    return server, admin


def test_registration_checks_the_roster_and_duplicates(community):
    server, admin = community
    lyra = Owner(server, "lyra")
    first = enroll(admin, lyra, "demo")
    assert first.status_code == 201, first.text
    assert first.json()["kid"]

    assert Owner(server, "mallory").register("demo").status_code == 403
    assert invite(admin, "demo", "mallory").status_code == 403  # not on the roster
    assert enroll(admin, Owner(server, "lyra"), "demo").status_code == 409
    # identity is per community: a community that does not exist has nobody to register
    nowhere = HTTP.post(
        server.url + "/v1/other/auth/challenge", json={"handle": "lyra"}
    )
    assert nowhere.status_code == 404


def test_registration_requires_proof_of_possession(community):
    server, _ = community
    lyra = Owner(server, "lyra")
    nonce = lyra.challenge()
    imposter = OwnerKey()
    r = HTTP.post(
        server.url + "/v1/demo/owners",
        json={
            "handle": "lyra",
            "public_jwk": lyra.key.jwk,
            "nonce": nonce,
            "signature": imposter.sign(nonce),
        },
    )
    assert r.status_code == 401
    # the challenge was spent by the failed attempt; replaying it with a good signature fails
    r = HTTP.post(
        server.url + "/v1/demo/owners",
        json={
            "handle": "lyra",
            "public_jwk": lyra.key.jwk,
            "nonce": nonce,
            "signature": lyra.key.sign(nonce),
        },
    )
    assert r.status_code == 401


def me(owner, headers=None):
    return HTTP.get(
        owner.url("/me"), headers=owner.headers() if headers is None else headers
    )


def test_sign_in_needs_the_registered_key_and_a_fresh_challenge(community):
    server, admin = community
    lyra = Owner(server, "lyra")
    enroll(admin, lyra, "demo")

    assert lyra.sign_in(key=OwnerKey()).status_code == 401
    nonce = lyra.challenge()
    body = {"handle": "lyra", "nonce": nonce, "signature": lyra.key.sign(nonce)}
    signed_in = HTTP.post(server.url + "/v1/demo/auth/token", json=body)
    assert signed_in.status_code == 200
    session = signed_in.json()
    assert session["key"].startswith("sak_") and len(session["key"]) == 47
    assert session["expires"] and session["kid"]
    assert signed_in.headers["cache-control"] == "no-store"
    assert HTTP.post(server.url + "/v1/demo/auth/token", json=body).status_code == 401

    mine = me(lyra, lyra.headers(session["key"])).json()
    assert mine["handle"] == "lyra" and mine["community"] == "demo"
    assert (mine["kind"], mine["role"], mine["kid"]) == (
        "session",
        "member",
        session["kid"],
    )
    assert mine["grants"] == [
        {"collection": "files", "perm": "read"},
        {"collection": "files", "perm": "write"},
        {"collection": "inbox", "perm": "write"},
        {"collection": "record", "perm": "read"},
    ]

    assert me(lyra, {}).status_code == 401
    for bad in (
        "not-a-key",
        "sak_" + "A" * 43,
        "sdr_" + "A" * 43,
        "eyJhbGciOiJFZERTQSJ9.e30.x",
    ):
        assert me(lyra, {"Authorization": f"Bearer {bad}"}).status_code == 401, bad


def test_a_session_ends_when_it_expires(community):
    server, admin = community
    lyra = Owner(server, "lyra")
    enroll(admin, lyra, "demo")
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


def test_only_the_admin_sets_the_roster(community):
    server, admin = community
    lyra = Owner(server, "lyra")
    enroll(admin, lyra, "demo")
    url = server.url + "/v1/demo/roster"
    assert (
        HTTP.get(url, headers=lyra.headers()).status_code == 200
    )  # any member lists it
    assert HTTP.post(f"{url}/mallory", headers=lyra.headers()).status_code == 403
    assert HTTP.delete(f"{url}/vega", headers=lyra.headers()).status_code == 403
    assert HTTP.post(f"{url}/mallory").status_code == 401
    mine = me(admin).json()
    assert (mine["role"], mine["kind"], mine["handle"]) == (
        "admin",
        "session",
        admin.handle,
    )
    assert mine["grants"] == []


def test_removing_a_member_revokes_membership_but_keeps_identity(community):
    server, admin = community
    vega = Owner(server, "vega")
    assert enroll(admin, vega, "demo").status_code == 201

    session = vega.headers()
    assert me(vega, session).status_code == 200

    result = set_roster(server, admin, "demo", ["lyra", "rigel"])
    assert result["removed"] == ["vega"] and result["added"] == []

    # off the roster, its session ends, and it cannot sign in to act as a Member again
    assert me(vega, session).status_code == 401
    assert Owner(server, "vega").register("demo").status_code == 403
    # R-D6: removal revokes the grants themselves, not just the roster entry
    revoked = server.exec(
        "gosu",
        "postgres",
        "psql",
        "-tA",
        "-d",
        "symposium_data",
        "-c",
        "SELECT count(*) FROM grants WHERE handle = 'vega'",
    ).stdout.strip()
    assert revoked == "0"


def test_key_rotation_retires_the_old_key(community):
    server, admin = community
    lyra = Owner(server, "lyra")
    enroll(admin, lyra, "demo")
    old_session = lyra.session_key()

    new_key = OwnerKey()
    nonce = lyra.challenge()
    r = HTTP.post(
        server.url + "/v1/demo/owners/lyra/keys",
        json={
            "public_jwk": new_key.jwk,
            "nonce": nonce,
            "signature": new_key.sign(nonce),
        },
        headers=lyra.headers(old_session),
    )
    assert r.status_code == 201, r.text

    # the old key's sessions end with it, and it cannot sign in again
    assert me(lyra, lyra.headers(old_session)).status_code == 401
    assert lyra.sign_in().status_code == 401
    rotated = Owner(server, "lyra", key=new_key)
    assert me(rotated).status_code == 200

    rigel = Owner(server, "rigel")
    enroll(admin, rigel, "demo")
    nonce = rigel.challenge()
    other = OwnerKey()
    r = HTTP.post(
        server.url + "/v1/demo/owners/lyra/keys",
        json={"public_jwk": other.jwk, "nonce": nonce, "signature": other.sign(nonce)},
        headers=rigel.headers(),
    )
    assert r.status_code == 403


def suspect_after(server, admin, handle, at):
    return HTTP.put(
        f"{server.url}/v1/demo/owners/{handle}/suspect-after",
        json={"at": at},
        headers=admin.headers(),
    )


def test_suspect_after_is_recorded_and_reported(community):
    server, admin = community
    lyra = Owner(server, "lyra")
    enroll(admin, lyra, "demo")
    flagged = suspect_after(server, admin, "lyra", "2026-10-01T12:00:00+00:00")
    assert flagged.status_code == 200, flagged.text
    assert flagged.json()["suspect_after"].startswith("2026-10-01T12:00:00")
    assert me(lyra).json()["suspect_after"].startswith("2026-10-01T12:00:00")

    assert suspect_after(server, admin, "lyra", "yesterday").status_code == 422
    no_zone = suspect_after(server, admin, "lyra", "2026-10-01T12:00:00")
    assert no_zone.status_code == 400 and "timezone" in no_zone.json()["detail"]
    nobody = suspect_after(server, admin, "nobody", "2026-10-01T12:00:00+00:00")
    assert nobody.status_code == 404


def test_registration_refuses_without_a_valid_invite(community):
    server, admin = community
    lyra_invite = invite(admin, "demo", "lyra").json()["invite"]

    assert Owner(server, "lyra").register("demo").status_code == 403
    assert Owner(server, "vega").register("demo", invite=lyra_invite).status_code == 403
    assert (
        Owner(server, "lyra").register("demo", invite="sdi_forged").status_code == 403
    )
    lyra = Owner(server, "lyra")
    assert lyra.register("demo", invite=lyra_invite).status_code == 201


def test_rebind_retires_keys_and_only_the_fresh_invite_works(community):
    server, admin = community
    first = invite(admin, "demo", "lyra").json()["invite"]
    lyra = Owner(server, "lyra")
    assert lyra.register("demo", invite=first).status_code == 201
    old_headers = lyra.headers()

    rebound = HTTP.post(
        f"{server.url}/v1/demo/owners/lyra/rebind", headers=admin.headers()
    )
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["retired_keys"] == 1
    fresh = rebound.json()["invite"]
    assert me(lyra, old_headers).status_code == 401

    replacement = Owner(server, "lyra")
    assert replacement.register("demo", invite=first).status_code == 403  # spent invite
    assert replacement.register("demo", invite=fresh).status_code == 201
    assert me(replacement).status_code == 200
    nobody = HTTP.post(
        f"{server.url}/v1/demo/owners/mallory/rebind", headers=admin.headers()
    )
    assert nobody.status_code == 404
