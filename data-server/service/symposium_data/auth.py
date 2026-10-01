"""Owner public keys: Ed25519 JWK validation and RFC 7638 thumbprints (the key id)."""

from __future__ import annotations

import base64
import hashlib
import json

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
