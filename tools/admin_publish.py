#!/usr/bin/env python3
"""Publish an artifact as the admin, straight into the record.

    python admin_publish.py --check  metrics.json data.json     # validate only
    python admin_publish.py          metrics.json data.json     # publish, one act

The admin cannot use `publish.py`. A Member submits by uploading and granting the admin READ,
and the gate discovers submissions from its own permission map — where it deliberately skips
networks it owns, since those are its record copies and rejection replies. An artifact the
admin uploaded would never be seen. So the admin takes the same last step directly.

**It is not a shortcut past the checks.** The candidate is validated by `validate` against
the accepted record, exactly as the gate validates a Member's submission, and refused on the
same terms. Nothing enters this record without passing what everything else passed; an admin
who could exempt themselves would make the whole record worth less.

Files given together are ONE ACT and share a single `created` stamp — the case this exists
for is an Analysis and the Data it produces, which name each other and so cannot validate
apart (spec 1.8, 2.5). If any of them fails, none is published.

Intended for the end of the day: the metrics Analysis and its Data, and the summary NonGroundable
that cites them. Publishing measurements while the work is still running hands Members a
scoreboard.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

import gate                                                            # admin auth, accept()
from validate import EMBED_REFUSE, embedded_size, passed, report, validate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="canonical JSON file(s); together = one act")
    ap.add_argument("--check", action="store_true", help="validate only; publish nothing")
    args = ap.parse_args(argv)

    arts = []
    for p in args.paths:
        try:
            arts.append(json.loads(pathlib.Path(p).read_text()))
        except Exception as exc:                                       # noqa: BLE001
            print(f"! {p}: not readable as JSON — {exc}")
            return 1

    record = gate.load_record()
    state = gate.load_state()
    # Same reason the gate does it: name uniqueness is checked against the mirror, so a mirror
    # behind the server could let a duplicate name into an immutable record. Cheap — one
    # permission-map call — and it repairs rather than refuses.
    _ok, added, unresolved, _extra = gate.checkpoint(record, state)
    if added:
        print(f"  mirror was behind by {len(added)}; repaired: {', '.join(sorted(added)[:5])}")
    if unresolved:
        print(f"! cannot account for {len(unresolved)} admin-owned network(s) — "
              f"run: python gate.py --rebuild")
        return 1
    names = {r["artifact"]["name"] for r in record if r.get("artifact", {}).get("name")}
    members = set(gate.MEMBERS) | {gate.ADMIN_USER}
    print(f"admin publish as {gate.ADMIN_USER} — record holds {len(record)} artifact(s)\n")

    # One act, one stamp. Provisional here so the ordering checks run against something
    # realistic; `accept()` sets the same value again when it writes.
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for a in arts:
        a["artifact"]["created"] = stamp

    fatal = False
    for a in arts:
        name = a["artifact"].get("name", "<unnamed>")
        if name in names:
            print(f"  {name}: FAIL  already in the record; names are never reused")
            fatal = True
            continue
        total, props = embedded_size(a)
        if total > EMBED_REFUSE:
            print(f"  {name}: FAIL  embedded payload is {total // 1024} KB, over the "
                  f"{EMBED_REFUSE // 1024} KB limit"
                  + (f" (largest: '{props[0][1]}' on {props[0][0]})" if props else ""))
            fatal = True
            continue
        sibs = [x for x in arts if x is not a]
        findings = validate(a, record + sibs, members)
        ok = passed(findings)
        print(f"  {name}: spec {'ok' if ok else 'FAIL'}")
        for f in findings:
            print(f"      [{f['level']:6} {f['check']:9}] {f['msg']}")
        fatal = fatal or not ok

    if fatal:
        print("\nnothing published — fix the failures above")
        return 1
    if args.check:
        print("\n--check: validation passed; nothing published")
        return 0

    muuids = gate.member_uuids()
    print()
    for a in arts:
        if not gate.accept(a, record, muuids, state, stamp=stamp):
            print("\n! publication failed part-way through. The record may hold some of this "
                  "act but not all of it — check the mirror before retrying.")
            return 1
        record.append(a)

    print(f"\n{len(arts)} artifact(s) in the record, stamped {stamp}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
