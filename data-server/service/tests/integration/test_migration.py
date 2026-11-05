"""Upgrading a server in place: a database written by the last published release, through that
release's own API, opens under this one on its first start. The database is backed up first;
the admin becomes the root user, every member a user holding the role its grants express,
every collection keeps its owner, and a member taken off the roster stays as a tombstone."""

import os

import pytest
from conftest import ADMIN, EVERY, Admin, Owner, OwnerKey, file_headers, place_key
from harness import HTTP, TEST_ENV, Server

# the last published release
PREVIOUS = os.environ.get(
    "SYMPOSIUM_DATA_PREVIOUS_IMAGE", "ndexbio/symposium-data:0.1.2"
)


class Previous:
    """A user of the previous release's API: members sign in per community, the admin through
    /v1/admin."""

    def __init__(self, server, handle, key=None, admin=False):
        self.server, self.handle, self.admin = server, handle, admin
        self.key = key or OwnerKey()
        self._session = None

    def url(self, path):
        return f"{self.server.url}/v1/demo{path}"

    def challenge(self):
        r = HTTP.post(self.url("/auth/challenge"), json={"handle": self.handle})
        assert r.status_code == 200, r.text
        return r.json()["nonce"]

    def headers(self):
        if self._session is None:
            if self.admin:
                nonce = HTTP.post(f"{self.server.url}/v1/admin/challenge").json()[
                    "nonce"
                ]
                r = HTTP.post(
                    f"{self.server.url}/v1/admin/token",
                    json={"nonce": nonce, "signature": self.key.sign(nonce)},
                )
            else:
                nonce = self.challenge()
                r = HTTP.post(
                    self.url("/auth/token"),
                    json={
                        "handle": self.handle,
                        "nonce": nonce,
                        "signature": self.key.sign(nonce),
                    },
                )
            assert r.status_code == 200, r.text
            body = r.json()
            self._session = body.get("token") or body.get("key")
        return {"Authorization": f"Bearer {self._session}"}

    def call(self, method, path, **kwargs):
        r = HTTP.request(method, self.url(path), headers=self.headers(), **kwargs)
        assert r.status_code in (200, 201), (path, r.text)
        return r.json() if r.content else None

    def join(self, admin):
        secret = admin.call("POST", "/invites", json={"handle": self.handle})["invite"]
        nonce = self.challenge()
        r = HTTP.post(
            self.url("/owners"),
            json={
                "handle": self.handle,
                "public_jwk": self.key.jwk,
                "nonce": nonce,
                "signature": self.key.sign(nonce),
                "invite": secret,
            },
        )
        assert r.status_code == 201, r.text

    def put(self, collection, name, data):
        r = HTTP.put(
            self.url(f"/collections/{collection}/files/{name}"),
            content=data,
            headers={**self.headers(), **file_headers(data)},
        )
        assert r.status_code == 201, r.text
        return r.json()["file_id"]


@pytest.fixture
def previous(tmp_path):
    """A server of the previous release, its admin's key file in place."""
    server = Server(TEST_ENV)
    server.admin_key = OwnerKey()
    key_file = place_key(tmp_path, ADMIN, server.admin_key)
    try:
        server.start(key_file, image=PREVIOUS)
        yield server
    finally:
        server.remove()


def psql(server, sql):
    return server.exec(
        "gosu", "postgres", "psql", "-tA", "-d", "symposium_data", "-c", sql
    ).stdout.strip()


def seed(server) -> tuple[dict, dict]:
    """A community as the previous release leaves it: members who joined by invite, one of
    them narrowed to reading and one to writing without publishing, one taken off the roster
    after it wrote; a collection a member owns and shares. -> ({handle: Previous}, file ids)."""
    admin = Previous(server, ADMIN, server.admin_key, admin=True)
    r = HTTP.post(
        f"{server.url}/v1/communities", json={"name": "demo"}, headers=admin.headers()
    )
    assert r.status_code == 201, r.text
    people = {h: Previous(server, h) for h in ("lyra", "vega", "rigel", "nova", "gone")}
    for handle, person in people.items():
        admin.call("POST", f"/roster/{handle}")
        person.join(admin)
    lyra = people["lyra"]
    lyra.call("POST", "/collections", json={"name": "lab"})
    files = {
        "lab": lyra.put("lab", "a.csv", b"lab data"),
        "files": lyra.put("files", "b.csv", b"files data"),
        "gone": people["gone"].put("files", "gone.csv", b"by gone"),
    }
    lyra.call(
        "PUT",
        "/collections/lab/grants",
        json={"handle": "vega", "perm": "read", "granted": True},
    )
    admin.call("DELETE", "/roster/gone")
    # rigel reads only; nova writes but cannot publish
    psql(server, "DELETE FROM grants WHERE handle = 'rigel' AND perm = 'write'")
    psql(server, "DELETE FROM grants WHERE handle = 'nova' AND collection = 'inbox'")
    return people, files


def roles_of(owner):
    r = HTTP.get(owner.url("/me"), headers=owner.headers())
    assert r.status_code == 200, r.text
    return r.json()["roles"]


def test_a_previous_release_upgrades_in_place_on_first_start(previous):
    people, files = seed(previous)
    before = psql(previous, "SELECT version_num FROM alembic_version")
    server = previous.upgrade()

    # backed up first, then upgraded
    status = server.status()
    assert status["mode"] == "operational" and status["root"] == ADMIN
    backups = server.exec("ls", "/apps/data/backups").stdout.split()
    assert len(backups) == 1 and backups[0].startswith(f"schema-{before}-"), backups
    dump = server.exec("sh", "-c", f"gunzip -c /apps/data/backups/{backups[0]}").stdout
    assert "CREATE TABLE public.roster" in dump and "lyra" in dump
    assert "community-observer on ['files', 'record']" in server.logs()
    for table in ("owners", "owner_keys", "roster", "grants", "admin_keys"):
        assert psql(server, f"SELECT to_regclass('{table}')") == "", table

    # the admin is root, and every member signs in with the key it joined with
    root = Admin(server, ADMIN, server.admin_key)
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
    roster = HTTP.get(lyra.url("/roster"), headers=lyra.headers()).json()["roster"]
    assert {e["handle"]: bool(e["removed"]) for e in roster} == {
        "lyra": False, "vega": False, "rigel": False, "nova": False, "gone": True
    }  # fmt: skip
    assert lyra.stat(files["gone"]).json()["created_by"] == "gone"

    # root runs the community until it names a community admin
    assert root.assign("community-admin", None, "lyra", "demo").status_code == 200
    invited = lyra.invite("mia", member, community="demo")
    assert invited.status_code == 201, invited.text

    # a later start finds the schema current: no second backup
    server.restarted()
    assert len(server.exec("ls", "/apps/data/backups").stdout.split()) == 1
