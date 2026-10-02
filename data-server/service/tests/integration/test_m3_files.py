"""M3: files and versions: streaming, integrity, versions, tombstones, the clock, quota,
purge, the janitor and the scrub."""

import base64
import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import pairwise

import httpx
import pytest
from conftest import assert_consistent, community_with, psql, repr_digest

GIB = 1024**3


@pytest.fixture
def demo(server):
    admin, owners = community_with(server)
    return server, admin, owners


def test_round_trip_with_headers_and_stat(demo):
    _, _, owners = demo
    lyra = owners["lyra"]
    data = b"gene,score\nBST2,0.91\n"
    r = lyra.put("demo", "files", "scores.csv", data, {"produced_by": "@x"}, "text/csv")
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["citation"] == f"symposium-data:{v1['file_id']}@v1"
    assert v1["sha256"] == hashlib.sha256(data).hexdigest() and v1["size"] == len(data)
    assert v1["created_by"] == "lyra" and v1["key_id"]
    assert v1["prev"] is None and v1["next"] is None and v1["latest"] == 1

    got = lyra.get(v1["file_id"], 1)
    assert got.status_code == 200 and got.content == data
    assert got.headers["repr-digest"] == repr_digest(data)
    assert got.headers["x-data-version"] == "1"
    assert got.headers["x-data-deleted"] == "false"
    assert got.headers["content-type"].startswith("text/csv")
    assert 'rel="latest"' in got.headers["link"]
    stat = lyra.stat(v1["file_id"], 1).json()
    assert stat["metadata"] == {"produced_by": "@x"} and stat["integrity"] == "ok"


def test_one_gib_streams_up_and_back(demo):
    _, _, owners = demo
    lyra = owners["lyra"]
    block = os.urandom(8 * 1024 * 1024)
    sha = hashlib.sha256()
    for i in range(GIB // len(block)):
        sha.update(block[i % 7 :] + block[: i % 7])
    digest = sha.digest()

    def body():
        for i in range(GIB // len(block)):
            yield block[i % 7 :] + block[: i % 7]

    headers = {
        **lyra.headers(),
        "Repr-Digest": "sha-256=:" + base64.b64encode(digest).decode() + ":",
        "X-Data-Size": str(GIB),
    }
    r = httpx.put(
        f"{lyra.server.url}/v1/c/demo/files/files/big.bin",
        content=body(),
        headers=headers,
        timeout=1800,
    )
    assert r.status_code == 201, r.text
    assert r.json()["size"] == GIB

    down = hashlib.sha256()
    size = 0
    with httpx.stream(
        "GET",
        f"{lyra.server.url}/v1/files/{r.json()['file_id']}/v/1",
        headers=lyra.headers(),
        timeout=1800,
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_bytes(1024 * 1024):
            down.update(chunk)
            size += len(chunk)
    assert size == GIB and down.digest() == digest


def test_digest_mismatch_leaves_no_payload_row_or_object(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    before = psql(server, "SELECT count(*) FROM payloads")
    data = os.urandom(12 * 1024 * 1024)  # large enough to use a multipart upload
    r = httpx.put(
        f"{server.url}/v1/c/demo/files/files/bad.bin",
        content=data,
        headers={**lyra.headers(), "Repr-Digest": repr_digest(b"something else")},
        timeout=300,
    )
    assert r.status_code == 400
    assert psql(server, "SELECT count(*) FROM payloads") == before
    assert psql(server, "SELECT count(*) FROM files WHERE name = 'bad.bin'") == "0"
    assert_consistent(server)


def test_identical_content_is_stored_once(demo):
    server, _, owners = demo
    data = b"same bytes"
    a = owners["lyra"].put("demo", "files", "a.txt", data).json()
    b = owners["vega"].put("demo", "files", "b.txt", data).json()
    assert a["sha256"] == b["sha256"] and a["file_id"] != b["file_id"]
    assert (
        psql(server, f"SELECT count(*) FROM payloads WHERE sha256 = '{a['sha256']}'")
        == "1"
    )
    assert_consistent(server)


def test_versions_links_and_metadata_rules(demo):
    _, _, owners = demo
    lyra = owners["lyra"]
    v1 = lyra.put("demo", "files", "notes.txt", b"one", {"a": 1}).json()
    fid = v1["file_id"]
    v2 = lyra.version(fid, metadata={"b": 2}).json()  # metadata only
    assert (
        v2["version"] == 2
        and v2["sha256"] == v1["sha256"]
        and v2["metadata"] == {"b": 2}
    )
    v3 = lyra.version(fid, data=b"three").json()  # content only keeps the metadata
    assert (
        v3["metadata"] == {"b": 2}
        and v3["sha256"] == hashlib.sha256(b"three").hexdigest()
    )

    links = [(v["version"], v["prev"], v["next"]) for v in _versions(lyra, fid)]
    assert links == [(1, None, 2), (2, 1, 3), (3, 2, None)]
    assert lyra.get(fid, 1).content == b"one"
    assert lyra.get(fid, "latest").headers["x-data-version"] == "3"


def _versions(owner, fid):
    r = httpx.get(
        f"{owner.server.url}/v1/files/{fid}/versions", headers=owner.headers()
    )
    assert r.status_code == 200, r.text
    return r.json()["versions"]


def test_tombstones_keep_every_version_readable(demo):
    _, _, owners = demo
    lyra = owners["lyra"]
    fid = lyra.put("demo", "files", "withdrawn.txt", b"v1").json()["file_id"]
    lyra.version(fid, data=b"v2")

    tomb = lyra.delete(fid, reason="withdrawn")
    assert tomb.status_code == 200, tomb.text
    tomb = tomb.json()
    assert tomb["version"] == 3 and tomb["deleted"] and tomb["reason"] == "withdrawn"
    assert tomb["sha256"] == hashlib.sha256(b"v2").hexdigest()

    latest = lyra.stat(fid, "latest").json()
    assert latest["version"] == 2 and latest["file_deleted"] is True
    tomb_read = lyra.get(fid, 3)
    assert tomb_read.content == b"v2" and tomb_read.headers["x-data-deleted"] == "true"
    assert lyra.get(fid, 1).content == b"v1"
    assert lyra.delete(fid).status_code == 409

    revived = lyra.version(fid, data=b"v4").json()
    assert revived["version"] == 4 and revived["file_deleted"] is False
    assert lyra.stat(fid, "latest").json()["version"] == 4


def test_only_the_creator_or_admin_changes_a_file(demo):
    _, admin, owners = demo
    fid = owners["lyra"].put("demo", "files", "mine.txt", b"lyra's").json()["file_id"]
    vega = owners["vega"]
    assert vega.version(fid, data=b"overwrite").status_code == 403
    assert vega.version(fid, metadata={"x": 1}).status_code == 403
    assert vega.delete(fid).status_code == 403
    assert vega.get(fid).content == b"lyra's"  # still readable by members
    assert admin.version(fid, metadata={"reviewed": True}).status_code == 201


def test_errors(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    assert lyra.put("demo", "files", "dup.txt", b"x").status_code == 201
    assert lyra.put("demo", "files", "dup.txt", b"y").status_code == 409
    assert lyra.put("demo", "nope", "a.txt", b"x").status_code == 404
    assert (
        lyra.put("demo", "record", "a.txt", b"x").status_code == 403
    )  # read-only for members
    assert lyra.put("demo", "files", "..", b"x").status_code in (400, 404)
    missing = "00000000-0000-0000-0000-000000000000"
    assert lyra.stat(missing, 1).status_code == 404
    fid = lyra.put("demo", "files", "f.txt", b"x").json()["file_id"]
    assert lyra.stat(fid, 9).status_code == 404
    assert httpx.get(f"{server.url}/v1/files/{fid}/v/1").status_code == 401


def test_inbox_submissions_are_private_to_submitter_admin_and_recipients(demo):
    _, admin, owners = demo
    lyra, vega, rigel = owners["lyra"], owners["vega"], owners["rigel"]
    fid = lyra.put("demo", "inbox", "sub.json", b"{}").json()["file_id"]
    assert vega.get(fid).status_code == 403
    assert admin.get(fid).status_code == 200
    reply = admin.put(
        "demo", "inbox", "reply.json", b"{}", {"recipients": ["vega"]}
    ).json()
    assert vega.get(reply["file_id"]).status_code == 200
    assert rigel.get(reply["file_id"]).status_code == 403


def test_twenty_concurrent_writers_get_a_gap_free_increasing_clock(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    lyra.headers()  # fetch the token once, before the threads start
    start = int(
        psql(
            server,
            "SELECT seq FROM collections WHERE community='demo' AND name='files'",
        )
    )
    lock = threading.Lock()
    results = []

    def write(i):
        r = lyra.put("demo", "files", f"c{i}.txt", f"concurrent {i}".encode())
        with lock:
            results.append(r)

    with ThreadPoolExecutor(20) as pool:
        list(pool.map(write, range(20)))
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    by_seq = sorted((r.json() for r in results), key=lambda v: v["seq"])
    assert [v["seq"] for v in by_seq] == list(range(start + 1, start + 21))
    created = [datetime.fromisoformat(v["created"]) for v in by_seq]
    assert all(a < b for a, b in pairwise(created))


def test_range_requests_return_206(demo):
    _, _, owners = demo
    lyra = owners["lyra"]
    data = bytes(range(256)) * 100
    fid = lyra.put("demo", "files", "range.bin", data).json()["file_id"]
    r = lyra.get(fid, 1, headers={"Range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.content == data[100:200]
    assert r.headers["content-range"] == f"bytes 100-199/{len(data)}"
    assert r.headers["repr-digest"] == repr_digest(data)


def test_suspect_versions_are_flagged(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    early = lyra.put("demo", "files", "early.txt", b"before").json()
    time.sleep(1)
    instant = datetime.now().astimezone().isoformat()
    time.sleep(1)
    assert (
        server.admin("suspect-after", "--handle", "lyra", "--at", instant).returncode
        == 0
    )
    late = lyra.put("demo", "files", "late.txt", b"after").json()
    assert lyra.stat(early["file_id"], 1).json()["suspect"] is False
    assert late["suspect"] is True


def test_quota_refuses_with_413(make_server):
    server = make_server(SYMPOSIUM_DATA_QUOTA_BYTES="1000")
    _, owners = community_with(server, ("lyra",))
    lyra = owners["lyra"]
    assert lyra.put("demo", "files", "a.bin", os.urandom(600)).status_code == 201
    assert lyra.put("demo", "files", "b.bin", os.urandom(600)).status_code == 413
    assert_consistent(server)


def test_purge_answers_410_and_frees_bytes_when_unshared(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    v1 = lyra.put("demo", "files", "secret.txt", b"to be purged", {"k": 1}).json()
    fid = v1["file_id"]
    lyra.version(fid, metadata={"k": 2})  # v2 shares v1's payload

    first = server.admin("purge", "--cite", v1["citation"])
    assert first.returncode == 0 and '"bytes_freed": false' in first.stdout
    gone = lyra.get(fid, 1)
    assert gone.status_code == 410 and gone.json()["metadata"] == {"k": 1}
    assert lyra.get(fid, 2).content == b"to be purged"  # still shared, still served

    second = server.admin("purge", "--cite", f"symposium-data:{fid}@v2")
    assert second.returncode == 0 and '"bytes_freed": true' in second.stdout
    assert lyra.get(fid, 2).status_code == 410
    assert lyra.stat(fid, 2).json()["purged"] is True
    bad = f"symposium-data:{fid}@v9"
    assert server.admin("purge", "--cite", bad).returncode == 2
    assert_consistent(server)


def test_janitor_sweeps_stale_pending_payloads(make_server):
    server = make_server(
        SYMPOSIUM_DATA_PENDING_TTL="5", SYMPOSIUM_DATA_JANITOR_INTERVAL="1"
    )
    community_with(server, ("lyra",))
    psql(
        server,
        "INSERT INTO payloads (id, state, s3_key, first_owner, created) VALUES "
        "('11111111-1111-1111-1111-111111111111', 'pending', 'payloads/stale', 'lyra', "
        "now() - interval '1 hour')",
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if psql(server, "SELECT count(*) FROM payloads WHERE state = 'pending'") == "0":
            break
        time.sleep(1)
    assert psql(server, "SELECT count(*) FROM payloads WHERE state = 'pending'") == "0"


def test_scrub_flags_corrupted_content(make_server):
    server = make_server(SYMPOSIUM_DATA_SCRUB_INTERVAL="1")
    _, owners = community_with(server, ("lyra",))
    lyra = owners["lyra"]
    bad = lyra.put("demo", "files", "rot.bin", b"original bytes").json()
    good = lyra.put("demo", "files", "fine.bin", b"untouched bytes").json()
    key = psql(
        server,
        "SELECT p.s3_key FROM payloads p JOIN versions v ON v.payload_id = p.id "
        f"WHERE v.file_id = '{bad['file_id']}'",
    )
    server.exec(
        "/opt/venv/bin/python",
        "-c",
        "from symposium_data.runtime import Settings, PayloadStore;"
        f"PayloadStore(Settings()).put_bytes('{key}', b'bit rot')",
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if lyra.stat(bad["file_id"], 1).json()["integrity"] == "mismatch":
            break
        time.sleep(1)
    assert lyra.stat(bad["file_id"], 1).json()["integrity"] == "mismatch"
    assert lyra.stat(good["file_id"], 1).json()["integrity"] == "ok"
