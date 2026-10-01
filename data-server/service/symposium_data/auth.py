"""Identity primitives: owner public keys (Ed25519 JWKs, RFC 7638 key ids), bearer secrets
stored as hashes, and the server's short-lived EdDSA access tokens."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class PublicKeys:
    def b64u_decode(self, text: str) -> bytes:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    def b64u(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def validate(self, jwk: dict) -> Ed25519PublicKey:
        """Accept only a public OKP/Ed25519 JWK; anything carrying a private part is refused."""
        if (
            not isinstance(jwk, dict)
            or jwk.get("kty") != "OKP"
            or jwk.get("crv") != "Ed25519"
            or "x" not in jwk
            or "d" in jwk
        ):
            raise ValueError("expected a public OKP/Ed25519 JWK")
        raw = self.b64u_decode(jwk["x"])
        if len(raw) != 32:
            raise ValueError("an Ed25519 public key is 32 bytes")
        return Ed25519PublicKey.from_public_bytes(raw)

    def thumbprint(self, jwk: dict) -> str:
        """RFC 7638 thumbprint over the required OKP members, in lexicographic order."""
        canon = json.dumps(
            {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]},
            separators=(",", ":"),
            sort_keys=True,
        )
        return self.b64u(hashlib.sha256(canon.encode()).digest())

    def verify(self, jwk: dict, message: bytes, signature_b64u: str) -> bool:
        """True when `signature_b64u` is this key's Ed25519 signature over `message`."""
        try:
            self.validate(jwk).verify(self.b64u_decode(signature_b64u), message)
            return True
        except Exception:
            return False


class Secrets:
    """Bearer secrets (invites now, read keys later): random, prefixed, stored only as hashes."""

    def new(self, prefix: str) -> str:
        return prefix + base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()

    def digest(self, secret: str) -> str:
        return hashlib.sha256(secret.encode()).hexdigest()


class Tokens:
    """Short-lived EdDSA access tokens, signed with the server's first-boot key."""

    def __init__(self, key_file: str, issuer: str, ttl_seconds: int):
        pem = Path(key_file).read_bytes()
        self.signing_key = serialization.load_pem_private_key(pem, password=None)
        self.issuer = issuer
        self.ttl = ttl_seconds

    def issue(self, handle: str, kid: str) -> str:
        now = int(time.time())
        claims = {
            "sub": handle,
            "kid": kid,
            "iat": now,
            "exp": now + self.ttl,
            "iss": self.issuer,
        }
        return jwt.encode(claims, self.signing_key, algorithm="EdDSA")

    def read(self, token: str) -> dict | None:
        """The claims of a valid, unexpired token from this server; None otherwise."""
        try:
            return jwt.decode(
                token,
                self.signing_key.public_key(),
                algorithms=["EdDSA"],
                issuer=self.issuer,
                options={"require": ["sub", "kid", "exp", "iss"]},
            )
        except jwt.PyJWTError:
            return None
