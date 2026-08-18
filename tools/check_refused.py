#!/usr/bin/env python3
"""Run the refused-case fixtures and check each is refused for the stated reason.

    python check_refused_v7.py ../validation_refused ../validation_record

Each fixture is an Artifact that must not be accepted. `EXPECTED.json` in the fixture
directory says, for each one, which checklist case it stands for and which finding the
validator must produce. A fixture that fails for the wrong reason is a failure of this
suite, not a pass: the point of the case is the rule it exercises, and a fixture that
happens to be malformed some other way exercises nothing.

Some cases need a second fixture present in the record to be refused at all, which the
`with` key supplies. J6 is such a case: an Artifact cannot be too late for a twin that
is not in the record.

Exit status is 0 when every fixture is refused for its stated reason.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from validate import validate


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture_dir")
    ap.add_argument("record_dir")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)

    fdir, rdir = Path(a.fixture_dir), Path(a.record_dir)
    expected = json.loads((fdir / "EXPECTED.json").read_text())
    record = [json.loads(p.read_text()) for p in sorted(rdir.glob("*.json"))]
    members = {h["artifact"]["published_by"].lstrip("@") for h in record}

    width = max(len(k) for k in expected)
    ok = True
    for fname in sorted(expected):
        exp = expected[fname]
        cand = json.loads((fdir / fname).read_text())
        extra = [json.loads((fdir / w).read_text()) for w in exp.get("with", [])]
        findings = validate(cand, record + extra, members)
        fails = [f for f in findings if f["level"] == "FAIL"]
        hit = [f for f in fails
               if f["check"] == exp["check"] and exp["msg"] in f["msg"]]
        if hit:
            status = "refused"
        elif fails:
            status = "REFUSED FOR THE WRONG REASON"
            ok = False
        else:
            status = "ACCEPTED — the rule is not enforced"
            ok = False
        print(f"{exp['case']:3} {fname:<{width}}  {status}")
        if hit and a.verbose:
            print(f"       {hit[0]['msg']}")
        if not hit:
            for f in fails:
                print(f"       [got {f['check']}] {f['msg']}")
            print(f"       [wanted {exp['check']}] ...{exp['msg']}...")

    cases = sorted({e["case"] for e in expected.values()})
    print(f"\n{'=' * 70}\n{len(expected)} fixtures over {len(cases)} cases: "
          f"{', '.join(cases)}\n{'all refused as stated' if ok else 'SUITE FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
