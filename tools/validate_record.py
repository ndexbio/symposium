#!/usr/bin/env python3
"""Validate a whole CommunityRecord directory, in publication order.

    python validate_record_v7.py ../validation_record
    python validate_record_v7.py ../validation_record --verbose

`validate.py` validates one candidate against an accepted record, which is what a gate
does. A record being authored has no gate yet, so this walks the directory in `created`
order and validates each Artifact against everything published before it. That is the same
sequence the gate would have seen, so a record that passes here is a record that could have
been accepted one Artifact at a time.

Exit status is 0 when nothing FAILs. REVIEW findings are printed and never gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from validate import parse_instant, validate


def load(record_dir: Path):
    arts = []
    for p in sorted(record_dir.glob("*.json")):
        try:
            arts.append((p, json.loads(p.read_text())))
        except json.JSONDecodeError as e:
            print(f"{p.name}: NOT JSON — {e}")
            raise SystemExit(2)
    def key(item):
        t = parse_instant(item[1].get("artifact", {}).get("created"))
        return (t is None, t, item[0].name)
    return sorted(arts, key=key)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("record_dir")
    ap.add_argument("--verbose", action="store_true", help="print REVIEW findings for every Artifact")
    a = ap.parse_args(argv)

    arts = load(Path(a.record_dir))
    members = {h["artifact"]["published_by"].lstrip("@")
               for _, h in arts if h.get("artifact", {}).get("published_by")}
    print(f"{len(arts)} artifacts, {len(members)} members: {', '.join(sorted(members))}\n")

    accepted, n_fail, n_review = [], 0, 0
    for path, cand in arts:
        findings = validate(cand, accepted, members)
        fails = [f for f in findings if f["level"] == "FAIL"]
        revs = [f for f in findings if f["level"] == "REVIEW"]
        n_fail += len(fails)
        n_review += len(revs)
        name = cand.get("artifact", {}).get("name", path.name)
        if fails or (revs and a.verbose):
            print(f"{name}  [{cand.get('artifact', {}).get('created', '?')}]")
            for f in fails:
                print(f"   [FAIL   {f['check']:12}] {f['msg']}")
            for f in revs:
                print(f"   [REVIEW {f['check']:12}] {f['msg']}")
            print()
        accepted.append(cand)

    print(f"{'=' * 70}\n{len(arts)} artifacts: {n_fail} FAIL, {n_review} REVIEW")
    if n_review and not a.verbose:
        print("(--verbose to print the review findings)")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
