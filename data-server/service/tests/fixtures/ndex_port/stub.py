"""The NDEx stub shared by the port tests (the data server's and the CLI's): it serves the
recorded NDEx 3.0.0 responses in this directory, with the credentials they were recorded for.
"""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingTCPServer
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).parent
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
