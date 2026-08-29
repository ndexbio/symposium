#!/usr/bin/env python3
"""Offline tests for the gate's acceptance ordering.

    python test_gate.py

No network and no credentials: `ndex_io.auth` is stubbed before `gate` is imported, because
the gate authenticates at module scope. Nothing here uploads, and nothing here needs a server.

Publication is strictly serial (spec 1.9). Every artifact gets its own `created` and is
validated against the record as it stands, so `order_submissions` returns a FLAT list: what
a pass considers, in the order it considers it. There are no publication units. An earlier
version grouped an Analysis with its outputs and stamped the group once, which produced two
artifacts with an identical `created` — exactly what spec 1.9 says cannot refer to each
other — and needed an ordering exemption on `produced_by` to be publishable at all.

An Analysis names no outputs. An artifact produced by one names it with `produced_by`, and
outputs are found by searching for that (spec 2.5). So an Analysis is complete on its own,
while an output can be too early: it waits for exactly one thing. Cases A-D pin that down.

Case E is the one that would not announce itself. A Ground carries its evidence address in
`citation`; reading any other key returns "" for every Ground rather than raising, and the
ordering then sees no evidential references at all. The Argument is stamped and validated
before the Data it grounds on, and the member is told their citation does not resolve.

Case F guards the regression this file was rewritten for: an output submitted BEFORE its
Analysis must still be ordered after it, never beside it.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
import ndex_io                                                        # noqa: E402

ndex_io.auth = lambda prefix: ("ndex-admin", "stub-token")            # noqa: E731

import gate                                                           # noqa: E402


def art(name, typ, objs=(), **header):
    return {"canonical": {"artifact": dict(name=name, type=typ, **header),
                          "objects": list(objs), "relationships": []}, "uuid": name}


def names(ordered):
    return [m["canonical"]["artifact"]["name"] for m in ordered]


GROUND = {"name": "g", "type": "Ground", "rationale": "r",
          "citation": "@a_data_v1.values#csv.row=X&col=Y"}

CASES = [
    ("an Analysis alone is accepted; it names no outputs to wait for",
     [art("a_an_v1", "Analysis")], set(),
     ["a_an_v1"], []),

    ("an Analysis and its output pending together are ordered serially, Analysis first",
     [art("a_an_v1", "Analysis"), art("a_out_v1", "Data", produced_by="@a_an_v1")], set(),
     ["a_an_v1", "a_out_v1"], []),

    ("an output alone stands when its Analysis is already in the record",
     [art("a_out_v1", "Data", produced_by="@a_an_v1")], {"a_an_v1"},
     ["a_out_v1"], []),

    ("an output whose Analysis is nowhere is deferred, waiting for exactly one thing",
     [art("a_out_v1", "Data", produced_by="@a_an_v1")], set(),
     [], [["a_an_v1"]]),

    ("acceptance order follows a Ground's `citation`, so evidence is stamped first",
     [art("a_arg_v1", "Argument", objs=[GROUND]), art("a_data_v1", "Data")], set(),
     ["a_data_v1", "a_arg_v1"], []),

    ("an output submitted before its Analysis is ordered after it, not beside it",
     [art("a_out_v1", "Data", produced_by="@a_an_v1"), art("a_an_v1", "Analysis")], set(),
     ["a_an_v1", "a_out_v1"], []),
]


def run():
    ok = 0
    for label, subs, record_names, want_order, want_deferred in CASES:
        ordered, deferred = gate.order_submissions(subs, record_names)
        got_o, got_d = names(ordered), [missing for _, missing in deferred]
        good = got_o == want_order and got_d == want_deferred
        ok += good
        print(f"  [{'ok ' if good else 'FAIL'}] {label}")
        if not good:
            print(f"         order    want {want_order}  got {got_o}")
            print(f"         deferred want {want_deferred}  got {got_d}")
    print(f"\n{ok}/{len(CASES)} gate cases behaved as specified")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(run())
