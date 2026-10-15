"""The commands that keep running, against the suite's data server: `gate.py --watch`,
`sync.py --watch` and `serve.py` each run until stopped, stop on a signal with exit code 0 well
before their wait would end (their poll is ten times MAX_WAIT here), even mid-decision, and a
restart takes over from the one still running on the session. Readiness is the state each
command leaves (the lock it holds, its state file, `serve`'s `/__build`) or the line it prints
when it is done, never a guess at how long anything takes."""

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from harness import HTTP, MAX_WAIT, Output
from skills.test_workflow import TOOLS, note, tool
from suite import enroll

WINDOWS = os.name == "nt"
STOPS = [signal.SIGINT] + ([] if WINDOWS else [signal.SIGTERM])
# far longer than any wait here may last, so a command that waited it out fails the test
POLL = str(int(10 * MAX_WAIT))
SERVING = re.compile(r"serving  http://localhost:(\d+)/")


def poll(probe, message: str):
    """Poll every 0.2 s until `probe` returns something truthy. -> that value."""
    deadline = time.monotonic() + MAX_WAIT
    while True:
        value = probe()
        if value:
            return value
        assert time.monotonic() < deadline, message
        time.sleep(0.2)


def built(port: int) -> bool:
    try:
        state = HTTP.get(f"http://127.0.0.1:{port}/__build").json()
    except (httpx.HTTPError, ValueError):
        return False
    return state.get("build", 0) >= 1


class Watch:
    """One command that keeps running, in a session's directory. `serve` takes a free port of
    its own (`--port 0`) unless it is given one, and `port` is the one it says it serves on."""

    def __init__(self, suite, cwd: Path, command: str, port: int = 0, env=None):
        script, args = {
            "gate": ("gate.py", ["--watch"]),
            "sync": ("sync.py", ["--watch"]),
            "serve": ("serve.py", ["--port", str(port)]),
        }[command]
        self.command, self.cwd = command, cwd
        self.started = time.time()
        self.process = subprocess.Popen(
            [sys.executable, str(TOOLS / script), *args],
            cwd=cwd,
            env={
                **suite.env,
                "SYMPOSIUM_POLL": POLL,
                "PYTHONUNBUFFERED": "1",
                **(env or {}),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.output = Output(self.process.stdout)
        self.port = 0
        if command == "serve":
            self.port = int(SERVING.search(self.output.wait_for("serving")).group(1))
        self.lock = f"serve-{self.port}" if command == "serve" else command

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

    def stop(self, stop=signal.SIGINT) -> int:
        """Signal it and wait for it to exit. -> its exit code."""
        self.process.send_signal(stop)
        return self.process.wait(MAX_WAIT)

    def ended(self) -> str:
        """Everything it printed, once it has exited."""
        return self.output.end()

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
def test_each_watch_stops_at_once_on_a_signal(suite, session, command, stop):
    watch = Watch(suite, session, command)
    try:
        poll(watch.passed_once, f"{command} never finished its first pass")
        code = watch.stop(
            stop
        )  # within MAX_WAIT: long before its wait would have ended
        out = watch.ended()
        assert code == 0, out
        assert "Traceback" not in out and "stopped" in out, out
    finally:
        watch.kill()


# Stands in for the CLI: on `promote` it says so (a file) and waits for the test to let it go
# on (another file), then runs the real CLI. The gate is then exactly mid-decision.
HELD_PROMOTE = """
import json, os, subprocess, sys, time
here = os.environ["HELD_PROMOTE_DIR"]
if sys.argv[1:2] == ["promote"]:
    open(os.path.join(here, "promoting"), "w").close()
    while not os.path.exists(os.path.join(here, "go-on")):
        time.sleep(0.05)
real = json.loads(os.environ["REAL_SYMPOSIUM_DATA_CLI"])
sys.exit(subprocess.call(real + sys.argv[1:]))
"""


def test_a_stop_during_a_decision_waits_for_it_and_shows_it(
    suite, cli, session, tmp_path
):
    lyra = session / "lyra"
    assert tool(suite, lyra, "publish.py", note(lyra, "lyra", "midpass"))[0] == 0
    stand_in = tmp_path / "held_promote.py"
    stand_in.write_text(HELD_PROMOTE)
    watch = Watch(
        suite,
        session,
        "gate",
        env={
            "SYMPOSIUM_DATA_CLI": json.dumps([sys.executable, str(stand_in)]),
            "REAL_SYMPOSIUM_DATA_CLI": suite.env["SYMPOSIUM_DATA_CLI"],
            "HELD_PROMOTE_DIR": str(tmp_path),
        },
    )
    try:
        poll(lambda: (tmp_path / "promoting").exists(), "the gate never promoted")
        watch.process.send_signal(
            signal.SIGINT
        )  # mid-decision: its promote is under way
        (tmp_path / "go-on").touch()
        code = watch.process.wait(MAX_WAIT)
        out = watch.ended()
        assert code == 0 and "Traceback" not in out, out
        assert "ACCEPTED" in out and "stopped" in out, (
            out
        )  # the decision, whole and shown
        record = cli.ok(session, "changes", "--collection", "record", "--all")["items"]
        assert "lyra_note_midpass_v1" in [i["name"] for i in record]
        state = json.loads((session / "record" / ".gate_state.json").read_text())
        assert any(d.startswith("accepted as") for d in state["decisions"].values())
    finally:
        watch.kill()


@pytest.mark.parametrize("command", ["gate", "sync", "serve"])
def test_a_restarted_watch_takes_over_and_exactly_one_runs(suite, session, command):
    first = Watch(suite, session, command)
    second = None
    try:
        poll(first.passed_once, f"the first {command} never finished its first pass")
        second = Watch(suite, session, command, port=first.port)
        assert first.process.wait(MAX_WAIT) == 0, first.ended()
        assert "stopped" in first.ended()
        poll(second.holds_the_lock, f"the second {command} never took the lock")
        assert second.process.poll() is None
        second.output.wait_for("taking over")
        if command == "serve":
            poll(lambda: built(first.port), "the restarted serve never answered")
    finally:
        for watch in (first, second):
            if watch is not None:
                watch.kill()
