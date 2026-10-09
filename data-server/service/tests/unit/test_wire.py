import base64
import hashlib
import json
import uuid

import pytest

from symposium_data.wire import (
    WireError,
    digest_header,
    parse_citation,
    parse_digest,
    parse_instant,
    parse_metadata,
    stamp,
    valid_community,
    valid_file_name,
    valid_sha256,
)


def test_digest_header_round_trips():
    sha = hashlib.sha256(b"hello").hexdigest()
    assert parse_digest(digest_header(sha)) == sha


@pytest.mark.parametrize(
    "value",
    [None, "", "sha-256=abc", "md5=:AAAA:", "sha-256=:not base64!:", "sha-256=:AAAA:"],
)
def test_bad_digests_are_refused(value):
    with pytest.raises(WireError) as e:
        parse_digest(value)
    assert e.value.status == 400


def _b64u(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def test_metadata_header_decodes_a_json_object():
    assert parse_metadata(_b64u({"produced_by": "@x"})) == {"produced_by": "@x"}
    assert parse_metadata(None) is None


@pytest.mark.parametrize(
    ("raw", "status"),
    [(_b64u([1, 2]), 400), ("%%%", 400), (_b64u({"x": "a" * 200_000}), 413)],
)
def test_bad_metadata_is_refused(raw, status):
    with pytest.raises(WireError) as e:
        parse_metadata(raw)
    assert e.value.status == status


@pytest.mark.parametrize("name", ["paper.pdf", "lyra_pub_v1", "table 1.csv", "a" * 255])
def test_valid_file_names(name):
    assert valid_file_name(name)


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "tab\there", "a" * 256])
def test_invalid_file_names(name):
    assert not valid_file_name(name)


def test_etag_round_trips_through_if_match():
    from symposium_data.wire import etag, parse_if_match

    assert etag(3) == '"v3"'
    assert parse_if_match(etag(3)) == 3
    assert parse_if_match(None) is None


@pytest.mark.parametrize(
    "value", ["v3", '"3"', '"v0"', '"v3", "v4"', "*", 'W/"v3"', '"vx"']
)
def test_if_match_accepts_only_one_strong_version_etag(value):
    from symposium_data.wire import parse_if_match

    with pytest.raises(WireError) as e:
        parse_if_match(value)
    assert e.value.status == 400


def test_stamp_sets_the_member_a_pointer_names():
    doc = {"artifact": {"created": None, "tags": ["a", "b"]}, "a/b": {"~x": 1}}
    stamp(doc, "/artifact/created", "2026-10-01T00:00:00+00:00")
    stamp(doc, "/artifact/tags/1", "z")
    stamp(doc, "/a~1b/~0x", 2)
    stamp(doc, "/artifact/new", True)
    assert doc == {
        "artifact": {
            "created": "2026-10-01T00:00:00+00:00",
            "tags": ["a", "z"],
            "new": True,
        },
        "a/b": {"~x": 2},
    }


@pytest.mark.parametrize(
    "pointer",
    ["artifact", "/missing/created", "/artifact/tags/9", "/artifact/tags/x", "/n/x"],
)
def test_stamp_refuses_a_pointer_without_a_parent(pointer):
    doc = {"artifact": {"tags": ["a"]}, "n": 3}
    with pytest.raises(WireError) as e:
        stamp(doc, pointer, "v")
    assert e.value.status == 422


def test_instants_need_an_offset():
    assert parse_instant("2026-10-01T12:00:00Z").utcoffset().total_seconds() == 0
    assert (
        parse_instant("2026-10-01T12:00:00+02:00").utcoffset().total_seconds() == 7200
    )
    for bad in ("2026-10-01T12:00:00", "yesterday"):
        with pytest.raises(WireError) as e:
            parse_instant(bad)
        assert e.value.status == 400


def test_sha256_is_64_lowercase_hex():
    assert valid_sha256(hashlib.sha256(b"x").hexdigest())
    assert not valid_sha256(hashlib.sha256(b"x").hexdigest().upper())
    assert not valid_sha256("abc")


def test_citations_parse_to_file_and_version():
    fid = "0b5e3a52-6a4f-4d55-9a65-1f3c2b7d9e10"
    assert parse_citation(f"symposium-data:{fid}@v3") == (uuid.UUID(fid), 3)
    for bad in (
        f"symposium-data:{fid}@v0",
        f"symposium-data:{fid}",
        f"other:{fid}@v1",
        "",
    ):
        assert parse_citation(bad) is None


@pytest.mark.parametrize(
    "name", ["comm1", "Comm_1", "a", "x" * 20, "lab_2026", "STATUS_x"]
)
def test_community_names_are_slugs(name):
    assert valid_community(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "x" * 21,
        "my comm",
        "my-comm",
        "comm.1",
        "café",
        "status",
        "Communities",
        "ADMIN",
    ],
)
def test_community_names_that_are_not_slugs_or_are_reserved_are_refused(name):
    assert not valid_community(name)
