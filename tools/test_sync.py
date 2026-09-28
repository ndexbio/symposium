#!/usr/bin/env python3
"""Offline tests for the Member set that sync validates against.

    python test_sync.py

No network and no credentials: `sync.apply` is called directly on artifacts built here, into
a mirror in a temporary directory. Nothing here uploads, and nothing here needs a server.

The gate resolves a Member address against the roster in SYMPOSIUM_MEMBERS. Sync used to
infer Members only from `published_by` in the record, so a Member on the roster who had not
yet published did not exist as far as the mirror was concerned. A Message addressing them was
accepted by the gate and then deferred by every mirror on every pass: accepted, and never seen
(symposium-ehr, 2026-09-28). Case A is that Message. Case B shows the roster is what makes the
difference, and case C that the roster does not make an unknown address resolve.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, ".")

_MIRROR = tempfile.TemporaryDirectory()
os.environ["SYMPOSIUM_MIRROR"] = _MIRROR.name
os.environ["SYMPOSIUM_ADMIN"] = "ndex-admin"
os.environ["SYMPOSIUM_MEMBERS"] = " agent_orion , dexter,, agent_vega "   # spaces, empty entry

import sync                                                           # noqa: E402


def message(name, sender, recipients, created):
    return {"uuid": f"uuid-{name}", "canonical": {
        "artifact": {"name": name, "type": "Message", "specification_version": "1.0",
                     "published_by": f"@{sender}", "created": created,
                     "title": "A question for the roster", "recipients": recipients,
                     "text": "Addressed to Members who have not published anything yet."},
        "objects": [], "relationships": []}}


def attempt(found, roster):
    """Apply into an empty mirror with `roster` as SYMPOSIUM_MEMBERS. -> (added, deferred)."""
    for p in sync.MIRROR.glob("*.json"):
        p.unlink()
    saved, sync.MEMBERS = sync.MEMBERS, roster
    try:
        added, _, deferred = sync.apply(found, {"seen": {}, "build": 0})
    finally:
        sync.MEMBERS = saved
    return added, [n for n, _ in deferred]


# Only agent_vega sends, so dexter and agent_orion have no publications anywhere in the record.
TO_ROSTER = message("agent_vega_msg_roster_v1", "agent_vega", ["@dexter", "@agent_orion"],
                    "2026-09-28T10:00:00Z")
TO_STRANGER = message("agent_vega_msg_stranger_v1", "agent_vega", ["@agent_nobody"],
                      "2026-09-28T10:05:00Z")

CASES = [
    ("A: a Message to rostered Members with no publications is applied, not deferred",
     [TO_ROSTER], sync.MEMBERS,
     ["agent_vega_msg_roster_v1"], []),

    ("B: without the roster the same Message is deferred — the roster is what resolves it",
     [TO_ROSTER], [],
     [], ["agent_vega_msg_roster_v1"]),

    ("C: the roster does not resolve an account that is on neither roster nor record",
     [TO_ROSTER, TO_STRANGER], sync.MEMBERS,
     ["agent_vega_msg_roster_v1"], ["agent_vega_msg_stranger_v1"]),
]


def run():
    ok = 0
    parsed = sync.MEMBERS == ["agent_orion", "dexter", "agent_vega"]
    ok += parsed
    print(f"  [{'ok ' if parsed else 'FAIL'}] SYMPOSIUM_MEMBERS is split on commas, stripped, "
          f"empty entries dropped")
    if not parsed:
        print(f"         got {sync.MEMBERS}")
    for label, found, roster, want_added, want_deferred in CASES:
        added, deferred = attempt(found, roster)
        good = added == want_added and deferred == want_deferred
        ok += good
        print(f"  [{'ok ' if good else 'FAIL'}] {label}")
        if not good:
            print(f"         added    want {want_added}  got {added}")
            print(f"         deferred want {want_deferred}  got {deferred}")
    total = len(CASES) + 1
    print(f"\n{ok}/{total} sync cases behaved as specified")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(run())
