"""The admin's gate: discover the members' submissions, validate them, accept or reject.

Run it as `/symposium gate`, in the admin's session directory: the context there says which
community, and `./record` beside it is the gate's copy of the record. One pass per run:

  1. a sync pass brings the copy up to date from the `record` feed, exactly as a member's;
  2. the `inbox` feed, from the gate's cursor, plus the submissions deferred last pass, gives
     the submissions (marked `symposium_submission`) not decided yet;
  3. a submission is considered only when its inbox name, before the `@`, is the artifact's
     name, prefixed with its submitter's handle, and the submitter is a member;
  4. `order_submissions` puts them in the order a serial publication needs: an artifact after
     anything it addresses, an output after its Analysis or deferred until it arrives;
  5. each is validated against the record as it stands, with a provisional `created` from
     the server's clock, and every `download` held on the data server is verified;
  6. ACCEPT: `promote` copies the submission into `record` under the artifact's name, and the
     server stamps `created` into it; REJECT: a reply in `inbox` only the submitter reads.

THE SERVER HOLDS EVERY DECISION. Each version the gate promotes and each reply it sends names
the submission it decided (`symposium_submission_citation`), so a submission is decided exactly
when a record version or a reply names it. `.gate_state.json` beside the copy only caches what
the server says (the feed cursors, the deferred submissions, the decisions): a pass first reads
both feeds from its cursors, so a decision written just before a crash is still seen, and a
lost state file is rebuilt from the feeds' start. No submission is decided twice, and no reply
is sent twice.

  python gate.py              one pass
  python gate.py --dry-run    decide and report; promote, reply and save nothing
  python gate.py --verify     compare the copy's artifacts with the `record` feed; change nothing
  python gate.py --rebuild    discard the copy's and the gate's caches, rebuild them, then exit
  python gate.py --watch      a pass every SYMPOSIUM_POLL seconds (default 30), reporting each
                              pass that accepts or rejects something. It runs until stopped,
                              with no time limit of its own: run it in the background. ctrl-c,
                              SIGTERM or (Windows) CTRL_BREAK stops it at once, with exit code
                              0, even mid-pass. A restart resumes where it left off, and takes
                              over from a gate still watching this session, which it stops.

Everything goes through the `symposium-data` CLI (R-I1). Exit 0 = the pass ran; 1 = no context
in this directory (the message names `/symposium setup` and `bootstrap`), the data server could
not be reached, or the copy differs from the record (`--verify`); 2 = `--watch` given with
`--verify` or `--rebuild`.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import time
from datetime import timedelta

import telemetry
from data_io import (
    IN_REPLY_TO,
    RECORD_MARK,
    REPLY_MARK,
    SUBMISSION_CITATION,
    SUBMISSION_MARK,
    DataError,
    Mirror,
    SymposiumData,
    stop_on_signals,
    take_over,
)
from symposium_rules.checks import skip_reason
from sync import POLL, Sync
from sync import STATE as SYNC_STATE
from validate import finding, method_of, parse_instant, passed, validate

# the feed cursors, the submissions waiting for their Analysis, and a decision per submission
STATE = ".gate_state.json"
DATA_LOCATION = "symposium-data:"


def _root(addr):
    """Artifact name at the head of an address."""
    return str(addr).lstrip("@").split("#")[0].split(".")[0]


def order_submissions(subs, record_names):
    """Order the pending submissions for serial acceptance.

    Publication is strictly serial (spec 1.9, 2.5). Every artifact receives its own
    `created` and is validated against the record as it stands at that moment. There are no
    publication units, no shared timestamps and no all-or-nothing groups: this function
    decides only the ORDER in which a pass considers what is pending, so that an artifact is
    stamped after anything it addresses.

    Bundling used to live here. It is gone because it created the one thing spec 1.9 says
    cannot happen — two artifacts with an identical `created`, which are therefore not
    earlier than one another and cannot refer to each other. Making that publishable at all
    required an ordering exemption on `produced_by`, and the exemption then suppressed the
    ordering check on the very property most in need of it.

    An output names its Analysis with `produced_by` and that address must resolve (spec 2.5).
    An output whose Analysis is neither in the record nor pending in this pass is DEFERRED
    rather than rejected: the member may not have published it yet, and the correct order is
    the Analysis first.

    -> (ordered, deferred) where deferred is [(submission, [missing names])]"""
    by_name = {s["canonical"]["artifact"]["name"]: s for s in subs}

    def refs(sub):
        c = sub["canonical"]
        h = c["artifact"]
        out = set()
        for k in ("produced_by", "extracted_from"):
            if h.get(k):
                out.add(_root(h[k]))
        for k in ("supersedes", "inputs", "recipients"):
            for v in (h.get(k) or []):
                out.add(_root(v))
        for o in c.get("objects", []):
            if o.get("type") == "Ground":
                # A Ground's evidence address. Reading the wrong key here does not fail --
                # it returns "" for every Ground -- and the ordering below then ignores
                # every evidential reference in the pass, silently stamping an Argument
                # `created` before the Data it grounds on. Covered by test_gate.py case E.
                out.add(_root(o.get("citation", "")))
        return out - {h["name"]}

    pending, deferred = [], []
    for sub in subs:
        pb = sub["canonical"]["artifact"].get("produced_by")
        if pb:
            lead = _root(pb)
            if lead not in record_names and lead not in by_name:
                deferred.append((sub, [lead]))
                continue
        pending.append(sub)

    # Ready = nothing this submission references is still sitting unplaced. References to
    # artifacts already in the record, or to names not submitted at all, do not block: the
    # validator decides whether those resolve, not the ordering.
    ordered, placed = [], set(record_names)
    while pending:
        unplaced = {x["canonical"]["artifact"]["name"] for x in pending} - placed
        ready = [x for x in pending if not (refs(x) & unplaced)]
        if not ready:                  # a cycle among submissions; fall back to given order
            ready = pending[:1]
        for x in ready:
            ordered.append(x)
            placed.add(x["canonical"]["artifact"]["name"])
            pending.remove(x)
    return ordered, deferred


class Gate:
    def __init__(self, data: SymposiumData | None = None, mirror: Mirror | None = None,
                 dry: bool = False):
        self.data = data or SymposiumData()
        self.mirror = mirror or Mirror()
        self.dry = dry
        self.decided = 0  # submissions accepted or rejected since the last look

    # ── state: a cache of what the server says ────────────────────────────────────────────
    def load_state(self):
        return self.mirror.read_state(
            STATE, {"inbox_since": 0, "record_since": 0, "deferred": [], "decisions": {}}
        )

    def save_state(self, state):
        if not self.dry:
            self.mirror.write_state(STATE, state)

    def refresh(self, state):
        """Read both feeds from the state's cursors. Every decision the server holds that the
        state does not (a lost state file, or a crash between a decision and its save) is
        folded in BEFORE anything is decided. -> the new inbox items."""
        record = self.data.changes("record", state["record_since"])
        inbox = self.data.changes("inbox", state["inbox_since"])
        for item in record["items"]:
            cite = (item.get("metadata") or {}).get(SUBMISSION_CITATION)
            if cite:
                state["decisions"][cite] = f"accepted as {item['name']}"
        for item in inbox["items"]:
            meta = item.get("metadata") or {}
            if meta.get(REPLY_MARK) and meta.get(SUBMISSION_CITATION):
                state["decisions"][meta[SUBMISSION_CITATION]] = "rejected"
        state["record_since"] = record["next_since"]
        return inbox["items"], inbox["next_since"]

    # ── one pass ──────────────────────────────────────────────────────────────────────────
    def once(self) -> int:
        sync = Sync(self.data, self.mirror, quiet=True)
        if sync.once(sync.load_state()) is None:
            print("! the data server could not be reached — nothing was decided")
            return 1
        try:
            admin = self.data.context()["handle"]
            state = self.load_state()
            items, inbox_since = self.refresh(state)
        except DataError as e:
            print(f"! {e}")
            return 1
        record = self.mirror.load()
        names = {r["artifact"]["name"] for r in record}
        members = sync.members | {
            r["artifact"]["published_by"].lstrip("@") for r in record
            if r["artifact"].get("published_by")
        }
        print(f"gate: record holds {len(record)} artifact(s); members {sorted(members)}"
              + ("  [DRY RUN]" if self.dry else ""))

        candidates = list(state["deferred"]) + [
            i for i in items
            if (i.get("metadata") or {}).get(SUBMISSION_MARK) and not i.get("deleted")
        ]
        subs = []
        for item in {i["citation"]: i for i in candidates}.values():
            if item["citation"] in state["decisions"]:
                continue
            sub = self.admit(item, members, state)
            if sub:
                subs.append(sub)
        print(f"gate: {len(subs)} submission(s) to decide\n")

        ordered, deferred = order_submissions(subs, names)
        state["deferred"] = [waiting["item"] for waiting, _ in deferred]
        for waiting, missing in deferred:
            print(f"  DEFERRED {waiting['name']}\n    waiting for: {', '.join(missing)} "
                  f"(an Analysis is published before its outputs, spec 2.5)")
            telemetry.emit("gate", "gate_defer", "deferred", artifact=waiting["name"],
                           atype=waiting["canonical"]["artifact"].get("type"),
                           submitter=waiting["owner"], waiting_for=sorted(missing))

        for sub in ordered:
            canonical = sub["canonical"]
            canonical["artifact"]["created"] = self.provisional(sub, record)
            print(f"  {sub['name']}")
            findings = validate(canonical, record, members) + self.verify_downloads(sub)
            if passed(findings):
                for x in findings:
                    print(f"    [REVIEW {x['check']}] {x['msg'][:110]}")
                stored = self.accept(sub)
                if stored is None:
                    continue           # not decided: the next pass tries it again
                record.append(stored)
                names.add(sub["name"])
                state["decisions"][sub["citation"]] = f"accepted as {sub['name']}"
                self.decided += 1
                telemetry.emit("gate", "gate_accept", "accepted", artifact=sub["name"],
                               atype=canonical["artifact"].get("type"),
                               submitter=sub["owner"], findings=findings)
            else:
                if not self.reject(sub, findings, admin):
                    continue
                state["decisions"][sub["citation"]] = "rejected"
                self.decided += 1
                telemetry.emit("gate", "gate_reject", "rejected", artifact=sub["name"],
                               atype=canonical["artifact"].get("type"),
                               submitter=sub["owner"], findings=findings, refusal=["spec"])
            self.save_state(state)     # each decision is cached as soon as it is made
        state["inbox_since"] = inbox_since
        self.save_state(state)
        return 0

    def admit(self, item, members, state):
        """A submission worth validating, or None. A submission that can never be one is
        noted in the cache with why, and gets no reply: it is not an artifact submitted by a
        member under its own name."""
        name, owner = item["name"].partition("@")[0], item.get("created_by")

        def skip(why):
            print(f"  {item['name']}: ! {why} — skipped")
            state["decisions"][item["citation"]] = f"skipped: {why}"

        try:
            canonical = self.data.get_json(item["citation"])
        except (DataError, ValueError) as e:
            return skip(f"not readable as an artifact ({e})")
        declared = (canonical.get("artifact") or {}).get("name") \
            if isinstance(canonical, dict) else None
        why = skip_reason(item["name"], owner, declared, members)
        if why:
            return skip(why)
        return {"item": item, "citation": item["citation"], "name": name, "owner": owner,
                "canonical": canonical}

    def provisional(self, sub, record):
        """The `created` to validate with: the submission's own `created` on the server, or,
        when the record has moved past it (an Analysis accepted earlier in this pass), just
        after the newest record stamp. Both are the server's clock, so it is never later than
        the stamp the promote assigns, and every check that something is strictly earlier
        holds for the real stamp too."""
        when = parse_instant(sub["item"]["created"])
        newest = max((t for t in (parse_instant(r["artifact"].get("created")) for r in record)
                      if t), default=None)
        if newest is not None and newest >= when:
            when = newest + timedelta(microseconds=1)
        return when.isoformat()

    def verify_downloads(self, sub):
        """Every `download` held on the data server: the file exists, its sha256 is the one
        declared, and it was stored before the submission (J5). Any other location stays
        unverifiable, and the validator's REVIEW says so."""
        out = []
        for o in sub["canonical"].get("objects", []):
            if o.get("type") != "Content" or method_of(o.get("name")) != "download":
                continue
            location = str(o.get("location") or "")
            if not location.startswith(DATA_LOCATION):
                continue
            args = ["verify", "--cite", location, "--before", sub["item"]["created"]]
            if o.get("sha256"):
                args += ["--sha256", o["sha256"]]
            try:
                checked = self.data.run(*args)
            except DataError as e:
                checked = {"ok": False, "reason": str(e)}
            if not checked.get("ok"):
                # the reason first: the console cuts a long line, and the location is the
                # part the submitter already knows
                out.append(finding("DOWNLOAD", "FAIL",
                                   f"Content '{o.get('name')}': {checked.get('reason')} "
                                   f"({location})"))
        return out

    def accept(self, sub):
        """Promote into `record`; the server stamps `created`. -> the stored artifact, or None
        when the promote failed."""
        if self.dry:
            print(f"    (dry-run) would accept {sub['name']}")
            return sub["canonical"]
        try:
            promoted = self.data.run(
                "promote", sub["citation"], "--collection", "record", "--name", sub["name"],
                "--metadata", json.dumps({RECORD_MARK: True, SUBMISSION_CITATION: sub["citation"]}),
                "--stamp-json-pointer", "/artifact/created",
            )
            stored = self.data.get_json(promoted["citation"])
        except DataError as e:
            print(f"    ! promote failed, left undecided: {e}")
            return None
        self.mirror.write(stored)
        print(f"    ACCEPTED -> {promoted['citation']}, created {stored['artifact']['created']}")
        return stored

    def reject(self, sub, findings, admin) -> bool:
        """A reply in `inbox` that only the submitter reads. -> whether it was sent."""
        fails = [f"{x['check']}: {x['msg']}" for x in findings if x["level"] == "FAIL"]
        print(f"    REJECTED ({len(fails)} failures)")
        for x in fails[:6]:
            print(f"      - {x[:150]}")
        if self.dry:
            return True
        reply_name = f"{admin}_REPLY_{sub['item']['name']}"
        reply = {
            "artifact": {
                "name": re.sub(r"[^A-Za-z0-9_]", "_", reply_name),
                "type": "NonGroundable",
                "specification_version": "1.0",
                "published_by": f"@{admin}",
                "created": None,
                "text": "REJECTED\n\nin_reply_to: " + sub["name"] + "\n\n"
                        + "\n".join(f"- {x}" for x in fails),
            },
            "objects": [],
            "relationships": [],
        }
        try:
            self.data.put_json(reply, "inbox", reply_name, {
                REPLY_MARK: True,
                IN_REPLY_TO: sub["name"],
                "recipients": [sub["owner"]],
                SUBMISSION_CITATION: sub["citation"],
            })
        except DataError as e:
            print(f"    ! reply failed, left undecided: {e}")
            return False
        print(f"    reply sent to {sub['owner']}")
        return True

    def watch(self) -> int:
        """A pass every POLL seconds until stopped. A pass's report is printed when it accepted
        or rejected something; a pass that fails is reported on the 1st, 5th and every 20th
        failure in a row. A stop mid-pass prints what the pass had decided so far: each line
        is a decision the admin must see."""
        stop_on_signals()
        lock = take_over("gate")  # noqa: F841 — held for as long as this gate watches
        print(f"watching inbox (every {POLL}s) — ctrl-c to stop", flush=True)
        misses = 0
        report = io.StringIO()
        try:
            while True:
                report = io.StringIO()
                with contextlib.redirect_stdout(report):
                    code = self.once()
                if code:
                    misses += 1
                    if misses in (1, 5) or misses % 20 == 0:
                        print(report.getvalue().rstrip(), flush=True)
                        print(f"  ({misses} consecutive failed pass(es) — nothing is being "
                              f"decided)", flush=True)
                else:
                    misses = 0
                    if self.decided:
                        print(report.getvalue().rstrip(), flush=True)
                self.decided = 0
                time.sleep(POLL)
        except KeyboardInterrupt:
            if self.decided:
                print(report.getvalue().rstrip(), flush=True)
            print("stopped", flush=True)
            return 0

    # ── the other modes ───────────────────────────────────────────────────────────────────
    def verify(self) -> int:
        """The copy's artifact names against the `record` feed. Changes nothing."""
        try:
            feed = self.data.changes("record", 0)
        except DataError as e:
            print(f"! the data server could not be reached: {e}")
            return 1
        server = {i["name"] for i in feed["items"]
                  if (i.get("metadata") or {}).get(RECORD_MARK) and not i.get("deleted")}
        held = {r["artifact"]["name"] for r in self.mirror.load()}
        print(f"copy {self.mirror.root}/: {len(held)} artifact(s); record: {len(server)}")
        print(f"  in the record, missing from the copy: {sorted(server - held) or 'none'}")
        print(f"  in the copy only, not in the record: {sorted(held - server) or 'none'}")
        same = server == held
        print("OK" if same else "THE COPY DIFFERS FROM THE RECORD — run `/symposium gate "
                                "--rebuild`")
        return 0 if same else 1

    def rebuild(self) -> int:
        """Discard the copy's cursor and the gate's state, and rebuild both from the server.
        Decides nothing: the next pass reads `inbox` from the start, skipping every
        submission the server already holds a decision for."""
        for name in (SYNC_STATE, STATE):
            (self.mirror.root / name).unlink(missing_ok=True)
        sync = Sync(self.data, self.mirror, quiet=True)
        synced = sync.once(sync.load_state())
        if synced is None:
            print("! the data server could not be reached — nothing was rebuilt")
            return 1
        state = self.load_state()
        try:
            self.refresh(state)
        except DataError as e:
            print(f"! {e}")
            return 1
        self.mirror.write_state(STATE, state)
        print(f"rebuilt {self.mirror.root}/ from the server: {synced['artifacts']} artifact(s), "
              f"{len(state['decisions'])} decision(s)")
        return 0


def main(argv) -> int:
    gate = Gate(dry="--dry-run" in argv)
    try:
        gate.data.context()  # local: with none, the CLI's message names setup and bootstrap
    except DataError as e:
        print(f"! {e}")
        return 1
    if "--watch" in argv:
        if "--verify" in argv or "--rebuild" in argv:
            print("! --watch runs passes; it does not combine with --verify or --rebuild")
            return 2
        return gate.watch()
    if "--rebuild" in argv:
        return gate.rebuild()
    if "--verify" in argv:
        return gate.verify()
    return gate.once()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
