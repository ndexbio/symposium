"""Write atomicity and concurrency (R-A6). Every racing or failing write either fully
happens or leaves nothing behind: no pending or unreferenced payload, no orphaned S3 object,
no open multipart upload and no stale name reservation."""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from conftest import (
    EXPIRED,
    assert_consistent,
    b64u_json,
    community_with,
    init_admin,
    psql,
    purge,
    repr_digest,
    set_quota,
    until_sql,
    untracked_objects,
)
from harness import HTTP, MAX_WAIT, TEST_ENV


@pytest.fixture
def demo(server):
    admin, owners = community_with(server)
    return server, admin, owners


def gated_body(data: bytes, pieces: int, gates: dict[int, threading.Event]):
    """The body in `pieces` chunks; chunk i is sent only once gates[i] is set, when it has a
    gate: the test decides how far the upload has got when it acts."""
    step = len(data) // pieces

    def body():
        for i, start in enumerate(range(0, len(data), step)):
            if i in gates:
                assert gates[i].wait(MAX_WAIT), f"chunk {i} was never released"
            yield data[start : start + step]

    return body()


def in_background(request) -> tuple[threading.Thread, dict]:
    """Run `request()` on a thread. -> (the thread, {"r": its response once it ends})."""
    result = {}
    thread = threading.Thread(target=lambda: result.update(r=request()))
    thread.start()
    return thread, result


def reserved(server, *names: str):
    """Wait until each name is reserved and an upload has begun for each: those uploads have
    passed the server's early checks (the quota among them) and their bytes may stream."""
    listed = ", ".join(f"'{n}'" for n in names)
    until_sql(
        server,
        f"SELECT count(*) FROM files WHERE state = 'reserved' AND name IN ({listed})",
        str(len(names)),
        f"never reserved: {names}",
    )
    until_sql(
        server,
        "SELECT count(*) FROM payloads WHERE state = 'pending'",
        str(len(names)),
        f"no upload begun for each of {names}",
    )


def put_stream(owner, name, data, body):
    return HTTP.put(
        f"{owner.server.url}/v1/demo/collections/files/files/{name}",
        content=body,
        headers={
            **owner.headers(),
            "Repr-Digest": repr_digest(data),
            "X-Data-Size": str(len(data)),
        },
    )


def test_a_concurrent_duplicate_name_is_refused_before_it_uploads(demo):
    server, _, owners = demo
    lyra, vega = owners["lyra"], owners["vega"]
    data = os.urandom(4 * 1024 * 1024)
    send = threading.Event()
    thread, first = in_background(
        lambda: put_stream(lyra, "contested.bin", data, gated_body(data, 4, {0: send}))
    )
    reserved(server, "contested.bin")  # lyra's upload has begun and holds the name
    second = vega.put("demo", "files", "contested.bin", os.urandom(4 * 1024 * 1024))
    assert second.status_code == 409, second.text
    # refused before it uploaded: lyra's is still the only upload the server has begun
    assert psql(server, "SELECT count(*) FROM payloads") == "1"
    send.set()
    thread.join(MAX_WAIT)
    assert first["r"].status_code == 201, first["r"].text
    assert lyra.get(first["r"].json()["file_id"], 1).content == data
    assert_consistent(server)


def test_a_failed_upload_releases_the_name_and_leaves_nothing(demo):
    server, _, owners = demo
    lyra = owners["lyra"]
    data = os.urandom(12 * 1024 * 1024)
    bad = HTTP.put(
        f"{server.url}/v1/demo/collections/files/files/retry.bin",
        content=data,
        headers={**lyra.headers(), "Repr-Digest": repr_digest(b"not the body")},
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


def test_concurrent_uploads_cannot_jointly_exceed_the_quota(server):
    set_quota(server, 1000)
    _, owners = community_with(server, ("lyra",))
    lyra = owners["lyra"]
    lyra.headers()
    send = threading.Event()
    results = []

    def upload(i):
        data = os.urandom(600)
        # both pass the early quota check, then stream together and race to commit
        results.append(
            put_stream(lyra, f"q{i}.bin", data, gated_body(data, 2, {0: send}))
        )

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    reserved(server, "q0.bin", "q1.bin")  # both passed the early quota check
    send.set()
    for t in threads:
        t.join(MAX_WAIT)
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
    url = f"{server.url}/v1/demo/files/{fid}/versions"

    def meta_version(if_match, meta):
        return HTTP.post(
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

    stale_content = HTTP.post(
        url,
        content=os.urandom(5 * 1024 * 1024),
        headers={
            **lyra.headers(),
            "Repr-Digest": repr_digest(b"x"),
            "If-Match": '"v1"',
        },
    )
    assert stale_content.status_code == 412  # refused before any bytes are stored

    stale_delete = HTTP.delete(
        f"{server.url}/v1/demo/files/{fid}",
        headers={**lyra.headers(), "If-Match": '"v1"'},
    )
    assert stale_delete.status_code == 412
    deleted = HTTP.delete(
        f"{server.url}/v1/demo/files/{fid}",
        headers={**lyra.headers(), "If-Match": '"v2"'},
    )
    assert deleted.status_code == 200 and deleted.headers["etag"] == '"v3"'

    assert lyra.stat(fid, 2).headers["etag"] == '"v2"'
    assert [
        v["version"] for v in HTTP.get(url, headers=lyra.headers()).json()["versions"]
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
        return HTTP.post(
            f"{server.url}/v1/demo/files/{fid}/versions",
            content=f"edit {i}".encode(),
            headers={
                **lyra.headers(),
                "Repr-Digest": repr_digest(f"edit {i}".encode()),
                "If-Match": '"v1"',
            },
        )

    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(write, range(10)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [412] * 9, codes
    versions = HTTP.get(
        f"{server.url}/v1/demo/files/{fid}/versions", headers=lyra.headers()
    )
    assert [v["version"] for v in versions.json()["versions"]] == [1, 2]
    assert_consistent(server)


def test_the_janitor_expires_stale_reservations(server):
    _, owners = community_with(server, ("lyra",))
    # a crash's leftover: it holds the name until it is older than the pending TTL
    psql(
        server,
        "INSERT INTO files (id, community, collection, name, state, reserved_by, reserved_at) "
        "VALUES ('22222222-2222-2222-2222-222222222222', 'demo', 'files', 'crashed.bin', "
        "'reserved', 'lyra', now())",
    )
    assert owners["lyra"].put("demo", "files", "crashed.bin", b"x").status_code == 409
    psql(server, f"UPDATE files SET reserved_at = {EXPIRED} WHERE name = 'crashed.bin'")
    server.sweep()
    assert_consistent(server)
    assert owners["lyra"].put("demo", "files", "crashed.bin", b"x").status_code == 201


def aged(server):
    """Age the upload in progress past the pending TTL, as if it had stopped a day ago."""
    psql(server, f"UPDATE payloads SET created = {EXPIRED} WHERE state = 'pending'")
    psql(server, f"UPDATE files SET reserved_at = {EXPIRED} WHERE state = 'reserved'")


def test_an_upload_in_progress_heartbeats_so_the_janitor_keeps_it(server):
    _, owners = community_with(server, ("lyra",))
    lyra = owners["lyra"]
    data = os.urandom(2 * 1024 * 1024)
    first, rest = threading.Event(), threading.Event()
    thread, result = in_background(
        lambda: put_stream(
            lyra, "patient.bin", data, gated_body(data, 4, {0: first, 1: rest})
        )
    )
    reserved(server, "patient.bin")
    aged(server)
    # the server beats on a chunk that comes at least one heartbeat interval after its last
    # beat: this pause is only a lower bound, never a guess at how long anything takes
    time.sleep(float(TEST_ENV["SYMPOSIUM_SERVER_HEARTBEAT"]))
    first.set()
    fresh = "> now() - interval '1 hour'"
    until_sql(
        server,
        f"SELECT count(*) FROM payloads WHERE state = 'pending' AND created {fresh}",
        "1",
        "the upload's heartbeat never refreshed its payload",
    )
    until_sql(
        server,
        f"SELECT count(*) FROM files WHERE state = 'reserved' AND reserved_at {fresh}",
        "1",
        "the upload's heartbeat never refreshed its name reservation",
    )
    assert server.sweep() == 0
    rest.set()
    thread.join(MAX_WAIT)
    assert result["r"].status_code == 201, result["r"].text
    assert lyra.get(result["r"].json()["file_id"], 1).content == data
    assert_consistent(server)


def test_an_upload_the_janitor_expired_is_refused_and_leaves_nothing(server):
    _, owners = community_with(server, ("lyra",))
    lyra = owners["lyra"]
    data = os.urandom(2 * 1024 * 1024)
    send = threading.Event()
    thread, result = in_background(
        lambda: put_stream(lyra, "late.bin", data, gated_body(data, 4, {0: send}))
    )
    reserved(server, "late.bin")
    aged(server)
    server.sweep()  # the janitor takes the stalled upload: its bytes, then its rows
    assert psql(server, "SELECT count(*) FROM payloads") == "0"
    send.set()  # the body arrives after all
    thread.join(MAX_WAIT)
    assert result["r"].status_code == 409, result["r"].text
    assert "expired" in result["r"].json()["detail"]
    assert_consistent(server)
    assert lyra.put("demo", "files", "late.bin", data).status_code == 201
    assert_consistent(server)


# Inside the container, with the server's own code: a commit and the janitor reaching the same
# pending payload, in the order the argument names. -> the outcome, as JSON.
COMMIT_AND_JANITOR = """
import hashlib, json, sys
from symposium_data.cleanup import Cleanup
from symposium_data.records import Conflict, Records
from symposium_data.runtime import Database, PayloadStore, Settings
settings = Settings()
db = Database(settings)
db.open()
store, records = PayloadStore(settings), Records()
cleanup = Cleanup(db, store, records)
data = b"bytes a commit and the janitor both reach"
sha = hashlib.sha256(data).hexdigest()
with db.connection() as conn:
    pid, key = records.begin_payload(conn, "demo", "lyra")
store.put_bytes(key, data)
outcome = {}
try:
    if sys.argv[1] == "commit-first":
        with db.connection() as conn:
            records.commit_payload(conn, pid, "demo", sha, len(data), "lyra", 0)
            # the commit holds the row, uncommitted: the janitor must pass it by, at once
            outcome["janitor"] = cleanup.discard_pending(pid)
        outcome["commit"] = "ready"
    else:
        outcome["janitor"] = cleanup.discard_pending(pid)
        try:
            with db.connection() as conn:
                records.commit_payload(conn, pid, "demo", sha, len(data), "lyra", 0)
            outcome["commit"] = "ready"
        except Conflict as error:
            outcome["commit"] = str(error)
    with db.connection() as conn:
        row = conn.execute("SELECT state FROM payloads WHERE id = %s", (pid,)).fetchone()
    outcome["state"] = row["state"] if row else None
    try:
        outcome["bytes"] = "intact" if store.digest(key) == sha else "corrupt"
    except Exception:
        outcome["bytes"] = "gone"
finally:
    db.pool.close()
print(json.dumps(outcome))
"""


def commit_and_janitor(server, order: str) -> dict:
    community_with(server, ("lyra",))
    result = server.exec("/opt/venv/bin/python", "-c", COMMIT_AND_JANITOR, order)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


def test_a_commit_holding_a_payload_is_never_swept_from_under_it(server):
    assert commit_and_janitor(server, "commit-first") == {
        "janitor": True,  # nothing for it to do: the commit decides
        "commit": "ready",
        "state": "ready",
        "bytes": "intact",
    }


def test_a_payload_the_janitor_removed_can_never_be_committed(server):
    outcome = commit_and_janitor(server, "janitor-first")
    assert outcome["janitor"] is True
    assert "expired before it was committed" in outcome["commit"]
    assert (outcome["state"], outcome["bytes"]) == (None, "gone")


# ── S3 delete failures: bytes are always tracked, and the janitor finishes the job ──────────
FAULT = "/apps/data/config/fault-s3-delete"


@pytest.fixture
def faulty(server):
    # the session server has test hooks on; faults act only while the fault file exists
    _, owners = community_with(server, ("lyra", "vega"))
    return server, owners


def s3_deletes_fail(server, failing: bool):
    server.exec("sh", "-c", f"touch {FAULT}" if failing else f"rm -f {FAULT}")


def test_a_failed_upload_whose_bytes_cannot_be_removed_stays_tracked(faulty):
    server, owners = faulty
    s3_deletes_fail(server, True)
    data = os.urandom(12 * 1024 * 1024)  # multipart: an upload and parts to clean up
    bad = HTTP.put(
        f"{server.url}/v1/demo/collections/files/files/stuck.bin",
        content=data,
        headers={
            **owners["lyra"].headers(),
            "Repr-Digest": repr_digest(b"not the body"),
        },
    )
    assert bad.status_code == 400
    assert (
        int(psql(server, "SELECT count(*) FROM payloads WHERE state = 'pending'")) >= 1
    )
    assert untracked_objects(server) == 0
    s3_deletes_fail(server, False)
    server.sweep()  # the janitor removes the bytes, then the row
    assert_consistent(server)


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
    server.sweep()
    assert_consistent(server)


def test_a_purge_whose_bytes_cannot_be_freed_stays_purging_until_the_janitor_frees_them(
    faulty,
):
    server, owners = faulty
    v1 = owners["lyra"].put("demo", "files", "secret.bin", b"purge me").json()
    s3_deletes_fail(server, True)
    result = purge(init_admin(server), v1["file_id"], 1)
    assert result.status_code == 200, result.text
    assert result.json()["bytes_freed"] is False
    assert "janitor will retry" in result.json()["note"]
    assert owners["lyra"].get(v1["file_id"], 1).status_code == 410  # purged regardless
    assert (
        psql(server, "SELECT state FROM payloads WHERE state <> 'ready'") == "purging"
    )
    assert untracked_objects(server) == 0
    s3_deletes_fail(server, False)
    server.sweep()
    assert_consistent(server)
    assert psql(server, "SELECT state FROM payloads") == "purged"
