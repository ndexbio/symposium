"""The local copy of a community's record.

One canonical JSON file per accepted artifact, `<name>.json`, in a session's `record/`, beside the
tools' own state files. It is a cache of the record and never the record itself: the server holds
the record, and `sync` rebuilds this from it.

An artifact is recognised by its shape rather than by its filename — any `*.json` whose top level
has a dict `artifact` — which is what keeps the state files out without having to name them.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
from pathlib import Path


class Record:
    """The accepted artifacts a session holds, for reading. Nothing here writes: an artifact
    enters the record by being published and accepted, never by appearing in this directory."""

    def __init__(self, directory: Path):
        self.directory = directory

    def artifacts(self) -> list:
        """Every accepted artifact, as parsed JSON, in name order. An empty record, and one
        that has never been synced, both read as empty: a caller that needs the difference
        asks whether the directory exists."""
        found = []
        if not self.directory.is_dir():
            return found
        for path in sorted(self.directory.glob("*.json")):
            try:
                held = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(held, dict) and isinstance(held.get("artifact"), dict):
                found.append(held)
        return found

    def names(self) -> set:
        """The names the record already holds. Names are permanent and never reused, so this is
        what a new artifact's name must not collide with."""
        return {
            a["artifact"]["name"]
            for a in self.artifacts()
            if isinstance(a["artifact"].get("name"), str)
        }

    def __len__(self) -> int:
        return len(self.artifacts())
