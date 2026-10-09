"""The toolchain's one way to the data server, and its local copy of the record.

`SymposiumData` runs the `symposium-data` CLI and reads the one JSON object each command prints
(R-I1): nothing in the toolchain makes an HTTP request to the server itself. It runs the CLI
with the command the skill prepared for the session and passed in SYMPOSIUM_DATA_CLI (a JSON
list: the interpreter of the skill's own environment, then the CLI's `cli.py`). `Mirror` is the
local copy of the community's record, `./record` beside the context in the session's working
directory: sync writes it on a member's machine and the gate on the admin's, and validation
reads it.

Standard library only, Python 3.9+, like the rest of tools/.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

NO_RUNTIME = (
    "no CLI command in SYMPOSIUM_DATA_CLI: the toolchain's tools run only as /symposium "
    "commands, which prepare it"
)
# The marks the toolchain finds artifacts by (shared with the port): what a member submits,
# what the gate accepts, and what the gate replies. The gate also writes, on each version it
# promotes and each reply it sends, the citation of the submission it decided, so the server
# holds every decision (ported versions carry none).
SUBMISSION_MARK = "symposium_submission"
RECORD_MARK = "symposium_record"
REPLY_MARK = "symposium_reply"
IN_REPLY_TO = "symposium_in_reply_to"
SUBMISSION_CITATION = "symposium_submission_citation"


# ── the commands that keep running (`gate --watch`, `sync --watch`, `serve`) ────────────────
WINDOWS = os.name == "nt"
# where a session keeps its watchers' locks: beside the context, in the session's directory
LOCKS = Path(".symposium")


def stop_on_signals():
    """Stop as ctrl-c does on the other signals a process is asked to stop with: SIGTERM on
    macOS and Linux, and on Windows SIGBREAK (CTRL_BREAK_EVENT, sent to a process started in
    its own process group); Windows delivers no SIGTERM between processes. Each raises
    KeyboardInterrupt in the main thread. On macOS and Linux it cuts short whatever call the
    thread is blocked in; on Windows a SIGBREAK lands once that call returns, which `pause`
    keeps to a second while a loop waits, and a CLI call in progress to its own length."""
    if threading.current_thread() is not threading.main_thread():
        return

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGBREAK if WINDOWS else signal.SIGTERM, stop)


def pause(seconds: float):
    """Wait `seconds`, in slices of at most 1 s. On macOS and Linux any signal cuts a sleep
    short, but on Windows only ctrl-c (SIGINT) wakes one: a CTRL_BREAK (SIGBREAK) is handled
    only once the sleep returns, so a wait in slices is what lets it stop a loop within a
    second. The wait in all is the same, so the loop's cadence is unchanged."""
    deadline = time.monotonic() + seconds
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 1.0))


def replace_text(path: Path, text: str, attempts: int = 20):
    """Write `path` whole or not at all: a sibling `.tmp` file, then an atomic rename. A stop
    at any point leaves the old file or the new one. On Windows the rename fails while
    another process holds the file open, so it is retried every 0.1 s, for up to 2 s."""
    staged = path.with_name(path.name + ".tmp")
    staged.write_text(text)
    for attempt in range(attempts):
        try:
            os.replace(staged, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                staged.unlink(missing_ok=True)
                raise
            time.sleep(0.1)


def _locked(handle) -> bool:
    """Take the exclusive lock on an open file without waiting. -> whether it was taken."""
    try:
        if WINDOWS:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _holder(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _end(pid: int, hard: bool):
    try:
        if WINDOWS or not hard:
            os.kill(pid, signal.SIGTERM)  # on Windows, TerminateProcess
        else:
            os.kill(pid, signal.SIGKILL)
    except (OSError, ValueError):
        pass  # it has ended already


def take_over(name: str, wait: float = 10.0):
    """Become the one `name` watcher of this session. A watcher still running, an orphan an
    agent left behind or one it restarted, is asked to stop (SIGTERM; Windows has only
    TerminateProcess), and after `wait` seconds it is killed. The lock is the OS's, so it
    falls to whoever runs next the moment its holder dies, however it died; a pid is
    signalled only while its lock is held, so a reused pid is never hit. -> the open lock
    file, which the caller keeps for as long as it runs."""
    LOCKS.mkdir(exist_ok=True)
    lock_file, pid_file = LOCKS / f"{name}.lock", LOCKS / f"{name}.pid"
    handle = open(lock_file, "a+")
    pid, hard, deadline = None, False, time.monotonic() + wait
    while not _locked(handle):
        if pid is None:
            # a holder that has just started may not have written its pid yet
            pid = _holder(pid_file)
            if pid is not None:
                print(f"taking over from the {name} watcher already running (pid {pid})",
                      flush=True)
                _end(pid, hard=False)
                deadline = time.monotonic() + wait
        elif time.monotonic() >= deadline and not hard:
            _end(pid, hard=True)
            hard, deadline = True, time.monotonic() + wait
        if time.monotonic() >= deadline:
            handle.close()
            sys.exit(f"! the {name} watcher (pid {pid}) would not stop")
        time.sleep(0.2)
    # the pid sits in its own file: on Windows a locked byte cannot be read by anyone else
    replace_text(pid_file, f"{os.getpid()}\n")
    return handle


class DataError(Exception):
    """A CLI command that failed: `report` is the JSON object it printed."""

    def __init__(self, report: dict):
        super().__init__(report.get("error", json.dumps(report)))
        self.report = report


class SymposiumData:
    def __init__(self, command: list | None = None):
        if command is None and os.environ.get("SYMPOSIUM_DATA_CLI"):
            command = json.loads(os.environ["SYMPOSIUM_DATA_CLI"])
        self.command = command

    def run(self, *args) -> dict:
        """Run one CLI command in the current directory. -> its JSON object. Raises
        DataError with the CLI's report when the command fails."""
        if not self.command:
            raise DataError({"error": NO_RUNTIME})
        result = subprocess.run(
            [*self.command, *map(str, args)], capture_output=True, text=True
        )
        try:
            out = json.loads(result.stdout)
        except ValueError:
            out = {"error": (result.stdout + result.stderr).strip()[-1000:]}
        if result.returncode != 0:
            raise DataError(out)
        return out

    # ── the context and the server ─────────────────────────────────────────────────────────
    def context(self) -> dict:
        """This directory's context; read locally, the server is not contacted."""
        return self.run("context", "show")["context"]

    def status(self) -> dict:
        """The data server's status, for this directory's context."""
        return self.run("status")

    def members(self) -> set:
        """Everyone validation counts as a member, fetched live: every handle on the community's
        roster, registered or not yet (any member may read it, R-D6), and the server's admin.
        An address to any of them (`@handle`) resolves, exactly as it does at the gate."""
        handles = {m["handle"] for m in self.run("roster", "list")["roster"]}
        admin = self.status().get("admin")
        return handles | ({admin} if admin else set())

    # ── reading ────────────────────────────────────────────────────────────────────────────
    def changes(self, collection: str, since: int = 0) -> dict:
        """Every change to a collection after the cursor `since`: {items, next_since}."""
        return self.run("changes", "--collection", collection, "--since", since, "--all")

    def query(self, collection: str, contains: dict) -> list:
        """Every version of a collection, readable here, whose metadata contains `contains`."""
        items, since = [], 0
        while True:
            page = self.run(
                "find",
                "meta",
                "--collection",
                collection,
                "--contains",
                json.dumps(contains),
                "--since",
                since,
                "--limit",
                1000,
            )
            items.extend(page["items"])
            if not page.get("more"):
                return items
            since = page["next_since"]

    def get_json(self, citation: str) -> dict:
        """A version's content, parsed as JSON (an artifact)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "content.json"
            self.run("get", citation, "--out", out)
            return json.loads(out.read_text())

    # ── writing ────────────────────────────────────────────────────────────────────────────
    def put_json(self, document: dict, collection: str, name: str, metadata: dict) -> dict:
        """Store a JSON document (an artifact) as a new file. -> the CLI's report (citation,
        sha256, created, ...)."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "document.json"
            source.write_text(json.dumps(document, indent=2) + "\n")
            return self.run(
                "put",
                source,
                "--collection",
                collection,
                "--name",
                name,
                "--metadata",
                json.dumps(metadata),
                "--content-type",
                "application/json",
            )


class Mirror:
    """The local copy of the community's record: one canonical JSON file per accepted artifact,
    `<name>.json`, plus the tools' own state files. It is a cache of the record, never the
    record itself: the server holds the record, and sync or the gate rebuild this from it."""

    def __init__(self, root: Path | str = "record"):
        self.root = Path(root)

    def exists(self) -> bool:
        return self.root.is_dir()

    def load(self) -> list:
        """Every artifact held. Filters on structure, not file name: the directory also holds
        state files (`manifest.json`, `.sync_state.json`, ...), which are skipped."""
        out = []
        if not self.root.is_dir():
            return out
        for path in sorted(self.root.glob("*.json")):
            try:
                doc = json.loads(path.read_text())
            except Exception as e:
                print(f"  ! mirror file {path.name} is unreadable: {e}")
                continue
            if isinstance(doc, dict) and isinstance(doc.get("artifact"), dict):
                out.append(doc)
        return out

    def write(self, canonical: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        name = canonical["artifact"]["name"]
        replace_text(self.root / f"{name}.json", json.dumps(canonical, indent=2) + "\n")

    def read_state(self, name: str, default: dict) -> dict:
        try:
            return json.loads((self.root / name).read_text())
        except (OSError, ValueError):
            return default

    def write_state(self, name: str, state: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        replace_text(self.root / name, json.dumps(state, indent=2) + "\n")
