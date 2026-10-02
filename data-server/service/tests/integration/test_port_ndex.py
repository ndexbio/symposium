"""M6: the one-time NDEx port (R-M), against recorded NDEx 3.0.0 responses served by a stub.

The port runs as its own container on the server's volume, the way an operator runs it before
the first boot; the server then boots on that volume.
"""

import base64
import hashlib
import json
import re
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from conftest import IMAGE, Owner, assert_consistent, docker, init_admin, psql

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ndex_port"
DATA_SERVER = Path(__file__).parents[3]
TOOLS = DATA_SERVER.parent / "tools"
CREDENTIALS = {"username": "ndex-admin", "password": "recorded-fixture"}


def attributes(network: list) -> dict:
    return next(a["networkAttributes"][0] for a in network if "networkAttributes" in a)


class NdexStub:
    """Serves the recorded responses. Listings are paged here, as NDEx pages them: `start`
    is a page index and `size` the page size."""

    def __init__(self, extra_networks: dict | None = None):
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
        self.listing_pages = 0
        self.server = ThreadingHTTPServer(("0.0.0.0", 0), self.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        # what the port container dials: Docker Desktop's host alias, mapped on Linux by
        # --add-host=host.docker.internal:host-gateway
        self.url = f"http://host.docker.internal:{self.server.server_port}"

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
        self.server.shutdown()


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


def run_port(server, url, tmp_path, page_size=4):
    """Run the port container on the server's volume. -> (exit code, its last event)."""
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps(CREDENTIALS))
    credentials.chmod(0o600)
    name = f"{server.name}-port"
    result = docker(
        "run",
        "--name",
        name,
        "--add-host=host.docker.internal:host-gateway",
        "-v",
        f"{server.volume}:/apps",
        "-v",
        f"{credentials}:/run/secrets/ndex.json:ro",
        "-e",
        f"PORT_NDEX_URL={url}",
        "-e",
        "PORT_NDEX_CREDENTIALS_FILE=/run/secrets/ndex.json",
        "-e",
        "PORT_COMMUNITY=demo",
        "-e",
        "PORT_ADMIN_HANDLE=demo-admin",
        "-e",
        f"PORT_NDEX_PAGE_SIZE={page_size}",
        IMAGE,
        check=False,
    )
    docker("rm", "-f", "-v", name, check=False)
    events = [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.startswith('{"event": "port-ndex"')
    ]
    if not events:
        return result.returncode, {
            "stdout": result.stdout[-1500:],
            "stderr": result.stderr[-1500:],
        }
    return result.returncode, events[-1]


def everything(server, headers, collection) -> list:
    items, since = [], 0
    while True:
        page = httpx.get(
            f"{server.url}/v1/c/demo/{collection}/changes",
            params={"since": since, "limit": 4},
            headers=headers,
        ).json()
        items += page["items"]
        since = page["next_since"]
        if not page["more"]:
            return items


def test_the_port_bootstraps_a_fresh_server_once(make_server, tmp_path):
    stub = NdexStub()
    server = make_server(start=False)
    try:
        code, event = run_port(server, stub.url, tmp_path)
    finally:
        stub.close()
    assert code == 0, event
    assert event["status"] == "ok"
    assert (event["networks"], event["record"], event["replies"]) == (10, 9, 1)
    assert event["pages"] == 3 and stub.listing_pages == 3  # 10 networks at page size 4
    assert event["reserved_roster"] == ["lyra", "vega"]

    # the server boots uninitialized; init must use the ported admin handle
    server.start()
    assert server.status()["initialized"] is False
    other = Owner(server, "other-admin")
    refused = server.admin(
        "init", "--admin", "other-admin", "--pubkey", "-", input=other.key.jwk_text()
    )
    assert refused.returncode == 2 and "ported for admin 'demo-admin'" in refused.stdout
    assert server.status()["initialized"] is False
    admin = init_admin(server)

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
        reply["created_by"] == "demo-admin"
    )  # the NDEx admin account maps to the admin

    # the authors and the recipient were reserved on the roster, and can claim their handles
    lyra, vega = Owner(server, "lyra"), Owner(server, "vega")
    assert lyra.register("demo").status_code == 201
    assert vega.register("demo").status_code == 201
    assert Owner(server, "mallory").register("demo").status_code == 403
    assert lyra.get(reply["file_id"]).status_code == 200
    assert (
        vega.get(reply["file_id"]).status_code == 403
    )  # only its recipient reads a reply
    assert vega.get(ported[0]["file_id"]).status_code == 200
    vegas = next(i for i in ported if i["created_by"] == "vega")
    keyed = httpx.post(
        f"{server.url}/v1/c/demo/record/keys",
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

    # never again: the same source is a no-op, any other is refused
    docker("stop", server.name)
    code, event = run_port(server, stub.url, tmp_path)
    assert code == 0 and event["status"] == "already-ported", event
    code, event = run_port(server, "http://elsewhere.example:8080", tmp_path)
    assert code == 1 and event["status"] == "refused", event
    server.restart()
    assert len(everything(server, admin.headers(), "record")) == 10


def test_a_failing_port_writes_nothing(make_server, tmp_path):
    # an eleventh network repeats a record's name: refused inside the commit transaction,
    # after every payload was uploaded
    records = [r for r in recorded_artifacts() if r[3].get("symposium_record") is True]
    _created, name, raw, na = records[0]
    artifact = json.loads(raw)
    artifact["artifact"]["created"] = "2026-10-02T23:00:00+00:00"
    copy = {**na, "symposium_canonical": json.dumps(artifact)}
    stub = NdexStub(extra_networks={"duplicate-name": [{"networkAttributes": [copy]}]})
    server = make_server(start=False)
    try:
        code, event = run_port(server, stub.url, tmp_path)
    finally:
        stub.close()
    assert code == 1 and event["status"] == "refused", event
    assert name in event["reason"] and "already exists" in event["reason"]

    server.start()
    assert psql(server, "SELECT count(*) FROM collections") == "0"
    assert psql(server, "SELECT count(*) FROM payloads") == "0"
    assert (
        psql(server, "SELECT count(*) FROM server_config WHERE k LIKE 'port_%'") == "0"
    )
    assert_consistent(server)

    # nothing was recorded, so the port can still run once
    docker("stop", server.name)
    stub = NdexStub()
    try:
        code, event = run_port(server, stub.url, tmp_path)
    finally:
        stub.close()
    assert code == 0 and event["status"] == "ok", event


def test_the_port_refuses_a_server_already_in_use(make_server, tmp_path):
    server = make_server()
    init_admin(server)
    docker("stop", server.name)
    stub = NdexStub()
    try:
        code, event = run_port(server, stub.url, tmp_path)
    finally:
        stub.close()
    assert code == 1 and event["status"] == "refused", event
    assert "initialized" in event["reason"] and stub.listing_pages == 0


# ── the port feature holds every NDEx reference (R-S1, R-S3 scoped to data-server/) ─────────
NDEX = re.compile(r"(?<![a-z])ndex(?!bio/)|cx2|/v[23]/|ndexbio\.org", re.IGNORECASE)
PORT_IDENTIFIER = re.compile(r"PORT_NDEX|port-ndex|port_ndex")
PORT_FILES = {
    "service/symposium_data/port_ndex.py",
    "service/tests/integration/test_port_ndex.py",
    "docker/k8s-data-port-job.yml",
    "PORT_NDEX.md",
}
PORT_LINES = {
    "docker/scripts/start.sh",
    "service/symposium_data/admin.py",
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
    assert importers == ["service/symposium_data/admin.py"]
    assert (DATA_SERVER / "PORT_NDEX.md").is_file()
