"""The commands that keep running until stopped (`gate --watch`, `sync --watch`, `serve`): the
skill runs each one's tool under a `LongRunning`, which stops it when the agent session that
started it ends, so it never outlives that session.

It notes the agent process (agent_process.py: its PID and start time) and checks every few
seconds that the same process is still running. When it has ended, or when the skill is told to
stop (SIGTERM, or ctrl-c), the tool is stopped: on macOS and Linux with ctrl-c (SIGINT), which
every tool handles by finishing cleanly, and killed if it has not exited within the grace period;
on Windows it is terminated, which is safe for the gate because the server holds every decision.
A last line says why it stopped.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Callable

from agent_process import AgentProcess

AGENT_ENDED = "stopped: the agent session that started this has ended"
STOPPED = "stopped"


class Stop(Exception):
    """The skill was told to stop (SIGTERM)."""


class LongRunning:
    def __init__(
        self,
        agent_process: Callable[[], AgentProcess] = AgentProcess,
        every: float = 5.0,
        grace: float = 10.0,
        windows: bool | None = None,
    ):
        self.agent_process = agent_process  # a fresh process read for each check
        self.every = every
        self.grace = grace
        self.windows = os.name == "nt" if windows is None else windows

    def run(self, process: list, env: dict, cwd) -> int:
        """Run the tool until it ends, or until it is stopped; -> its exit code (0 when it was
        stopped because its agent session ended)."""
        agent = self.agent_process().find()
        child = subprocess.Popen(process, env=env, cwd=cwd)
        previous = signal.signal(signal.SIGTERM, self.stop_requested)
        try:
            while True:
                try:
                    return child.wait(timeout=self.every)  # the tool ended on its own
                except subprocess.TimeoutExpired:
                    pass
                if agent is not None and not self.running(agent):
                    self.stop(child, interrupt=True)
                    print(AGENT_ENDED, flush=True)
                    return 0
        except Stop:
            code = self.stop(child, interrupt=True)
        except KeyboardInterrupt:
            # a terminal's ctrl-c reaches the tool too: give it a moment before asking again
            code = self.stop(child, interrupt=not self.ended_within(child, 1.0))
        finally:
            signal.signal(signal.SIGTERM, previous)
        print(STOPPED, flush=True)
        return code

    def running(self, agent) -> bool:
        """The agent process is still the same running process."""
        return self.agent_process().started(agent.pid) == agent.started

    def stop_requested(self, *_):
        raise Stop()

    def stop(self, child: subprocess.Popen, interrupt: bool) -> int:
        if child.poll() is not None:
            return child.returncode
        if self.windows:
            child.terminate()
            return child.wait()
        if interrupt:
            child.send_signal(signal.SIGINT)
        if self.ended_within(child, self.grace):
            return child.returncode
        child.kill()
        return child.wait()

    def ended_within(self, child: subprocess.Popen, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if child.poll() is not None:
                return True
            time.sleep(0.1)
        return child.poll() is not None
