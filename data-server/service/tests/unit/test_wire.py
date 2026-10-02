import base64
import hashlib
import json

import pytest

from symposium_data.wire import (
    WireError,
    digest_header,
    parse_digest,
    parse_metadata,
    valid_file_name,
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
