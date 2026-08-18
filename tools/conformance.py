#!/usr/bin/env python3
"""The conformance suite: everything that checks this toolchain, in one command.

    python3 conformance.py
    python3 conformance.py --quiet        # section totals only

Three sections, and they check different things.

**Scenarios** mutate a known-good corpus held in this file and assert *which check* fires.
A validator that accepts everything passes no scenario here; one that rejects everything
fails the first. Asserting the check and not merely the refusal is the point: a fixture
that fails for the wrong reason has exercised nothing, and would go on passing after the
rule it was written for was deleted.

**Refused fixtures** are whole Artifacts on disk, validated against the 34-Artifact
example record rather than against a toy corpus. They overlap the scenarios by design in
about eight places; what they add is the same rule met at full scale, where an address
has somewhere real to resolve and a name has a real namespace to collide in.

**The record** is validated in publication order, each Artifact against everything
published before it, which is the sequence the gate saw when it accepted them.

**The gate** is checked offline for how it groups a batch into publication units and
orders them, which is the one part of the publishing loop that can be wrong without any
Artifact being wrong.

Nothing here needs a network, a server, or credentials.
"""
from __future__ import annotations

import argparse
import copy
import pathlib
import sys

from validate import validate, passed

HERE = pathlib.Path(__file__).resolve().parent
MEMBERS = {"agent_lyra", "agent_vega", "ndex-admin"}
V = "1.0"

# --------------------------------------------------------------------------- corpus
# Deliberately small and deliberately conformant. Every scenario below is one mutation
# away from this, so a change here that breaks a baseline breaks loudly and at once.

DATA = {
    "artifact": {
        "name": "agent_lyra_gdsc_v1", "type": "Data", "specification_version": V,
        "published_by": "@agent_lyra", "created": "2026-08-01T10:00:00Z",
        "authors": ["GDSC consortium"],
        "import_method": "GDSC2 release 8.5, paclitaxel, filtered to breast lines.",
        "measurements": "cell_line,arid1a_status,ic50_z\nMCF7,WT,-0.34\nHCC1143,MUT,-1.21\n",
    },
    "objects": [{"name": "csv", "type": "Content", "groundable": True,
                 "description": "The measured values, held in `measurements`.",
                 "addressing_method": "row=<cell_line>&col=<column name>."}],
    "relationships": [],
}

PAPER = {
    "artifact": {
        "name": "agent_lyra_chen2025_v1", "type": "ScientificPublication",
        "specification_version": V, "published_by": "@agent_lyra",
        "created": "2026-08-01T11:00:00Z", "authors": ["Chen, Y.", "Okafor, N."],
        "import_method": "Extracted the Results section as plain text from the publisher PDF.",
        "results_text": "ARID1A knockdown raised CHK1 levels across all lines tested.",
    },
    "objects": [{"name": "text_span", "type": "Content", "groundable": True,
                 "description": "Passages of the Results section, held in `results_text`.",
                 "addressing_method": 'quote="<exact text>", with &nth= or &near= if it repeats.'}],
    "relationships": [],
}

NOTE = {
    "artifact": {"name": "agent_vega_plan_v1", "type": "NonGroundable",
                 "specification_version": V, "published_by": "@agent_vega",
                 "created": "2026-08-01T09:00:00Z", "text": "Proposed screening plan."},
    "objects": [], "relationships": [],
}

# A Model is a property graph: Objects of the author's own types, relationships of the
# author's own naming, and a Content Object that says how to address an element.
MODEL = {
    "artifact": {
        "name": "agent_vega_pathway_v1", "type": "Model", "specification_version": V,
        "published_by": "@agent_vega", "created": "2026-08-01T12:00:00Z",
        "authors": ["agent_vega"],
        "modeling_choices": "Two stages because two assays; one effector placed at one stage.",
    },
    "objects": [
        {"name": "graph", "type": "Content", "groundable": True,
         "description": "The stages and effectors, held as this Artifact's own graph.",
         "addressing_method": "node=<Object name>, or edge=<source>|<rel>|<target>."},
        {"name": "stage_entry", "type": "ReplicationStage", "title": "Entry"},
        {"name": "stage_egress", "type": "ReplicationStage", "title": "Egress"},
        {"name": "eff_arid1a", "type": "Effector", "title": "ARID1A"},
    ],
    "relationships": [
        {"rel": "precedes", "source": "stage_entry", "target": "stage_egress"},
        {"rel": "restricts", "source": "eff_arid1a", "target": "stage_egress"},
    ],
}

ANALYSIS = {
    "artifact": {
        "name": "agent_vega_join_v1", "type": "Analysis", "specification_version": V,
        "published_by": "@agent_vega", "created": "2026-08-01T13:00:00Z",
        "inputs": ["@agent_lyra_gdsc_v1"],
        "procedure": "Joined the measurements on cell line; no filtering or transformation.",
    },
    "objects": [], "relationships": [],
}

OUTPUT = {
    "artifact": {
        "name": "agent_vega_joined_v1", "type": "Data", "specification_version": V,
        "published_by": "@agent_vega", "created": "2026-08-01T13:30:00Z",
        "authors": ["agent_vega"], "produced_by": "@agent_vega_join_v1",
        "values": "cell_line,ic50_z\nMCF7,-0.34\nHCC1143,-1.21\n",
    },
    "objects": [{"name": "csv", "type": "Content", "groundable": True,
                 "description": "The joined rows.", "addressing_method": "row=<cell_line>&col=<column>."}],
    "relationships": [],
}

# A second output of the SAME Analysis, so two Grounds can descend from one source
# without addressing the same Artifact — the case the independence walk exists for.
OUTPUT_B = {
    "artifact": {
        "name": "agent_vega_residuals_v1", "type": "Data", "specification_version": V,
        "published_by": "@agent_vega", "created": "2026-08-01T13:45:00Z",
        "authors": ["agent_vega"], "produced_by": "@agent_vega_join_v1",
        "values": "cell_line,residual\nMCF7,0.02\nHCC1143,-0.11\n",
    },
    "objects": [{"name": "csv", "type": "Content", "groundable": True,
                 "description": "Residuals.", "addressing_method": "row=<cell_line>&col=<column>."}],
    "relationships": [],
}

EXTERNAL = {
    "artifact": {
        "name": "agent_lyra_depmap_v1", "type": "Data", "specification_version": V,
        "published_by": "@agent_lyra", "created": "2026-08-01T08:00:00Z",
        "authors": ["DepMap"], "import_method": "REST query against the DepMap portal.",
    },
    "objects": [{"name": "rest", "type": "Content", "groundable": True,
                 "description": "A DepMap query result, held outside this record.",
                 "addressing_method": "A query string appended to the endpoint.",
                 "access_method": "https://depmap.org/api", "location": "depmap.org"}],
    "relationships": [],
}

QUOTE = "ARID1A knockdown raised CHK1 levels"

ARG = {
    "artifact": {
        "name": "agent_lyra_arid1a_v1", "type": "Argument", "specification_version": V,
        "published_by": "@agent_lyra", "created": "2026-08-02T09:00:00Z",
        "authors": ["agent_lyra"], "primary_assertion": "a_primary",
        "description": "Revisits [the earlier plan](@agent_vega_plan_v1).",
        "verdict": "Supported for prioritisation, not for a mechanistic claim.",
        "purpose": "Choosing which lines to take into a validation screen; a wrong pick "
                   "costs a plate and is visible within a week.",
        "rationale": "Two lines separate in the expected direction and the effect is "
                     "consistent with the published mechanism. The sample is small and the "
                     "Assumption below carries the claim out of the dish.",
    },
    "objects": [
        {"name": "a_primary", "type": "Assertion",
         "claim": "ARID1A-mutant breast lines are more paclitaxel-sensitive.",
         "scope": "GDSC2 breast carcinoma lines; in vitro viability."},
        {"name": "a_sub", "type": "Assertion",
         "claim": "ARID1A loss raises CHK1 in these lines.",
         "scope": "The lines assayed in the source publication."},
        {"name": "g_csv", "type": "Ground",
         "citation": "@agent_lyra_gdsc_v1.measurements#csv.row=HCC1143&col=ic50_z",
         "rationale": "The sensitivity value for the one mutant line in the panel.",
         "criterion": "An ic50_z at or above the wild-type value would have counted against it."},
        {"name": "g_quote", "type": "Ground",
         "citation": f'@agent_lyra_chen2025_v1.results_text#text_span.quote="{QUOTE}"',
         "rationale": "The authors' statement of the mechanism, built upon rather than tested."},
        {"name": "u_invitro", "type": "Assumption",
         "rationale": "That in vitro viability tracks clinical response. No evidence is "
                      "offered; it is the standing premise of the assay and should be "
                      "granted only for prioritisation."},
    ],
    "relationships": [
        {"rel": "depends_on", "source": "a_primary", "target": "a_sub"},
        {"rel": "grounded_by", "source": "a_primary", "target": "g_csv"},
        {"rel": "grounded_by", "source": "a_sub", "target": "g_quote"},
        {"rel": "assumes", "source": "a_primary", "target": "u_invitro"},
    ],
}

RECORD = [DATA, PAPER, NOTE, MODEL, ANALYSIS, OUTPUT, OUTPUT_B, EXTERNAL]


def mut(fn, base=None):
    a = copy.deepcopy(base if base is not None else ARG)
    fn(a)
    return a


def obj(a, name):
    return next(o for o in a["objects"] if o["name"] == name)


def ground(a, **kw):
    """Replace g_csv's citation and drop its criterion where a scenario needs a bare Ground."""
    obj(a, "g_csv").update(**kw)


# --------------------------------------------------------------------- pass/fail cases
# (label, artifact, expect_pass, expected_check_or_None)
CASES = [
    # ---- baselines: one per Artifact type the specification defines ------------------
    ("baseline conformant Argument", ARG, True, None),
    ("conformant Data", DATA, True, None),
    ("conformant ScientificPublication", PAPER, True, None),
    ("conformant NonGroundable", NOTE, True, None),
    ("conformant Model, holding its own Objects and relationships", MODEL, True, None),
    ("conformant Analysis", ANALYSIS, True, None),
    ("conformant output citing its Analysis", OUTPUT, True, None),

    # ---- Argument structure (spec 2.2) ----------------------------------------------
    ("Assertion with no basis", mut(lambda a: a["relationships"].remove(
        {"rel": "grounded_by", "source": "a_sub", "target": "g_quote"})), False, "C-ARG"),
    ("primary_assertion names something that is not an Assertion",
     mut(lambda a: a["artifact"].update(primary_assertion="g_csv")), False, "C-ARG"),
    ("an Assertion depends on the primary", mut(lambda a: a["relationships"].append(
        {"rel": "depends_on", "source": "a_sub", "target": "a_primary"})), False, "C-ARG"),
    ("depends_on cycle", mut(lambda a: a["relationships"].append(
        {"rel": "depends_on", "source": "a_sub", "target": "a_primary"})), False, "C-ARG"),
    ("Ground bearing on two Assertions", mut(lambda a: a["relationships"].append(
        {"rel": "grounded_by", "source": "a_sub", "target": "g_csv"})), False, "C-ARG"),
    ("Assumption bearing on two Assertions", mut(lambda a: a["relationships"].append(
        {"rel": "assumes", "source": "a_sub", "target": "u_invitro"})), False, "C-ARG"),
    ("grounded_by pointing at an Assertion", mut(lambda a: a["relationships"].append(
        {"rel": "grounded_by", "source": "a_sub", "target": "a_primary"})), False, "C-ARG"),
    ("a relationship leaving the Artifact", mut(lambda a: a["relationships"].append(
        {"rel": "grounded_by", "source": "a_primary", "target": "@agent_lyra_gdsc_v1"})),
     False, "STRUCT"),
    ("an Argument using a relationship the specification does not define",
     mut(lambda a: a["relationships"].append(
        {"rel": "supports", "source": "a_primary", "target": "a_sub"})), False, "STRUCT"),
    ("an Argument containing an Object type it may not hold",
     mut(lambda a: a["objects"].append({"name": "n_x", "type": "ReplicationStage"})),
     False, "TYPE"),
    ("Argument missing its verdict", mut(lambda a: a["artifact"].pop("verdict")), False, "TYPE"),
    ("Argument missing its purpose", mut(lambda a: a["artifact"].pop("purpose")), False, "TYPE"),
    ("Argument missing its rationale", mut(lambda a: a["artifact"].pop("rationale")), False, "TYPE"),
    ("Argument without authors", mut(lambda a: a["artifact"].pop("authors")), False, "TYPE"),
    ("Assertion without a scope", mut(lambda a: obj(a, "a_sub").pop("scope")), False, "TYPE"),
    ("Ground without a rationale", mut(lambda a: obj(a, "g_csv").pop("rationale")), False, "TYPE"),
    ("Assumption without a rationale",
     mut(lambda a: obj(a, "u_invitro").pop("rationale")), False, "TYPE"),

    # ---- the trust firewall (spec 2.1, 2.2.4) ---------------------------------------
    ("Ground citing content inside its own Argument",
     mut(lambda a: ground(a, citation="@agent_lyra_arid1a_v1.a_sub")), False, "GROUND"),
    ("Ground citing a NonGroundable",
     mut(lambda a: ground(a, citation="@agent_vega_plan_v1.text")), False, "GROUND"),
    ("Ground citing an Analysis",
     mut(lambda a: ground(a, citation="@agent_vega_join_v1.procedure")), False, "GROUND"),
    ("Ground citing a Member",
     mut(lambda a: ground(a, citation="@agent_vega")), False, "GROUND"),
    ("Ground citing a Content Object itself",
     mut(lambda a: ground(a, citation="@agent_lyra_gdsc_v1.csv")), False, "GROUND"),
    ("Ground citing content not declared groundable", mut(lambda a: (
        obj(DATA, "csv"),
        ground(a, citation="@agent_lyra_gdsc_v1.measurements#csv"))), True, None),
    ("Ground citing a Model element is permitted",
     mut(lambda a: ground(a, citation="@agent_vega_pathway_v1#graph.node=eff_arid1a")),
     True, None),

    # ---- addresses and content verification (spec 1.8) ------------------------------
    ("csv column that does not exist", mut(lambda a: ground(
        a, citation="@agent_lyra_gdsc_v1.measurements#csv.row=HCC1143&col=nope")),
     False, "ADDRESS"),
    ("csv row that does not exist", mut(lambda a: ground(
        a, citation="@agent_lyra_gdsc_v1.measurements#csv.row=NOPE&col=ic50_z")),
     False, "ADDRESS"),
    ("a fabricated quote", mut(lambda a: obj(a, "g_quote").update(
        citation='@agent_lyra_chen2025_v1.results_text#text_span.quote="ARID1A silences CHK1"')),
     False, "ADDRESS"),
    ("a Content Object the Artifact does not declare", mut(lambda a: ground(
        a, citation="@agent_lyra_gdsc_v1.measurements#table.row=HCC1143")), False, "ADDRESS"),
    ("an address into an Artifact that does not exist", mut(lambda a: ground(
        a, citation="@agent_lyra_nowhere_v1.values#csv.row=X&col=Y")), False, "ADDRESS"),
    ("a whole-content address, with no reference string", mut(lambda a: ground(
        a, citation="@agent_lyra_gdsc_v1.measurements#csv")), True, None),
    ("a graph node that is not an Object of the Model", mut(lambda a: ground(
        a, citation="@agent_vega_pathway_v1#graph.node=eff_nope")), False, "ADDRESS"),
    ("a graph edge that the Model does not hold", mut(lambda a: ground(
        a, citation="@agent_vega_pathway_v1#graph.edge=eff_arid1a|restricts|stage_entry")),
     False, "ADDRESS"),
    ("a graph edge the Model does hold", mut(lambda a: ground(
        a, citation="@agent_vega_pathway_v1#graph.edge=eff_arid1a|restricts|stage_egress")),
     True, None),
    ("a graph reference naming neither node nor edge", mut(lambda a: ground(
        a, citation="@agent_vega_pathway_v1#graph.thing=x")), False, "ADDRESS"),

    # ---- provenance (spec 2.5) ------------------------------------------------------
    ("produced_by naming something that is not an Analysis", mut(
        lambda a: a["artifact"].update(produced_by="@agent_lyra_gdsc_v1"), base=OUTPUT),
     False, "TYPE"),
    ("produced_by naming an Artifact that does not exist", mut(
        lambda a: a["artifact"].update(produced_by="@agent_vega_nowhere_v1"), base=OUTPUT),
     False, "ADDRESS"),

    # ---- corpus-level rules (spec 1.5, 1.9) -----------------------------------------
    ("an Artifact citing one published later", mut(
        lambda a: a["artifact"].update(created="2026-08-01T09:30:00Z")), False, "ORDER"),
    ("an Artifact citing one created in the same instant", mut(
        lambda a: a["artifact"].update(created="2026-08-01T10:00:00Z")), False, "ORDER"),
    ("a name already in the record", mut(
        lambda a: a["artifact"].update(name="agent_lyra_gdsc_v1")), False, "UNIQUE"),
    ("a name without the account prefix", mut(
        lambda a: a["artifact"].update(name="arid1a")), False, "NAMING"),
    ("a hyphenated account prefix is accepted", mut(
        lambda a: a["artifact"].update(name="ndex-admin_arid1a_v1",
                                       published_by="@ndex-admin")), True, None),
    ("a name carrying an address delimiter", mut(
        lambda a: a["artifact"].update(name="agent_lyra_arid1a.v1")), False, "STRUCT"),
    ("the wrong specification version", mut(
        lambda a: a["artifact"].update(specification_version="6")), False, "STRUCT"),
    ("supersedes without a rationale", mut(lambda a: a["artifact"].update(
        supersedes=["@agent_vega_plan_v1"])), False, "STRUCT"),
    ("extracted_from without an extraction_method", mut(lambda a: a["artifact"].update(
        extracted_from="@agent_lyra_chen2025_v1")), False, "TYPE"),
    ("published_by that is not a bare Member address", mut(lambda a: a["artifact"].update(
        published_by="@agent_lyra.name")), False, "STRUCT"),
    ("an Object name colliding with a property of its Artifact", mut(
        lambda a: obj(a, "a_sub").update(name="authors")), False, "STRUCT"),
    ("two Objects sharing a name", mut(
        lambda a: a["objects"].append({"name": "g_csv", "type": "Assumption",
                                       "rationale": "duplicate"})), False, "STRUCT"),

    # ---- Content declarations (spec 1.8.1, 2.1) -------------------------------------
    ("groundable declared as a string rather than a boolean", mut(
        lambda a: obj(a, "csv").update(groundable="true"), base=DATA), False, "TYPE"),
    ("a Content Object without an addressing_method", mut(
        lambda a: obj(a, "csv").pop("addressing_method"), base=DATA), False, "TYPE"),
    ("a non-groundable Artifact type declaring groundable content", mut(
        lambda a: a["objects"].append(
            {"name": "text_span", "type": "Content", "groundable": True,
             "description": "the procedure", "addressing_method": 'quote="…"'}),
        base=ANALYSIS), False, "TYPE"),
    ("a rest method with no access_method", mut(
        lambda a: obj(a, "rest").pop("access_method"), base=EXTERNAL), False, "TYPE"),
    ("a Model may hold Objects and relationships of its own", MODEL, True, None),
]

# --------------------------------------------------------- independence (REVIEW only)
# (label, artifact, should_be_flagged)
def two_grounds(c1, c2, r1="first", r2="second"):
    def apply(a):
        a["objects"] = [o for o in a["objects"] if o["name"] not in ("g_quote", "u_invitro")]
        a["relationships"] = [r for r in a["relationships"]
                              if r["target"] not in ("g_quote", "u_invitro")]
        a["objects"] = [o for o in a["objects"] if o["name"] != "a_sub"]
        a["relationships"] = [r for r in a["relationships"] if r["target"] != "a_sub"]
        obj(a, "g_csv").update(citation=c1, rationale=r1)
        obj(a, "g_csv").pop("criterion", None)
        a["objects"].append({"name": "g_two", "type": "Ground", "citation": c2, "rationale": r2})
        a["relationships"].append({"rel": "grounded_by", "source": "a_primary", "target": "g_two"})
    return mut(apply)


INDEPENDENCE_CASES = [
    ("two Grounds on one Artifact are flagged as one source",
     two_grounds("@agent_lyra_gdsc_v1.measurements#csv.row=MCF7&col=ic50_z",
                 "@agent_lyra_gdsc_v1.measurements#csv.row=HCC1143&col=ic50_z"), True),
    ("two Grounds on distinct Artifacts descending from one Analysis are flagged",
     two_grounds("@agent_vega_joined_v1.values#csv.row=MCF7&col=ic50_z",
                 "@agent_vega_residuals_v1.values#csv.row=MCF7&col=residual"), True),
    ("genuinely independent sources are not flagged",
     two_grounds("@agent_lyra_gdsc_v1.measurements#csv.row=MCF7&col=ic50_z",
                 f'@agent_lyra_chen2025_v1.results_text#text_span.quote="{QUOTE}"'), False),
    ("BLIND SPOT: two imports of one external source cannot be detected, and are not flagged",
     two_grounds("@agent_lyra_gdsc_v1.measurements#csv.row=MCF7&col=ic50_z",
                 "@agent_lyra_depmap_v1#rest.query=ARID1A"), False),
]

# ------------------------------------------------------------- accepted, but reviewed
# (label, artifact, expected_review_check)
REVIEW_CASES = [
    ("a bare @name in prose is reviewed, not refused", mut(lambda a: a["artifact"].update(
        description="Revisits @agent_vega_plan_v1.")), "CITATION"),
    ("an @name inside a code span is NOT a citation and is not reviewed", mut(
        lambda a: a["artifact"].update(
            description="Addresses look like `@agent_vega_plan_v1.text#text_span.quote=\"x\"`.")),
     None),
    ("grounding on content outside the record is accepted and reviewed", mut(
        lambda a: ground(a, citation="@agent_lyra_depmap_v1#rest.query=ARID1A")), "GROUND"),
    ("a Content Object outside the standard set is reviewed", mut(
        lambda a: obj(a, "csv").update(name="table"), base=DATA), "TYPE"),
    ("an oversized embedded payload is reviewed, not refused", mut(
        lambda a: a["artifact"].update(measurements="cell_line,v\n" + "x,1\n" * 20000),
        base=DATA), "SIZE"),
]


# --------------------------------------------------------------------------- runner
def _without(art):
    """The record minus any entry sharing the candidate's name.

    A scenario that mutates a corpus member is asking about that member's own
    conformance, not about name reuse; leaving the original in place would fail every
    one of them on UNIQUE and hide what they were written to check. The pass/fail
    scenarios below exclude by IDENTITY instead, so that the uniqueness rule itself can
    still be tested by a mutation that deliberately takes a name already in the record.
    """
    name = art.get("artifact", {}).get("name")
    return [r for r in RECORD if r["artifact"]["name"] != name]


def run_scenarios(quiet=False):
    bad = 0
    for label, art, want_pass, want_check in CASES:
        record = [r for r in RECORD if r is not art]     # identity, so a name clash can fire
        got = validate(art, record, MEMBERS)
        ok = passed(got)
        checks = {x["check"] for x in got if x["level"] == "FAIL"}
        good = (ok == want_pass) and (want_check is None or want_check in checks)
        bad += not good
        if not good or not quiet:
            print(f"  [{'ok ' if good else 'BAD'}] {label}"
                  + ("" if good else f"  -> pass={ok} (want {want_pass}), "
                                     f"checks={sorted(checks)} (want {want_check})"))
        if not good:
            for x in got:
                print(f"          {x['level']:6} {x['check']:12} {x['msg'][:110]}")

    for label, art, want_flag in INDEPENDENCE_CASES:
        got = validate(art, _without(art), MEMBERS)
        flagged = any(x["check"] == "INDEPENDENCE" for x in got)
        good = passed(got) and flagged == want_flag
        bad += not good
        if not good or not quiet:
            print(f"  [{'ok ' if good else 'BAD'}] {label}"
                  + ("" if good else f"  -> flagged={flagged} (want {want_flag}), "
                                     f"passes={passed(got)}"))
        if not good:
            for x in got:
                print(f"          {x['level']:6} {x['check']:12} {x['msg'][:110]}")

    for label, art, want_check in REVIEW_CASES:
        got = validate(art, _without(art), MEMBERS)
        revs = {x["check"] for x in got if x["level"] == "REVIEW"}
        good = passed(got) and (want_check in revs if want_check else want_check not in revs)
        if want_check is None:
            good = passed(got) and "CITATION" not in revs
        bad += not good
        if not good or not quiet:
            print(f"  [{'ok ' if good else 'BAD'}] {label}"
                  + ("" if good else f"  -> passes={passed(got)}, reviews={sorted(revs)} "
                                     f"(want {want_check})"))
        if not good:
            for x in got:
                print(f"          {x['level']:6} {x['check']:12} {x['msg'][:110]}")

    total = len(CASES) + len(INDEPENDENCE_CASES) + len(REVIEW_CASES)
    return total - bad, total


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="section totals only")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(HERE))
    import check_refused
    import validate_record

    print("SCENARIOS — one mutation from a conformant corpus, asserting which check fires\n")
    ok, total = run_scenarios(a.quiet)
    print(f"\n{ok}/{total} scenarios behaved as specified\n")

    print("REFUSED FIXTURES — whole Artifacts, against the example record\n")
    rc_fix = check_refused.main([str(HERE.parent / "examples" / "refused"),
                                 str(HERE.parent / "examples" / "record")])

    print("\nTHE RECORD — every Artifact against everything published before it\n")
    rc_rec = validate_record.main([str(HERE.parent / "examples" / "record")])

    print("\nTHE GATE — publication units and acceptance order, offline\n")
    import test_gate
    rc_gate = test_gate.run()

    failed = (ok != total) or rc_fix or rc_rec or rc_gate
    print("\n" + "=" * 70)
    print("CONFORMANCE: " + ("FAILED" if failed else "everything behaved as specified"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
