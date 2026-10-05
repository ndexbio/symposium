"""The toolchain's one way to the data server, and its local copy of the record.

`SymposiumData` runs the `symposium-data` CLI and reads the one JSON object each command prints
(R-I1): nothing in the toolchain makes an HTTP request to the server itself. `Mirror` is the
local copy of the community's record, `./record` beside the context in the session's working
directory: sync writes it on a member's machine and the gate on the admin's, and validation
reads it.

Standard library only, Python 3.9+, like the rest of tools/.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

INSTALL = (
    "the symposium-data CLI is not on PATH: install the Symposium bundle (`make deploy-local` "
    "from a checkout, or the release's Symposium_skill.zip) and keep ~/.local/bin on PATH"
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


class DataError(Exception):
    """A CLI command that failed: `report` is the JSON object it printed."""

    def __init__(self, report: dict):
        super().__init__(report.get("error", json.dumps(report)))
        self.report = report


class SymposiumData:
    def __init__(self, program: str = "symposium-data"):
        self.program = program

    def available(self) -> bool:
        return shutil.which(self.program) is not None

    def run(self, *args) -> dict:
        """Run one CLI command in the current directory. -> its JSON object. Raises
        DataError with the CLI's report when the command fails."""
        if not self.available():
            raise DataError({"error": INSTALL})
        result = subprocess.run(
            [self.program, *map(str, args)], capture_output=True, text=True
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
        (self.root / f"{name}.json").write_text(json.dumps(canonical, indent=2) + "\n")

    def read_state(self, name: str, default: dict) -> dict:
        try:
            return json.loads((self.root / name).read_text())
        except (OSError, ValueError):
            return default

    def write_state(self, name: str, state: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(json.dumps(state, indent=2) + "\n")
