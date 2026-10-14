"""The single-container harness: one data-server container for a whole test session, shared
by the data server's integration suites and the top-level CLI and skill suites.

`make -C data-server test` builds the image once and sets SYMPOSIUM_DATA_TEST_IMAGE (and
SYMPOSIUM_DATA_TEST_VERSION). A session starts one container (named sdtest-*, removed with its
volume at the end), resets the data before each test, and never restarts the container: a test
that needs a new start-up restarts only the API process.

No test depends on how fast the machine is. The server keeps its production timings, so its
background jobs never act on their own during a test: a test that needs the janitor or the
scrub runs it (sweep(), scrub()) and continues once it has finished. Every wait is for an
event or a state, and MAX_WAIT, the one limit for all of them, only bounds a wait that would
otherwise hang.
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx

IMAGE = os.environ.get("SYMPOSIUM_DATA_TEST_IMAGE", "")
VERSION = os.environ.get("SYMPOSIUM_DATA_TEST_VERSION", "")
# The one limit, in seconds, on any wait in any suite: `make test` sets it from
# MAX_PER_TEST_WAIT. Reaching it means something hung; a wait that works ends long before.
MAX_WAIT = float(os.environ.get("SYMPOSIUM_TEST_MAX_WAIT", "120"))
# httpx's request functions, with MAX_WAIT as their timeout in place of httpx's 5 s
HTTP = SimpleNamespace(
    **{
        name: functools.partial(getattr(httpx, name), timeout=MAX_WAIT)
        for name in ("get", "post", "put", "delete", "request", "stream")
    }
)

# The server's production timings, except two that only pace work already under way: the
# janitor and the scrub never run on their own during a test (sweep() and scrub() run them).
# The test hooks act only while a test has created their file: S3 delete faults (the fault
# file) and a quota (the quota file, set_quota()); the reset before each test removes both.
TEST_ENV = {
    "SYMPOSIUM_SERVER_TEST_HOOKS": "1",
    # an upload's heartbeat, so a test can see one without streaming for a minute
    "SYMPOSIUM_SERVER_HEARTBEAT": "0.2",
    # the streams' heartbeat, which also paces each stream's key and access re-check
    "SYMPOSIUM_SERVER_STREAM_HEARTBEAT": "2",
}

SUPERVISORCTL = ("supervisorctl", "-c", "/tmp/supervisord.conf")

# Run inside the container: empty every data table and the bucket, keeping the admin binding
# and the admin's sessions, as a test's admin signed in before the reset.
RESET = """
import os, psycopg
from symposium_data.runtime import PayloadStore, Settings
settings = Settings()
store = PayloadStore(settings)
with psycopg.connect(settings.database_url) as conn:
    conn.execute(
        "TRUNCATE communities, owners, owner_keys, challenges, roster, grants, invites, "
        "collections, files, versions, payloads, ports, api_streams, "
        "api_index, api_citations, api_index_position CASCADE"
    )
    conn.execute("DELETE FROM api_keys WHERE role <> 'admin'")
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

# Run inside the container: one pass of a background job (sweep_pending or scrub), with the
# server's own code and settings, exactly as the API process runs it; it prints the job's result.
JOB = """
import sys
from pathlib import Path
from symposium_data.api_keys import ApiKeys, Sealer, key_file_from
from symposium_data.jobs import Jobs
from symposium_data.records import Records
from symposium_data.runtime import Database, PayloadStore, Settings
settings = Settings()
db = Database(settings)
db.open()
keys = ApiKeys(Sealer(key_file_from(Path(settings.path))))
try:
    print(getattr(Jobs(settings, db, PayloadStore(settings), Records(), keys), sys.argv[1])())
finally:
    db.pool.close()
"""


class Output:
    """Every line a process prints, read on a thread as it comes, so a test waits for the line
    it expects rather than guessing when it is written, and the pipe never fills."""

    def __init__(self, stream):
        self.lines, self.ended = [], False
        self.changed = threading.Condition()
        self.reader = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self.reader.start()

    def _read(self, stream):
        for line in stream:
            with self.changed:
                self.lines.append(line)
                self.changed.notify_all()
        with self.changed:
            self.ended = True
            self.changed.notify_all()

    def text(self) -> str:
        with self.changed:
            return "".join(self.lines)

    def wait_for(self, text: str) -> str:
        """Wait until a line holding `text` is printed. -> that line."""

        def found():
            return next((line for line in self.lines if text in line), None)

        with self.changed:
            self.changed.wait_for(lambda: found() or self.ended, timeout=MAX_WAIT)
            line = found()
        assert line, f"never printed {text!r}:\n{self.text()}"
        return line

    def end(self) -> str:
        """Wait for the end of the output, which comes only once every process writing to it
        has exited, its last line written. -> all of it."""
        self.reader.join(MAX_WAIT)
        assert not self.reader.is_alive(), f"the output never ended:\n{self.text()}"
        return self.text()


def docker(*args, check=True, input=None):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, input=input, timeout=MAX_WAIT
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
        return self

    def wait(self):
        deadline = time.monotonic() + MAX_WAIT
        while time.monotonic() < deadline:
            try:
                r = HTTP.get(self.url + "/v1/status")
                if r.status_code == 200 and r.json().get("s3") == "ok":
                    return r.json()
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError(f"{self.name} never became healthy:\n{self.logs()[-2000:]}")

    def api_status(self) -> str:
        """supervisord's line for the API process: its state and pid."""
        return self.exec(*SUPERVISORCTL, "status", "api-server").stdout.strip()

    def api_pid(self) -> str | None:
        found = re.search(r"\bpid (\d+)", self.api_status())
        return found.group(1) if found else None

    def restart_api(self, signal: str = "TERM"):
        """End the API process only; supervisord starts it again and the container keeps
        running. It first waits for supervisord to count the process as RUNNING (up for its
        first 5 s): one ended before that is a failed start, and after a few supervisord
        gives up on it."""
        deadline = time.monotonic() + MAX_WAIT
        while "RUNNING" not in self.api_status():
            assert time.monotonic() < deadline, (
                f"the API never ran: {self.api_status()}"
            )
            time.sleep(0.2)
        result = self.exec(*SUPERVISORCTL, "signal", signal, "api-server")
        assert result.returncode == 0, result.stdout + result.stderr

    def restarted(self) -> dict:
        """Restart the API and wait until the new process answers. -> its /v1/status. With
        the old pid gone from supervisord's report, the answer is the new process's."""
        old = self.api_pid()
        self.restart_api()
        deadline = time.monotonic() + MAX_WAIT
        while not (self.api_pid() not in (None, old) and self.answering()):
            assert time.monotonic() < deadline, (
                f"the API never answered again ({self.api_status()})"
            )
            time.sleep(0.2)
        return self.status()

    def answering(self) -> bool:
        try:
            return HTTP.get(self.url + "/v1/status").status_code == 200
        except httpx.HTTPError:
            return False

    def status(self) -> dict:
        return HTTP.get(self.url + "/v1/status").json()

    def exec(self, *args, input=None):
        return docker("exec", "-i", self.name, *args, input=input, check=False)

    def logs(self) -> str:
        result = docker("logs", self.name, check=False)
        return result.stdout + result.stderr

    def reset(self):
        """Empty every community, file and payload; the admin binding stays."""
        result = self.exec("/opt/venv/bin/python", "-c", RESET)
        assert result.returncode == 0, result.stderr[-2000:]

    def job(self, name: str) -> int:
        """One pass of a background job, run to its end. -> its result."""
        result = self.exec("/opt/venv/bin/python", "-c", JOB, name)
        assert result.returncode == 0, result.stderr[-2000:]
        return int(result.stdout.strip())

    def sweep(self) -> int:
        """One janitor pass. -> how many items still wait for a retry."""
        return self.job("sweep_pending")

    def scrub(self) -> int:
        """One scrub pass. -> how many payloads did not match their digest."""
        return self.job("scrub")

    def remove(self):
        docker("rm", "-f", "-v", self.name, check=False)
        docker("volume", "rm", "-f", self.volume, check=False)
