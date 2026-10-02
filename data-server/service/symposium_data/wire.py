"""Wire formats of the file API: the Repr-Digest header, metadata headers and file names."""

from __future__ import annotations

import base64
import json
import re

# A file name is one path segment: no slashes, no control characters, not . or ..
FILE_NAME = re.compile(r"^(?!\.{1,2}$)[^/\x00-\x1f\x7f]{1,255}$")
MAX_METADATA = 64 * 1024


class WireError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def parse_digest(value: str | None) -> str:
    """`sha-256=:<base64>:` (RFC 9530) -> the sha-256 as hex."""
    if not value or not value.startswith("sha-256=:") or not value.endswith(":"):
        raise WireError(400, "Repr-Digest: sha-256=:<base64>: is required")
    try:
        raw = base64.b64decode(value[len("sha-256=:") : -1], validate=True)
    except ValueError:
        raise WireError(400, "Repr-Digest is not valid base64") from None
    if len(raw) != 32:
        raise WireError(400, "Repr-Digest must carry a 32-byte sha-256")
    return raw.hex()


def digest_header(sha_hex: str) -> str:
    return "sha-256=:" + base64.b64encode(bytes.fromhex(sha_hex)).decode() + ":"


def parse_metadata(raw: str | None) -> dict | None:
    """X-Data-Metadata: a base64url-encoded JSON object. None when the header is absent."""
    if raw is None:
        return None
    if len(raw) > MAX_METADATA * 2:
        raise WireError(413, "metadata is too large")
    try:
        value = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except ValueError:
        raise WireError(400, "X-Data-Metadata must be base64url-encoded JSON") from None
    if not isinstance(value, dict):
        raise WireError(400, "metadata must be a JSON object")
    return value


def valid_file_name(name: str) -> bool:
    return FILE_NAME.match(name) is not None


ETAG = re.compile(r'^"v([1-9][0-9]{0,9})"$')


def etag(version: int) -> str:
    """The ETag of a file version: "v<n>" (RFC 9110 strong validator)."""
    return f'"v{version}"'


def parse_if_match(value: str | None) -> int | None:
    """If-Match: "v<n>" -> n, the head the client built on. None when the header is absent."""
    if value is None:
        return None
    match = ETAG.match(value.strip())
    if not match:
        raise WireError(400, 'If-Match must be one version ETag, e.g. "v3"')
    return int(match.group(1))
