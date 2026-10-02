"""M3, R-A6: write atomicity and concurrency. Every racing or failing write either fully
happens or leaves nothing behind: no pending or unreferenced payload, no orphaned S3 object,
no open multipart upload and no stale name reservation."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from conftest import (
    assert_consistent,
    b64u_json,
    community_with,
    psql,
    repr_digest,
    untracked_objects,
)


@pytest.fixture
def demo(server):
    admin, owners = community_with(server)
    return server, admin, owners


def slow_body(
    data: bytes, pieces: int, pause: float, gate: threading.Event | None = None
):
    def body():
        if gate is not None:
            gate.wait(30)
        step = len(data) // pieces
        for i in range(0, len(data), step):
            yield data[i : i + step]
            time.sleep(pause)

    return body()


def put_stream(owner, name, data, body, timeout=120):
    return httpx.put(
        f"{owner.server.url}/v1/c/demo/files/files/{name}",
        content=body,
        headers={
            **owner.headers(),
            "Repr-Digest": repr_digest(data),
            "X-Data-Size": str(len(data)),
        },
        timeout=timeout,
    )


def test_a_concurrent_duplicate_name_is_refused_before_it_uploads(demo):
    server, _, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    data = os.urandom(4 * 1024 * 1024)
    first = {}

    def slow_create():
        first["r"] = put_stream(lyra, "contested.bin", data, slow_body(data, 20, 0.25))

    thread = threading.Thread(target=slow_create)
    thread.start()
    time.sleep(1.5)  # lyra's upload is under way and holds the name
    started = time.time()
    second = vega.put("demo", "files", "contested.bin", os.urandom(4 * 1024 * 1024))
    assert second.status_code == 409, second.text
    assert time.time() - started < 3, (
        "the duplicate should be refused before it uploads"
    )
    thread.join(60)
    assert first["r"].status_code == 201, first["r"].text
    assert lyra.get(first["r"].json()["file_id"], 1).content == data
    assert_consistent(server)


def test_a_failed_upload_releases_the_name_and_leaves_nothing(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    data = os.urandom(12 * 1024 * 1024)
    bad = httpx.put(
        f"{server.url}/v1/c/demo/files/files/retry.bin",
        content=data,
        headers={**lyra.headers(), "Repr-Digest": repr_digest(b"not the body")},
        timeout=120,
    )
    assert bad.status_code == 400
    assert_consistent(server)
    assert lyra.put("demo", "files", "retry.bin", data).status_code == 201
    assert_consistent(server)


def test_a_client_disconnect_mid_upload_leaves_nothing(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    data = os.urandom(20 * 1024 * 1024)

    def broken_body():
        yield data[: 10 * 1024 * 1024]
        raise ConnectionAbortedError("client went away")

    with pytest.raises((ConnectionAbortedError, httpx.HTTPError)):
        put_stream(lyra, "abandoned.bin", data, broken_body())
    assert_consistent(server)  # polls: the server cleans up once it sees the disconnect
    assert lyra.put("demo", "files", "abandoned.bin", b"second try").status_code == 201
    assert_consistent(server)


def test_concurrent_uploads_cannot_jointly_exceed_the_quota(make_server):
    server = make_server(SYMPOSIUM_DATA_QUOTA_BYTES="1000")
    _, owners = community_with(server, ("lyra",))
    lyra = owners["lyra"]
    lyra.headers()
    gate = threading.Event()
    results = []

    def upload(i):
        data = os.urandom(600)
        # both pass the early quota check, then stream together and race to commit
        results.append(
            put_stream(lyra, f"q{i}.bin", data, slow_body(data, 2, 0.1, gate))
        )

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    time.sleep(1.5)
    gate.set()
    for t in threads:
        t.join(60)
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 413], [r.text for r in results]
    assert (
        int(
            psql(
                server,
                "SELECT COALESCE(SUM(size), 0) FROM payloads WHERE state = 'ready'",
            )
        )
        <= 1000
    )
    assert_consistent(server)


def test_identical_content_racing_is_stored_once_without_orphans(demo):
    server, _, owners = demo
    data = os.urandom(3 * 1024 * 1024)
    names = [("lyra", "same-a.bin"), ("vega", "same-b.bin"), ("rigel", "same-c.bin")]
    for handle, _ in names:
        owners[handle].headers()
    with ThreadPoolExecutor(3) as pool:
        results = list(
            pool.map(lambda hn: owners[hn[0]].put("demo", "files", hn[1], data), names)
        )
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert len({r.json()["sha256"] for r in results}) == 1
    assert_consistent(server)


def test_if_match_applies_a_write_only_on_the_expected_head(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    created = lyra.put("demo", "files", "edited.txt", b"v1")
    assert created.headers["etag"] == '"v1"'
    fid = created.json()["file_id"]
    url = f"{server.url}/v1/files/{fid}/versions"

    def meta_version(if_match, meta):
        return httpx.post(
            url,
            content=b"",
            headers={
                **lyra.headers(),
                "X-Data-Metadata-Only": "1",
                "X-Data-Metadata": b64u_json(meta),
                "If-Match": if_match,
            },
        )

    ok = meta_version('"v1"', {"edit": 1})
    assert ok.status_code == 201 and ok.headers["etag"] == '"v2"'
    stale = meta_version('"v1"', {"edit": 2})
    assert stale.status_code == 412
    assert meta_version("v2", {"edit": 3}).status_code == 400  # not a quoted ETag

    stale_content = httpx.post(
        url,
        content=os.urandom(5 * 1024 * 1024),
        headers={
            **lyra.headers(),
            "Repr-Digest": repr_digest(b"x"),
            "If-Match": '"v1"',
        },
    )
    assert stale_content.status_code == 412  # refused before any bytes are stored

    stale_delete = httpx.delete(
        f"{server.url}/v1/files/{fid}", headers={**lyra.headers(), "If-Match": '"v1"'}
    )
    assert stale_delete.status_code == 412
    deleted = httpx.delete(
        f"{server.url}/v1/files/{fid}", headers={**lyra.headers(), "If-Match": '"v2"'}
    )
    assert deleted.status_code == 200 and deleted.headers["etag"] == '"v3"'

    assert lyra.stat(fid, 2).headers["etag"] == '"v2"'
    assert [
        v["version"] for v in httpx.get(url, headers=lyra.headers()).json()["versions"]
    ] == [
        1,
        2,
        3,
    ]
    assert_consistent(server)


def test_racing_writers_with_the_same_if_match_produce_exactly_one_version(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    fid = lyra.put("demo", "files", "race.txt", b"base").json()["file_id"]
    lyra.headers()

    def write(i):
        return httpx.post(
            f"{server.url}/v1/files/{fid}/versions",
            content=f"edit {i}".encode(),
            headers={
                **lyra.headers(),
                "Repr-Digest": repr_digest(f"edit {i}".encode()),
                "If-Match": '"v1"',
            },
            timeout=60,
        )

    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(write, range(10)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [412] * 9, codes
    versions = httpx.get(
        f"{server.url}/v1/files/{fid}/versions", headers=lyra.headers()
    )
    assert [v["version"] for v in versions.json()["versions"]] == [1, 2]
    assert_consistent(server)


def test_the_janitor_expires_stale_reservations(make_server):
    server = make_server(
        SYMPOSIUM_DATA_PENDING_TTL="5", SYMPOSIUM_DATA_JANITOR_INTERVAL="1"
    )
    _, owners = community_with(server, ("lyra",))
    psql(
        server,
        "INSERT INTO files (id, community, collection, name, state, reserved_by, reserved_at) "
        "VALUES ('22222222-2222-2222-2222-222222222222', 'demo', 'files', 'crashed.bin', "
        "'reserved', 'lyra', now() - interval '1 hour')",
    )
    assert owners["lyra"].put("demo", "files", "crashed.bin", b"x").status_code == 409
    assert_consistent(server)  # polls until the janitor has expired the reservation
    assert owners["lyra"].put("demo", "files", "crashed.bin", b"x").status_code == 201


def test_a_long_upload_outlives_the_ttl_because_it_heartbeats(make_server):
    # The janitor reaps work older than 3 s every second; this upload streams for ~8 s. Its
    # heartbeat keeps its reservation and pending payload fresh, so it must still commit.
    server = make_server(
        SYMPOSIUM_DATA_PENDING_TTL="3", SYMPOSIUM_DATA_JANITOR_INTERVAL="1"
    )
    _, owners = community_with(server, ("lyra",))
    lyra = owners["lyra"]
    data = os.urandom(2 * 1024 * 1024)
    r = put_stream(lyra, "patient.bin", data, slow_body(data, 16, 0.5))
    assert r.status_code == 201, r.text
    assert lyra.get(r.json()["file_id"], 1).content == data
    assert_consistent(server)


# ── S3 delete failures: bytes are always tracked, and the janitor finishes the job ──────────
FAULT = "/apps/data/config/fault-s3-delete"


@pytest.fixture
def faulty(make_server):
    server = make_server(
        SYMPOSIUM_DATA_FAULT_INJECTION="1",
        SYMPOSIUM_DATA_PENDING_TTL="5",
        SYMPOSIUM_DATA_JANITOR_INTERVAL="1",
    )
    _, owners = community_with(server, ("lyra", "vega"))
    return server, owners


def s3_deletes_fail(server, failing: bool):
    server.exec("sh", "-c", f"touch {FAULT}" if failing else f"rm -f {FAULT}")


def test_a_failed_upload_whose_bytes_cannot_be_removed_stays_tracked(faulty):
    server, owners = faulty
    s3_deletes_fail(server, True)
    data = os.urandom(12 * 1024 * 1024)  # multipart: an upload and parts to clean up
    bad = httpx.put(
        f"{server.url}/v1/c/demo/files/files/stuck.bin",
        content=data,
        headers={
            **owners["lyra"].headers(),
            "Repr-Digest": repr_digest(b"not the body"),
        },
        timeout=120,
    )
    assert bad.status_code == 400
    assert (
        int(psql(server, "SELECT count(*) FROM payloads WHERE state = 'pending'")) >= 1
    )
    assert untracked_objects(server) == 0
    s3_deletes_fail(server, False)
    assert_consistent(server)  # the janitor removes the bytes, then the row


def test_a_duplicate_whose_copy_cannot_be_removed_stays_tracked(faulty):
    server, owners = faulty
    data = os.urandom(2 * 1024 * 1024)
    assert owners["lyra"].put("demo", "files", "orig.bin", data).status_code == 201
    s3_deletes_fail(server, True)
    copy = owners["vega"].put("demo", "files", "copy.bin", data)
    assert (
        copy.status_code == 201
    )  # the file is fine; only the spare copy's removal failed
    assert owners["vega"].get(copy.json()["file_id"], 1).content == data
    assert psql(server, "SELECT count(*) FROM payloads WHERE state = 'pending'") == "1"
    assert untracked_objects(server) == 0
    s3_deletes_fail(server, False)
    assert_consistent(server)


def test_a_purge_whose_bytes_cannot_be_freed_stays_purging_until_the_janitor_frees_them(
    faulty,
):
    server, owners = faulty
    v1 = owners["lyra"].put("demo", "files", "secret.bin", b"purge me").json()
    s3_deletes_fail(server, True)
    result = server.admin("purge", "--cite", v1["citation"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        '"bytes_freed": false' in result.stdout
        and "janitor will retry" in result.stdout
    )
    assert owners["lyra"].get(v1["file_id"], 1).status_code == 410  # purged regardless
    assert (
        psql(server, "SELECT state FROM payloads WHERE state <> 'ready'") == "purging"
    )
    assert untracked_objects(server) == 0
    s3_deletes_fail(server, False)
    assert_consistent(server)
    assert psql(server, "SELECT state FROM payloads") == "purged"
