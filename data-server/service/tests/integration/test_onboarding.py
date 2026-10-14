"""Onboarding (R-D5, R-D6): the roster one handle at a time, retrievable
pending invites, and registration by invite only."""

import pytest
from conftest import (
    Owner,
    create_community,
    enroll,
    init_admin,
    invite,
    psql,
    set_roster,
)
from harness import HTTP


@pytest.fixture
def demo(server):
    admin = init_admin(server)
    create_community(server, admin, "demo")
    return server, admin


def roster_url(server, handle=""):
    return f"{server.url}/v1/demo/roster" + (f"/{handle}" if handle else "")


def roster(server, admin) -> dict:
    r = HTTP.get(roster_url(server), headers=admin.headers())
    assert r.status_code == 200, r.text
    return {m["handle"]: m for m in r.json()["roster"]}


def pending(server, admin) -> dict:
    r = HTTP.get(f"{server.url}/v1/demo/invites", headers=admin.headers())
    assert r.status_code == 200, r.text
    return {i["handle"]: i for i in r.json()["invites"]}


def test_the_roster_changes_one_handle_at_a_time(demo):
    server, admin = demo
    first = HTTP.post(roster_url(server, "lyra"), headers=admin.headers())
    assert first.status_code == 201 and first.json()["added"] is True
    again = HTTP.post(roster_url(server, "lyra"), headers=admin.headers())
    assert again.status_code == 200 and again.json()["added"] is False
    HTTP.post(roster_url(server, "vega"), headers=admin.headers())
    assert sorted(roster(server, admin)) == ["lyra", "vega"]  # adding never removes

    refused = HTTP.post(roster_url(server, "demo-admin"), headers=admin.headers())
    assert refused.status_code == 400 and "admin's handle" in refused.json()["detail"]

    assert (
        HTTP.delete(roster_url(server, "vega"), headers=admin.headers()).status_code
        == 200
    )
    assert (
        HTTP.delete(roster_url(server, "vega"), headers=admin.headers()).status_code
        == 404
    )
    assert sorted(roster(server, admin)) == ["lyra"]
    grants = psql(server, "SELECT count(*) FROM grants WHERE handle = 'vega'")
    assert grants == "0"


def test_the_roster_reports_registration_and_pending_invites(demo):
    server, admin = demo
    for handle in ("lyra", "vega"):
        HTTP.post(roster_url(server, handle), headers=admin.headers())
    assert roster(server, admin)["lyra"] == {
        "handle": "lyra",
        "registered": False,
        "invite_expires": None,
    }

    issued = invite(admin, "demo", "lyra")
    assert issued.status_code == 201
    body = issued.json()
    assert body["handle"] == "lyra" and body["invite"].startswith("sdi_")
    assert roster(server, admin)["lyra"]["invite_expires"] == body["expires"]

    lyra = Owner(server, "lyra")
    assert lyra.register("demo", invite=body["invite"]).status_code == 201
    after = roster(server, admin)["lyra"]
    assert after["registered"] is True and after["invite_expires"] is None
    assert roster(server, admin)["vega"]["registered"] is False


def test_pending_invites_are_retrievable_until_used_or_revoked(demo):
    server, admin = demo
    for handle in ("lyra", "vega", "rigel"):
        HTTP.post(roster_url(server, handle), headers=admin.headers())
    lyra_invite = invite(admin, "demo", "lyra").json()["invite"]
    vega_first = invite(admin, "demo", "vega").json()["invite"]
    vega_second = invite(admin, "demo", "vega").json()["invite"]  # revokes the first
    rigel_invite = invite(admin, "demo", "rigel").json()["invite"]

    listed = pending(server, admin)
    assert {h: i["invite"] for h, i in listed.items()} == {
        "lyra": lyra_invite,
        "vega": vega_second,
        "rigel": rigel_invite,
    }

    # only the newest invite works
    assert Owner(server, "vega").register("demo", invite=vega_first).status_code == 403
    assert Owner(server, "vega").register("demo", invite=vega_second).status_code == 201
    # a used invite is no longer retrievable, and neither is one revoked by a removal
    assert "vega" not in pending(server, admin)
    HTTP.delete(roster_url(server, "rigel"), headers=admin.headers())
    assert sorted(pending(server, admin)) == ["lyra"]
    assert (
        Owner(server, "rigel").register("demo", invite=rigel_invite).status_code == 403
    )

    secrets = psql(
        server,
        "SELECT count(*) FROM invites WHERE secret IS NOT NULL AND handle <> 'lyra'",
    )
    assert secrets == "0"  # the secret is erased, not just hidden


def test_an_expired_invite_is_refused_and_its_secret_erased(demo):
    server, admin = demo
    HTTP.post(roster_url(server, "lyra"), headers=admin.headers())
    stale = invite(admin, "demo", "lyra").json()["invite"]
    psql(server, "UPDATE invites SET expires = now() - interval '1 second'")

    assert pending(server, admin) == {}
    assert Owner(server, "lyra").register("demo", invite=stale).status_code == 403
    server.sweep()  # the janitor erases the secret of an invite that expired unused
    assert psql(server, "SELECT count(*) FROM invites WHERE secret IS NOT NULL") == "0"


def test_only_the_admin_invites_and_only_roster_handles(demo):
    server, admin = demo
    HTTP.post(roster_url(server, "lyra"), headers=admin.headers())
    assert invite(admin, "demo", "mallory").status_code == 403  # not on the roster
    lyra = Owner(server, "lyra")
    lyra.register("demo", invite=invite(admin, "demo", "lyra").json()["invite"])
    url = f"{server.url}/v1/demo/invites"
    assert (
        HTTP.post(url, json={"handle": "lyra"}, headers=lyra.headers()).status_code
        == 403
    )
    assert HTTP.get(url, headers=lyra.headers()).status_code == 403
    assert HTTP.get(url).status_code == 401


def test_registration_needs_an_invite(demo):
    server, admin = demo
    HTTP.post(roster_url(server, "lyra"), headers=admin.headers())
    assert Owner(server, "lyra").register("demo").status_code == 403
    status = HTTP.get(f"{server.url}/v1/status").json()
    assert "registration" not in status and "public_base_url" not in status


def test_any_member_reads_the_whole_roster(demo):
    # members validate addresses to one another (`@handle`), so each may read every handle on
    # its community's roster, registered or not yet; nobody outside the community can
    server, admin = demo
    for handle in ("lyra", "vega", "rigel"):
        HTTP.post(roster_url(server, handle), headers=admin.headers())
    lyra = Owner(server, "lyra")
    lyra.register("demo", invite=invite(admin, "demo", "lyra").json()["invite"])
    invited = invite(admin, "demo", "vega").json()  # invited, not yet joined

    listed = HTTP.get(roster_url(server), headers=lyra.headers())
    assert listed.status_code == 200, listed.text
    members = {m["handle"]: m for m in listed.json()["roster"]}
    assert sorted(members) == ["lyra", "rigel", "vega"]
    assert members["lyra"]["registered"] is True
    assert members["vega"] == {
        "handle": "vega",
        "registered": False,
        "invite_expires": invited["expires"],
    }
    assert members["rigel"] == {
        "handle": "rigel",
        "registered": False,
        "invite_expires": None,
    }
    assert "invite" not in listed.text.replace(
        "invite_expires", ""
    )  # no invite secrets

    assert HTTP.get(roster_url(server)).status_code == 401
    key = lyra.issue("dashboard", role="non-member")["key"]
    by_key = HTTP.get(roster_url(server), headers={"Authorization": f"Bearer {key}"})
    assert by_key.status_code == 403  # a non-member key acts as no Member
    member_key = lyra.issue("notebook")["key"]
    by_member_key = HTTP.get(
        roster_url(server), headers={"Authorization": f"Bearer {member_key}"}
    )
    assert by_member_key.status_code == 200  # a member key acts as its Member
    set_roster(server, admin, "other", ["bob"])
    bob = Owner(server, "bob")
    enroll(admin, bob, "other")
    elsewhere = HTTP.get(roster_url(server), headers=bob.headers())
    assert elsewhere.status_code == 403  # a key is good only in its own community
