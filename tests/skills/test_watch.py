"""The commands that keep running, against the suite's data server: `gate.py --watch`,
`sync.py --watch` and `serve.py` each run until stopped, stop at once on a signal with exit
code 0 however long their wait (SYMPOSIUM_POLL is 600 here), even mid-pass, and a restart
takes over from the one still running on the session. Readiness is the state each command
leaves (the lock it holds, its state file, `serve`'s `/__build`), never its output."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from skills.test_workflow import TOOLS, note, tool
from suite import enroll

WINDOWS = os.name == "nt"
STOPS = [signal.SIGINT] + ([] if WINDOWS else [signal.SIGTERM])


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def poll(probe, message: str, seconds: float = 120):
    """Poll every 0.2 s until `probe` returns something truthy. -> that value."""
    deadline = time.monotonic() + seconds
    while True:
        value = probe()
        if value:
            return value
        assert time.monotonic() < deadline, message
        time.sleep(0.2)


def built(port: int) -> bool:
    try:
        state = httpx.get(f"http://127.0.0.1:{port}/__build", timeout=2).json()
    except (httpx.HTTPError, ValueError):
        return False
    return state.get("build", 0) >= 1


class Watch:
    """One command that keeps running, in a session's directory, its output in a file."""

    def __init__(self, suite, cwd: Path, command: str, out: Path, port: int = 0):
        script, args = {
            "gate": ("gate.py", ["--watch"]),
            "sync": ("sync.py", ["--watch"]),
            "serve": ("serve.py", ["--port", str(port)]),
        }[command]
        self.command, self.cwd, self.port, self.out = command, cwd, port, out
        self.lock = f"serve-{port}" if command == "serve" else command
        self.started = time.time()
        self.process = subprocess.Popen(
            [sys.executable, str(TOOLS / script), *args],
            cwd=cwd,
            env={**suite.env, "SYMPOSIUM_POLL": "600", "PYTHONUNBUFFERED": "1"},
            stdout=out.open("w"),
            stderr=subprocess.STDOUT,
        )

    def holds_the_lock(self) -> bool:
        """This process is the session's watcher: its pid is in the lock's pid file, which is
        written once its stop handlers are installed, just before its first pass."""
        try:
            pid = int((self.cwd / ".symposium" / f"{self.lock}.pid").read_text())
        except (OSError, ValueError):
            return False
        return pid == self.process.pid

    def passed_once(self) -> bool:
        """This process has finished a pass: it holds the lock, and the state a pass leaves
        was written since it started."""
        if not self.holds_the_lock():
            return False
        if self.command == "serve":
            return built(self.port)
        state = self.cwd / "record" / f".{self.command}_state.json"
        return state.exists() and state.stat().st_mtime >= self.started

    def output(self) -> str:
        return self.out.read_text()

    def stop(self, stop=signal.SIGINT) -> tuple[int, float]:
        """-> (exit code, seconds from the signal to the exit)."""
        sent = time.monotonic()
        self.process.send_signal(stop)
        code = self.process.wait(timeout=30)
        return code, time.monotonic() - sent

    def kill(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()


@pytest.fixture
def session(suite, cli, admin_dir):
    """The admin's session with one Artifact accepted into the record and in its copy, so
    every command has something to keep (`serve` stops on an empty record)."""
    lyra = enroll(cli, admin_dir, "lyra")
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "kept"))[0] == 0
    code, out = tool(suite, admin_dir, "gate.py")
    assert code == 0 and "ACCEPTED" in out, out
    return admin_dir


@pytest.mark.parametrize("command", ["gate", "sync", "serve"])
@pytest.mark.parametrize("stop", STOPS, ids=lambda s: s.name)
def test_each_watch_stops_at_once_on_a_signal(suite, session, tmp_path, command, stop):
    watch = Watch(suite, session, command, tmp_path / "out.log", free_port())
    try:
        poll(watch.passed_once, f"{command} never finished its first pass")
        code, seconds = watch.stop(stop)
        out = watch.output()
        assert code == 0, out
        assert seconds < 2, f"{command} took {seconds:.1f}s, not its 600 s wait"
        assert "Traceback" not in out and "stopped" in out, out
    finally:
        watch.kill()


def test_a_gate_stopped_mid_pass_stops_cleanly_and_shows_its_decisions(
    suite, cli, session, tmp_path
):
    lyra = session / "lyra"
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "midpass"))[0] == 0
    watch = Watch(suite, session, "gate", tmp_path / "out.log")
    try:
        poll(watch.holds_the_lock, "the gate never started watching")
        code, _ = watch.stop(signal.SIGINT)  # its first pass has just begun
        out = watch.output()
        assert code == 0 and "Traceback" not in out, out
        state = session / "record" / ".gate_state.json"
        json.loads(state.read_text())  # whole, however the stop fell
        record = cli.ok(session, "changes", "--collection", "record", "--all")["items"]
        if any(i["name"] == "lyra_note_midpass_v1" for i in record):
            assert "ACCEPTED" in out, out  # a decision made is a decision shown
    finally:
        watch.kill()


@pytest.mark.parametrize("command", ["gate", "sync", "serve"])
def test_a_restarted_watch_takes_over_and_exactly_one_runs(
    suite, session, tmp_path, command
):
    port = free_port()
    first = Watch(suite, session, command, tmp_path / "first.log", port)
    second = None
    try:
        poll(first.passed_once, f"the first {command} never finished its first pass")
        second = Watch(suite, session, command, tmp_path / "second.log", port)
        assert first.process.wait(timeout=30) == 0, first.output()
        assert "stopped" in first.output()
        poll(second.holds_the_lock, f"the second {command} never took the lock")
        assert second.process.poll() is None
        assert "taking over" in second.output()
        if command == "serve":
            poll(lambda: built(port), "the restarted serve never answered on its port")
    finally:
        for watch in (first, second):
            if watch is not None:
                watch.kill()
