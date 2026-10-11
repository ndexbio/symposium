"""The admin key file (R-D4) on a real server. Every start-up case is decided
in `AdminKeyFile` and unit-tested; these check the first bind, the non-operational wiring and
the rebind end to end, restarting only the API process: the container keeps running."""

import json
import re
import time

import httpx
import pytest
from conftest import ADMIN, Admin, OwnerKey, init_admin, place_key
from harness import docker

from symposium_data.auth import PublicKeys

KEY_FILE = f"/apps/admin_pub_{ADMIN}.key"
BACKUP = "/apps/data/config/admin_pub.backup"


def status_until(server, predicate, message, timeout=30) -> dict:
    """Poll /v1/status every 0.2 s, through the API's restart, until `predicate` holds."""
    deadline = time.time() + timeout
    while True:
        try:
            status = httpx.get(server.url + "/v1/status", timeout=5).json()
            if predicate(status):
                return status
        except httpx.HTTPError:
            pass  # the API is starting again
        assert time.time() < deadline, message
        time.sleep(0.2)


def restart_api(server, predicate, message) -> dict:
    server.restart_api()
    # the old process may still answer for a moment: wait for the state the new one reports
    return status_until(server, predicate, message)


def fingerprint(key: OwnerKey) -> str:
    return PublicKeys().thumbprint(key.jwk)


def test_the_admin_is_bound_from_its_key_file(server):
    status = server.status()
    assert status["mode"] == "operational" and "reason" not in status
    assert status["admin"] == ADMIN
    assert status["fingerprint"] == fingerprint(server.admin_key)
    backup = json.loads(server.exec("cat", BACKUP).stdout)
    assert backup == {"handle": ADMIN, "jwk": server.admin_key.jwk}
    admin = init_admin(server)
    assert (
        httpx.get(f"{server.url}/v1/communities", headers=admin.headers()).status_code
        == 200
    )


def test_without_its_key_the_server_is_not_operational(server):
    try:
        for path in (KEY_FILE, BACKUP):
            assert server.exec("mv", path, f"{path}.aside").returncode == 0
        status = restart_api(
            server,
            lambda s: s.get("mode") == "non-operational",
            "the server never left operational mode",
        )
        assert status["reason"] == "admin key missing"
        assert status["server_id"] and "admin" not in status
        for method, path in (
            ("GET", "/v1/communities"),
            ("POST", "/v1/admin/challenge"),
            ("POST", "/v1/demo/auth/challenge"),
            ("GET", "/v1/demo/collections/record/changes"),
        ):
            r = httpx.request(method, server.url + path)
            assert r.status_code == 501, (path, r.text)
            assert "admin key missing" in r.json()["detail"]
    finally:
        for path in (KEY_FILE, BACKUP):
            server.exec("mv", f"{path}.aside", path)
        restart_api(
            server,
            lambda s: s.get("mode") == "operational",
            "the server never came back",
        )


def test_a_new_key_file_rebinds_the_admin(server, tmp_path):
    original = init_admin(server)
    old_token = original.headers()
    new_key = OwnerKey()
    try:
        docker(
            "cp", str(place_key(tmp_path, ADMIN, new_key)), f"{server.name}:{KEY_FILE}"
        )
        status = restart_api(
            server,
            lambda s: s.get("fingerprint") == fingerprint(new_key),
            "the admin was never rebound",
        )
        assert status["mode"] == "operational" and status["admin"] == ADMIN

        # the old key is retired: its token and its signature are both refused
        url = f"{server.url}/v1/communities"
        assert httpx.get(url, headers=old_token).status_code == 401
        assert (
            Admin(server, ADMIN, server.admin_key).token_response().status_code == 401
        )
        assert (
            httpx.get(url, headers=Admin(server, ADMIN, new_key).headers()).status_code
            == 200
        )
        backup = json.loads(server.exec("cat", BACKUP).stdout)
        assert backup == {"handle": ADMIN, "jwk": new_key.jwk}
    finally:
        (tmp_path / "original").mkdir()
        original_file = place_key(tmp_path / "original", ADMIN, server.admin_key)
        docker("cp", str(original_file), f"{server.name}:{KEY_FILE}")
        restart_api(
            server,
            lambda s: s.get("fingerprint") == fingerprint(server.admin_key),
            "the session's admin key was never restored",
        )


STATUS = ("supervisorctl", "-c", "/tmp/supervisord.conf", "status", "api-server")


def api_pid(server) -> str | None:
    """The API process's pid, as supervisord reports it, or None while it has none."""
    found = re.search(r"\bpid (\d+)", server.exec(*STATUS).stdout)
    return found.group(1) if found else None


def answering(server) -> bool:
    try:
        return httpx.get(server.url + "/v1/status", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def restarted(server) -> dict:
    """Restart the API and wait until the new process answers. -> its `/v1/status`.

    It first waits for supervisord to count the current process as RUNNING (up for its first
    5 s): a process ended before that is a failed start, and after a few supervisord gives up.
    Then it signals the process and polls every 0.2 s until supervisord no longer reports the
    old pid and `/v1/status` answers: with the old process gone, the answer is the new one's."""
    deadline = time.time() + 30
    while "RUNNING" not in server.exec(*STATUS).stdout:
        assert time.time() < deadline, "the API never reached RUNNING"
        time.sleep(0.2)
    old = api_pid(server)
    server.restart_api()
    deadline = time.time() + 30
    while not (api_pid(server) != old and answering(server)):
        assert time.time() < deadline, (
            f"the API never answered again ({server.exec(*STATUS).stdout.strip()})"
        )
        time.sleep(0.2)
    return server.status()


def test_the_key_file_is_read_from_the_mounted_directory_too(server):
    # where the Helm chart mounts the Secret holding it: /apps/admin-key/
    mounted = f"/apps/admin-key/admin_pub_{ADMIN}.key"
    saved = server.exec("cat", BACKUP).stdout
    try:
        assert server.exec("mkdir", "-p", "/apps/admin-key").returncode == 0
        assert server.exec("mv", KEY_FILE, mounted).returncode == 0
        # with no backup to fall back on, the server is operational only by reading the
        # mounted file, and reading it saves the backup again
        assert server.exec("rm", BACKUP).returncode == 0
        status = restarted(server)
        assert status["mode"] == "operational" and status["admin"] == ADMIN
        assert status["fingerprint"] == fingerprint(server.admin_key)
        assert json.loads(server.exec("cat", BACKUP).stdout) == json.loads(saved)
    finally:
        if server.exec("test", "-f", BACKUP).returncode != 0:
            server.exec("sh", "-c", f"cat > {BACKUP}", input=saved)
        server.exec("mv", mounted, KEY_FILE)
        server.exec("rmdir", "/apps/admin-key")
        restarted(server)


@pytest.fixture(autouse=True)
def operational_afterwards(server):
    """Every test here leaves the session's admin bound, as every other test expects."""
    yield
    status = server.status()
    assert status["mode"] == "operational"
    assert status["fingerprint"] == fingerprint(server.admin_key)
