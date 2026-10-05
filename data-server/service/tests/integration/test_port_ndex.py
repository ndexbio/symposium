"""The NDEx port as a route (R-M1), against recorded NDEx 3.0.0 responses
served by a stub on this machine. Every port runs on the shared session container, into an
empty community, and is polled until it finishes.
"""

import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from conftest import (
    Owner,
    assert_consistent,
    create_community,
    enroll,
    init_admin,
    invite,
    psql,
    store_counts,
)
from fixtures.ndex_port.stub import CREDENTIALS, FIXTURES, NdexStub, attributes

DATA_SERVER = Path(__file__).parents[3]
TOOLS = DATA_SERVER.parent / "tools"


@pytest.fixture
def stub():
    stub = NdexStub()
    yield stub
    stub.close()


@pytest.fixture
def demo(server):
    """The admin and an empty `demo` community."""
    admin = init_admin(server)
    create_community(server, admin, "demo")
    return server, admin


def recorded_artifacts() -> list:
    """(created, name, canonical bytes, attributes) for every recorded network, oldest first."""
    out = []
    for p in (FIXTURES / "networks").glob("*.json"):
        na = attributes(json.loads(p.read_text()))
        header = json.loads(na["symposium_canonical"])["artifact"]
        out.append(
            (
                datetime.fromisoformat(header["created"]),
                header["name"],
                na["symposium_canonical"].encode(),
                na,
            )
        )
    return sorted(out, key=lambda x: x[0])


def start_port(server, headers, url, community="demo"):
    return httpx.post(
        f"{server.url}/v1/{community}/port-ndex",
        # 4 networks per page, so the 10 recorded networks take 3 listing pages
        json={"ndex_url": url, "credentials": CREDENTIALS, "page_size": 4},
        headers=headers,
    )


def port_outcome(server, admin, port_id, community="demo", timeout=30) -> dict:
    """Poll the port until it is no longer running. -> its view."""
    deadline = time.time() + timeout
    while True:
        view = httpx.get(
            f"{server.url}/v1/{community}/port-ndex/{port_id}", headers=admin.headers()
        ).json()
        if view["state"] != "running":
            return view
        assert time.time() < deadline, f"the port never finished: {view}"
        time.sleep(0.2)


def run_port(server, admin, url, community="demo") -> dict:
    started = start_port(server, admin.headers(), url, community)
    assert started.status_code == 202, started.text
    assert started.json()["state"] in ("running", "ok", "failed")
    assert started.json()["requested_by"] == admin.handle
    return port_outcome(server, admin, started.json()["id"], community)


def everything(server, headers, collection) -> list:
    items, since = [], 0
    while True:
        page = httpx.get(
            f"{server.url}/v1/demo/collections/{collection}/changes",
            params={"since": since, "limit": 4},
            headers=headers,
        ).json()
        items += page["items"]
        since = page["next_since"]
        if not page["more"]:
            return items


def test_the_port_fills_an_empty_community_once(demo, stub, tmp_path):
    server, admin = demo
    outcome = run_port(server, admin, stub.url)
    assert outcome["state"] == "ok", outcome["result"]
    result = outcome["result"]
    assert (result["networks"], result["record"], result["replies"]) == (10, 9, 1)
    assert (
        result["pages"] == 3 and stub.listing_pages == 3
    )  # 10 networks at page size 4
    assert result["reserved_roster"] == ["lyra", "vega"]
    assert result["admin"] == admin.handle and result["source"] == stub.url

    recorded = recorded_artifacts()
    records = [r for r in recorded if r[3].get("symposium_record") is True]
    ported = everything(server, admin.headers(), "record")
    assert [i["name"] for i in ported] == [r[1] for r in records]
    assert [i["seq"] for i in ported] == list(range(1, 10))
    for item, (created, _name, raw, _na) in zip(ported, records, strict=True):
        assert datetime.fromisoformat(item["created"]) == created
        assert (
            item["sha256"] == hashlib.sha256(raw).hexdigest()
        )  # exact canonical bytes
        author = json.loads(raw)["artifact"]["published_by"].lstrip("@")
        assert item["created_by"] == author and item["key_id"] is None
        assert item["metadata"] == {"symposium_record": True}
        assert admin.get(item["file_id"]).content == raw

    [reply] = everything(server, admin.headers(), "inbox")
    assert reply["metadata"] == {
        "symposium_reply": True,
        "symposium_in_reply_to": "lyra_note_bad_v1",
        "recipients": ["lyra"],
    }
    assert (
        reply["created_by"] == admin.handle
    )  # the NDEx admin account maps to the server's admin

    # the authors and the recipient are on the roster, and claim their handles by invite
    lyra, vega = Owner(server, "lyra"), Owner(server, "vega")
    assert enroll(admin, lyra, "demo").status_code == 201
    assert enroll(admin, vega, "demo").status_code == 201
    assert invite(admin, "demo", "mallory").status_code == 403  # not on the roster
    assert lyra.get(reply["file_id"]).status_code == 200
    assert (
        vega.get(reply["file_id"]).status_code == 403
    )  # only its recipient reads a reply
    assert vega.get(ported[0]["file_id"]).status_code == 200
    vegas = next(i for i in ported if i["created_by"] == "vega")
    keyed = httpx.post(
        f"{server.url}/v1/demo/collections/record/keys",
        json={"label": "reviewer", "file_id": vegas["file_id"]},
        headers=vega.headers(),
    )
    assert keyed.status_code == 201  # credited to its author, who may key it (R-E2)

    # R-M4: the ported record, fetched into a directory, re-validates with Symposium's validator
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    for item in ported:
        (record_dir / f"{item['name']}.json").write_bytes(
            admin.get(item["file_id"]).content
        )
    validated = subprocess.run(
        [sys.executable, "validate_record.py", str(record_dir)],
        cwd=TOOLS,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert "9 artifacts: 0 FAIL" in validated.stdout

    # the record's clock continues after the last ported instant
    after = admin.put("demo", "record", "after.json", b"{}").json()
    assert after["seq"] == 10
    assert datetime.fromisoformat(after["created"]) > records[-1][0]
    assert_consistent(server)

    # never again: the community holds files, whatever the source
    for url in (stub.url, "http://elsewhere.example:8080"):
        again = start_port(server, admin.headers(), url)
        assert again.status_code == 400 and "holds files" in again.json()["detail"]
    assert len(everything(server, admin.headers(), "record")) == 10


def test_a_failing_port_writes_nothing(demo):
    # an eleventh network repeats a record's name: it fails inside the commit transaction,
    # after every payload was uploaded
    server, admin = demo
    records = [r for r in recorded_artifacts() if r[3].get("symposium_record") is True]
    _created, name, raw, na = records[0]
    artifact = json.loads(raw)
    artifact["artifact"]["created"] = "2026-10-02T23:00:00+00:00"
    copy = {**na, "symposium_canonical": json.dumps(artifact)}
    stub = NdexStub(extra_networks={"duplicate-name": [{"networkAttributes": [copy]}]})
    try:
        outcome = run_port(server, admin, stub.url)
    finally:
        stub.close()
    assert outcome["state"] == "failed", outcome
    reason = outcome["result"]["reason"]
    assert name in reason and "already exists" in reason

    for table in ("files", "versions", "payloads", "roster"):
        assert psql(server, f"SELECT count(*) FROM {table}") == "0", table
    assert (
        psql(server, "SELECT count(*) FROM collections") == "3"
    )  # the defaults, empty
    assert_consistent(server)

    # nothing was written, so the community can still be ported
    stub = NdexStub()
    try:
        assert run_port(server, admin, stub.url)["state"] == "ok"
    finally:
        stub.close()


def test_an_author_with_the_admins_handle_fails_the_port(demo):
    # a record published by an NDEx account named like this server's admin, which is not
    # the NDEx admin account: known only once NDEx is read, so reported in the port's status
    server, admin = demo
    records = [r for r in recorded_artifacts() if r[3].get("symposium_record") is True]
    _created, _name, raw, na = records[0]
    artifact = json.loads(raw)
    artifact["artifact"].update(
        name="admin_handle_note_v1",
        created="2026-10-02T23:00:00+00:00",
        published_by=f"@{admin.handle}",
    )
    copy = {**na, "symposium_canonical": json.dumps(artifact)}
    stub = NdexStub(extra_networks={"admin-handle": [{"networkAttributes": [copy]}]})
    try:
        outcome = run_port(server, admin, stub.url)
    finally:
        stub.close()
    assert outcome["state"] == "failed", outcome
    assert outcome["result"]["reason"] == "handle collision"
    for table in ("files", "versions", "payloads", "roster"):
        assert psql(server, f"SELECT count(*) FROM {table}") == "0", table
    assert_consistent(server)


def test_a_file_that_lands_while_the_port_runs_fails_it(demo):
    server, admin = demo
    stub = NdexStub(hold=True)
    try:
        started = start_port(server, admin.headers(), stub.url)
        assert started.status_code == 202, started.text
        assert stub.held.wait(timeout=10), "the port never reached the listing"
        landed = admin.put("demo", "files", "landed.csv", b"written mid-port")
        assert landed.status_code == 201, landed.text
        stub.released.set()
        outcome = port_outcome(server, admin, started.json()["id"])
    finally:
        stub.close()
    assert outcome["state"] == "failed" and "holds files" in outcome["result"]["reason"]
    assert (
        psql(server, "SELECT name FROM files") == "landed.csv"
    )  # only the member's file
    assert psql(server, "SELECT count(*) FROM roster") == "0"
    assert_consistent(server)


def test_a_port_cut_off_by_a_restart_leaves_no_bytes(demo, stub):
    # a second session holds a lock on the community's collections, as a member's write does,
    # so the real port uploads every payload and then waits at its commit; the API process is
    # killed there
    server, admin = demo
    lock = subprocess.Popen(
        ["docker", "exec", "-e", "PGAPPNAME=port-lock", server.name]
        + ["gosu", "postgres", "psql", "-d", "symposium_data", "-c"]
        + [
            "SELECT 1 FROM collections WHERE community = 'demo' FOR NO KEY UPDATE; "
            "SELECT pg_sleep(60)"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        waiting = (
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE application_name = 'port-lock' AND wait_event = 'PgSleep'"
        )
        poll_until(lambda: psql(server, waiting) == "1", "the lock was never taken")
        started = start_port(server, admin.headers(), stub.url)
        assert started.status_code == 202, started.text
        blocked = "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'"
        poll_until(
            lambda: psql(server, blocked) == "1", "the port never reached its commit"
        )
        pending = "SELECT count(*) FROM payloads WHERE state = 'pending'"
        assert psql(server, pending) == "10"  # every artifact's bytes are uploaded
        assert store_counts(server)[0] == 10

        server.restart_api("KILL")
        view = poll_until(
            lambda: port_view_after_restart(server, admin, started.json()["id"]),
            "the restarted service never marked the port",
        )
        assert view["state"] == "failed" and "restarted" in view["result"]["reason"]
    finally:
        psql(
            server,
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE application_name = 'port-lock'",
        )
        lock.wait(timeout=30)
    server.wait()
    # the transaction never committed, and the janitor removes the pending bytes
    assert psql(server, "SELECT count(*) FROM files") == "0"
    assert_consistent(server)
    assert store_counts(server)[0] == 0


def poll_until(probe, message, timeout=30):
    """Poll every 0.2 s until `probe` returns something truthy. -> that value."""
    deadline = time.time() + timeout
    while True:
        value = probe()
        if value:
            return value
        assert time.time() < deadline, message
        time.sleep(0.2)


def port_view_after_restart(server, admin, port_id) -> dict | None:
    """The port's view once it is no longer running; None while the API restarts."""
    try:
        view = httpx.get(
            f"{server.url}/v1/demo/port-ndex/{port_id}", headers=admin.headers()
        ).json()
    except httpx.HTTPError:
        return None
    return view if view.get("state") not in (None, "running") else None


def test_a_port_is_refused_before_any_ndex_call(demo, stub):
    server, admin = demo
    assert start_port(server, admin.headers(), stub.url, "nowhere").status_code == 404
    assert start_port(server, {}, stub.url).status_code == 401
    httpx.post(f"{server.url}/v1/demo/roster/lyra", headers=admin.headers())
    lyra = Owner(server, "lyra")
    enroll(admin, lyra, "demo")
    assert start_port(server, lyra.headers(), stub.url).status_code == 403
    status_url = f"{server.url}/v1/demo/port-ndex/{uuid.uuid4()}"
    assert httpx.get(status_url, headers=admin.headers()).status_code == 404
    assert httpx.get(status_url).status_code == 401
    assert httpx.get(status_url, headers=lyra.headers()).status_code == 403
    httpx.post(
        f"{server.url}/v1/demo/collections",
        json={"name": "project"},
        headers=lyra.headers(),
    )
    read_key = httpx.post(
        f"{server.url}/v1/demo/collections/project/keys",
        json={"label": "reviewer"},
        headers=lyra.headers(),
    ).json()["key"]
    by_key = {"Authorization": f"Bearer {read_key}"}
    assert start_port(server, by_key, stub.url).status_code == 403
    assert httpx.get(status_url, headers=by_key).status_code == 403

    create_community(server, admin, "full")
    admin.put("full", "files", "data.csv", b"already here")
    held = start_port(server, admin.headers(), stub.url, "full")
    assert held.status_code == 400 and "holds files" in held.json()["detail"]
    assert stub.requests == 0


def test_one_port_runs_at_a_time(demo):
    server, admin = demo
    create_community(server, admin, "other")
    stub = NdexStub(hold=True)
    try:
        first = start_port(server, admin.headers(), stub.url)
        assert first.status_code == 202, first.text
        assert stub.held.wait(timeout=10), "the port never reached the listing"
        second = start_port(server, admin.headers(), stub.url, "other")
        assert second.status_code == 409 and "another port" in second.json()["detail"]
        stub.released.set()
        assert port_outcome(server, admin, first.json()["id"])["state"] == "ok"
    finally:
        stub.close()
    stub = NdexStub()
    try:
        assert run_port(server, admin, stub.url, "other")["state"] == "ok"
    finally:
        stub.close()


# ── the port feature holds every NDEx reference (R-S1, R-S3 scoped to data-server/) ─────────
NDEX = re.compile(r"(?<![a-z])ndex(?!bio/)|cx2|/v[23]/|ndexbio\.org", re.IGNORECASE)
PORT_IDENTIFIER = re.compile(r"PORT_NDEX|port-ndex|port_ndex")
PORT_FILES = {
    "service/symposium_data/port_ndex.py",
    "service/tests/integration/test_port_ndex.py",
    "PORT_NDEX.md",
}
PORT_LINES = {
    "service/symposium_data/app.py",
    "README.md",
    "RUNBOOK.md",
}
SKIPPED_DIRS = {".venv", "__pycache__", ".ruff_cache", ".pytest_cache"}
IMPORTS_PORT = re.compile(
    r"^\s*(from\s+\S*port_ndex\s+import|import\s+\S*port_ndex|from\s+\.\s+import\s+port_ndex)"
)


def data_server_files():
    for path in sorted(DATA_SERVER.rglob("*")):
        rel = path.relative_to(DATA_SERVER)
        if path.is_file() and not SKIPPED_DIRS & set(rel.parts):
            try:
                yield rel.as_posix(), path.read_text().splitlines()
            except UnicodeDecodeError:
                continue


def test_ndex_stays_inside_the_port_feature():
    stray, importers = [], []
    for rel, lines in data_server_files():
        for number, line in enumerate(lines, 1):
            if IMPORTS_PORT.match(line):
                importers.append(rel)
            if rel in PORT_FILES or rel.startswith("service/tests/fixtures/ndex_port/"):
                continue
            if not NDEX.search(line) or "github.com/ndexbio/" in line:
                continue
            if rel in PORT_LINES and PORT_IDENTIFIER.search(line):
                continue
            stray.append(f"{rel}:{number}: {line.strip()}")
    assert stray == []
    assert importers == ["service/symposium_data/app.py"]
    assert (DATA_SERVER / "PORT_NDEX.md").is_file()
