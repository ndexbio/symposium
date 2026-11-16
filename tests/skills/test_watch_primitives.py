"""What keeps the commands that keep running (`gate --watch`, `sync --watch`, `serve`) safe to
stop and to restart, on any OS and with no server: a stop by signal ends the loop with exit
code 0 long before its wait would; one watcher behind a lock, a second one standing by until
the first ends, or stopping it when told to take over; and writes that are whole or not at all,
each process staging its own. Each process here reports its state through files the
tests poll, and what it says through its output, read whole once it has exited."""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from harness import MAX_WAIT, Output
from suite import REPO

TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))

from data_io import replace_text  # noqa: E402

WINDOWS = os.name == "nt"
# a stand-in watcher: the stop handlers, the lock it names (taken as `gate --watch` and
# `sync --watch` take theirs: standing by, or with "take-over" stopping the holder), a file
# saying it is ready with its own pid, then a wait far longer than MAX_WAIT that only a stop
# ends, so a watcher that waited it out fails the test. (On Windows a
# virtualenv's python.exe is a launcher running the interpreter as its child, so the pid that
# holds the lock is the one the interpreter reports, not the launcher's Popen.pid.)
WATCHER = """
import os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from data_io import pause, stop_on_signals, watch_alone
stop_on_signals()
ready = pathlib.Path(sys.argv[3])
try:
    name = sys.argv[2]
    lock = name and watch_alone(
        name, pathlib.Path(".symposium") / f"{name}.lock", f"demo/{sys.argv[5] or 'gate'}",
        replace=sys.argv[5] == "take-over")
    ready.write_text(f"ready {os.getpid()}")
    pause(float(sys.argv[4]))
except KeyboardInterrupt:
    ready.write_text("stopped")
    sys.exit(0)
"""


def start(cwd: Path, lock_name: str, ready: Path, mode: str = "") -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
    process = subprocess.Popen(
        [sys.executable, "-c", WATCHER, str(TOOLS), lock_name, str(ready)]
        + [str(10 * MAX_WAIT), mode],
        cwd=cwd,
        creationflags=flags,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process.output = Output(process.stdout)
    return process


def poll(probe, message: str):
    """Poll every 0.1 s until `probe` returns something truthy. -> that value."""
    deadline = time.monotonic() + MAX_WAIT
    while True:
        value = probe()
        if value:
            return value
        assert time.monotonic() < deadline, message
        time.sleep(0.1)


def says(path: Path, word: str) -> bool:
    return path.exists() and path.read_text().split(" ")[0] == word


def reported_pid(path: Path) -> int:
    """The pid the stand-in wrote beside "ready": the interpreter's own."""
    return int(path.read_text().split()[1])


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
        graceful_stop(watcher)
        assert watcher.wait(MAX_WAIT) == 0  # long before its wait would have ended
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
        assert watcher.wait(MAX_WAIT) == 0
    finally:
        watcher.kill()


def holder_pid(directory: Path, name: str) -> int:
    """The pid the watcher holding a lock wrote beside it, before its user context."""
    return int((directory / ".symposium" / f"{name}.pid").read_text().split()[0])


def test_a_second_watcher_stands_by_and_watches_when_the_first_ends(tmp_path):
    first_ready, second_ready = tmp_path / "first", tmp_path / "second"
    first = start(tmp_path, "gate", first_ready)
    second = None
    try:
        poll(lambda: says(first_ready, "ready"), "the first watcher never started")
        second = start(tmp_path, "gate", second_ready, "keeper")
        second.output.wait_for("standing by")
        # the first runs on, untouched, and is still the one behind the lock
        assert first.poll() is None and not second_ready.exists()
        first_pid = reported_pid(first_ready)
        assert holder_pid(tmp_path, "gate") == first_pid
        graceful_stop(first)
        assert first.wait(MAX_WAIT) == 0
        poll(lambda: says(second_ready, "ready"), "the standby never took the lock")
        assert holder_pid(tmp_path, "gate") == reported_pid(second_ready)
        graceful_stop(second)
        assert second.wait(MAX_WAIT) == 0
        said = second.output.end()
        # it named the watcher it waited for, by pid and by user context
        assert f"pid {first_pid}, demo/gate" in said
        assert "this one is watching now" in said
    finally:
        for process in (first, second):
            if process is not None:
                process.kill()
                process.wait()


def test_a_standby_takes_the_lock_of_a_watcher_that_was_killed(tmp_path):
    first_ready, second_ready = tmp_path / "first", tmp_path / "second"
    first = start(tmp_path, "sync", first_ready)
    second = None
    try:
        poll(lambda: says(first_ready, "ready"), "the first watcher never started")
        second = start(tmp_path, "sync", second_ready)
        second.output.wait_for("standing by")
        first.kill()  # no chance to release anything itself
        first.wait()
        poll(lambda: says(second_ready, "ready"), "the lock outlived its holder")
    finally:
        for process in (first, second):
            if process is not None:
                process.kill()
                process.wait()


def test_a_standby_stops_at_once_on_a_stop_signal(tmp_path):
    first_ready, second_ready = tmp_path / "first", tmp_path / "second"
    first = start(tmp_path, "gate", first_ready)
    second = None
    try:
        poll(lambda: says(first_ready, "ready"), "the first watcher never started")
        second = start(tmp_path, "gate", second_ready)
        second.output.wait_for("standing by")
        graceful_stop(second)
        assert second.wait(MAX_WAIT) == 0
        assert says(second_ready, "stopped") and first.poll() is None
    finally:
        for process in (first, second):
            if process is not None:
                process.kill()
                process.wait()


def test_take_over_stops_the_watcher_and_exactly_one_runs(tmp_path):
    first_ready, second_ready = tmp_path / "first", tmp_path / "second"
    first = start(tmp_path, "gate", first_ready)
    second = None
    try:
        poll(lambda: says(first_ready, "ready"), "the first watcher never started")
        second = start(tmp_path, "gate", second_ready, "take-over")
        poll(lambda: says(second_ready, "ready"), "the second watcher never took over")
        # the first was stopped for it: gracefully where the OS can (exit 0), else terminated
        code = first.wait(MAX_WAIT)
        assert code == 0 or WINDOWS
        assert second.poll() is None
        assert holder_pid(tmp_path, "gate") == reported_pid(second_ready)
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
    second = start(tmp_path, "sync", second_ready)
    try:
        poll(lambda: says(second_ready, "ready"), "the lock outlived its holder")
    finally:
        second.kill()
        second.wait()
    # taken as a free lock: there was no holder left to wait for
    assert "standing by" not in second.output.end()


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


def test_two_processes_writing_one_path_each_stage_their_own_file(tmp_path):
    """Many writers of one path at once: every write lands whole, and none trips on another's
    staged file."""
    target = tmp_path / "state.json"
    writer = (
        "import sys, pathlib; sys.path.insert(0, sys.argv[1]); "
        "from data_io import replace_text; "
        "[replace_text(pathlib.Path(sys.argv[2]), sys.argv[3] * 2000 + chr(10)) "
        "for _ in range(200)]"
    )
    writers = [
        subprocess.Popen(
            [sys.executable, "-c", writer, str(TOOLS), str(target), letter]
        )
        for letter in "abcd"
    ]
    assert [w.wait(MAX_WAIT) for w in writers] == [0, 0, 0, 0]
    text = target.read_text()
    assert len(text) == 2001 and len(set(text[:-1])) == 1
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_a_write_waits_out_a_reader_holding_the_file(tmp_path):
    """On Windows a reader holding the file blocks the rename until it lets go; elsewhere the
    rename goes through at once. Either way the write lands whole. The reader lets go once the
    write has begun (its staged file exists, or it is already done), and the write retries for
    as long as MAX_WAIT."""
    target = tmp_path / "state.json"
    staged = tmp_path / f"state.json.{os.getpid()}.tmp"
    target.write_text("old\n")
    reader = open(target)
    writer = threading.Thread(
        target=replace_text, args=(target, "new\n", int(10 * MAX_WAIT))
    )
    writer.start()
    poll(
        lambda: staged.exists() or target.read_text() == "new\n",
        "the write never began",
    )
    reader.close()
    writer.join(MAX_WAIT)
    assert target.read_text() == "new\n"
    assert not staged.exists()
