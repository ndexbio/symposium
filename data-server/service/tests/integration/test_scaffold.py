"""The image and its first boot. Binding the admin is the key file's (R-D4), checked in
test_admin_key_file.py and the unit tests."""

import time
from pathlib import Path

import httpx
from harness import IMAGE, VERSION, docker

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
        time.sleep(0.2)
    assert running == ["data-api", "postgres", "seaweed"], out


def test_banner_reports_the_built_version(server):
    first_line = server.logs().splitlines()[0]
    assert first_line == f"symposium-data {VERSION}"
    assert server.status()["version"] == VERSION


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


def _status_until(server, predicate, timeout=15):
    deadline = time.time() + timeout
    while True:
        r = httpx.get(server.url + "/v1/status", timeout=30)
        if predicate(r) or time.time() > deadline:
            return r
        time.sleep(0.2)


def test_status_reports_an_unavailable_database_with_503_and_recovers(server):
    # PostgreSQL only: SeaweedFS's own shutdown and start-up take ~25 s, which no test hook
    # can shorten
    ctl = ("supervisorctl", "-c", "/tmp/supervisord.conf")
    server.exec(*ctl, "stop", "postgres")
    down = _status_until(server, lambda r: r.json()["postgres"] == "unavailable")
    assert down.status_code == 503, down.text
    assert down.json()["postgres"] == "unavailable"
    assert down.elapsed.total_seconds() < 1  # inside a readiness probe's timeout

    server.exec(*ctl, "start", "postgres")
    up = _status_until(server, lambda r: r.status_code == 200)
    assert up.status_code == 200, up.text
    assert up.json()["postgres"] == "ok" and up.json()["s3"] == "ok"


def test_the_image_declares_no_stray_volumes():
    # every byte of state lives under /apps; a declared VOLUME would leave an anonymous
    # volume behind for every container ever started from the image
    volumes = docker(
        "image", "inspect", IMAGE, "--format", "{{json .Config.Volumes}}"
    ).stdout
    assert volumes.strip() in ("null", "{}"), volumes
