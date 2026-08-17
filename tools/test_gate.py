#!/usr/bin/env python3
"""Offline tests for the gate's publication-unit logic.

    python test_gate.py

No network and no credentials: `ndex_io.auth` is stubbed before `gate` is imported, because
the gate authenticates at module scope. Nothing here uploads, and nothing here needs a server.

An Analysis names no outputs. An Artifact produced by one names it with `produced_by`, and
outputs are found by searching for that (spec 2.5). So an Analysis is complete on its own and
is accepted the moment it validates, while an output can be too early — it waits for exactly
one thing, its Analysis. Cases A-D pin that down in both directions.

Case E is the one that would not announce itself. A Ground carries its evidence address in
`citation`; reading any other key returns "" for every Ground rather than raising, and the
acceptance ordering then sees no evidential references at all. The Argument is stamped and
validated before the Data it grounds on, and the member is told their citation does not
resolve — for an artifact sitting in the same submission.
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


def names(bundles):
    return [[m["canonical"]["artifact"]["name"] for m in b] for b in bundles]


GROUND = {"name": "g", "type": "Ground", "rationale": "r",
          "citation": "@a_data_v1.values#csv.row=X&col=Y"}

CASES = [
    ("an Analysis alone is accepted; it names no outputs to wait for",
     [art("a_an_v1", "Analysis")], set(),
     [["a_an_v1"]], []),

    ("an output and its Analysis in one batch are one act",
     [art("a_out_v1", "Data", produced_by="@a_an_v1"), art("a_an_v1", "Analysis")], set(),
     [["a_an_v1", "a_out_v1"]], []),

    ("an output alone stands when its Analysis is already in the record",
     [art("a_out_v1", "Data", produced_by="@a_an_v1")], {"a_an_v1"},
     [["a_out_v1"]], []),

    ("an output whose Analysis is nowhere is deferred, waiting for exactly one thing",
     [art("a_out_v1", "Data", produced_by="@a_an_v1")], set(),
     [], [["a_an_v1"]]),

    ("acceptance order follows a Ground's `citation`, so evidence is stamped first",
     [art("a_arg_v1", "Argument", objs=[GROUND]), art("a_data_v1", "Data")], set(),
     [["a_data_v1"], ["a_arg_v1"]], []),
]


def run():
    ok = 0
    for label, subs, record_names, want_bundles, want_deferred in CASES:
        bundles, deferred = gate.form_bundles(subs, record_names)
        got_b, got_d = names(bundles), [missing for _, missing in deferred]
        good = got_b == want_bundles and got_d == want_deferred
        ok += good
        print(f"  [{'ok ' if good else 'FAIL'}] {label}")
        if not good:
            print(f"         bundles  want {want_bundles}  got {got_b}")
            print(f"         deferred want {want_deferred}  got {got_d}")
    print(f"\n{ok}/{len(CASES)} gate cases behaved as specified")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(run())
