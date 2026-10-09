"""What keeps the commands that keep running (`gate --watch`, `sync --watch`, `serve`) safe to
stop and to restart, on any OS and with no server: a stop by signal ends the loop at once with
exit code 0; one watcher per session, a restarted one taking over; and writes that are whole
or not at all. Each process here reports its state through files the tests poll, never its
output."""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from suite import REPO

TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))

from data_io import replace_text  # noqa: E402

WINDOWS = os.name == "nt"
# a stand-in watcher: the stop handlers, the session's lock when it names one, a file saying
# it is ready, then a long wait that only a stop ends
WATCHER = """
import pathlib, sys, time
sys.path.insert(0, sys.argv[1])
from data_io import stop_on_signals, take_over
stop_on_signals()
lock = take_over(sys.argv[2]) if sys.argv[2] else None
ready = pathlib.Path(sys.argv[3])
ready.write_text("ready")
try:
    time.sleep(600)
except KeyboardInterrupt:
    ready.write_text("stopped")
    sys.exit(0)
"""


def start(cwd: Path, lock_name: str, ready: Path) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
    return subprocess.Popen(
        [sys.executable, "-c", WATCHER, str(TOOLS), lock_name, str(ready)],
        cwd=cwd,
        creationflags=flags,
    )


def poll(probe, message: str, seconds: float = 10):
    """Poll every 0.1 s until `probe` returns something truthy. -> that value."""
    deadline = time.monotonic() + seconds
    while True:
        value = probe()
        if value:
            return value
        assert time.monotonic() < deadline, message
        time.sleep(0.1)


def says(path: Path, word: str) -> bool:
    return path.exists() and path.read_text() == word


def graceful_stop(process: subprocess.Popen):
    """The signal a process is asked to stop with: SIGTERM, or CTRL_BREAK on Windows, where
    SIGTERM is TerminateProcess."""
    if WINDOWS:
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGTERM)


def test_a_stop_signal_ends_the_wait_at_once_with_exit_code_0(tmp_path):
    ready = tmp_path / "ready"
    watcher = start(tmp_path, "", ready)
    try:
        poll(lambda: says(ready, "ready"), "the watcher never started")
        stopped_at = time.monotonic()
        graceful_stop(watcher)
        assert watcher.wait(timeout=10) == 0
        assert time.monotonic() - stopped_at < 2  # not after its 600 s wait
        assert says(ready, "stopped")
    finally:
        watcher.kill()


@pytest.mark.skipif(WINDOWS, reason="ctrl-c reaches a console group on Windows")
def test_ctrl_c_ends_the_wait_the_same_way(tmp_path):
    ready = tmp_path / "ready"
    watcher = start(tmp_path, "", ready)
    try:
        poll(lambda: says(ready, "ready"), "the watcher never started")
        watcher.send_signal(signal.SIGINT)
        assert watcher.wait(timeout=10) == 0
    finally:
        watcher.kill()


def test_a_restarted_watcher_takes_over_and_exactly_one_runs(tmp_path):
    first_ready, second_ready = tmp_path / "first", tmp_path / "second"
    first = start(tmp_path, "gate", first_ready)
    second = None
    try:
        poll(lambda: says(first_ready, "ready"), "the first watcher never started")
        second = start(tmp_path, "gate", second_ready)
        poll(lambda: says(second_ready, "ready"), "the second watcher never took over")
        # the first was stopped for it: gracefully where the OS can (exit 0), else terminated
        code = first.wait(timeout=10)
        assert code == 0 or WINDOWS
        assert second.poll() is None
        pid = int((tmp_path / ".symposium" / "gate.pid").read_text())
        assert pid == second.pid
    finally:
        for process in (first, second):
            if process is not None:
                process.kill()
                process.wait()


def test_a_killed_watcher_leaves_no_stale_lock(tmp_path):
    first_ready, second_ready = tmp_path / "first", tmp_path / "second"
    first = start(tmp_path, "sync", first_ready)
    poll(lambda: says(first_ready, "ready"), "the first watcher never started")
    first.kill()  # no chance to release anything itself
    first.wait()
    started = time.monotonic()
    second = start(tmp_path, "sync", second_ready)
    try:
        poll(lambda: says(second_ready, "ready"), "the lock outlived its holder")
        assert (
            time.monotonic() - started < 5
        )  # taken at once, not after a takeover wait
    finally:
        second.kill()
        second.wait()


def test_watchers_of_different_names_run_side_by_side(tmp_path):
    gate_ready, sync_ready = tmp_path / "gate", tmp_path / "sync"
    gate = start(tmp_path, "gate", gate_ready)
    sync = start(tmp_path, "sync", sync_ready)
    try:
        poll(
            lambda: says(gate_ready, "ready") and says(sync_ready, "ready"),
            "not both ran",
        )
        assert gate.poll() is None and sync.poll() is None
    finally:
        for process in (gate, sync):
            process.kill()
            process.wait()


def test_a_write_is_whole_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "state.json"
    replace_text(target, '{"since": 1}\n')
    replace_text(target, '{"since": 2}\n')
    assert target.read_text() == '{"since": 2}\n'
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_a_write_waits_out_a_reader_holding_the_file(tmp_path):
    """On Windows a reader holding the file blocks the rename until it lets go; elsewhere the
    rename goes through at once. Either way the write lands whole."""
    target = tmp_path / "state.json"
    target.write_text("old\n")
    reader = open(target)
    threading.Timer(0.3, reader.close).start()
    replace_text(target, "new\n")
    assert target.read_text() == "new\n"
    assert not (tmp_path / "state.json.tmp").exists()
