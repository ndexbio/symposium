"""The data server's integration fixtures: the session's container (tests/harness.py), started
with the root user's key file copied onto its volume before it starts, as an operator places it
(R-D4), and the users acting on it over HTTP: the root, server admins, community admins and
members, each with its own key and roles.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from harness import HTTP, IMAGE, MAX_WAIT, TEST_ENV, Server

ADMIN = "demo-admin"  # the root user, bound from the key file
STEWARD = (
    "steward"  # each community's first community admin, unless a test names another
)
EVERY = ["*"]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """The one container, started with the root's key file in place: the root user is bound at
    its first start (R-D4)."""
    if not IMAGE:
        pytest.fail(
            "SYMPOSIUM_DATA_TEST_IMAGE is not set; run through `make -C data-server test`"
        )
    server = Server(TEST_ENV)
    server.admin_key = OwnerKey()
    key_file = place_key(tmp_path_factory.mktemp("admin"), ADMIN, server.admin_key)
    try:
        server.start(key_file)
        yield server
    finally:
        server.remove()


def place_key(directory: Path, handle: str, key: OwnerKey) -> Path:
    """The public key file as `admin-config` writes it: admin_pub_<handle>.key, mode 0644."""
    path = directory / f"admin_pub_{handle}.key"
    path.write_text(key.jwk_text())
    path.chmod(0o644)
    return path


@pytest.fixture(autouse=True)
def clean_slate(server):
    """Every test starts from an empty, initialized server."""
    server.reset()
    yield


class OwnerKey:
    """An owner's Ed25519 key pair, as a member's keystore would hold it."""

    def __init__(self):
        self.private = Ed25519PrivateKey.generate()
        raw = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.jwk = {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode(),
        }

    def jwk_text(self) -> str:
        return json.dumps(self.jwk)

    def sign(self, message: str) -> str:
        return (
            base64.urlsafe_b64encode(self.private.sign(message.encode()))
            .rstrip(b"=")
            .decode()
        )


class Owner:
    """A user as the skill would act: a handle homed in one community (None: server-level), a
    locally generated key, a server URL."""

    def __init__(
        self,
        server: Server,
        handle: str,
        key: OwnerKey | None = None,
        community: str | None = "demo",
    ):
        self.server, self.handle, self.community = server, handle, community
        self.home = community
        self.key = key or OwnerKey()

    def url(self, path: str) -> str:
        """A route of the community this user is calling."""
        return f"{self.server.url}/v1/{self.community}{path}"

    def challenge(self) -> str:
        r = HTTP.post(
            f"{self.server.url}/v1/auth/challenge",
            json={"handle": self.handle, "community": self.home},
        )
        r.raise_for_status()
        return r.json()["nonce"]

    def register(self, invite: str, key: OwnerKey | None = None, **extra):
        """Join with `invite`, proving `key`; `extra` adds fields a test sends on purpose."""
        key = key or self.key
        nonce = self.challenge()
        body = {
            "handle": self.handle,
            "public_jwk": key.jwk,
            "nonce": nonce,
            "signature": key.sign(nonce),
            "invite": invite,
            **extra,
        }
        return HTTP.post(f"{self.server.url}/v1/users", json=body)

    def sign_in(self, key: OwnerKey | None = None):
        key = key or self.key
        nonce = self.challenge()
        return HTTP.post(
            f"{self.server.url}/v1/auth/token",
            json={
                "handle": self.handle,
                "community": self.home,
                "nonce": nonce,
                "signature": key.sign(nonce),
            },
        )

    def session_key(self) -> str:
        """A session key: what signing in with this owner's Ed25519 key answers."""
        r = self.sign_in()
        assert r.status_code == 200, r.text
        return r.json()["key"]

    def issue(
        self, label: str, roles=None, non_member: bool = False, expires_days=None
    ) -> dict:
        """An issued API key, made with this user's session: by default a member key carrying
        community-member on every collection. -> the key's row, with its value in `key`."""
        r = self.issue_request(label, roles, non_member, expires_days)
        assert r.status_code == 201, r.text
        return r.json()

    def issue_request(self, label, roles=None, non_member=False, expires_days=None):
        if roles is None:
            roles = [{"role": "community-member", "collections": EVERY}]
        body = {"label": label, "roles": roles, "non_member": non_member}
        if expires_days is not None:
            body["expires_days"] = expires_days
        return HTTP.post(self.url("/api-keys"), json=body, headers=self.headers())

    # ── roles ────────────────────────────────────────────────────────────────────────────────
    def assign(
        self, role: str, collections=None, handle=None, community=None, api_key_id=None
    ):
        return HTTP.post(
            f"{self.server.url}/v1/assignments",
            json=assignment(role, collections, handle, community, api_key_id),
            headers=self.headers(),
        )

    def unassign(
        self, role: str, collections=None, handle=None, community=None, api_key_id=None
    ):
        return HTTP.request(
            "DELETE",
            f"{self.server.url}/v1/assignments",
            json=assignment(role, collections, handle, community, api_key_id),
            headers=self.headers(),
        )

    def invite(self, handle: str, roles, community=None, hours=None):
        body = {"handle": handle, "roles": roles, "community": community}
        if hours is not None:
            body["hours"] = hours
        return HTTP.post(
            f"{self.server.url}/v1/invites", json=body, headers=self.headers()
        )

    def user_id(self, handle: str, community=None) -> str:
        r = HTTP.get(
            f"{self.server.url}/v1/users",
            params={"community": community} if community else {},
            headers=self.headers(),
        )
        assert r.status_code == 200, r.text
        return next(u["id"] for u in r.json()["users"] if u["handle"] == handle)

    def headers(self, key: str | None = None) -> dict:
        """This owner's key as a request header: by default a session key, signed in once."""
        if key is None:
            key = getattr(self, "_session", None) or self.session_key()
            self._session = key
        return {"Authorization": f"Bearer {key}"}

    # ── files ────────────────────────────────────────────────────────────────────────────────
    def put(
        self, community, collection, name, data: bytes, metadata=None, content_type=None
    ):
        headers = {**self.headers(), **file_headers(data, metadata)}
        if content_type:
            headers["Content-Type"] = content_type
        return HTTP.put(
            f"{self.server.url}/v1/{community}/collections/{collection}/files/{name}",
            content=data,
            headers=headers,
        )

    def version(self, file_id, data: bytes | None = None, metadata=None):
        headers = dict(self.headers())
        if data is None:
            headers["X-Data-Metadata-Only"] = "1"
            headers["X-Data-Metadata"] = b64u_json(metadata)
            data = b""
        else:
            headers.update(file_headers(data, metadata))
        return HTTP.post(
            self.url(f"/files/{file_id}/versions"),
            content=data,
            headers=headers,
        )

    def delete(self, file_id, reason=None):
        params = {"reason": reason} if reason else {}
        return HTTP.delete(
            self.url(f"/files/{file_id}"),
            params=params,
            headers=self.headers(),
        )

    def get(self, file_id, ref="latest", headers=None):
        return HTTP.get(
            self.url(f"/files/{file_id}/v/{ref}"),
            headers={**self.headers(), **(headers or {})},
        )

    def stat(self, file_id, ref="latest"):
        return HTTP.get(
            self.url(f"/files/{file_id}/v/{ref}/stat"), headers=self.headers()
        )


class Admin(Owner):
    """A server-level user (the root, or a server admin): its home is none, and `community`
    only selects which community's routes it calls."""

    def __init__(self, server, handle, key=None, community="demo"):
        super().__init__(server, handle, key, community)
        self.home = None

    def at(self, community: str) -> Admin:
        """The same user, calling another community's routes."""
        other = Admin(self.server, self.handle, self.key, community)
        other._session = getattr(self, "_session", None)
        return other


def assignment(
    role, collections=None, handle=None, community=None, api_key_id=None
) -> dict:
    body = {"role": role, "collections": collections}
    if api_key_id is not None:
        body["api_key_id"] = api_key_id
    else:
        body["handle"], body["community"] = handle, community
    return body


def b64u_json(value) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


def repr_digest(data: bytes) -> str:
    return "sha-256=:" + base64.b64encode(hashlib.sha256(data).digest()).decode() + ":"


def file_headers(data: bytes, metadata=None) -> dict:
    headers = {
        "Repr-Digest": repr_digest(data),
        "Content-Type": "application/octet-stream",
    }
    if metadata is not None:
        headers["X-Data-Metadata"] = b64u_json(metadata)
    return headers


def set_quota(server: Server, quota_bytes: int):
    """The per-member quota, through the test hook, until the next test's reset."""
    result = server.exec(
        "sh", "-c", f"echo {quota_bytes} > /apps/data/config/test-quota"
    )
    assert result.returncode == 0, result.stderr


def purge(admin: Owner, file_id, n: int, community: str = "demo"):
    """A holder of `manage` frees one version's content through the purge route."""
    return HTTP.post(
        f"{admin.server.url}/v1/{community}/files/{file_id}/v/{n}/purge",
        headers=admin.headers(),
    )


def psql(server: Server, sql: str) -> str:
    return server.exec(
        "gosu", "postgres", "psql", "-tA", "-d", "symposium_data", "-c", sql
    ).stdout.strip()


# A timestamp older than the server's pending TTL (one day): what the janitor's next pass
# (server.sweep()) treats as abandoned. A test ages a row with it instead of waiting.
EXPIRED = "now() - interval '2 days'"


def until_sql(server: Server, query: str, expected: str, message: str):
    """Poll `query` every 0.2 s until it answers `expected`."""
    deadline = time.monotonic() + MAX_WAIT
    while (answer := psql(server, query)) != expected:
        assert time.monotonic() < deadline, f"{message}: {answer!r}"
        time.sleep(0.2)


def community_with(server: Server, members=("lyra", "vega", "rigel"), community="demo"):
    """An initialized server: the community, each member joined by invite with
    community-member on every collection. -> (root, {handle: Owner})."""
    admin = init_admin(server)
    create_community(server, admin, community)
    owners = {}
    for handle in members:
        owner = Owner(server, handle, community=community)
        r = enroll(admin.at(community), owner, community)
        assert r.status_code == 201, r.text
        owners[handle] = owner
    return admin, owners


def invite(admin: Owner, community: str, handle: str, hours=None, roles=None):
    """An invite through the API, as bootstrap does: by default community-member on every
    collection. -> the response."""
    roles = roles or [{"role": "community-member", "collections": EVERY}]
    return admin.invite(handle, roles, community=community, hours=hours)


def enroll(admin: Owner, owner: Owner, community: str, roles=None):
    """Invite a handle and join with that invite: the only way to join."""
    r = invite(admin, community, owner.handle, roles=roles)
    assert r.status_code == 201, r.text
    return owner.register(r.json()["invite"])


def init_admin(server: Server) -> Admin:
    """The session's root user, bound once when the server started."""
    return Admin(server, ADMIN, server.admin_key)


def create_community(server: Server, admin: Owner, community: str, steward=STEWARD):
    """Create `community` with `steward` as its first community admin, invited but not yet
    joined. -> the response; its admin invite is in `admin_invite`."""
    r = HTTP.post(
        f"{server.url}/v1/communities",
        json={"name": community, "admin": steward},
        headers=admin.headers(),
    )
    assert r.status_code in (200, 201), r.text
    return r


def steward_of(server: Server, community: str = "demo", handle=STEWARD) -> Owner:
    """The community's first admin, joined: creates the community when it does not exist."""
    admin = init_admin(server)
    created = create_community(server, admin, community, handle).json()
    owner = Owner(server, handle, community=community)
    issued = created.get("admin_invite")
    if issued is None:
        r = admin.invite(
            handle,
            [{"role": "community-admin", "collections": None}],
            community=community,
        )
        assert r.status_code == 201, r.text
        issued = r.json()
    r = owner.register(issued["invite"])
    assert r.status_code == 201, r.text
    return owner


def store_counts(server: Server) -> tuple[int, int]:
    """(objects, open multipart uploads) in the internal S3 bucket."""
    out = server.exec(
        "/opt/venv/bin/python",
        "-c",
        "from symposium_data.runtime import Settings, PayloadStore;"
        "s = PayloadStore(Settings());"
        "keys = [o['Key'] for p in s.s3.get_paginator('list_objects_v2').paginate(Bucket=s.bucket)"
        " for o in p.get('Contents', [])];"
        "u = s.s3.list_multipart_uploads(Bucket=s.bucket).get('Uploads', []);"
        "print(len(keys), len(u))",
    ).stdout.split()
    return int(out[0]), int(out[1])


def untracked_objects(server: Server) -> int:
    """Objects no payload row accounts for. Must be zero at every moment, even while S3
    deletes are failing: a row always records bytes before they exist and outlives them."""
    tracked = int(
        psql(
            server,
            "SELECT count(*) FROM payloads WHERE state IN ('pending', 'ready', 'purging')",
        )
    )
    objects, _ = store_counts(server)
    return max(0, objects - tracked)


def consistency(server: Server) -> dict:
    """The R-A6 invariants, as numbers that must all be zero (or equal)."""
    ready = int(psql(server, "SELECT count(*) FROM payloads WHERE state = 'ready'"))
    objects, uploads = store_counts(server)
    return {
        "purging_payloads": int(
            psql(server, "SELECT count(*) FROM payloads WHERE state = 'purging'")
        ),
        "pending_payloads": int(
            psql(server, "SELECT count(*) FROM payloads WHERE state = 'pending'")
        ),
        "unreferenced_ready_payloads": int(
            psql(
                server,
                "SELECT count(*) FROM payloads p WHERE p.state = 'ready' AND NOT EXISTS "
                "(SELECT 1 FROM versions v WHERE v.payload_id = p.id)",
            )
        ),
        "reserved_files": int(
            psql(server, "SELECT count(*) FROM files WHERE state = 'reserved'")
        ),
        "live_files_without_versions": int(
            psql(
                server,
                "SELECT count(*) FROM files f WHERE f.state = 'live' AND NOT EXISTS "
                "(SELECT 1 FROM versions v WHERE v.file_id = f.id)",
            )
        ),
        "objects_minus_ready_payloads": objects - ready,
        "open_multipart_uploads": uploads,
    }


def assert_consistent(server: Server):
    """Every write either fully happened or left nothing; polls for the cleanup a request runs
    once it has seen its client disconnect."""
    deadline = time.monotonic() + MAX_WAIT
    while True:
        state = consistency(server)
        if not any(state.values()) or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert not any(state.values()), state
