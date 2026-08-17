"""The session event log: what was attempted, what was refused, and why.

This is the measurement substrate for the event, and it exists because **the record cannot
answer the questions the event is asking.** Every artifact in the record passed validation —
that is what acceptance means — so any statistic of the form "what fraction of the record
conforms" is 100 % by construction and measures nothing.

What is worth measuring sits on either side of that:

  * **Before the gate.** What agents tried that was refused, what the refusal said, and how
    many rounds it took to get an artifact right. This is the whole of "where does the
    framework get in the way", and it exists nowhere except here. It cannot be
    reconstructed afterwards from the record, because the record holds only what succeeded.
  * **Above the gate.** Properties no validator can check — scope discipline, whether a
    `criterion` describes a test that could actually have failed, whether an `evaluation`
    admits that two Grounds are not independent. Those are read from the record after the
    fact, not logged here.

One line of JSON per event, append-only.

**There is no shared filesystem between participants.** A session's log is written on
whatever machine ran it, so member-side refusals — the most valuable half — do not reach the
admin machine by themselves. They have to be COLLECTED: at the end of a session, the log file
is handed over alongside the session report, and dropped into the admin's events directory.
`metrics.py` merges an arbitrary set of collected files and de-duplicates, so collection is
nothing more than copying files into one place.

Two consequences the defaults have to handle, because a collision here is silent:

  * the default filename carries the hostname, so two participants handing over their logs
    do not both hand over `symposium_events.jsonl`;
  * the session key carries the hostname too, so two people who both used the default mirror
    directory in the same role do not merge into one session when their logs are pooled.

Deliberately NOT in the record: `role` is governance, and the specification keeps governance
out of the CommunityRecord (S1.3). A refusal is not a published fact about a Member either —
it is an observation about the tooling, and it belongs to the people running the event.

Schema — every event carries:

    at        ISO-8601 UTC, second resolution
    session   groups the events of one session; see session_id()
    actor     the Member account, or "gate"
    role      the session's role, or null for the gate
    action    check | publish | gate_accept | gate_reject | gate_defer | gate_withhold
    outcome   passed | refused | submitted | accepted | rejected | deferred | withheld
    artifact  the artifact's name
    type      its Artifact type
    refusal   [] or the KINDS of refusal, which are not the same thing and must not be
              pooled: "naming" and "role" are the local tooling declining, "spec" is the
              validator declining. Only the third says anything about the specification.
    fail      the FAIL findings, in full. The reasons are the point; do not truncate them.
    review    the REVIEW findings, in full. These do not block acceptance, so they survive
              into the record — the one validator signal that is still there tomorrow.

Attempts-per-artifact is NOT stored. It is derived when the log is read, by counting events
per (session, artifact) — storing a counter would only be a second thing to get wrong.
"""
from __future__ import annotations

import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path


def _host():
    """Short machine name — the only thing distinguishing two participants who took every
    other default. Deterministic, so every command in a session agrees on it."""
    try:
        return re.sub(r"[^A-Za-z0-9_-]", "", socket.gethostname().split(".")[0])[:24] or "host"
    except Exception:                                          # noqa: BLE001
        return "host"


LOG = Path(os.environ.get("SYMPOSIUM_LOG") or f"./symposium_events_{_host()}.jsonl")


def session_id(actor, role=None):
    """A stable key for one session, without a clock or a random number.

    `SYMPOSIUM_SESSION` if it is set — set it when two sessions of one account share a role
    on one machine. Otherwise it is derived from the account, the role, the machine, and the
    mirror directory, which the session template already tells you to give each session its
    own copy of. Derived rather than generated, so every command in a session agrees on it
    without anything being passed around, and so a log collected from another machine keeps
    its own identity when it is pooled with the rest.
    """
    explicit = os.environ.get("SYMPOSIUM_SESSION")
    if explicit:
        return explicit
    mirror = Path(os.environ.get("SYMPOSIUM_MIRROR", "./record")).resolve().name
    return f"{actor or '?'}:{role or '-'}:{_host()}:{mirror}"


def split_findings(findings):
    """-> (fail, review), each a list of {check, msg}, in full."""
    fail, review = [], []
    for f in findings or []:
        bucket = fail if f.get("level") == "FAIL" else review
        bucket.append({"check": f.get("check"), "msg": f.get("msg")})
    return fail, review


def emit(actor, action, outcome, artifact=None, atype=None, role=None,
         findings=None, refusal=None, session=None, **extra):
    """Append one event. Never raises: losing the log must not stop the work.

    A failure to write is reported once on stderr rather than silently swallowed — a
    measurement plan that quietly captures nothing is worse than one that captures nothing
    loudly.
    """
    fail, review = split_findings(findings)
    event = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": session or session_id(actor, role),
        "actor": actor,
        "role": role,
        "action": action,
        "outcome": outcome,
        "artifact": artifact,
        "type": atype,
        "refusal": sorted(refusal or []),
        "fail": fail,
        "review": review,
    }
    event.update(extra)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(event) + "\n")
    except Exception as exc:                                   # noqa: BLE001
        import sys
        print(f"! telemetry not written to {LOG}: {exc}", file=sys.stderr)
    return event


def read(path=None):
    """Every event, oldest first. Tolerates a partially-written final line."""
    p = Path(path or LOG)
    out = []
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
