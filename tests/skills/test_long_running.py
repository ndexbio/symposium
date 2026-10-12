"""The commands that keep running until stopped (R-I3): the skill runs each one's tool under a
`LongRunning`, which passes its output through as it is printed and stops it when the agent
session that started it ends, or when the skill is told to stop. On a stand-in tool and a
stand-in agent process, real processes on any OS, with no server."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from harness import MAX_WAIT
from suite import REPO

SCRIPTS = REPO / "skills" / "symposium" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from long_running import AGENT_ENDED, STOPPED  # noqa: E402

# a tool that keeps running: a line when it starts, a clean exit on ctrl-c, and its pid and
# a tick count in a state file beside it, which the tests poll instead of its output
TOOL = """
import os, pathlib, sys, time
state = pathlib.Path(__file__).with_suffix(".state")
def record(ticks):
    staged = state.with_suffix(".staged")
    staged.write_text(f"{os.getpid()} {ticks}")
    os.replace(staged, state)
print(f"tool started {os.getpid()}")
record(0)
if len(sys.argv) > 1:
    sys.exit(int(sys.argv[1]))
try:
    ticks = 0
    while True:
        time.sleep(0.1)
        ticks += 1
        record(ticks)
except KeyboardInterrupt:
    print("tool stopped")
"""
# the skill's part: the tool run under a LongRunning that watches the given agent process,
# or, given "none", one that finds no agent process at all
WRAPPER = """
import os, sys
sys.path.insert(0, sys.argv[1])
from agent_process import AgentProcess
from long_running import LongRunning
class NoAgent:
    def find(self):
        return None
agent = sys.argv[2]
find = NoAgent if agent == "none" else lambda: AgentProcess(start=int(agent), launcher="")
running = LongRunning(find, every=0.1, grace=5)
environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
sys.exit(running.run([sys.executable, *sys.argv[3:]], environment, None))
"""


@pytest.fixture
def tool(tmp_path) -> Path:
    path = tmp_path / "tool.py"
    path.write_text(TOOL)
    return path


@pytest.fixture
def agent():
    """A stand-in agent process, running until the test ends it, abruptly."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import threading; threading.Event().wait()"]
    )
    yield process
    process.kill()
    process.wait()


def wrapped(tmp_path, agent_pid, *tool_args) -> tuple:
    """The wrapper started with its output going to a file, as an agent's background command."""
    log = tmp_path / "out.log"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            WRAPPER,
            str(SCRIPTS),
            str(agent_pid),
            *map(str, tool_args),
        ],
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
    )
    return process, log


def tool_state(tool: Path) -> tuple[int, int] | None:
    """(pid, ticks) the running tool last recorded, or None before it starts."""
    state = tool.with_suffix(".state")
    if not state.exists():
        return None
    pid, ticks = state.read_text().split()
    return int(pid), int(ticks)


def tool_running(tool: Path, ticks: int = 0) -> int:
    """Poll every 0.1 s until the tool has started and ticked `ticks` times. -> its pid."""
    deadline = time.monotonic() + MAX_WAIT
    while True:
        state = tool_state(tool)
        if state is not None and state[1] >= ticks:
            return state[0]
        assert time.monotonic() < deadline, f"the tool never ran {ticks} ticks: {state}"
        time.sleep(0.1)


def test_the_tools_output_arrives_as_it_is_printed(tmp_path, tool, agent):
    wrapper, log = wrapped(tmp_path, agent.pid, tool)
    try:
        pid = tool_running(tool)
        # the tool prints its first line before it records its state, unbuffered: it is in
        # the output now, while the tool still runs
        assert "tool started" in log.read_text()
        assert wrapper.poll() is None
    finally:
        os.kill(pid, signal.SIGTERM)
        wrapper.wait(MAX_WAIT)


def test_the_tool_stops_when_its_agent_session_ends(tmp_path, tool, agent):
    wrapper, log = wrapped(tmp_path, agent.pid, tool)
    tool_running(tool)
    agent.kill()  # abruptly: no chance to stop anything itself
    agent.wait()
    assert wrapper.wait(MAX_WAIT) == 0
    out = log.read_text()
    assert out.rstrip().endswith(AGENT_ENDED)
    if os.name != "nt":
        assert "tool stopped" in out  # stopped with ctrl-c, and finished cleanly


@pytest.mark.skipif(os.name == "nt", reason="SIGTERM is delivered on macOS and Linux")
def test_a_stop_from_outside_stops_the_tool_cleanly(tmp_path, tool, agent):
    wrapper, log = wrapped(tmp_path, agent.pid, tool)
    tool_running(tool)
    wrapper.send_signal(signal.SIGTERM)
    assert wrapper.wait(MAX_WAIT) == 0
    out = log.read_text()
    assert "tool stopped" in out and out.rstrip().endswith(STOPPED)


def test_without_an_agent_process_the_tool_runs_until_stopped(tmp_path, tool):
    wrapper, log = wrapped(tmp_path, "none", tool)
    try:
        # running through ten of the wrapper's 0.1 s check intervals, and still running
        pid = tool_running(tool, ticks=10)
        assert wrapper.poll() is None and AGENT_ENDED not in log.read_text()
    finally:
        os.kill(pid, signal.SIGTERM)
        wrapper.wait(MAX_WAIT)


def test_a_tool_that_ends_on_its_own_gives_its_exit_code(tmp_path, tool, agent):
    wrapper, log = wrapped(tmp_path, agent.pid, tool, 3)
    assert wrapper.wait(MAX_WAIT) == 3
    assert STOPPED not in log.read_text()
