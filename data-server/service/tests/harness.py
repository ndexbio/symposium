"""The single-container harness: one data-server container for a whole test session, shared
by the data server's integration suites and the top-level CLI and skill suites.

`make -C data-server test` builds the image once and sets SYMPOSIUM_DATA_TEST_IMAGE (and
SYMPOSIUM_DATA_TEST_VERSION). A session starts one container (named sdtest-*, removed with its
volume at the end) with every duration shortened for tests, resets the data before each test,
and never restarts the container: a test that needs a new start-up restarts only the API
process.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import httpx

IMAGE = os.environ.get("SYMPOSIUM_DATA_TEST_IMAGE", "")
VERSION = os.environ.get("SYMPOSIUM_DATA_TEST_VERSION", "")

# Every duration the server exposes, shortened so no test waits more than about a second. The
# test hooks act only while a test has created their file: S3 delete faults (the fault file)
# and a quota (the quota file, set_quota()); the reset before each test removes both.
TEST_ENV = {
    "SYMPOSIUM_SERVER_PENDING_TTL": "1",
    "SYMPOSIUM_SERVER_JANITOR_INTERVAL": "0.5",
    "SYMPOSIUM_SERVER_SCRUB_INTERVAL": "0.5",
    "SYMPOSIUM_SERVER_TEST_HOOKS": "1",
    # the API's stream heartbeat, which also paces each stream's key re-check
    "SYMPOSIUM_DATA_API_HEARTBEAT": "2",
}

# Run inside the container: empty every data table and the bucket, keeping the admin binding.
RESET = """
import os, psycopg
from symposium_data.runtime import PayloadStore, Settings
settings = Settings()
store = PayloadStore(settings)
with psycopg.connect(settings.database_url) as conn:
    conn.execute(
        "TRUNCATE communities, owners, owner_keys, challenges, roster, grants, invites, "
        "collections, files, versions, payloads, read_keys, ports, api_keys, api_streams, "
        "api_index, api_citations, api_index_position CASCADE"
    )
for page in store.s3.get_paginator("list_objects_v2").paginate(Bucket=store.bucket):
    for item in page.get("Contents", []):
        store.s3.delete_object(Bucket=store.bucket, Key=item["Key"])
for upload in store.s3.list_multipart_uploads(Bucket=store.bucket).get("Uploads", []):
    store.s3.abort_multipart_upload(
        Bucket=store.bucket, Key=upload["Key"], UploadId=upload["UploadId"]
    )
for hook in (store.FAULT_FILE, Settings.QUOTA_FILE):
    if os.path.exists(hook):
        os.remove(hook)
"""


# Run inside the container once it is healthy: SeaweedFS takes seconds over its first write
# (it allocates storage then), which would race the 1 s pending TTL of whichever test wrote
# first. One throwaway object, written and removed before any test runs.
WARM_UP = """
from symposium_data.runtime import PayloadStore, Settings
store = PayloadStore(Settings())
store.put_bytes("warm-up", b"warm-up")
store.s3.delete_object(Bucket=store.bucket, Key="warm-up")
"""


def docker(*args, check=True, input=None, timeout=600):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, input=input, timeout=timeout
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {result.stderr.strip()[-600:]}")
    return result


class Server:
    """The session's data-server container and the volume holding its state."""

    def __init__(self, env: dict):
        self.env = env
        self.name = f"sdtest-{uuid.uuid4().hex[:10]}"
        self.volume = f"{self.name}-vol"
        self.url = ""

    def start(self, key_file: Path | None = None):
        """Create the container, copy the admin key file onto its volume when one is given (as
        an operator places it), and start it. Without a key file it starts non-operational,
        for a suite that onboards it the way an operator does."""
        # Docker assigns the host port itself: picking a "free" port first races with
        # anything else that grabs it before the container binds. The host alias lets the
        # server reach a stub a test runs on this machine.
        cmd = ["create", "--name", self.name, "-p", "127.0.0.1::8080"]
        cmd += ["--add-host=host.docker.internal:host-gateway"]
        cmd += ["-v", f"{self.volume}:/apps"]
        for key, value in self.env.items():
            cmd += ["-e", f"{key}={value}"]
        docker(*cmd, IMAGE)
        if key_file is not None:
            docker("cp", str(key_file), f"{self.name}:/apps/{key_file.name}")
        docker("start", self.name)
        mapped = docker("port", self.name, "8080").stdout.splitlines()[0].strip()
        self.url = f"http://127.0.0.1:{mapped.rsplit(':', 1)[1]}"
        self.wait()
        warmed = self.exec("/opt/venv/bin/python", "-c", WARM_UP)
        assert warmed.returncode == 0, warmed.stderr[-2000:]
        return self

    def wait(self, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = httpx.get(self.url + "/v1/status", timeout=5)
                if r.status_code == 200 and r.json().get("s3") == "ok":
                    return r.json()
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError(f"{self.name} never became healthy:\n{self.logs()[-2000:]}")

    def restart_api(self, signal: str = "TERM"):
        """End the API process only; supervisord starts it again and the container keeps
        running. The caller waits for the state the new process reports."""
        ctl = ("supervisorctl", "-c", "/tmp/supervisord.conf")
        result = self.exec(*ctl, "signal", signal, "api-server")
        assert result.returncode == 0, result.stdout + result.stderr

    def status(self) -> dict:
        return httpx.get(self.url + "/v1/status", timeout=10).json()

    def exec(self, *args, input=None):
        return docker("exec", "-i", self.name, *args, input=input, check=False)

    def logs(self) -> str:
        result = docker("logs", self.name, check=False)
        return result.stdout + result.stderr

    def reset(self):
        """Empty every community, file and payload; the admin binding stays."""
        result = self.exec("/opt/venv/bin/python", "-c", RESET)
        assert result.returncode == 0, result.stderr[-2000:]

    def remove(self):
        docker("rm", "-f", "-v", self.name, check=False)
        docker("volume", "rm", "-f", self.volume, check=False)
