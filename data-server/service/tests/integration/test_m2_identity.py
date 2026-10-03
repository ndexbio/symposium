"""M2: identity: registration, tokens, the roster, invites, rotation, rebind and suspicion."""

import json
import time

import httpx
import pytest
from conftest import Owner, OwnerKey, init_admin, set_roster


@pytest.fixture
def community(server):
    """An initialized open-mode server with lyra, vega and rigel on the demo roster."""
    admin = init_admin(server)
    set_roster(server, admin, "demo", ["lyra", "vega", "rigel"])
    return server, admin


def test_registration_is_refused_with_503_before_init(server):
    # registration starts with a challenge, and that already answers 503
    r = httpx.post(server.url + "/v1/demo/auth/challenge", json={"handle": "lyra"})
    assert r.status_code == 503, r.text


def test_open_registration_checks_the_roster_and_duplicates(community):
    server, _ = community
    lyra = Owner(server, "lyra")
    first = lyra.register("demo")
    assert first.status_code == 201, first.text
    assert first.json()["kid"]

    assert Owner(server, "mallory").register("demo").status_code == 403
    assert Owner(server, "lyra").register("demo").status_code == 409
    # identity is per community: a community that does not exist has nobody to register
    nowhere = httpx.post(
        server.url + "/v1/other/auth/challenge", json={"handle": "lyra"}
    )
    assert nowhere.status_code == 404


def test_registration_requires_proof_of_possession(community):
    server, _ = community
    lyra = Owner(server, "lyra")
    nonce = lyra.challenge()
    imposter = OwnerKey()
    r = httpx.post(
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
    r = httpx.post(
        server.url + "/v1/demo/owners",
        json={
            "handle": "lyra",
            "public_jwk": lyra.key.jwk,
            "nonce": nonce,
            "signature": lyra.key.sign(nonce),
        },
    )
    assert r.status_code == 401


def test_tokens_need_the_registered_key_and_a_fresh_challenge(community):
    server, _ = community
    lyra = Owner(server, "lyra")
    lyra.register("demo")

    assert lyra.token_response(key=OwnerKey()).status_code == 401
    nonce = lyra.challenge()
    body = {"handle": "lyra", "nonce": nonce, "signature": lyra.key.sign(nonce)}
    assert httpx.post(server.url + "/v1/demo/auth/token", json=body).status_code == 200
    assert httpx.post(server.url + "/v1/demo/auth/token", json=body).status_code == 401

    me = httpx.get(lyra.url("/whoami"), headers=lyra.headers()).json()
    assert me["handle"] == "lyra" and me["community"] == "demo"
    assert me["admin"] is False
    assert me["grants"] == [
        {"collection": "files", "perm": "read"},
        {"collection": "files", "perm": "write"},
        {"collection": "inbox", "perm": "write"},
        {"collection": "record", "perm": "read"},
    ]

    assert httpx.get(lyra.url("/whoami")).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert httpx.get(lyra.url("/whoami"), headers=bad).status_code == 401


def test_only_the_admin_sets_the_roster(community):
    server, admin = community
    lyra = Owner(server, "lyra")
    lyra.register("demo")
    url = server.url + "/v1/demo/roster"
    assert (
        httpx.put(url, json={"handles": ["lyra"]}, headers=lyra.headers()).status_code
        == 403
    )
    assert httpx.put(url, json={"handles": ["lyra"]}).status_code == 401
    assert httpx.get(admin.url("/whoami"), headers=admin.headers()).json()["admin"]


def test_removing_a_member_revokes_membership_but_keeps_identity(community):
    server, admin = community
    vega = Owner(server, "vega")
    assert vega.register("demo").status_code == 201

    result = set_roster(server, admin, "demo", ["lyra", "rigel"])
    assert result["removed"] == ["vega"] and result["added"] == []

    me = httpx.get(vega.url("/whoami"), headers=vega.headers()).json()
    assert me["handle"] == "vega" and me["grants"] == []
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
    server, _ = community
    lyra = Owner(server, "lyra")
    lyra.register("demo")
    old_token = lyra.token()

    new_key = OwnerKey()
    nonce = lyra.challenge()
    r = httpx.post(
        server.url + "/v1/demo/owners/lyra/keys",
        json={
            "public_jwk": new_key.jwk,
            "nonce": nonce,
            "signature": new_key.sign(nonce),
        },
        headers=lyra.headers(old_token),
    )
    assert r.status_code == 201, r.text

    assert (
        httpx.get(lyra.url("/whoami"), headers=lyra.headers(old_token)).status_code
        == 401
    )
    assert lyra.token_response().status_code == 401  # the old key cannot sign in
    rotated = Owner(server, "lyra", key=new_key)
    assert (
        httpx.get(rotated.url("/whoami"), headers=rotated.headers()).status_code == 200
    )

    rigel = Owner(server, "rigel")
    rigel.register("demo")
    nonce = rigel.challenge()
    other = OwnerKey()
    r = httpx.post(
        server.url + "/v1/demo/owners/lyra/keys",
        json={"public_jwk": other.jwk, "nonce": nonce, "signature": other.sign(nonce)},
        headers=rigel.headers(),
    )
    assert r.status_code == 403


def test_suspect_after_is_recorded_and_reported(community):
    server, _ = community
    lyra = Owner(server, "lyra")
    lyra.register("demo")
    result = server.admin(
        "suspect-after",
        "--community",
        "demo",
        "--handle",
        "lyra",
        "--at",
        "2026-10-01T12:00:00+00:00",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    me = httpx.get(lyra.url("/whoami"), headers=lyra.headers()).json()
    assert me["suspect_after"].startswith("2026-10-01T12:00:00")

    assert (
        server.admin(
            "suspect-after",
            "--community",
            "demo",
            "--handle",
            "lyra",
            "--at",
            "yesterday",
        ).returncode
        == 1
    )
    assert (
        server.admin(
            "suspect-after",
            "--community",
            "demo",
            "--handle",
            "lyra",
            "--at",
            "2026-10-01T12:00:00",
        ).returncode
        == 1
    )
    assert (
        server.admin(
            "suspect-after",
            "--community",
            "demo",
            "--handle",
            "nobody",
            "--at",
            "2026-10-01T12:00:00+00:00",
        ).returncode
        == 2
    )


def test_tokens_expire(make_server):
    server = make_server(SYMPOSIUM_DATA_TOKEN_TTL="2")
    admin = init_admin(server)
    token = admin.token()
    url = server.url + "/v1/communities"
    assert httpx.get(url, headers=admin.headers(token)).status_code == 200
    time.sleep(3)
    assert httpx.get(url, headers=admin.headers(token)).status_code == 401


@pytest.fixture
def invite_server(make_server):
    server = make_server(
        SYMPOSIUM_DATA_REGISTRATION="invite",
        SYMPOSIUM_DATA_PUBLIC_BASE_URL="https://data.example.org",
    )
    admin = init_admin(server)
    set_roster(server, admin, "demo", ["lyra", "vega"])
    return server


def mint(server, handle, *extra):
    result = server.admin("invite", "--community", "demo", "--handle", handle, *extra)
    assert result.returncode == 0, result.stdout + result.stderr
    invite = result.stdout.strip()
    assert invite.startswith("sdi_") and "\n" not in invite
    return invite


def test_invite_mode_refuses_without_a_valid_invite(invite_server):
    server = invite_server
    lyra_invite = mint(server, "lyra")

    assert Owner(server, "lyra").register("demo").status_code == 403
    assert Owner(server, "vega").register("demo", invite=lyra_invite).status_code == 403
    assert (
        Owner(server, "lyra").register("demo", invite="sdi_forged").status_code == 403
    )

    lyra = Owner(server, "lyra")
    assert lyra.register("demo", invite=lyra_invite).status_code == 201

    # a member not on the roster cannot be invited at all
    assert (
        server.admin("invite", "--community", "demo", "--handle", "mallory").returncode
        == 2
    )


def test_expired_invite_is_refused(invite_server):
    stale = mint(invite_server, "vega", "--hours", "0")
    assert (
        Owner(invite_server, "vega").register("demo", invite=stale).status_code == 403
    )


def test_rebind_retires_keys_and_only_the_fresh_invite_works(invite_server):
    server = invite_server
    first = mint(server, "lyra")
    assert Owner(server, "lyra").register("demo", invite=first).status_code == 201

    rebound = server.admin("rebind-key", "--community", "demo", "--handle", "lyra")
    assert rebound.returncode == 0, rebound.stdout + rebound.stderr
    assert json.loads(rebound.stderr.strip().splitlines()[-1])["retired_keys"] == 1
    fresh = rebound.stdout.strip()

    replacement = Owner(server, "lyra")
    assert replacement.register("demo", invite=first).status_code == 403  # spent invite
    assert replacement.register("demo", invite=fresh).status_code == 201
    assert (
        httpx.get(replacement.url("/whoami"), headers=replacement.headers()).status_code
        == 200
    )
