#!/usr/bin/env python3
"""Publish an artifact as the admin, straight into the record.

    python admin_publish.py --check  metrics.json     # validate only
    python admin_publish.py          metrics.json     # publish
    python admin_publish.py --role none  replay.json  # no type limit (record replay, migration)

The admin cannot use `publish.py`. A Member submits by uploading and granting the admin READ,
and the gate discovers submissions from its own permission map — where it deliberately skips
networks it owns, since those are its record copies and rejection replies. An artifact the
admin uploaded would never be seen. So the admin takes the same last step directly.

**It is not a shortcut past the checks.** The candidate is validated by `validate` against
the accepted record, exactly as the gate validates a Member's submission, and refused on the
same terms. Nothing enters this record without passing what everything else passed; an admin
who could exempt themselves would make the whole record worth less.

ONE ARTIFACT PER RUN. Publication is strictly serial: every artifact gets its own `created`
and is validated against the record as it stands (spec 1.9). An Analysis and the Data it
produces go in separate runs, the Analysis first, because an output's `produced_by` must
resolve to something already in the record (spec 2.5).

Intended for the end of the day: the metrics Analysis and its Data, and the summary NonGroundable
that cites them. Publishing measurements while the work is still running hands Members a
scoreboard.

THE ADMIN HOLDS A ROLE LIKE ANYONE ELSE, and it is `operator` (roles/operator.md) unless you say
otherwise. It is the narrowest role in the set on purpose: the party that runs the gate must not
also publish the material the community reasons over, because a contest against it is accepted or
refused by the publisher of the thing being contested. The corpus goes in through a Member session
holding `importer`. Like every role limit this is SELF-IMPOSED — the gate has no basis to reject a
conformant artifact for being out of role and does not try — and `--role none` lifts it for work
that is not publication in the ordinary sense, such as replaying a record onto a new server.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

import gate                                                            # admin auth, accept()
from publish import load_roles                                         # roles/*.md contracts
from validate import EMBED_REFUSE, embedded_size, passed, report, validate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs=1, metavar="path",
                    help="one canonical JSON file; publication is serial (spec 1.9)")
    ap.add_argument("--check", action="store_true", help="validate only; publish nothing")
    ap.add_argument("--role", default="operator",
                    help="role limit to impose on this run; 'none' lifts it (default: operator)")
    args = ap.parse_args(argv)

    # The role limit is self-imposed, exactly as it is in publish.py: the gate has no basis to
    # reject a conformant artifact for being out of role. It is here because the admin is the one
    # Member whose out-of-role publication nobody else can contest on equal terms — a critic's
    # Argument against an admin import is accepted or refused by the party that published it.
    roles = load_roles()
    allowed = None
    if args.role != "none":
        if args.role not in roles:
            print(f"! unknown role '{args.role}'. Known: {', '.join(roles)}, none")
            return 2
        allowed = set(roles[args.role]["may_publish"])

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
    print(f"admin publish as {gate.ADMIN_USER}"
          + (f", role {args.role} ({', '.join(sorted(allowed))})" if allowed
             else ", NO ROLE LIMIT (--role none)")
          + f" — record holds {len(record)} artifact(s)\n")

    # One artifact, one stamp. Provisional here so the ordering checks run against something
    # realistic; `accept()` sets the same value again when it writes.
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    arts[0]["artifact"]["created"] = stamp

    fatal = False
    for a in arts:
        name = a["artifact"].get("name", "<unnamed>")
        if name in names:
            print(f"  {name}: FAIL  already in the record; names are never reused")
            fatal = True
            continue
        # Kept apart from the spec verdict below: this tool declining is not the specification
        # declining, and only the second says anything about whether the spec is workable.
        atype = a["artifact"].get("type")
        if allowed is not None and atype not in allowed:
            print(f"  {name}: OUT OF ROLE  role '{args.role}' may not publish a {atype}"
                  f" ({', '.join(sorted(allowed))})")
            for m in roles[args.role].get("must_not", []):
                print(f"      must not: {m}")
            print("      --role none lifts this if the run is a replay rather than a publication")
            fatal = True
            continue
        total, props = embedded_size(a)
        if total > EMBED_REFUSE:
            print(f"  {name}: FAIL  embedded payload is {total // 1024} KB, over the "
                  f"{EMBED_REFUSE // 1024} KB limit"
                  + (f" (largest: '{props[0][1]}' on {props[0][0]})" if props else ""))
            fatal = True
            continue
        findings = validate(a, record, members)
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
            print("\n! publication failed — check the mirror before retrying.")
            return 1
        record.append(a)

    print(f"\n{len(arts)} artifact(s) in the record, stamped {stamp}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
