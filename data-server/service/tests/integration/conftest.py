"""Integration harness: runs the image under test and drives it over HTTP and `docker exec`.

The Makefile sets SYMPOSIUM_DATA_TEST_IMAGE (and SYMPOSIUM_DATA_TEST_VERSION) after building
the image; every container and volume a test creates is named sdtest-* and removed afterwards.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

IMAGE = os.environ.get("SYMPOSIUM_DATA_TEST_IMAGE", "")
VERSION = os.environ.get("SYMPOSIUM_DATA_TEST_VERSION", "")


def docker(*args, check=True, input=None, timeout=600):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, input=input, timeout=timeout
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {result.stderr.strip()[-600:]}")
    return result


class Server:
    """One running data-server container and the volume holding its state."""

    def __init__(self, env: dict):
        self.env = env
        self.name = f"sdtest-{uuid.uuid4().hex[:10]}"
        self.volume = f"{self.name}-vol"
        self.url = ""

    def start(self, wait=True):
        # Docker assigns the host port itself: picking a "free" port first races with
        # anything else that grabs it before the container binds.
        cmd = ["run", "-d", "--name", self.name, "-p", "127.0.0.1::8080"]
        cmd += ["-v", f"{self.volume}:/apps"]
        for key, value in self.env.items():
            cmd += ["-e", f"{key}={value}"]
        docker(*cmd, IMAGE)
        self.locate()
        if wait:
            self.wait()
        return self

    def locate(self):
        """Read the host port Docker assigned; it changes on every start and restart."""
        mapped = docker("port", self.name, "8080").stdout.splitlines()[0].strip()
        self.url = f"http://127.0.0.1:{mapped.rsplit(':', 1)[1]}"

    def wait(self, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = httpx.get(self.url + "/v1/status", timeout=5)
                if r.status_code == 200 and r.json().get("s3") == "ok":
                    return r.json()
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise RuntimeError(f"{self.name} never became healthy:\n{self.logs()[-2000:]}")

    def status(self) -> dict:
        return httpx.get(self.url + "/v1/status", timeout=10).json()

    def exec(self, *args, input=None):
        return docker("exec", "-i", self.name, *args, input=input, check=False)

    def admin(self, *args, input=None):
        return self.exec("data-admin", *args, input=input)

    def logs(self) -> str:
        result = docker("logs", self.name, check=False)
        return result.stdout + result.stderr

    def restart(self):
        docker("restart", self.name)
        self.locate()
        self.wait()

    def recreate(self):
        """Remove the container and start a new one on the same volume."""
        docker("rm", "-f", "-v", self.name)
        self.start()

    def remove(self):
        docker("rm", "-f", "-v", self.name, check=False)
        docker("volume", "rm", "-f", self.volume, check=False)


@pytest.fixture
def make_server():
    if not IMAGE:
        pytest.fail(
            "SYMPOSIUM_DATA_TEST_IMAGE is not set; run through `make -C data-server test`"
        )
    servers = []

    def factory(start=True, **env):
        server = Server({"SYMPOSIUM_DATA_REGISTRATION": "open", **env})
        servers.append(server)
        return server.start() if start else server

    yield factory
    for server in servers:
        server.remove()


@pytest.fixture
def server(make_server):
    return make_server()


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


@pytest.fixture
def owner_key():
    return OwnerKey


class Owner:
    """A member as the skill would act: a handle in one community, a locally generated key,
    a server URL. Identity is per community, so the same handle elsewhere is someone else."""

    def __init__(
        self,
        server: Server,
        handle: str,
        key: OwnerKey | None = None,
        community: str = "demo",
    ):
        self.server, self.handle, self.community = server, handle, community
        self.key = key or OwnerKey()

    def url(self, path: str) -> str:
        """A route of this owner's community."""
        return f"{self.server.url}/v1/{self.community}{path}"

    def challenge(self) -> str:
        r = httpx.post(self.url("/auth/challenge"), json={"handle": self.handle})
        r.raise_for_status()
        return r.json()["nonce"]

    def register(
        self, community: str, invite: str | None = None, key: OwnerKey | None = None
    ):
        """Register in `community`, which becomes this owner's community."""
        self.community = community
        key = key or self.key
        nonce = self.challenge()
        body = {
            "handle": self.handle,
            "public_jwk": key.jwk,
            "nonce": nonce,
            "signature": key.sign(nonce),
        }
        if invite is not None:
            body["invite"] = invite
        return httpx.post(self.url("/owners"), json=body)

    def token_response(self, key: OwnerKey | None = None):
        key = key or self.key
        nonce = self.challenge()
        return httpx.post(
            self.url("/auth/token"),
            json={"handle": self.handle, "nonce": nonce, "signature": key.sign(nonce)},
        )

    def token(self) -> str:
        r = self.token_response()
        assert r.status_code == 200, r.text
        return r.json()["token"]

    def headers(self, token: str | None = None) -> dict:
        if token is None:
            token = getattr(self, "_token", None) or self.token()
            self._token = token
        return {"Authorization": f"Bearer {token}"}

    # ── files ────────────────────────────────────────────────────────────────────────────────
    def put(
        self, community, collection, name, data: bytes, metadata=None, content_type=None
    ):
        headers = {**self.headers(), **file_headers(data, metadata)}
        if content_type:
            headers["Content-Type"] = content_type
        return httpx.put(
            f"{self.server.url}/v1/{community}/collections/{collection}/files/{name}",
            content=data,
            headers=headers,
            timeout=600,
        )

    def version(self, file_id, data: bytes | None = None, metadata=None):
        headers = dict(self.headers())
        if data is None:
            headers["X-Data-Metadata-Only"] = "1"
            headers["X-Data-Metadata"] = b64u_json(metadata)
            data = b""
        else:
            headers.update(file_headers(data, metadata))
        return httpx.post(
            self.url(f"/files/{file_id}/versions"),
            content=data,
            headers=headers,
            timeout=600,
        )

    def delete(self, file_id, reason=None):
        params = {"reason": reason} if reason else {}
        return httpx.delete(
            self.url(f"/files/{file_id}"),
            params=params,
            headers=self.headers(),
        )

    def get(self, file_id, ref="latest", headers=None):
        return httpx.get(
            self.url(f"/files/{file_id}/v/{ref}"),
            headers={**self.headers(), **(headers or {})},
            timeout=600,
        )

    def stat(self, file_id, ref="latest"):
        return httpx.get(
            self.url(f"/files/{file_id}/v/{ref}/stat"), headers=self.headers()
        )


class Admin(Owner):
    """The server admin: server-wide, signed in through /v1/admin/..., and acting in any
    community. `community` only selects which community's routes it calls."""

    def challenge(self) -> str:
        r = httpx.post(self.server.url + "/v1/admin/challenge")
        r.raise_for_status()
        return r.json()["nonce"]

    def token_response(self, key: OwnerKey | None = None):
        key = key or self.key
        nonce = self.challenge()
        return httpx.post(
            self.server.url + "/v1/admin/token",
            json={"nonce": nonce, "signature": key.sign(nonce)},
        )

    def at(self, community: str) -> Admin:
        """The same admin, calling another community's routes."""
        other = Admin(self.server, self.handle, self.key, community)
        other._token = getattr(self, "_token", None)
        return other


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


def psql(server: Server, sql: str) -> str:
    return server.exec(
        "gosu", "postgres", "psql", "-tA", "-d", "symposium_data", "-c", sql
    ).stdout.strip()


def community_with(server: Server, members=("lyra", "vega", "rigel")):
    """An initialized open server: the demo roster, each member registered. -> (admin, {h: Owner})."""
    admin = init_admin(server)
    set_roster(server, admin, "demo", list(members))
    owners = {}
    for handle in members:
        owner = Owner(server, handle)
        r = owner.register("demo")
        assert r.status_code == 201, r.text
        owners[handle] = owner
    return admin, owners


def init_admin(server: Server, handle: str = "demo-admin") -> Admin:
    """Bind the admin's public key through data-admin, as the operator does."""
    admin = Admin(server, handle)
    result = server.admin(
        "init", "--admin", handle, "--pubkey", "-", input=admin.key.jwk_text()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return admin


def create_community(server: Server, admin: Admin, community: str):
    r = httpx.post(
        f"{server.url}/v1/communities",
        json={"name": community},
        headers=admin.headers(),
    )
    assert r.status_code in (200, 201), r.text
    return r


def set_roster(server: Server, admin: Admin, community: str, handles: list) -> dict:
    """Create the community if it does not exist yet, then set its roster."""
    create_community(server, admin, community)
    r = httpx.put(
        f"{server.url}/v1/{community}/roster",
        json={"handles": handles},
        headers=admin.headers(),
    )
    assert r.status_code == 200, r.text
    return r.json()


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


def assert_consistent(server: Server, timeout: float = 30):
    """Every write either fully happened or left nothing; poll briefly for cleanup that runs
    after a client disconnect."""
    deadline = time.time() + timeout
    while True:
        state = consistency(server)
        if not any(state.values()) or time.time() > deadline:
            break
        time.sleep(1)
    assert not any(state.values()), state
