"""Post-M6 stage 3: the NDEx port as a route (R-M1), against recorded NDEx 3.0.0 responses
served by a stub on this machine. Every port runs on the shared session container, into an
empty community, and is polled until it finishes.
"""

import base64
import hashlib
import json
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingTCPServer
from urllib.parse import parse_qs, urlparse

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
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ndex_port"
DATA_SERVER = Path(__file__).parents[3]
TOOLS = DATA_SERVER.parent / "tools"
CREDENTIALS = {"username": "ndex-admin", "password": "recorded-fixture"}


def attributes(network: list) -> dict:
    return next(a["networkAttributes"][0] for a in network if "networkAttributes" in a)


class NdexStub:
    """Serves the recorded responses. Listings are paged here, as NDEx pages them: `start`
    is a page index and `size` the page size. With `hold`, the first listing request waits
    until the test releases it, so a port stays running."""

    def __init__(self, extra_networks: dict | None = None, hold: bool = False):
        self.whoami = json.loads((FIXTURES / "whoami.json").read_text())
        self.listing = json.loads((FIXTURES / "admin_networks.json").read_text())
        self.networks = {
            p.stem: p.read_text() for p in (FIXTURES / "networks").glob("*.json")
        }
        self.permissions = {
            p.stem: json.loads(p.read_text())
            for p in (FIXTURES / "network_permissions").glob("*.json")
        }
        self.users = {
            p.stem: p.read_text() for p in (FIXTURES / "users").glob("*.json")
        }
        for network_id, body in (extra_networks or {}).items():
            self.listing[network_id] = "ADMIN"
            self.networks[network_id] = json.dumps(body)
        self.requests = self.listing_pages = 0
        self.held = threading.Event()  # a held listing request has arrived
        self.released = threading.Event()
        if not hold:
            self.released.set()
        # a plain TCP server: HTTPServer looks up the host's name at bind, which can take
        # seconds, and the handler never needs it
        self.server = ThreadingTCPServer(("0.0.0.0", 0), self.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        # what the server dials: Docker Desktop's host alias, mapped on Linux by the session
        # container's --add-host=host.docker.internal:host-gateway
        self.url = f"http://host.docker.internal:{self.server.server_address[1]}"

    def page(self, listing: dict, query: dict) -> str:
        start, size = int(query["start"][0]), int(query["size"][0])
        return json.dumps(
            dict(list(listing.items())[start * size : (start + 1) * size])
        )

    def respond(self, path: str, query: dict) -> str | None:
        parts = path.strip("/").split("/")
        if path == "/v2/user" and query.get("valid") == ["true"]:
            return json.dumps(self.whoami)
        if parts[:2] == ["v2", "user"] and parts[3:] == ["permission"]:
            self.held.set()
            self.released.wait(timeout=30)
            self.listing_pages += 1
            return self.page(self.listing, query)
        if parts[:2] == ["v3", "networks"] and len(parts) == 3:
            return self.networks.get(parts[2])
        if parts[:2] == ["v2", "network"] and parts[3:] == ["permission"]:
            return self.page(self.permissions.get(parts[2], {}), query)
        if parts[:2] == ["v2", "user"] and len(parts) == 3:
            return self.users.get(parts[2])
        return None

    def handler(self):
        stub = self
        expected = (
            "Basic "
            + base64.b64encode(
                f"{CREDENTIALS['username']}:{CREDENTIALS['password']}".encode()
            ).decode()
        )

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                stub.requests += 1
                if self.headers.get("Authorization") != expected:
                    self.send_response(401)
                    self.end_headers()
                    return
                url = urlparse(self.path)
                body = stub.respond(url.path, parse_qs(url.query))
                self.send_response(404 if body is None else 200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write((body or "{}").encode())

            def log_message(self, *_args):
                pass

        return Handler

    def close(self):
        self.released.set()
        self.server.shutdown()


@pytest.fixture
def stub():
    stub = NdexStub()
    yield stub
    stub.close()


@pytest.fixture
def demo(server):
    """The admin and an empty `demo` community; the port reads 4 networks per page."""
    admin = init_admin(server)
    create_community(server, admin, "demo")
    hook = server.exec("sh", "-c", "echo 4 > /apps/data/config/test-port-page-size")
    assert hook.returncode == 0, hook.stderr
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
        json={"url": url, **CREDENTIALS},
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
    assert started.json()["state"] in ("running", "ok", "refused", "failed")
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
    assert outcome["state"] == "ok", outcome
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
    # an eleventh network repeats a record's name: refused inside the commit transaction,
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
    assert outcome["state"] == "refused", outcome
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


def test_a_port_is_refused_before_any_ndex_call(demo, stub):
    server, admin = demo
    assert start_port(server, admin.headers(), stub.url, "nowhere").status_code == 404
    assert start_port(server, {}, stub.url).status_code == 401
    httpx.post(f"{server.url}/v1/demo/roster/lyra", headers=admin.headers())
    lyra = Owner(server, "lyra")
    enroll(admin, lyra, "demo")
    assert start_port(server, lyra.headers(), stub.url).status_code == 403
    unknown = httpx.get(
        f"{server.url}/v1/demo/port-ndex/{uuid.uuid4()}", headers=admin.headers()
    )
    assert unknown.status_code == 404

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


def test_a_restart_marks_a_running_port_failed(demo):
    server, admin = demo
    port_id = psql(
        server,
        "INSERT INTO ports (community, source) VALUES ('demo', 'http://cut.example') "
        "RETURNING id",
    ).splitlines()[0]
    # end the API process only; supervisord starts it again, the container keeps running
    ctl = ("supervisorctl", "-c", "/tmp/supervisord.conf")
    assert server.exec(*ctl, "signal", "TERM", "data-api").returncode == 0
    deadline = time.time() + 30
    while True:
        try:
            view = httpx.get(
                f"{server.url}/v1/demo/port-ndex/{port_id}", headers=admin.headers()
            ).json()
            if view["state"] != "running":
                break
        except httpx.HTTPError:
            pass  # the API is starting again
        assert time.time() < deadline, "the restarted service never marked the port"
        time.sleep(0.2)
    assert view["state"] == "failed" and "restarted" in view["result"]["reason"]
    assert view["finished"] is not None
    server.wait()


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
