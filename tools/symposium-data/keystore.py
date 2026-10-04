"""Key storage for the symposium-data CLI. Nobody handles a raw private key.

    ~/.symposium/keys/<server-id>/admin/<handle>.ed25519.pem         the server admin's key
    ~/.symposium/keys/<server-id>/<community>/<handle>.ed25519.pem   a member's key, per community
    … each with <handle>.pub.jwk beside it (the public JWK, not a secret)

Keys are keyed by the server's id, not its URL: a server reached through a new address is the
same identity domain. `admin` is never a community name (it is reserved), so the two kinds of
key never share a directory. Private keys are encrypted PKCS#8, mode 0600. The passphrase comes
from SYMPOSIUM_KEY_PASSPHRASE when it is set, otherwise from the OS keychain through the
optional `keyring` package. Nothing here prints a private key or a passphrase.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEYRING_SERVICE = "symposium-data"
ADMIN_SCOPE = "admin"


class KeystoreError(Exception):
    pass


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def thumbprint(jwk: dict) -> str:
    """The RFC 7638 thumbprint of an OKP key: the fingerprint the server reports."""
    canonical = json.dumps(
        {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]},
        separators=(",", ":"),
        sort_keys=True,
    )
    return b64u(hashlib.sha256(canonical.encode()).digest())


class Passphrase:
    """The passphrase protecting one key: SYMPOSIUM_KEY_PASSPHRASE, else the OS keychain."""

    def __init__(self, account: str):
        self.account = account

    def keyring(self):
        try:
            import keyring  # optional (R-I6)
        except ImportError:
            return None
        return keyring

    def get(self) -> bytes | None:
        value = os.environ.get("SYMPOSIUM_KEY_PASSPHRASE")
        if value:
            return value.encode()
        keyring = self.keyring()
        if keyring is None:
            return None
        try:
            stored = keyring.get_password(KEYRING_SERVICE, self.account)
        except Exception:  # no usable keychain backend
            return None
        return stored.encode() if stored else None

    def create(self) -> bytes:
        existing = self.get()
        if existing:
            return existing
        keyring = self.keyring()
        if keyring is not None:
            value = secrets.token_urlsafe(32)
            try:
                keyring.set_password(KEYRING_SERVICE, self.account, value)
                return value.encode()
            except Exception:
                pass
        raise KeystoreError(
            "no OS keychain is available: set SYMPOSIUM_KEY_PASSPHRASE in your own shell "
            "(never in a chat) and run the command again"
        )


class Keystore:
    def __init__(self, server_id: str, root: Path | None = None):
        safe = server_id.replace(":", "_").replace("/", "_")
        self.server_id = server_id
        self.root = (root or Path.home() / ".symposium" / "keys") / safe

    def paths(self, scope: str, handle: str) -> tuple[Path, Path]:
        directory = self.root / scope
        return directory / f"{handle}.ed25519.pem", directory / f"{handle}.pub.jwk"

    def exists(self, scope: str, handle: str) -> bool:
        return self.paths(scope, handle)[0].exists()

    def handles(self, scope: str) -> list[str]:
        directory = self.root / scope
        if not directory.is_dir():
            return []
        return sorted(
            p.name[: -len(".ed25519.pem")] for p in directory.glob("*.ed25519.pem")
        )

    def create(self, scope: str, handle: str, replace: bool = False) -> dict:
        """A new key pair for (scope, handle). -> its public JWK. An existing key is kept
        unless `replace`."""
        private_path, public_path = self.paths(scope, handle)
        if private_path.exists() and not replace:
            return self.public_jwk(scope, handle)
        private_path.parent.mkdir(parents=True, exist_ok=True)
        for directory in (private_path.parent, self.root, self.root.parent):
            os.chmod(directory, 0o700)
        passphrase = Passphrase(self.account(scope, handle)).create()
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(passphrase),
        )
        partial = private_path.with_suffix(".partial")
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
        raw = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        jwk = {"kty": "OKP", "crv": "Ed25519", "x": b64u(raw)}
        public_path.write_text(json.dumps(jwk))
        os.replace(partial, private_path)
        return jwk

    def public_jwk(self, scope: str, handle: str) -> dict:
        path = self.paths(scope, handle)[1]
        if not path.exists():
            raise KeystoreError(f"no key for '{handle}' ({scope}) on this machine")
        return json.loads(path.read_text())

    def sign(self, scope: str, handle: str, message: bytes) -> str:
        return b64u(self.private_key(scope, handle).sign(message))

    def private_key(self, scope: str, handle: str) -> Ed25519PrivateKey:
        private_path = self.paths(scope, handle)[0]
        if not private_path.exists():
            raise KeystoreError(f"no key for '{handle}' ({scope}) on this machine")
        passphrase = Passphrase(self.account(scope, handle)).get()
        if passphrase is None:
            raise KeystoreError(
                "the key's passphrase is unavailable: set SYMPOSIUM_KEY_PASSPHRASE in your "
                "own shell, or unlock the OS keychain"
            )
        try:
            return serialization.load_pem_private_key(
                private_path.read_bytes(), password=passphrase
            )
        except ValueError:
            raise KeystoreError(
                "the key's passphrase does not open it: check SYMPOSIUM_KEY_PASSPHRASE"
            ) from None

    def account(self, scope: str, handle: str) -> str:
        return f"{self.server_id}/{scope}/{handle}"
