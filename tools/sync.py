"""Member-side sync — keep this session's copy of the community record current.

Every member can read the community's `record` collection (the roster's default grants), so
the server's change feed IS the distribution mechanism: a member needs no git access to hold a
current copy of the record.

Two things make this simple, and both come from the specification:

  * Artifacts are IMMUTABLE, so sync is purely additive. Nothing already local is ever
    re-fetched or revised. The only thing that changes about an artifact already held is the
    set of later artifacts pointing AT it — its backlinks.
  * `created` is stamped by the server when the gate accepts, so it is a total order over the
    record. New artifacts are applied in that order, which is what makes address resolution
    work: an Argument applied before the Data it grounds on would fail to resolve.

Run it as `/symposium sync`, in the session's working directory: the context there says which
community, and `./record` beside it is the copy it keeps.

  python sync.py            # one pass
  python sync.py --watch    # poll every SYMPOSIUM_POLL seconds (default 30)

A pass also lists the gate's replies addressed to you (a rejected submission): they are never
part of the record.

Writes `manifest.json` into the copy: a build counter plus the dirty set, recording what
changed on each pass.

The browser does NOT patch itself from this. `serve.py` watches the copy and recompiles the
whole record whenever a file changes — a full pass is fast enough at any size this event will
reach, and a full pass cannot drift from the record the way a partial update can. The manifest
is a log of what moved, not a build instruction.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from data_io import (
    IN_REPLY_TO,
    RECORD_MARK,
    REPLY_MARK,
    DataError,
    Mirror,
    SymposiumData,
)
from validate import parse_address, passed, validate

POLL = int(os.environ.get("SYMPOSIUM_POLL", "30"))
# the record feed's cursor, the accepted artifacts still waiting for a dependency, the replies
# already listed, and the build counter
STATE = ".sync_state.json"


def outbound(canonical):
    """Artifact names this artifact points at — the pages whose backlinks it changes."""
    h, out = canonical["artifact"], set()

    def add(v):
        p = parse_address(v) if isinstance(v, str) and v.startswith("@") else None
        if p:
            out.add(p["root"])

    for k in ("produced_by", "extracted_from"):
        add(h.get(k))
    for k in ("supersedes", "outputs", "inputs", "used_models", "recipients"):
        for v in (h.get(k) or []):
            add(v)
    for o in canonical.get("objects", []):
        if o.get("type") == "Ground":
            add(o.get("citation"))          # a Ground's evidence address (spec 2.2.4)
    return out - {h.get("name")}


def _root(addr):
    """Artifact name at the head of an address."""
    return str(addr).lstrip("@").split("#")[0].split(".")[0]


class Sync:
    def __init__(self, data: SymposiumData | None = None, mirror: Mirror | None = None,
                 quiet: bool = False):
        self.data = data or SymposiumData()
        self.mirror = mirror or Mirror()
        self.quiet = quiet
        self.members = set()  # fetched live on every pass

    def say(self, line):
        if not self.quiet:
            print(line)

    def load_state(self):
        return self.mirror.read_state(
            STATE, {"since": 0, "pending": [], "replies": [], "build": 0}
        )

    def fetch(self, state):
        """-> (list of {citation, canonical} to apply, reachable, why).

        `reachable` is separate from an empty list ON PURPOSE: a failure to reach the server
        must never look like a record that is up to date. A frozen copy and a current one
        would be indistinguishable in the output, the exit code, and in --watch, and a stale
        copy approves an artifact that reuses a name someone else just took.
        """
        try:
            feed = self.data.changes("record", state["since"])
            # every member, live: an address to one who has not published (or even joined) yet
            # resolves, exactly as at the gate
            self.members = self.data.members()
        except DataError as e:
            return [], False, str(e)
        citations = list(state["pending"])
        for item in feed["items"]:
            if (item.get("metadata") or {}).get(RECORD_MARK) and not item.get("deleted"):
                citations.append(item["citation"])
        found = []
        for citation in dict.fromkeys(citations):
            try:
                found.append({"citation": citation, "canonical": self.data.get_json(citation)})
            except DataError as e:
                return [], False, str(e)
        state["since"] = feed["next_since"]
        return found, True, ""

    def apply(self, found, state):
        """Validate and write, oldest first. -> (added, dirty, deferred)."""
        record = self.mirror.load()
        names = {r["artifact"]["name"] for r in record}
        members = {r["artifact"]["published_by"].lstrip("@") for r in record
                   if r.get("artifact", {}).get("published_by")}
        members |= {f["canonical"]["artifact"].get("published_by", "@").lstrip("@")
                    for f in found}
        members |= self.members

        # the server's `created` is the record's total order; apply in it or addresses will
        # not resolve
        found.sort(key=lambda f: f["canonical"]["artifact"].get("created") or "")

        added, dirty, deferred, pending = [], set(), [], []
        for f in found:
            # One artifact at a time, in `created` order. Publication is serial (spec 1.9), so
            # every address an artifact holds points at something strictly earlier and
            # therefore already applied.
            c = f["canonical"]
            name = c["artifact"]["name"]
            if name in names:
                continue

            findings = validate(c, record, members)
            if not passed(findings):
                # Usually a dependency that has not arrived yet — retry next pass, never drop.
                deferred.append((name, [x["msg"] for x in findings if x["level"] == "FAIL"][:2]))
                pending.append(f["citation"])
                continue

            self.mirror.write(c)
            record.append(c)
            names.add(name)
            added.append(name)
            dirty |= {name} | (outbound(c) & names)  # its own page + every page it points at
        state["pending"] = pending
        return added, dirty, deferred

    def replies(self, state):
        """The gate's replies addressed to this member that have not been listed yet."""
        new = []
        for item in self.data.query("inbox", {REPLY_MARK: True}):
            if item["citation"] in state["replies"]:
                continue
            state["replies"].append(item["citation"])
            new.append((item["name"], (item.get("metadata") or {}).get(IN_REPLY_TO, "?")))
        return new

    def write_manifest(self, state, added, dirty, total):
        state["build"] += 1
        self.mirror.write_state("manifest.json", {
            "build": state["build"],
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "artifacts": total,
            "added": sorted(added),
            "dirty": sorted(dirty | {"index"}),
        })

    def once(self, state):
        """One pass. -> {added, deferred, replies, artifacts}, or None when the server could
        not be reached (the copy is then unchanged and may be stale)."""
        found, reachable, why = self.fetch(state)
        if not reachable:
            held = len(self.mirror.load())
            self.say(f"! COULD NOT REACH THE SERVER — {why}")
            self.say(f"  Your copy of the record is UNCHANGED at {held} artifact(s) and may "
                     f"now be STALE.")
            self.say("  Do not publish against it: validation can only see the record it has, "
                     "so a")
            self.say("  stale copy will approve a name someone else has already taken.")
            return None
        added, dirty, deferred = self.apply(found, state)
        for name, why in deferred:
            self.say(f"  deferred {name}: {why[0] if why else 'unresolved'}")
        replies = self.replies(state)
        for name, about in replies:
            self.say(f"  reply from the gate: {name} (re {about}) — not part of the record")
        total = len(self.mirror.load())
        if added:
            self.write_manifest(state, added, dirty, total)
            self.say(f"  +{len(added)}: {', '.join(added)}")
            self.say(f"  build {state['build']}, {total} artifact(s), "
                     f"{len(dirty | {'index'})} page(s) dirty")
        self.mirror.write_state(STATE, state)
        return {
            "added": added,
            "deferred": [name for name, _ in deferred],
            "replies": [name for name, _ in replies],
            "artifacts": total,
        }


def main(argv):
    sync = Sync()
    try:
        sync.data.context()  # local: with none, the CLI's message names setup and bootstrap
    except DataError as e:
        print(f"! {e}")
        return 1
    sync.mirror.root.mkdir(parents=True, exist_ok=True)
    state = sync.load_state()

    if "--watch" not in argv:
        result = sync.once(state)
        if result is None:
            return 1                       # unreachable: never report a stale copy as fine
        if not result["added"]:
            print(f"  up to date — {result['artifacts']} artifact(s)")
        return 0

    print(f"watching {sync.mirror.root}/ (every {POLL}s) — ctrl-c to stop")
    misses = 0
    while True:
        try:
            if sync.once(state) is None:
                misses += 1
                if misses in (1, 5) or misses % 20 == 0:
                    print(f"  ({misses} consecutive failed poll(s) — the copy is not being "
                          f"updated)")
            else:
                misses = 0
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"  ! sync error (will retry): {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
