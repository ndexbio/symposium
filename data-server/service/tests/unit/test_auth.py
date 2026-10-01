import pytest

from symposium_data.auth import PublicKeys

# RFC 8037 Appendix A.2/A.3: the Ed25519 example key and its RFC 7638 thumbprint.
RFC8037_JWK = {
    "kty": "OKP",
    "crv": "Ed25519",
    "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo",
}
RFC8037_THUMBPRINT = "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"


def test_thumbprint_matches_rfc8037_example():
    assert PublicKeys().thumbprint(RFC8037_JWK) == RFC8037_THUMBPRINT


def test_thumbprint_ignores_member_order_and_extra_members():
    reordered = {
        "x": RFC8037_JWK["x"],
        "kid": "anything",
        "crv": "Ed25519",
        "kty": "OKP",
    }
    assert PublicKeys().thumbprint(reordered) == RFC8037_THUMBPRINT


def test_validate_accepts_public_ed25519_jwk():
    PublicKeys().validate(RFC8037_JWK)


@pytest.mark.parametrize(
    "jwk",
    [
        {**RFC8037_JWK, "d": "nWGxne_9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A"},
        {**RFC8037_JWK, "crv": "X25519"},
        {"kty": "RSA", "n": "x", "e": "AQAB"},
        {"kty": "OKP", "crv": "Ed25519"},
        {"kty": "OKP", "crv": "Ed25519", "x": "c2hvcnQ"},
        "not a dict",
    ],
    ids=["private-part", "wrong-curve", "rsa", "no-x", "short-key", "not-a-dict"],
)
def test_validate_refuses_anything_else(jwk):
    with pytest.raises(ValueError):
        PublicKeys().validate(jwk)


# ── signatures, secrets, tokens ─────────────────────────────────────────────────────────────
def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": PublicKeys().b64u(raw)}
    return private, jwk


def test_verify_accepts_the_keys_own_signature_only():
    pk = PublicKeys()
    private, jwk = _keypair()
    _, other_jwk = _keypair()
    signature = pk.b64u(private.sign(b"n_abc"))
    assert pk.verify(jwk, b"n_abc", signature)
    assert not pk.verify(jwk, b"n_other", signature)
    assert not pk.verify(other_jwk, b"n_abc", signature)
    assert not pk.verify(jwk, b"n_abc", "not-base64!")


def test_secrets_are_prefixed_unique_and_hashed():
    from symposium_data.auth import Secrets

    s = Secrets()
    a, b = s.new("sdi_"), s.new("sdi_")
    assert a.startswith("sdi_") and a != b and len(a) > 40
    assert s.digest(a) == s.digest(a) != s.digest(b)
    assert a not in s.digest(a)


def _write_key(path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return str(path)


def test_tokens_round_trip(tmp_path):
    from symposium_data.auth import Tokens

    tokens = Tokens(_write_key(tmp_path / "k.pem"), "server-1", 60)
    claims = tokens.read(tokens.issue("lyra", "kid-1"))
    assert claims["sub"] == "lyra" and claims["kid"] == "kid-1"
    assert claims["exp"] - claims["iat"] == 60


def test_tokens_refuse_expired_foreign_and_other_issuer(tmp_path):
    from symposium_data.auth import Tokens

    mine = _write_key(tmp_path / "mine.pem")
    other = _write_key(tmp_path / "other.pem")
    expired = Tokens(mine, "s", -1)
    assert expired.read(expired.issue("a", "k")) is None
    token = Tokens(mine, "s", 60).issue("a", "k")
    assert Tokens(other, "s", 60).read(token) is None
    assert Tokens(mine, "another-server", 60).read(token) is None
    assert Tokens(mine, "s", 60).read("garbage") is None
