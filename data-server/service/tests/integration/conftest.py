"""Integration harness: runs the image under test and drives it over HTTP and `docker exec`.

The Makefile sets SYMPOSIUM_DATA_TEST_IMAGE (and SYMPOSIUM_DATA_TEST_VERSION) after building
the image; every container and volume a test creates is named sdtest-* and removed afterwards.
"""

from __future__ import annotations

import base64
import json
import os
import socket
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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """One running data-server container and the volume holding its state."""

    def __init__(self, env: dict):
        self.env = env
        self.name = f"sdtest-{uuid.uuid4().hex[:10]}"
        self.volume = f"{self.name}-vol"
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"

    def start(self, wait=True):
        cmd = ["run", "-d", "--name", self.name, "-p", f"127.0.0.1:{self.port}:8080"]
        cmd += ["-v", f"{self.volume}:/apps"]
        for key, value in self.env.items():
            cmd += ["-e", f"{key}={value}"]
        docker(*cmd, IMAGE)
        if wait:
            self.wait()
        return self

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
        self.wait()

    def recreate(self):
        """Remove the container and start a new one on the same volume and port."""
        docker("rm", "-f", self.name)
        self.start()

    def remove(self):
        docker("rm", "-f", self.name, check=False)
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
    """A member as the skill would act: a handle, a locally generated key, a server URL."""

    def __init__(self, server: Server, handle: str, key: OwnerKey | None = None):
        self.server, self.handle = server, handle
        self.key = key or OwnerKey()

    def challenge(self) -> str:
        r = httpx.post(
            self.server.url + "/v1/auth/challenge", json={"handle": self.handle}
        )
        r.raise_for_status()
        return r.json()["nonce"]

    def register(
        self, community: str, invite: str | None = None, key: OwnerKey | None = None
    ):
        key = key or self.key
        nonce = self.challenge()
        body = {
            "handle": self.handle,
            "community": community,
            "public_jwk": key.jwk,
            "nonce": nonce,
            "signature": key.sign(nonce),
        }
        if invite is not None:
            body["invite"] = invite
        return httpx.post(self.server.url + "/v1/owners", json=body)

    def token_response(self, key: OwnerKey | None = None):
        key = key or self.key
        nonce = self.challenge()
        return httpx.post(
            self.server.url + "/v1/auth/token",
            json={"handle": self.handle, "nonce": nonce, "signature": key.sign(nonce)},
        )

    def token(self) -> str:
        r = self.token_response()
        assert r.status_code == 200, r.text
        return r.json()["token"]

    def headers(self, token: str | None = None) -> dict:
        return {"Authorization": f"Bearer {token or self.token()}"}


def init_admin(server: Server, handle: str = "demo-admin") -> Owner:
    """Bind the admin's public key through data-admin, as the operator does."""
    admin = Owner(server, handle)
    result = server.admin(
        "init", "--admin", handle, "--pubkey", "-", input=admin.key.jwk_text()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return admin


def set_roster(server: Server, admin: Owner, community: str, handles: list) -> dict:
    r = httpx.put(
        f"{server.url}/v1/c/{community}/roster",
        json={"handles": handles},
        headers=admin.headers(),
    )
    assert r.status_code == 200, r.text
    return r.json()
