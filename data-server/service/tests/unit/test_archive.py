import json

import pytest

from symposium_data.archive import FORMAT, FORMAT_VERSION, Archive, Malformed

archive = Archive(None, None, None, None)


def test_a_manifest_must_name_this_format_and_version():
    good = {"format": FORMAT, "format_version": FORMAT_VERSION, "community": "demo"}
    assert archive.read_manifest(json.dumps(good).encode())["community"] == "demo"
    for bad in (
        b"not json",
        json.dumps({**good, "format": "other"}).encode(),
        json.dumps({**good, "format_version": FORMAT_VERSION + 1}).encode(),
    ):
        with pytest.raises(Malformed):
            archive.read_manifest(bad)


def test_only_stored_versions_carry_bytes():
    tables = {
        "versions": [
            {"sha256": "a" * 64, "stored": True, "size": 1},
            {"sha256": "b" * 64, "stored": False, "size": 2},
        ]
    }
    assert set(archive.stored(tables)) == {"a" * 64}
    with pytest.raises(Malformed):
        archive.stored({})
