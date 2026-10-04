"""#20 stage 2: what the CLI reports when the server is not the one it speaks to (R-I5) or is
not operational (R-D4), against a small local server that answers like one; and the CLI's own
pieces: keys, citations, secret files and the generated reference."""

import json
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import keystore
import main
import pytest
from suite import CLI_DIR
from symposium_data.auth import PublicKeys


class FakeServer:
    """Answers /v1/status with `status`, and every other route with a 501."""

    def __init__(self, status: dict):
        payload = json.dumps(status).encode()
        refusal = json.dumps(
            {"detail": "the server is not operational: admin key missing"}
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            def answer(self):
                body, code = (
                    (payload, 200) if self.path == "/v1/status" else (refusal, 501)
                )
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = answer

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()


def admin_context(directory: Path, url: str):
    (directory / ".symposium").mkdir()
    (directory / ".symposium" / "context.json").write_text(
        json.dumps(
            {
                "community": "demo",
                "data-server-url": url,
                "handle": "demo-admin",
                "role": "admin",
                "server_id": "fake",
            }
        )
    )


@pytest.mark.parametrize("api", ["2", None])
def test_a_server_speaking_another_api_version_is_refused(cli, tmp_path, api):
    fake = FakeServer({"api": api, "server_id": "fake", "mode": "operational"})
    try:
        admin_context(tmp_path, fake.url)
        code, out = cli(tmp_path, "roster", "list")
    finally:
        fake.close()
    assert code == 1
    assert "API version 1" in out["error"] and f"speaks version {api}" in out["error"]
    assert "development checkout" in out["error"]  # no compat.json outside the bundle


def test_a_non_operational_server_is_reported_with_its_reason(cli, tmp_path):
    fake = FakeServer(
        {
            "api": "1",
            "server_id": "fake",
            "mode": "non-operational",
            "reason": "admin key missing",
        }
    )
    try:
        admin_context(tmp_path, fake.url)
        code, out = cli(tmp_path, "communities", "list")
        status = cli.ok(tmp_path, "status")
    finally:
        fake.close()
    assert code == 1 and out["status"] == 501
    assert (
        "admin key missing" in out["error"]
        and "/symposium admin-config" in out["error"]
    )
    assert status["mode"] == "non-operational"  # status answers in either mode


def test_usage_errors_are_json_too(cli, tmp_path):
    code, out = cli(tmp_path, "purge")
    assert code == 1 and "--cite" in out["error"] and out["usage"].startswith("usage:")


def test_keys_are_encrypted_and_their_fingerprint_matches_the_servers(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SYMPOSIUM_KEY_PASSPHRASE", "unit-passphrase")
    store = keystore.Keystore("server:1", root=tmp_path)
    jwk = store.create("admin", "lyra")
    assert store.create("admin", "lyra") == jwk  # kept unless replaced
    private, public = store.paths("admin", "lyra")
    assert b"ENCRYPTED PRIVATE KEY" in private.read_bytes()
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    assert store.handles("admin") == ["lyra"] and store.handles("demo") == []
    assert keystore.thumbprint(jwk) == PublicKeys().thumbprint(jwk)
    signature = store.sign("admin", "lyra", b"nonce")
    assert PublicKeys().verify(jwk, b"nonce", signature)

    monkeypatch.setenv("SYMPOSIUM_KEY_PASSPHRASE", "wrong")
    with pytest.raises(keystore.KeystoreError, match="does not open it"):
        store.sign("admin", "lyra", b"nonce")
    monkeypatch.setenv("SYMPOSIUM_KEY_PASSPHRASE", "unit-passphrase")
    assert store.create("admin", "lyra", replace=True) != jwk


def test_citations_and_file_ids_name_a_version():
    file_id = "0b4f1c2e-1111-4a5b-9c8d-123456789abc"
    assert main.parse_ref(f"symposium-data:{file_id}@v3", None) == (file_id, "3")
    assert main.parse_ref(file_id, None) == (file_id, "latest")
    assert main.parse_ref(file_id, "2") == (file_id, "2")
    for bad, version in (("not-a-ref", None), (f"symposium-data:{file_id}@v3", "2")):
        with pytest.raises(main.CommandError):
            main.parse_ref(bad, version)


def test_secret_files_are_owner_only(tmp_path):
    path = tmp_path / "deep" / "lyra.invite"
    main.write_secret(path, {"invite": "sdi_x"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    main.write_secret(path, {"invite": "sdi_y"})  # overwritten, still owner-only
    assert json.loads(path.read_text()) == {"invite": "sdi_y"}


def test_the_committed_reference_is_current():
    generated = main.reference(main.build_parser(main.Commands()))
    committed = (CLI_DIR / "reference" / "COMMANDS.md").read_text()
    assert generated == committed, (
        "run `symposium-data --reference` and commit the result"
    )
