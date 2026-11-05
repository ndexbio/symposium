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

  python sync.py              # one pass
  python sync.py --messages   # one pass, then every Message addressed to you, newest first
  python sync.py --watch      # a pass every SYMPOSIUM_POLL seconds (default 30)

`--watch` runs until stopped, with no time limit of its own: run it in the background. ctrl-c,
SIGTERM or (Windows) CTRL_BREAK stops it within a second, with exit code 0, even mid-pass. A restart
resumes where the copy left off, and takes over from a sync still watching this session, which
it stops.

A pass also lists the gate's replies addressed to you (a rejected submission): they are never
part of the record.

And it lists each Message in the record whose `recipients` include you, one line apiece:

  message for you from @planner: Kickoff: the plan is in the record (@planner_scout_kickoff_v1)

Each is listed once, by the first command that lists it: `sync`, and also `publish` (so
`validate`), which prints the same lines straight after the pass it runs first, and `setup`,
which returns them in its JSON as `messages_for_you`. A member agent asked only to join and
publish runs nothing but `setup` and `publish`; when those two synced without listing, a
Message waiting for it reached its copy of the record and was never shown to it. The gate's
pass is the one that lists nothing: it applies a Message and leaves it for the member's next
listing. `.sync_state.json` keeps the names already listed, so a restart lists nothing twice.

`sync --messages` lists them all again, newest first, marking `new` each one not listed before:
a Message is an artifact in the record, so it can be found again long after it was first shown.

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
import unicodedata
from datetime import datetime, timezone

from data_io import (
    IN_REPLY_TO,
    RECORD_MARK,
    REPLY_MARK,
    DataError,
    Mirror,
    SymposiumData,
    file_lock,
    pause,
    stop_on_signals,
    take_over,
)
from validate import parse_address, passed, validate

POLL = int(os.environ.get("SYMPOSIUM_POLL", "30"))
# the record feed's cursor, the accepted artifacts still waiting for a dependency, the replies
# and the Messages already listed, and the build counter
STATE = ".sync_state.json"


def messages_for(record, handle):
    """Messages in `record` whose `recipients` include `handle`, oldest first. A Message the
    member published themselves is left out: nobody needs telling about their own."""
    if not handle:
        return []
    out = []
    for doc in record:
        h = doc.get("artifact") or {}
        if h.get("type") != "Message":
            continue
        if str(h.get("published_by") or "").lstrip("@") == handle:
            continue
        recipients = h.get("recipients") or []
        if isinstance(recipients, str):
            recipients = [recipients]
        if any(str(r).lstrip("@") == handle for r in recipients):
            out.append(h)
    out.sort(key=lambda h: h.get("created") or "")
    return out


def one_line(text):
    """Text a Member wrote, made fit to print inside one line of output: every control
    character becomes a space, and every run of whitespace one space. A line break or a tab
    would start a line of its own, and an escape sequence, a backspace or a DEL can move the
    cursor or erase what a terminal already shows, so none of them reaches the output."""
    text = "".join(" " if unicodedata.category(c) == "Cc" else c for c in str(text))
    return " ".join(text.split())


def message_line(m):
    """The one line that lists a Message to this member, wherever it is listed. Its sender,
    title and name are each what a Member wrote, and an agent is asked to relay this line,
    so each is put on one line first: a title cannot add a line that seems to come from the
    admin or the gate."""
    return (f"message for you from {one_line(m['from'])}: {one_line(m['title'])} "
            f"(@{one_line(m['name'])})")


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
                 quiet: bool = False, lists_messages: bool | None = None):
        self.data = data or SymposiumData()
        self.mirror = mirror or Mirror()
        self.quiet = quiet
        # Whether the caller shows this member its Messages: a printing pass does, and so do
        # `publish` and `setup`, quiet about everything else, which list the pass's `messages`
        # themselves. Only what is listed is marked; the gate's pass lists nothing.
        self.lists_messages = (not quiet) if lists_messages is None else lists_messages
        # and whether the pass prints them itself: only when the caller left it to the pass
        self.prints_messages = lists_messages is None and not quiet
        self.members = set()  # fetched live on every pass
        self.handle = None  # this session's own handle, read once from its context

    def say(self, line):
        if not self.quiet:
            print(line)

    def load_state(self):
        state = self.mirror.read_state(
            STATE, {"since": 0, "pending": [], "replies": [], "messages": [], "build": 0}
        )
        state.setdefault("messages", [])  # a state file written before Messages were listed
        return state

    def me(self):
        """This session's handle, from its context (local; the server is not contacted)."""
        if self.handle is None:
            try:
                self.handle = str(self.data.context().get("handle") or "").lstrip("@")
            except DataError:
                self.handle = ""
        return self.handle

    def messages(self, record, state):
        """Messages to this member not yet listed. -> [{name, from, title, created}].

        Marked as listed only by a pass whose caller lists them. Any other pass (the gate's)
        returns them in its result and leaves them for the next one that lists."""
        shown = set(state["messages"])
        new = [h for h in messages_for(record, self.me()) if h.get("name") not in shown]
        if self.lists_messages:
            state["messages"].extend(h["name"] for h in new)
        return [{"name": h["name"], "from": h.get("published_by") or "?",
                 "title": h.get("title") or "(untitled)", "created": h.get("created")}
                for h in new]

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

    def once(self):
        """Run one pass while sharing state atomically with other sync callers."""
        with file_lock(self.mirror.root / ".sync.lock"):
            return self._once(self.load_state())

    def _once(self, state):
        """One pass. -> {added, deferred, replies, messages, artifacts}, or None when the
        server could not be reached (the copy is then unchanged and may be stale)."""
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
        held = self.mirror.load()
        total = len(held)
        if added:
            self.write_manifest(state, added, dirty, total)
            self.say(f"  +{len(added)}: {', '.join(added)}")
            self.say(f"  build {state['build']}, {total} artifact(s), "
                     f"{len(dirty | {'index'})} page(s) dirty")
        # last, so the lines that ask something of this member are the ones left on screen
        messages = self.messages(held, state)
        if self.prints_messages:
            for m in messages:
                self.say(f"  {message_line(m)}")
        self.mirror.write_state(STATE, state)
        return {
            "added": added,
            "deferred": [name for name, _ in deferred],
            "replies": [name for name, _ in replies],
            "messages": messages,
            "artifacts": total,
        }


def list_messages(sync):
    """`sync --messages`: a pass, then every Message addressed to you, newest first, each one
    not listed to you before marked `new`. -> exit code (1 when the server could not be reached;
    the list is then read from your copy as it stands).

    The plain pass lists a Message once and never again, which is right for noticing one and
    wrong for finding it a week later. This lists them all, from the copy, which holds every
    one: Messages are artifacts in the record, not notifications that expire."""
    before = set(sync.load_state()["messages"])
    result = sync.once()
    mine = messages_for(sync.mirror.load(), sync.me())
    if result is None:
        print("  Listing the Messages in your copy as it stands.")
    if not mine:
        print("  no Message in your copy of the record is addressed to you")
        return 1 if result is None else 0
    fresh = sum(1 for h in mine if h.get("name") not in before)
    print(f"  {len(mine)} Message(s) addressed to you, newest first"
          + (f"; {fresh} new since they were last listed:" if fresh else ":"))
    for h in reversed(mine):
        mark = "new" if h.get("name") not in before else "   "
        when = (h.get("created") or "")[:16].replace("T", " ")
        m = {"name": h["name"], "from": h.get("published_by") or "?",
             "title": h.get("title") or "(untitled)"}
        print(f"  {mark}  {when}  {message_line(m)[len('message for you '):]}")
    return 1 if result is None else 0


def main(argv):
    if "--messages" in argv and "--watch" in argv:
        print("! --messages lists once; run `/symposium sync --watch` on its own to keep watching")
        return 2
    # with --messages this command lists the Messages itself, all of them, after the pass
    sync = Sync(lists_messages=True if "--messages" in argv else None)
    try:
        sync.data.context()  # local: with none, the CLI's message names setup and bootstrap
    except DataError as e:
        print(f"! {e}")
        return 1
    sync.mirror.root.mkdir(parents=True, exist_ok=True)

    if "--messages" in argv:
        return list_messages(sync)

    if "--watch" not in argv:
        result = sync.once()
        if result is None:
            return 1                       # unreachable: never report a stale copy as fine
        if not result["added"]:
            print(f"  up to date — {result['artifacts']} artifact(s)")
        return 0

    stop_on_signals()
    lock = take_over("sync")  # noqa: F841 — held for as long as this sync watches
    print(f"watching {sync.mirror.root}/ (every {POLL}s) — ctrl-c to stop", flush=True)
    misses = 0
    try:
        while True:
            try:
                if sync.once() is None:
                    misses += 1
                    if misses in (1, 5) or misses % 20 == 0:
                        print(f"  ({misses} consecutive failed poll(s) — the copy is not "
                              f"being updated)", flush=True)
                else:
                    misses = 0
            except Exception as e:
                print(f"  ! sync error (will retry): {e}", flush=True)
            pause(POLL)
    except KeyboardInterrupt:
        print("stopped", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
