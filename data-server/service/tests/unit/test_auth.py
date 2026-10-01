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
