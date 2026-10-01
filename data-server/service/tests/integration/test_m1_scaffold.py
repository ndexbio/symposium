"""M1: the image, its first boot, initialization and persistence."""

import json
import subprocess
import time
from pathlib import Path

import httpx
from conftest import IMAGE, VERSION, docker

DOCKER_DIR = Path(__file__).resolve().parents[3] / "docker"


def test_supervisord_runs_all_three_programs(server):
    # supervisord reports RUNNING only after each program's startsecs, which can trail the
    # first healthy /v1/status by a few seconds.
    deadline = time.time() + 30
    while True:
        out = server.exec(
            "supervisorctl", "-c", "/tmp/supervisord.conf", "status"
        ).stdout
        running = sorted(
            line.split()[0] for line in out.splitlines() if " RUNNING " in line
        )
        if running == ["data-api", "postgres", "seaweed"] or time.time() > deadline:
            break
        time.sleep(1)
    assert running == ["data-api", "postgres", "seaweed"], out


def test_banner_reports_the_built_version(server):
    first_line = server.logs().splitlines()[0]
    assert first_line == f"symposium-data {VERSION}"
    assert server.status()["version"] == VERSION


def test_starts_uninitialized_and_init_works_exactly_once(server, owner_key):
    status = server.status()
    assert status["initialized"] is False
    assert status["api"] == "1"

    admin = owner_key()
    first = server.admin(
        "init", "--admin", "demo-admin", "--pubkey", "-", input=admin.jwk_text()
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(first.stdout)["admin"] == "demo-admin"
    assert server.status()["initialized"] is True

    second = server.admin(
        "init", "--admin", "intruder", "--pubkey", "-", input=owner_key().jwk_text()
    )
    assert second.returncode == 2
    assert "already initialized" in second.stdout
    assert json.loads(server.admin("status").stdout)["admin"] == "demo-admin"


def test_init_refuses_a_private_key(server, owner_key):
    jwk = {**owner_key().jwk, "d": "nWGxne_9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A"}
    result = server.admin(
        "init", "--admin", "demo-admin", "--pubkey", "-", input=json.dumps(jwk)
    )
    assert result.returncode == 1
    assert server.status()["initialized"] is False


def test_first_boot_secrets_are_owner_only_and_sentinels_exist(server):
    out = server.exec(
        "sh",
        "-c",
        "stat -c '%a %n' /apps/data/config/service.env /apps/data/config/token_ed25519.pem "
        "/apps/seaweed/config/s3.json /apps/postgres/config/superuser.pw; "
        "ls /apps/postgres/config/.initialized /apps/seaweed/config/.initialized",
    ).stdout.splitlines()
    assert all(line.startswith("600 ") for line in out[:4]), out
    assert any(line.endswith("postgres/config/.initialized") for line in out)
    assert any(line.endswith("seaweed/config/.initialized") for line in out)


def test_invite_mode_without_public_base_url_refuses_to_start():
    result = subprocess.run(
        ["docker", "run", "--rm", "-e", "SYMPOSIUM_DATA_REGISTRATION=invite", IMAGE],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 1
    assert "requires SYMPOSIUM_DATA_PUBLIC_BASE_URL" in result.stderr


def test_state_survives_restart_and_recreate_without_reinitializing(server, owner_key):
    server.admin(
        "init", "--admin", "demo-admin", "--pubkey", "-", input=owner_key().jwk_text()
    )
    server_id = server.status()["server_id"]

    server.restart()
    assert server.status()["initialized"] is True
    assert server.status()["server_id"] == server_id

    server.recreate()
    status = server.status()
    assert status["initialized"] is True
    assert status["server_id"] == server_id
    assert "first boot" not in server.logs()


def test_kubeconform_accepts_the_manifests():
    manifests = sorted(p.name for p in DOCKER_DIR.glob("k8s-*.yml"))
    assert manifests, "no Kubernetes manifests found"
    result = docker(
        "run",
        "--rm",
        "-v",
        f"{DOCKER_DIR}:/m:ro",
        "ghcr.io/yannh/kubeconform:v0.6.7",
        "-strict",
        "-summary",
        *[f"/m/{name}" for name in manifests],
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Invalid: 0, Errors: 0" in result.stdout


def _status_until(server, predicate, timeout=60):
    deadline = time.time() + timeout
    while True:
        r = httpx.get(server.url + "/v1/status", timeout=30)
        if predicate(r) or time.time() > deadline:
            return r
        time.sleep(1)


def test_status_reports_unavailable_dependencies_with_503_and_recovers(server):
    ctl = ("supervisorctl", "-c", "/tmp/supervisord.conf")
    for program, field in (("postgres", "postgres"), ("seaweed", "s3")):
        server.exec(*ctl, "stop", program)
        down = _status_until(server, lambda r, f=field: r.json()[f] == "unavailable")
        assert down.status_code == 503, down.text
        assert down.json()[field] == "unavailable"

        server.exec(*ctl, "start", program)
        up = _status_until(server, lambda r: r.status_code == 200)
        assert up.status_code == 200, up.text
        assert up.json()["postgres"] == "ok" and up.json()["s3"] == "ok"
