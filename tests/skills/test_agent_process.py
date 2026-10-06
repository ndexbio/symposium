"""The agent process (R-I3): the long-lived process that starts the shell each `/symposium`
command runs in, found by walking up from the skill's parent past shells and plain wrappers.
On an injected process table on any OS, then against this test's own real process tree: through
`ps` on macOS and Linux, through the Windows API on Windows."""

import os
import subprocess
import sys

import pytest
from suite import REPO

sys.path.insert(0, str(REPO / "skills" / "symposium" / "scripts"))

from agent_process import AgentProcess, Process, normalized  # noqa: E402


class Table:
    """An injected process table: pid -> Process."""

    def __init__(self, *processes: Process):
        self.rows = {p.pid: p for p in processes}

    def get(self, pid: int):
        return self.rows.get(pid)


def walk(table: Table, start: int, windows: bool = False):
    return AgentProcess(table, windows=windows, start=start).find()


def test_the_walk_passes_shells_and_wrappers_to_the_agent():
    table = Table(
        Process(1, 0, "boot", "launchd"),
        Process(100, 1, "t0", "-zsh"),  # the terminal's login shell
        Process(200, 100, "t1", "/usr/local/bin/agent"),  # the agent
        Process(300, 200, "t2", "/bin/zsh"),  # the command's shell
        Process(310, 300, "t3", "env"),  # a wrapper
        Process(320, 310, "t4", "bash"),
    )
    agent = walk(table, 320)
    assert (agent.pid, agent.started) == (200, "t1")


def test_an_agent_that_is_an_interpreter_is_found():
    table = Table(
        Process(1, 0, "boot", "init"),
        Process(200, 1, "t1", "python3"),  # an agent written in Python
        Process(300, 200, "t2", "sh"),
    )
    assert walk(table, 300).pid == 200


def test_names_are_normalized():
    assert normalized("-zsh") == "zsh"
    assert normalized("/bin/bash") == "bash"
    assert normalized(r"C:\Windows\System32\cmd.exe") == "cmd"
    assert normalized("PowerShell.EXE") == "powershell"


def test_windows_shells_are_passed_and_a_younger_parent_is_not_trusted():
    table = Table(
        Process(10, 4, "100", "explorer.exe"),
        Process(20, 10, "200", "agent.exe"),
        Process(30, 20, "300", "PowerShell.exe"),
        Process(40, 30, "400", "cmd.exe"),
    )
    assert walk(table, 40, windows=True).pid == 20
    # a parent ID now held by a process that started after its child: the walk stops there
    reused = Table(
        Process(20, 10, "900", "agent.exe"), Process(30, 20, "300", "pwsh.exe")
    )
    assert walk(reused, 30, windows=True).pid == 30


def test_the_real_process_tree_finds_this_tests_parent_process():
    """A child of this test, run through a shell, finds this test's own process: the
    long-lived process that started its shell, as an agent starts each command's shell."""
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from agent_process import AgentProcess; p = AgentProcess().find(); "
        "print(p.pid, p.started)"
    )
    scripts = str(REPO / "skills" / "symposium" / "scripts")
    if os.name == "nt":
        command = [
            sys.executable,
            "-c",
            probe,
            scripts,
        ]  # its parent is this test itself
    else:
        command = ["sh", "-c", f'"{sys.executable}" -c "{probe}" "{scripts}"']
    pid, started = subprocess.run(
        command, capture_output=True, text=True, check=True
    ).stdout.split(" ", 1)
    assert int(pid) == os.getpid()
    assert started.strip() == AgentProcess().started(os.getpid())


@pytest.mark.skipif(os.name != "nt", reason="the Windows lookup runs on Windows")
def test_the_windows_lookup_reads_this_process():
    me = AgentProcess(windows=True).processes.get(os.getpid())
    assert me is not None and me.parent > 0 and me.started.isdigit()
    assert normalized(me.name).startswith("python")
