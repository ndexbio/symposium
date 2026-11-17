"""The last published release, as its own clients used it: `Previous` speaks that release's
API, and `seed` leaves a community the way it did, for the suites that upgrade a server of it in
place to this release."""

from __future__ import annotations

import os

from harness import HTTP, OwnerKey, file_headers

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


def psql(server, sql):
    return server.exec(
        "gosu", "postgres", "psql", "-tA", "-d", "symposium_data", "-c", sql
    ).stdout.strip()


def seed(server, root: str) -> tuple[dict, dict]:
    """A community as the previous release leaves it: members who joined by invite, one of
    them narrowed to reading and one to writing without publishing, one taken off the roster
    after it wrote; a collection a member owns and shares. -> ({handle: Previous}, file ids)."""
    admin = Previous(server, root, server.admin_key, admin=True)
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
