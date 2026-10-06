"""The agent process: the long-lived process that starts the shell each `/symposium` command runs
in. Every command of one agent session has the same one, and two agent sessions running at once
have two, so its process ID and start time key what one agent session chose (`/symposium use`),
with nothing specific to any agent.

The skill finds it by walking up from its own parent (the skill's own Python process is never a
candidate) past shells and plain wrappers to the first ancestor that is neither. Interpreters are
not skipped: an agent that is itself a Python or Node program is found. Process names are
compared normalized: the base name, a login shell's leading `-` removed, `.exe` removed, case
ignored. On Windows a parent is accepted only when it started before its child: a parent ID can
belong to a newer process once the original has ended.

macOS and Linux read each process with `ps`; Windows through the Windows API (`ctypes`). Start
times are opaque strings, compared only on the same host.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

# what starts or wraps a command, never the agent itself
PASS_THROUGH = {
    "sh",
    "bash",
    "zsh",
    "dash",
    "fish",
    "ksh",
    "cmd",
    "powershell",
    "pwsh",
    "env",
    "nohup",
    "timeout",
}


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    started: str
    name: str


def normalized(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lstrip("-").lower()
    return base[:-4] if base.endswith(".exe") else base


class PosixProcesses:
    """One process at a time, through `ps`."""

    def get(self, pid: int) -> Process | None:
        result = subprocess.run(
            ["ps", "-o", "ppid=,lstart=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "LC_ALL": "C",
            },  # the same start-time format on every call
        )
        fields = result.stdout.split(None, 6)
        if result.returncode != 0 or len(fields) < 7:
            return None
        return Process(pid, int(fields[0]), " ".join(fields[1:6]), fields[6].strip())


class WindowsProcesses:
    """Every process at once, through a Toolhelp snapshot; start times from GetProcessTimes."""

    def __init__(self):
        self.table = None

    def get(self, pid: int) -> Process | None:
        if self.table is None:
            self.table = self.snapshot()
        return self.table.get(pid)

    def snapshot(self) -> dict:
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snapshot = kernel32.CreateToolhelp32Snapshot(
            0x00000002, 0
        )  # TH32CS_SNAPPROCESS
        table = {}
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while found:
                pid = entry.th32ProcessID
                table[pid] = Process(
                    pid,
                    entry.th32ParentProcessID,
                    self.started(kernel32, pid),
                    entry.szExeFile,
                )
                found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return table

    def started(self, kernel32, pid: int) -> str:
        import ctypes
        from ctypes import wintypes

        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(
            0x1000, False, pid
        )  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return ""
            created = times[0]
            return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            kernel32.CloseHandle(handle)


class AgentProcess:
    def __init__(
        self, processes=None, windows: bool | None = None, start: int | None = None
    ):
        self.start = start  # where the walk starts: the skill's parent unless given
        self.windows = os.name == "nt" if windows is None else windows
        self.processes = processes or (
            WindowsProcesses() if self.windows else PosixProcesses()
        )

    def find(self) -> Process | None:
        """The agent process, walking up from the skill's parent (or the given start)."""
        current = self.processes.get(
            self.start if self.start is not None else os.getppid()
        )
        while current is not None and normalized(current.name) in PASS_THROUGH:
            parent = self.processes.get(current.parent) if current.parent > 0 else None
            if parent is None or (self.windows and not self.earlier(parent, current)):
                return current  # the top this walk can trust
            current = parent
        return current

    def earlier(self, parent: Process, child: Process) -> bool:
        """A Windows parent started before its child (FILETIME counts, as decimal strings)."""
        try:
            return int(parent.started) < int(child.started)
        except ValueError:
            return False

    def started(self, pid: int) -> str | None:
        """The start time of a process that is running now, or None."""
        process = self.processes.get(pid)
        return process.started if process else None
