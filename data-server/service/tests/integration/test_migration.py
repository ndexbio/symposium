"""Upgrading a server in place: a database written by the last published release, through that
release's own API, opens under this one on its first start. The database is backed up first;
the admin becomes the root user, every member a user holding the role its grants express,
every collection keeps its owner, and a member taken off the roster stays as a tombstone."""

import pytest
from conftest import EVERY, ROOT, Owner, OwnerKey, ServerUser, place_key
from harness import HTTP, TEST_ENV, Server
from previous import PREVIOUS, psql, seed


@pytest.fixture
def previous(tmp_path):
    """A server of the previous release, its admin's key file in place."""
    server = Server(TEST_ENV)
    server.admin_key = OwnerKey()
    key_file = place_key(tmp_path, ROOT, server.admin_key)
    try:
        server.start(key_file, image=PREVIOUS)
        yield server
    finally:
        server.remove()


def roles_of(owner):
    r = HTTP.get(owner.server.url + "/v1/me", headers=owner.headers())
    assert r.status_code == 200, r.text
    return r.json()["roles"]


def test_a_previous_release_upgrades_in_place_on_first_start(previous):
    people, files = seed(previous, ROOT)
    before = psql(previous, "SELECT version_num FROM alembic_version")
    server = previous.upgrade()

    # backed up first, then upgraded
    status = server.status()
    assert status["mode"] == "operational" and status["root"] == ROOT
    backups = server.exec("ls", "/apps/data/backups").stdout.split()
    assert len(backups) == 1 and backups[0].startswith(f"schema-{before}-"), backups
    dump = server.exec("sh", "-c", f"gunzip -c /apps/data/backups/{backups[0]}").stdout
    assert "CREATE TABLE public.roster" in dump and "lyra" in dump
    assert "community-observer on ['files', 'record']" in server.logs()
    for table in ("owners", "owner_keys", "roster", "grants", "admin_keys"):
        assert psql(server, f"SELECT to_regclass('{table}')") == "", table

    # the admin is root, and every member signs in with the key it joined with
    root = ServerUser(server, ROOT, server.admin_key)
    assert root.sign_in().status_code == 200
    users = {h: Owner(server, h, p.key) for h, p in people.items()}
    member = [{"role": "community-member", "collections": EVERY}]
    reader = [{"role": "community-observer", "collections": ["files", "record"]}]
    assert roles_of(users["lyra"]) == member and roles_of(users["vega"]) == member
    assert roles_of(users["rigel"]) == reader and roles_of(users["nova"]) == reader
    assert users["vega"].get(files["lab"]).status_code == 200
    assert users["rigel"].get(files["files"]).status_code == 200
    assert users["nova"].put("demo", "files", "x.csv", b"x").status_code == 403

    # collections keep their owner
    lyra = users["lyra"]
    listed = HTTP.get(lyra.url("/collections"), headers=lyra.headers()).json()
    assert {c["name"]: c["owner"] for c in listed["collections"]}["lab"] == "lyra"
    assert lyra.put("demo", "lab", "c.csv", b"more").status_code == 201

    # a member taken off the roster is a tombstone that keeps its work
    gone = users["gone"].sign_in()
    assert gone.status_code == 401 and "removed" in gone.json()["detail"]
    roster = HTTP.get(lyra.url("/users"), headers=lyra.headers()).json()["users"]
    assert {e["handle"]: bool(e["removed"]) for e in roster} == {
        "lyra": False, "vega": False, "rigel": False, "nova": False, "gone": True
    }  # fmt: skip
    assert lyra.stat(files["gone"]).json()["created_by"] == "gone"

    # root runs the community until it names a community admin
    assert root.assign("community-admin", None, "lyra", "demo").status_code in (
        200,
        201,
    )
    invited = lyra.invite("mia", member, community="demo")
    assert invited.status_code == 201, invited.text

    # a later start finds the schema current: no second backup
    server.restarted()
    assert len(server.exec("ls", "/apps/data/backups").stdout.split()) == 1


def test_an_upgrade_takes_ownership_of_a_cluster_written_under_other_ids(previous):
    """A cluster whose files belong to an id this image does not use still opens.

    The postgres account's id is assigned when an image is built and has moved between base
    images, so a volume written by an earlier release can belong to an id the new one does
    not have. Phase 2 of start.sh takes ownership of /apps/postgres for that reason; without
    it postgres cannot read its own postgresql.conf and the server never starts.

    The id here is one no build uses, so this holds whatever the two images happen to carry
    — which is what the test above cannot do, since it passes whenever they happen to agree.
    """
    seed(previous, ROOT)
    previous.exec("chown", "-R", "1234:1234", "/apps/postgres")
    assert (
        previous.exec("stat", "-c", "%u", "/apps/postgres/data").stdout.strip()
        == "1234"
    )

    server = previous.upgrade()

    assert server.status()["mode"] == "operational"
    owner = server.exec(
        "stat", "-c", "%u", "/apps/postgres/data/postgresql.conf"
    ).stdout.strip()
    assert owner == server.exec("id", "-u", "postgres").stdout.strip()
