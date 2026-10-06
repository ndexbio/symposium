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
from suite import REPO

SCRIPTS = REPO / "skills" / "symposium" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from long_running import AGENT_ENDED, STOPPED  # noqa: E402

# a tool that keeps running: a line when it starts, and a clean exit on ctrl-c
TOOL = """
import os, sys, time
print(f"tool started {os.getpid()}")
if len(sys.argv) > 1:
    sys.exit(int(sys.argv[1]))
try:
    while True:
        time.sleep(0.2)
except KeyboardInterrupt:
    print("tool stopped")
"""
# the skill's part: the tool run under a LongRunning that watches the given agent process
WRAPPER = """
import os, sys
sys.path.insert(0, sys.argv[1])
from agent_process import AgentProcess
from long_running import LongRunning
agent = int(sys.argv[2])
running = LongRunning(lambda: AgentProcess(start=agent, launcher=""), every=0.5, grace=5)
environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
sys.exit(running.run([sys.executable, *sys.argv[3:]], environment, None))
"""
NO_SUCH_PROCESS = 4_000_000


@pytest.fixture
def tool(tmp_path) -> Path:
    path = tmp_path / "tool.py"
    path.write_text(TOOL)
    return path


@pytest.fixture
def agent():
    """A stand-in agent process; ended abruptly by the test that needs it to end."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield process
    process.kill()
    process.wait()


def wrapped(tmp_path, agent_pid: int, *tool_args) -> tuple:
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


def until(log: Path, text: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if log.exists() and text in log.read_text():
            return True
        time.sleep(0.1)
    return False


def tool_pid(log: Path) -> int:
    return int(log.read_text().split("tool started ", 1)[1].split()[0])


def test_the_tools_output_arrives_as_it_is_printed(tmp_path, tool, agent):
    wrapper, log = wrapped(tmp_path, agent.pid, tool)
    try:
        assert until(log, "tool started", 5)  # while the tool is still running
        assert wrapper.poll() is None
    finally:
        os.kill(tool_pid(log), signal.SIGTERM)
        wrapper.wait(timeout=20)


def test_the_tool_stops_when_its_agent_session_ends(tmp_path, tool, agent):
    wrapper, log = wrapped(tmp_path, agent.pid, tool)
    assert until(log, "tool started", 5)
    agent.kill()  # abruptly: no chance to stop anything itself
    agent.wait()
    assert wrapper.wait(timeout=20) == 0
    out = log.read_text()
    assert out.rstrip().endswith(AGENT_ENDED)
    if os.name != "nt":
        assert "tool stopped" in out  # stopped with ctrl-c, and finished cleanly


@pytest.mark.skipif(os.name == "nt", reason="SIGTERM is delivered on macOS and Linux")
def test_a_stop_from_outside_stops_the_tool_cleanly(tmp_path, tool, agent):
    wrapper, log = wrapped(tmp_path, agent.pid, tool)
    assert until(log, "tool started", 5)
    wrapper.send_signal(signal.SIGTERM)
    assert wrapper.wait(timeout=20) == 0
    out = log.read_text()
    assert "tool stopped" in out and out.rstrip().endswith(STOPPED)


def test_without_an_agent_process_the_tool_runs_until_stopped(tmp_path, tool):
    wrapper, log = wrapped(tmp_path, NO_SUCH_PROCESS, tool)
    try:
        assert until(log, "tool started", 5)
        time.sleep(2)  # several checks' worth
        assert wrapper.poll() is None and AGENT_ENDED not in log.read_text()
    finally:
        os.kill(tool_pid(log), signal.SIGTERM)
        wrapper.wait(timeout=20)


def test_a_tool_that_ends_on_its_own_gives_its_exit_code(tmp_path, tool, agent):
    wrapper, log = wrapped(tmp_path, agent.pid, tool, 3)
    assert wrapper.wait(timeout=20) == 3
    assert STOPPED not in log.read_text()
