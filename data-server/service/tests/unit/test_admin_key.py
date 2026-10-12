"""R-D4: who the server admin is, decided at start-up from the key file and the backup. One test
per case, on a temporary apps directory with fake records."""

import base64
import json
import logging
from contextlib import contextmanager

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from symposium_data.admin_key import AdminKeyFile
from symposium_data.auth import PublicKeys

KEYS = PublicKeys()


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_jwk(private: bool = False) -> dict:
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": b64u(raw)}
    if private:
        jwk["d"] = b64u(
            key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
        )
    return jwk


class FakeDb:
    @contextmanager
    def connection(self):
        yield None


class FakeRecords:
    """The admin binding: the handle, and every admin key with whether it is active."""

    def __init__(self, admin=None, jwk=None):
        self.admin, self.keys, self.events = admin, {}, []
        if jwk is not None:
            self.keys[KEYS.thumbprint(jwk)] = True

    def config(self, _conn, key):
        return self.admin if key == "admin" else None

    def admin_keys(self, _conn):
        return [{"kid": kid} for kid, active in self.keys.items() if active]

    def bind_admin(self, _conn, handle, kid, _jwk):
        self.admin, self.keys[kid] = handle, True
        self.events.append(("bind", handle, kid))

    def rebind_admin(self, _conn, handle, kid, _jwk):
        self.keys = {k: False for k in self.keys} | {kid: True}
        self.events.append(("rebind", handle, kid))


@pytest.fixture
def apps(tmp_path):
    (tmp_path / "data" / "config").mkdir(parents=True)
    return tmp_path


def place(apps, handle, content, where="."):
    """A key file in /apps (where `docker cp` puts it) or in /apps/admin-key (the directory
    the Helm chart mounts from its Secret)."""
    (apps / where).mkdir(exist_ok=True)
    path = apps / where / f"admin_pub_{handle}.key"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


def backup_of(apps) -> dict:
    return json.loads((apps / "data" / "config" / "admin_pub.backup").read_text())


def resolve(apps, records):
    return AdminKeyFile(apps, FakeDb(), records, KEYS).resolve()


def test_a_key_file_and_no_admin_binds_and_saves_the_backup(apps):
    jwk = new_jwk()
    place(apps, "lyra", jwk)
    records = FakeRecords()
    mode = resolve(apps, records)
    kid = KEYS.thumbprint(jwk)
    assert (mode.operational, mode.action, mode.handle, mode.fingerprint) == (
        True,
        "bound",
        "lyra",
        kid,
    )
    assert records.events == [("bind", "lyra", kid)]
    assert backup_of(apps) == {"handle": "lyra", "jwk": jwk}


def test_the_bound_key_starts_unchanged(apps):
    jwk = new_jwk()
    place(apps, "lyra", jwk)
    records = FakeRecords("lyra", jwk)
    mode = resolve(apps, records)
    assert mode.operational and mode.action == "unchanged"
    assert records.events == []
    assert backup_of(apps) == {
        "handle": "lyra",
        "jwk": jwk,
    }  # written if it was missing


def test_a_new_key_for_the_admin_rebinds_and_updates_the_backup(apps, caplog):
    old, new = new_jwk(), new_jwk()
    place(apps, "lyra", new)
    records = FakeRecords("lyra", old)
    mode = resolve(apps, records)
    kid = KEYS.thumbprint(new)
    assert mode.operational and mode.action == "rebound" and mode.fingerprint == kid
    assert records.keys == {
        KEYS.thumbprint(old): False,
        kid: True,
    }  # the old key retired
    assert backup_of(apps)["jwk"] == new
    assert "rebound" in caplog.text


def test_a_missing_key_file_runs_from_the_backup_and_writes_nothing(apps, caplog):
    jwk = new_jwk()
    place(apps, "lyra", jwk)
    resolve(apps, FakeRecords())  # binds and saves the backup
    (apps / "admin_pub_lyra.key").unlink()
    before = sorted(p.relative_to(apps) for p in apps.rglob("*"))

    records = FakeRecords("lyra", jwk)
    with caplog.at_level(logging.WARNING):
        mode = resolve(apps, records)
    assert mode.operational and mode.action == "backup" and mode.handle == "lyra"
    assert records.events == []
    assert "missing" in caplog.text and "backup" in caplog.text
    assert sorted(p.relative_to(apps) for p in apps.rglob("*")) == before


def test_a_key_file_for_another_handle_is_ignored_with_an_error(apps, caplog):
    jwk = new_jwk()
    place(apps, "lyra", jwk)
    resolve(apps, FakeRecords())
    (apps / "admin_pub_lyra.key").unlink()
    place(apps, "vega", new_jwk())

    records = FakeRecords("lyra", jwk)
    mode = resolve(apps, records)
    assert mode.operational and mode.handle == "lyra" and mode.action == "backup"
    assert records.events == []  # the admin handle never changes
    assert "admin_pub_vega.key" in caplog.text and "'lyra'" in caplog.text


def test_no_key_file_and_no_admin_is_not_operational(apps, caplog):
    mode = resolve(apps, FakeRecords())
    assert not mode.operational and mode.reason == "admin key not provided"
    assert "NOT OPERATIONAL" in caplog.text


def test_two_key_files_are_ambiguous(apps):
    place(apps, "lyra", new_jwk())
    place(apps, "vega", new_jwk())
    records = FakeRecords()
    mode = resolve(apps, records)
    assert not mode.operational and mode.reason == "ambiguous admin key files"
    assert records.events == []


def test_a_key_file_in_the_mounted_directory_binds(apps):
    jwk = new_jwk()
    place(apps, "lyra", jwk, "admin-key")
    records = FakeRecords()
    mode = resolve(apps, records)
    assert (mode.operational, mode.action, mode.handle) == (True, "bound", "lyra")
    assert backup_of(apps) == {"handle": "lyra", "jwk": jwk}


def test_one_key_file_in_each_place_is_ambiguous(apps):
    place(apps, "lyra", new_jwk())
    place(apps, "vega", new_jwk(), "admin-key")
    records = FakeRecords()
    mode = resolve(apps, records)
    assert not mode.operational and mode.reason == "ambiguous admin key files"
    assert records.events == []


def test_the_same_handle_in_both_places_is_ambiguous_even_once_bound(apps):
    jwk = new_jwk()
    place(apps, "lyra", jwk)
    place(apps, "lyra", jwk, "admin-key")
    records = FakeRecords("lyra", jwk)
    mode = resolve(apps, records)
    assert not mode.operational and mode.reason == "ambiguous admin key files"
    assert records.events == []


def test_initialized_with_neither_the_file_nor_the_backup_is_not_operational(
    apps, caplog
):
    records = FakeRecords("lyra", new_jwk())
    mode = resolve(apps, records)
    assert not mode.operational and mode.reason == "admin key missing"
    assert "admin_pub_lyra.key is missing" in caplog.text
    assert records.events == []


@pytest.mark.parametrize(
    "content, why",
    [
        ("not json", "not a JSON public key"),
        ('"a string"', "not a JSON public key"),
        ({"kty": "RSA", "n": "x", "e": "AQAB"}, "expected a public OKP/Ed25519 JWK"),
        (new_jwk(private=True), "PRIVATE key"),
    ],
)
@pytest.mark.parametrize("initialized", [False, True])
def test_an_invalid_key_file_is_not_operational(
    apps, caplog, content, why, initialized
):
    bound = new_jwk()
    if initialized:
        place(apps, "lyra", bound)
        resolve(apps, FakeRecords())  # the established admin and its backup
    place(apps, "lyra", content)
    records = FakeRecords("lyra", bound) if initialized else FakeRecords()
    backup = (
        (apps / "data" / "config" / "admin_pub.backup").read_bytes()
        if initialized
        else None
    )

    mode = resolve(apps, records)
    assert not mode.operational and mode.reason == "admin key invalid"
    assert "admin_pub_lyra.key" in caplog.text and why in caplog.text
    assert records.events == []  # nothing bound or rebound
    if initialized:
        assert (apps / "data" / "config" / "admin_pub.backup").read_bytes() == backup
