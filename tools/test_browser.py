#!/usr/bin/env python3
"""Offline tests for the record browser.

    python test_browser.py

No network. Compiles the example records into a temporary directory and asserts properties
of the HTML, plus a handful of unit cases the example corpus does not happen to exercise.

THE INVARIANT THIS FILE EXISTS FOR. An address that resolves in the validator must land the
reader on the thing it names. That is the whole difference between a record you can check
and a record you can only read: a Ground says a number is in a cell, and the reader has to
be able to see that cell without taking the author's word for the address. When it breaks it
breaks SILENTLY — the validator still passes, the page still renders, the link still works,
and it goes to the top of the page instead of to the value. Four separate faults of exactly
that shape were found in one sitting on 2026-09-03:

  * cell ids were written under the literal method name `csv`, so an address through a
    Content named `pooled_csv` or `inventory_csv` landed nowhere;
  * tables were capped at 200 rows, so an address into row 400 of a 714-row table landed
    nowhere;
  * headings and list items skipped `_mark_grounded`, so a `text_span` quote falling on one
    landed nowhere;
  * the `code` property was rendered without marking at all.

Case A is the general guard: every Ground in both example records, checked against the
compiled page it addresses.

Case B guards the other silent renderer fault of that day, which corrupts values rather than
losing them. Prose was detected as CSV by "has a newline and a comma", so `import_method`
rendered as a table and `19,113 data rows` displayed as two cells. A reader cannot tell that
from looking; the page is confident and wrong.

Case C guards the Content Object section, which matched an Object type name from a
superseded draft and therefore matched nothing, silently omitting from every artifact page
the one section that says what may be cited and how to write the address.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import browse  # noqa: E402
import templates as T  # noqa: E402
from validate import parse_address  # noqa: E402

RECORDS = [HERE.parent / "examples" / "record",
           HERE.parent / "examples" / "manuscript_example"]

#: A fixture record, written fresh for each run, because the example records cannot see two
#: of the four faults this file guards: every Content in them is named `csv`, and their
#: largest table is 66 lines. Both faults were found in a live record whose Contents are
#: named `pooled_csv`, `control_rows_csv`, `inventory_csv` and whose tables run to 2,857
#: rows, and a test that only ever meets `csv` and 66 rows would have passed throughout.
#: So the fixture is deliberately the awkward case: a non-default method name, and a Ground
#: addressing a row far past any plausible display cap.
FIXTURE_ROWS = 400
FIXTURE_TARGET_ROW = 377


def fixture_record(root):
    rows = ["GeneSymbol,Effect,q"] + [
        f"gene{i:04d},{-0.01 * i:.6f},{0.5 if i % 3 else 0.02}" for i in range(FIXTURE_ROWS)]
    data = {
        "artifact": {
            "name": "fx_analyst_pooled_v1", "type": "Data", "specification_version": "1.0",
            "published_by": "@agent_fixture", "created": "2026-01-01T00:00:01+00:00",
            "authors": ["Someone Else"], "title": "Fixture: a long table behind a Content "
            "whose name is not `csv`",
            "import_method": "Rendered for the browser tests. Not a real study, and the "
            "first line of this property carries a comma, 4,364,823 of them, so that a "
            "renderer guessing at CSV by punctuation has something to trip over.",
            "pooled_effects": "\n".join(rows),
        },
        "objects": [{
            "name": "pooled_csv", "type": "Content", "groundable": True,
            "description": "The pooled table, held in the `pooled_effects` property.",
            "addressing_method": "`#pooled_csv.row=<GeneSymbol>&col=<column name>`. "
                                 "Line 1 is the header.",
        }],
        "relationships": [],
    }
    target = f"gene{FIXTURE_TARGET_ROW:04d}"
    arg = {
        "artifact": {
            "name": "fx_researcher_reach_v1", "type": "Argument",
            "specification_version": "1.0", "published_by": "@agent_fixture",
            "created": "2026-01-01T00:00:02+00:00", "authors": ["agent_fixture"],
            "title": "Fixture: a Ground reaching a cell far down a long table",
            "primary_assertion": "a_primary", "verdict": "Fixture.",
            "rationale": "Fixture.", "purpose": "To be reached.",
        },
        "objects": [
            {"name": "a_primary", "type": "Assertion",
             "claim": f"The effect recorded for {target} is negative.",
             "scope": "The fixture table as rendered."},
            {"name": "g_deep", "type": "Ground",
             "citation": f"@fx_analyst_pooled_v1.pooled_effects"
                         f"#pooled_csv.row={target}&col=Effect",
             "rationale": "Names one cell, several hundred rows down."},
        ],
        "relationships": [{"rel": "grounded_by", "source": "a_primary", "target": "g_deep"}],
    }
    root.mkdir(parents=True, exist_ok=True)
    for doc in (data, arg):
        (root / f'{doc["artifact"]["name"]}.json').write_text(json.dumps(doc, indent=1))
    return root

#: A second fixture, shaped like a community that works in rounds (c037_2): two ResearchGoals,
#: a plan, an analysis and its result, Arguments whose Grounds address a cell, a row, a whole
#: table and a quoted passage, testimony, a Message, and one artifact serving both goals. Two
#: artifacts exist to trip a browser that places by NAME rather than by address (N4):
#: `fx_goal_two_notes` serves no goal whatever it is called, and `fx_misfiled` names in
#: `serves_goals` something that is not a goal. Neither may land in a goal's column.
ROUNDS_EXPECTED = {"corpus": {"fx_goal_one", "fx_import_table", "fx_goal_two",
                              "fx_goal_two_notes", "fx_misfiled"},
                   "fx_goal_one": {"fx_plan_one", "fx_analysis_one", "fx_result_one",
                                   "fx_arg_one", "fx_closing"},
                   "fx_goal_two": {"fx_arg_two", "fx_msg", "fx_closing"}}


def rounds_fixture_record(root):
    def art(name, typ, t, member, **props):
        return {"artifact": {"name": name, "type": typ, "specification_version": "1.0",
                             "published_by": f"@{member}",
                             "created": f"2026-02-01T00:{t:02d}:00+00:00",
                             "title": props.pop("title", f"Fixture {name}"), **props},
                "objects": props.pop("objects", None) or [], "relationships": []}

    def goal(name, t, title):
        d = art(name, "ResearchGoal", t, "lead", title=title, groundable=False,
                text=f"{title} Asked for the browser tests.")
        d["objects"] = [{"name": "goal_text", "type": "Content", "groundable": False,
                         "description": "The goal, in `text`.",
                         "addressing_method": '`quote="<exact text>"` against `text`.'}]
        return d

    imp = art("fx_import_table", "Data", 2, "lead", import_method="Written for the tests.",
              measures="key,a,b,c\nk1,1,2,3\nk2,4,5,6\nk3,7,8,9",
              text="The source says a load-bearing sentence here, and nothing else.")
    imp["objects"] = [
        {"name": "measures_csv", "type": "Content", "groundable": True,
         "description": "The table in `measures`.",
         "addressing_method": "`row=<key>&col=<column>`; no reference names the whole table."},
        {"name": "text_span", "type": "Content", "groundable": True,
         "description": "The `text` property.", "addressing_method": '`quote="<exact text>"`.'}]
    result = art("fx_result_one", "Data", 5, "analyst", produced_by="@fx_analysis_one",
                 serves_goals=["@fx_goal_one"], effects="row,effect,p\nr1,0.5,0.01\nr2,0.1,0.4")
    result["objects"] = [{"name": "effects_csv", "type": "Content", "groundable": True,
                          "description": "The table in `effects`.",
                          "addressing_method": "`row=<row>&col=<column>`."}]

    arg1 = art("fx_arg_one", "Argument", 6, "analyst", serves_goals=["@fx_goal_one"],
               primary_assertion="a_primary", verdict="It holds where tested. Not beyond.",
               purpose="Round one.", rationale="See the Grounds.")
    arg1["objects"] = [
        {"name": "a_primary", "type": "Assertion", "claim": "The effect is positive.",
         "scope": "The fixture."},
        {"name": "g_cell", "type": "Ground", "criterion": "Counts against if effect <= 0.",
         "citation": "@fx_result_one.effects#effects_csv.row=r1&col=effect", "rationale": "A cell."},
        {"name": "g_row", "type": "Ground", "citation": "@fx_import_table.measures#measures_csv.row=k2",
         "rationale": "A whole row."},
        {"name": "g_table", "type": "Ground", "criterion": "Counts against if any row is negative.",
         "citation": "@fx_import_table.measures#measures_csv", "rationale": "The whole table."},
        {"name": "g_quote", "type": "Ground", "rationale": "A passage.",
         "citation": '@fx_import_table.text#text_span.quote="a load-bearing sentence"'}]
    arg1["relationships"] = [{"rel": "grounded_by", "source": "a_primary", "target": g}
                             for g in ("g_cell", "g_row", "g_table", "g_quote")]

    arg2 = art("fx_arg_two", "Argument", 8, "critic", serves_goals=["@fx_goal_two"],
               supersedes=["@fx_arg_one"], primary_assertion="a_primary",
               verdict="It holds, more narrowly.", purpose="Round two.",
               rationale="Builds on [the effects](@fx_result_one) and on the first verdict.")
    arg2["objects"] = [
        {"name": "a_primary", "type": "Assertion", "claim": "The effect is positive in r1 only.",
         "scope": "The fixture."},
        {"name": "g_prior", "type": "Ground", "citation": "@fx_arg_one.a_primary",
         "rationale": "Takes the first Argument's conclusion as testimony."}]
    arg2["relationships"] = [{"rel": "grounded_by", "source": "a_primary", "target": "g_prior"}]

    docs = [
        goal("fx_goal_one", 1, "Does the effect hold?"), imp,
        art("fx_plan_one", "AnalysisPlan", 3, "lead", serves_goals=["@fx_goal_one"],
            groundable=False, text="Plan: one analysis."),
        art("fx_analysis_one", "Analysis", 4, "analyst", serves_goals=["@fx_goal_one"],
            inputs=["@fx_import_table"], procedure="Compute the effect.", code="effect = a - b"),
        result, arg1, goal("fx_goal_two", 7, "Does it hold more narrowly?"), arg2,
        art("fx_msg", "Message", 9, "lead", serves_goals=["@fx_goal_two"],
            recipients=["@critic"], text="Please read [the second verdict](@fx_arg_two)."),
        art("fx_closing", "Message", 10, "lead", serves_goals=["@fx_goal_one", "@fx_goal_two"],
            recipients=["@analyst", "@critic"], text="Both goals have verdicts."),
        art("fx_goal_two_notes", "NonGroundable", 11, "lead", text="Notes, serving nothing."),
        art("fx_misfiled", "NonGroundable", 12, "lead", serves_goals=["@fx_import_table"],
            text="Names a table where a goal belongs."),
    ]
    root.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (root / f'{doc["artifact"]["name"]}.json').write_text(json.dumps(doc, indent=1))
    return root


def lineage_fixture_record(root):
    """Two lines of Arguments shaped like c037_2's R1 and R2 (F3): prose citations that skip a
    generation (R1″ cites R1 beside R1′) and one that crosses lines (R2″ cites R1″). Then what
    c037_2 has none of: a successor that supersedes, which outranks a prose citation; a Ground
    under the primary Assertion, which links; and a Ground under another Assertion, which
    does not."""
    def arg(name, t, rationale="", **props):
        objs = props.pop("objects", [])
        rels = props.pop("relationships", [])
        return {"artifact": {"name": name, "type": "Argument", "specification_version": "1.0",
                             "published_by": "@lx", "title": f"Fixture {name}",
                             "created": f"2026-03-01T00:{t:02d}:00+00:00",
                             "primary_assertion": "a_primary", "purpose": "Lineage.",
                             "verdict": f"{name} holds. More follows.", "rationale": rationale,
                             **props},
                "objects": [{"name": "a_primary", "type": "Assertion",
                             "claim": f"Claim made by {name}.", "scope": "The fixture."}, *objs],
                "relationships": rels}

    data = {"artifact": {"name": "lx_data", "type": "Data", "specification_version": "1.0",
                         "published_by": "@lx", "title": "Fixture lx_data",
                         "created": "2026-03-01T00:01:00+00:00",
                         "import_method": "Written for the tests.", "measures": "key,a\nk1,1"},
            "objects": [{"name": "measures_csv", "type": "Content", "groundable": True,
                         "description": "The table in `measures`.",
                         "addressing_method": "`row=<key>&col=<column>`."}],
            "relationships": []}
    docs = [
        data,
        arg("lx_r1", 2, "Opens line one.",
            objects=[{"name": "g_data", "type": "Ground", "criterion": "Against if a <= 0.",
                      "citation": "@lx_data.measures#measures_csv.row=k1",
                      "rationale": "The row."}],
            relationships=[{"rel": "grounded_by", "source": "a_primary", "target": "g_data"}]),
        arg("lx_r2", 3, "Opens line two."),
        arg("lx_r1p", 4, "Narrows [R1](@lx_r1)."),
        arg("lx_r2p", 5, "Re-runs [R2](@lx_r2)."),
        arg("lx_r1pp", 6, "Tests [R1](@lx_r1) and [R1 prime](@lx_r1p)."),
        arg("lx_r2pp", 7, "From [R2](@lx_r2), [R2 prime](@lx_r2p) and [R1 second](@lx_r1pp)."),
        arg("lx_r1ppp", 8, "Checks [R1 second](@lx_r1pp).",
            objects=[{"name": "a_side", "type": "Assertion", "claim": "A side remark.",
                      "scope": "The fixture."},
                     {"name": "g_side", "type": "Ground", "citation": "@lx_r2pp.a_primary",
                      "rationale": "Under the side Assertion, not the primary."}],
            relationships=[{"rel": "grounded_by", "source": "a_side", "target": "g_side"}]),
        arg("lx_r3", 9, "Also see [R1 third](@lx_r1ppp).", supersedes=["@lx_r2pp"],
            supersedes_rationale="Narrows it."),
        arg("lx_r4", 10, "Rests on the third.",
            objects=[{"name": "g_prior", "type": "Ground", "citation": "@lx_r1ppp.a_primary",
                      "rationale": "Testimony, under the primary Assertion."}],
            relationships=[{"rel": "grounded_by", "source": "a_primary", "target": "g_prior"}]),
    ]
    root.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (root / f'{doc["artifact"]["name"]}.json').write_text(json.dumps(doc, indent=1))
    return root


#: The lines lineage_fixture_record's Arguments make, and the links drawn between them:
#: (earlier, later) -> the kind it is drawn as. R1″ -> R1 and R2″ -> R2 are implied by a longer
#: chain and not drawn; R1‴'s Ground under a side Assertion is no link at all.
LINEAGE_EXPECTED = [["lx_r1", "lx_r1p", "lx_r1pp", "lx_r1ppp", "lx_r4"],
                    ["lx_r2", "lx_r2p", "lx_r2pp", "lx_r3"]]
LINEAGE_DRAWN = {
    ("lx_r1", "lx_r1p"): "cites", ("lx_r1p", "lx_r1pp"): "cites",
    ("lx_r1pp", "lx_r1ppp"): "cites", ("lx_r1ppp", "lx_r4"): "ground",
    ("lx_r2", "lx_r2p"): "cites", ("lx_r2p", "lx_r2pp"): "cites", ("lx_r2pp", "lx_r3"): "supersedes",
    ("lx_r1pp", "lx_r2pp"): "cites", ("lx_r1ppp", "lx_r3"): "cites",
}


def renamed_copy(src, dst):
    """The same record with every artifact given an opaque name, every address rewritten to
    match. Everything derived from addresses must come out the same; anything that differs
    was read from a name (N4)."""
    docs = [json.loads(p.read_text()) for p in sorted(src.glob("*.json"))
            if not p.name.startswith(".")]
    names = sorted((d["artifact"]["name"] for d in docs), key=len, reverse=True)
    new = {n: f"zz{i:03d}" for i, n in enumerate(sorted(names))}
    pattern = re.compile(r"@(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9_])")
    dst.mkdir(parents=True, exist_ok=True)
    for d in docs:
        text = pattern.sub(lambda m: "@" + new[m.group(1)], json.dumps(d))
        d2 = json.loads(text)
        d2["artifact"]["name"] = new[d["artifact"]["name"]]
        (dst / f'{d2["artifact"]["name"]}.json').write_text(json.dumps(d2, indent=1))
    return new


#: Which addresses the browser is expected to anchor, decided from the REFERENCE and never
#: from the method's name. A Content Object may be called anything — this record's are
#: `pooled_csv`, `control_rows_csv`, `inventory_csv` — and a check that looked for the name
#: `csv` would have been blind to the fault that shipped, which is that cell ids were
#: written under `csv` whatever the Content was called. `rest` names content held outside
#: the record and `graph` addresses a Model's nodes and edges; neither has a page rendering
#: yet, so a Ground through one is expected not to land.
ANCHORED_REF = re.compile(r"\brow=|\bquote=|^col=[^&]*$")


def anchored(p):
    """Does the browser anchor what this parsed address names? A cell, a row, a column or a
    quoted passage; or a whole property of an artifact page (`@x.prop#content`, no reference),
    which lands on that property's heading."""
    if p["ref"]:
        return bool(ANCHORED_REF.search(p["ref"]))
    return bool(p["method"] and p["segs"])


def compile_all(tmp):
    out = {}
    for rec in RECORDS + [fixture_record(tmp / "_fixture_record"),
                          rounds_fixture_record(tmp / "_rounds_record"),
                          lineage_fixture_record(tmp / "_lineage_record")]:
        d = tmp / ("build_" + rec.name)
        browse.compile_record(str(rec), str(d), quiet=True)
        out[rec] = d
    return out


def _docs(rec):
    return [json.loads(fn.read_text()) for fn in sorted(rec.glob("*.json"))
            if not fn.name.startswith(".")]


def case_a_grounds_land(dists):
    """Every Ground whose target the browser anchors must find its anchor: a cell, and since
    phase 2 a whole row, a whole column and a whole table, which on c037_2 were 73 of its 82
    Grounds and landed at the top of the page."""
    bad, total = [], 0
    for rec, dist in dists.items():
        types = {d["artifact"]["name"]: d["artifact"]["type"] for d in _docs(rec)}
        for doc in _docs(rec):
            for o in doc.get("objects", []):
                if o.get("type") != "Ground":
                    continue
                p = parse_address(o.get("citation", ""))
                if not p or not anchored(p) or types.get(p["root"]) == "Argument":
                    continue
                total += 1
                page = dist / browse.page_name(p["root"])
                frag = html.escape(browse.address_fragment(o["citation"]))
                if not (page.is_file() and f'id="{frag}"' in page.read_text()):
                    bad.append(f'{doc["artifact"]["name"]}.{o["name"]} -> {frag[:70]}')
    return (not bad, f"{total - len(bad)}/{total} Grounds land on the content they name", bad)


def case_b_prose_is_not_a_table(dists):
    """No prose property may be rendered as a table.

    Checked structurally rather than by eye: a property that reached `csv_table` announces
    itself with the "Addressed as" hint, so any long prose property whose text appears
    inside a `<table class='data'>` is the fault recurring."""
    bad = 0
    checks = [
        # (value, declares a row/col Content, should render as a table)
        ("SOURCE. Nature Communications 2025, doi 10.1038/x, PMID 41372121.\n"
         "FILE. One workbook, 4,364,823 bytes, holding 19,113 data rows.", True, False),
        ("An import that anchors the corpus, with three matrices behind download.\n"
         "What is rendered here is every row whose identifier is not a gene symbol.",
         True, False),
        ("Vega, copied to Rigel.\nI have read your message, and I checked your numbers.",
         False, False),
        ("key,fdr_lt_0.10,control_rank\nDENV_pos,15,148\nCHIKV_pos,6,9012", True, True),
        ("key,fdr_lt_0.10\nDENV_pos,15\nCHIKV_pos,6", False, False),   # nothing declared
    ]
    for value, declares, want in checks:
        got = browse.looks_tabular(value, declares)
        if got != want:
            bad += 1
            print(f"         {'rendered as a table' if got else 'rendered as prose'}, "
                  f"wanted the other: {value.splitlines()[0][:60]!r}")
    return (not bad, f"{len(checks) - bad}/{len(checks)} prose/table decisions correct", [])


def case_c_content_section(dists):
    """Every artifact declaring a Content Object shows how to reach its content."""
    missing = []
    for rec, dist in dists.items():
        for fn in sorted(rec.glob("*.json")):
            if fn.name.startswith("."):
                continue
            doc = json.loads(fn.read_text())
            if doc["artifact"]["type"] == "Argument":
                continue                          # claim map, not an artifact page
            if not any(o.get("type") == "Content" for o in doc.get("objects", [])):
                continue
            page = dist / browse.page_name(doc["artifact"]["name"])
            if "How to reach this content" not in page.read_text():
                missing.append(doc["artifact"]["name"])
    return (not missing, f"{'no' if not missing else len(missing)} artifact(s) hide their "
            f"Content Objects", missing)


def case_d_marking_paths(dists):
    """A grounded quote is marked wherever it falls, not only in a paragraph.

    The example corpus grounds only on plain paragraphs, so these are the paths it cannot
    tell you about. Each is a real fault that shipped."""
    spans = [("the load-bearing phrase", "agent_x_arg_v1")]
    anchor = 'id="text_span.quote=&quot;the load-bearing phrase&quot;"'
    paths = {
        "paragraph": T.md_to_html("Body with the load-bearing phrase in it.", {}, spans),
        "heading": T.md_to_html("## the load-bearing phrase", {}, spans),
        "list item": T.md_to_html("- the load-bearing phrase", {}, spans),
        "code": T.preformatted("x = 1  # the load-bearing phrase", spans),
    }
    bad = [k for k, v in paths.items() if anchor not in v]
    return (not bad, f"{len(paths) - len(bad)}/{len(paths)} rendering paths anchor a "
            f"grounded quote", bad)


def case_e_quoted_commas(dists):
    """A quoted field holding a comma is one cell, and the cells to its right keep their id.

    Splitting on commas shifted every later cell by a column, so an anchor named the right
    address and held the wrong value — the failure that looks correct."""
    csv = ('study,universe,note\n'
           's15,"19113 genes per arm, identifier sets identical bar one",matched\n')
    out = T.csv_table(csv, method="csv")
    want_cell = "19113 genes per arm, identifier sets identical bar one"
    want_id = 'id="csv.row=s15&amp;col=note"'
    bad = []
    if want_cell not in out:
        bad.append("quoted field was split")
    if want_id not in out or f'{want_id}>matched<' not in out:
        bad.append("column after the quoted field carries the wrong value")
    return (not bad, "quoted commas keep their cell and their neighbours' ids", bad)


def plain_run(md, least=40):
    """The longest stretch of a property that survives markdown rendering unchanged.

    Comparing against a raw prefix is wrong: a `rationale` that opens with a markdown link
    is rendered as an anchor and the prefix never appears. What must appear is the prose
    between the markup."""
    runs = [s.strip() for s in re.split(r"[\[\]()*`#\n]+", md)]
    runs = [s for s in runs if len(s) >= least]
    return max(runs, key=len) if runs else ""


def case_f_argument_is_readable(dists):
    """Every Argument's prose has a page that scrolls, carrying all of it.

    The claim map once put prose in a fixed 96-pixel strip beside the graph; on this record's
    one Argument that was 95 pixels of 26,019, so the verdict, purpose and rationale an
    author is required to write were four tenths of one per cent visible. A reader must be
    able to reach all of it without scrolling a letterbox. (The claim map now shows the
    verdict whole, case M; the reading page is still where all of it reads in one place.)"""
    bad = []
    for rec, dist in dists.items():
        for fn in sorted(rec.glob("*.json")):
            if fn.name.startswith("."):
                continue
            doc = json.loads(fn.read_text())
            h = doc["artifact"]
            if h["type"] != "Argument":
                continue
            page = dist / browse.page_name(h["name"]).replace(".html", "_reading.html")
            if not page.is_file():
                bad.append(f'{h["name"]}: no reading page')
                continue
            text = page.read_text()
            for key in ("verdict", "purpose", "rationale"):
                probe = plain_run(h.get(key) or "")
                if probe and html.escape(probe) not in text:
                    bad.append(f'{key} of {h["name"]} not on the reading page')
            if any(o.get("type") == "Ground" for o in doc.get("objects", [])) \
                    and "What this Argument stands on" not in text:
                bad.append(f'{h["name"]}: Grounds not tabulated')
    return (not bad, f"{'every' if not bad else 'not every'} Argument's prose and evidence "
            f"are on a page that scrolls", bad)


_STRUCTURAL_RELS = {"produced_by", "inputs", "grounded_by", "testimony", "cites",
                    "extracted_from", "used_models"}


def _overview_of(rec):
    """Rebuild the overview elements for a record directory.

    This must read the sidecar exactly as compile_record does — positions AND annotations —
    or a test passes against a build path no reader ever sees.
    """
    arts = browse.load_record(str(rec))
    colors = browse.member_colors(arts)
    index = browse.build_index(arts)
    pages = {a["artifact"]["name"]: browse.page_name(a["artifact"]["name"]) for a in arts}
    findings = browse.run_validator(arts, set(colors))
    pins = browse.load_pins(str(rec))
    annotations = browse.load_annotations(str(rec))
    return browse.build_overview(arts, index, colors, pages, findings,
                                 pins=pins, annotations=annotations)


def case_g_citation_edges_span_columns(dists):
    """A citing artifact is never drawn in the same column as one it cites.

    This is the layout rule the overview exists to honour. When position came from
    publication time, a whole round shared one x and its citation edges ran vertically
    through a stack of unrelated nodes — visible in the picture as lines that could not be
    followed. Nothing but a test keeps that from coming back, because the failure is
    invisible to every other check: the record is valid either way.
    """
    bad, total = [], 0
    for rec in dists:
        elements, _meta = _overview_of(rec)
        pos = {n["data"]["id"]: n["data"]["_pos"] for n in elements["nodes"]}
        for e in elements["edges"]:
            d = e["data"]
            if d["rel"] not in _STRUCTURAL_RELS or d["source"] == d["target"]:
                continue
            s, t = pos.get(d["source"]), pos.get(d["target"])
            if not (s and t):
                continue
            total += 1
            dx = abs(s["x"] - t["x"])
            if dx < browse._MIN_DX - 0.5:
                bad.append(f"{rec.name}: {d['source']} --{d['rel']}--> {d['target']} "
                           f"dx={dx:.0f} < {browse._MIN_DX:.0f}")
    return (not bad, f"{total - len(bad)}/{total} citation edges clear the minimum column gap",
            bad)


def case_h_pins_survive_a_rebuild(dists):
    """A hand-placed node stays where it was put, and a bad pin file cannot break the build.

    Manual arrangement used to be lost on every rebuild. The sidecar is also hand-editable,
    so the malformed case is part of the contract: a typo in a viewing preference must cost
    the arrangement and nothing else.
    """
    bad = []
    rec = sorted(dists)[0]
    sidecar = pathlib.Path(rec) / browse.PIN_FILE
    saved = sidecar.read_text() if sidecar.is_file() else None
    try:
        elements, _ = _overview_of(rec)
        first = elements["nodes"][0]["data"]["id"]
        sidecar.write_text(json.dumps({"positions": {first: {"x": 4242.0, "y": -777.0}}}))
        elements, meta = _overview_of(rec)
        got = {n["data"]["id"]: n["data"] for n in elements["nodes"]}[first]
        if got["_pos"] != {"x": 4242.0, "y": -777.0}:
            bad.append(f"pinned node moved: {got['_pos']}")
        if not got.get("_pinned"):
            bad.append("pinned node not marked _pinned")
        if meta["counts"].get("pinned") != 1:
            bad.append(f"pinned count {meta['counts'].get('pinned')} != 1")

        sidecar.write_text("{ not json at all")
        elements, meta = _overview_of(rec)
        if len(elements["nodes"]) != len(got and elements["nodes"]):
            bad.append("node count changed on malformed pin file")
        if meta["counts"].get("pinned"):
            bad.append("malformed pin file still reported pins")
        # and the validator must not choke on it either
        if browse.load_pins(str(rec)) != {}:
            bad.append("malformed pin file did not degrade to no pins")
    finally:
        if saved is None:
            sidecar.unlink(missing_ok=True)
        else:
            sidecar.write_text(saved)
    return (not bad, "a pinned position survives a rebuild; a malformed sidecar does not "
                     "break one", bad)


def case_i_claim_positions_restore_on_load(dists):
    """An Argument page restores hand-moved nodes on a plain load, not only on a mode switch.

    The first version of this feature applied saved positions inside runLayout(), which only
    the three mode buttons call. The FIRST layout is run by the cytoscape() constructor, so a
    refresh — the case that matters — silently showed the computed arrangement and the reader's
    work looked lost. The page must therefore apply saved positions on load as well.

    Checked by reading the generated page rather than by driving a browser: the suite runs
    without a headless Chrome, and what regressed was the presence of the initial-apply call.
    """
    bad, checked = [], 0
    for rec, dist in dists.items():
        for a in browse.load_record(str(rec)):
            h = a["artifact"]
            if h["type"] != browse.ARGUMENT:
                continue
            page = pathlib.Path(dist) / browse.page_name(h["name"])
            if not page.is_file():
                continue
            txt = page.read_text(encoding="utf-8")
            checked += 1
            if "dragfree" not in txt:
                bad.append(f"{h['name']}: no dragfree handler — drags are never captured")
            if "initSavedPos" not in txt:
                bad.append(f"{h['name']}: no initial apply — a refresh would drop saved positions")
            # the initial apply must not be reachable only from the mode buttons
            if "applySavedPos" in txt and txt.count("applySavedPos") < 2:
                bad.append(f"{h['name']}: applySavedPos called once; load path likely missing")
    return (not bad, f"{checked} Argument page(s) restore hand-moved nodes on load", bad)


def case_j_internal_structure_is_shown(dists):
    """An Artifact that contains Objects and relationships shows them.

    The specification's structural claim is that an Artifact IS a property graph (spec 1.7).
    An Argument's graph is drawn by its claim map; for every other type it was drawn nowhere,
    so a Model published as thirteen nodes and fifteen edges rendered as prose with its own
    node names absent from the page — while its `graph` Content told readers to address
    `node=<name>`. A reader could not see that the names existed.

    Also checks the two ways this can go wrong in the other direction: an artifact with only
    Content Objects must NOT get an empty graph pane, and an Argument must keep using its
    claim map rather than growing a second, redundant graph.
    """
    bad, drawn = [], 0
    for rec, dist in dists.items():
        for a in browse.load_record(str(rec)):
            h = a["artifact"]
            page = pathlib.Path(dist) / browse.page_name(h["name"])
            if not page.is_file():
                continue
            txt = page.read_text(encoding="utf-8")
            structural = [o for o in a.get("objects", []) if o.get("type") != "Content"]
            if h["type"] == browse.ARGUMENT:
                if 'id="og"' in txt:
                    bad.append(f"{h['name']}: Argument grew a second graph; the claim map owns it")
                continue
            if structural:
                drawn += 1
                if 'id="og"' not in txt:
                    bad.append(f"{h['name']}: {len(structural)} Object(s) and no internal graph")
                    continue
                if "cytoscape.min.js" not in txt:
                    bad.append(f"{h['name']}: graph emitted but cytoscape never loaded")
                for o in structural:
                    if '"' + o["name"] + '"' not in txt:
                        bad.append(f"{h['name']}: Object {o['name']} absent from its own page")
                        break
            elif 'id="og"' in txt:
                bad.append(f"{h['name']}: empty graph pane on an artifact with no Objects")
    return (not bad, f"{drawn} artifact(s) with internal structure draw it", bad)


def case_k_annotations_are_not_artifacts(dists):
    """A presenter caption is drawn, and is not mistaken for something the community published.

    Captions let a presenter write "more analytic work not shown" where a section of the graph
    has been hidden. They live in the same sidecar as the manual positions, carry no address,
    and nothing can cite one. The risk is not that they fail to draw; it is that they are
    counted, clicked or cited as if they were artifacts, so that is what this checks.
    """
    bad = []
    rec = sorted(dists)[0]
    sidecar = pathlib.Path(rec) / browse.PIN_FILE
    saved = sidecar.read_text() if sidecar.is_file() else None
    try:
        sidecar.write_text(json.dumps({"annotations": [
            {"text": "more analytic work not shown", "x": 10.0, "y": 20.0},
            {"text": "no coordinates"},                       # malformed, must be dropped
            {"text": "   ", "x": 1, "y": 2},                  # empty, must be dropped
        ]}))
        anns = browse.load_annotations(str(rec))
        if len(anns) != 1:
            bad.append(f"expected 1 usable annotation, got {len(anns)}")
        elements, meta = _overview_of(rec)
        ann = [n for n in elements["nodes"] if n["data"].get("ntype") == "Annotation"]
        if len(ann) != 1:
            bad.append(f"{len(ann)} annotation node(s) emitted, expected 1")
        arts = browse.load_record(str(rec))
        if meta["counts"]["artifacts"] != len(arts):
            bad.append("annotation counted among the artifacts")
        ids = {n["data"]["id"] for n in elements["nodes"]}
        for e in elements["edges"]:
            if e["data"]["source"] in ids and e["data"]["source"].startswith("__annotation"):
                bad.append("an edge starts at an annotation")
            if e["data"]["target"].startswith("__annotation"):
                bad.append("an edge ends at an annotation")
        if ann and ann[0]["data"].get("nav_file"):
            bad.append("annotation carries a nav_file and would navigate somewhere")
        # a malformed sidecar must cost the captions and nothing else
        sidecar.write_text("{ not json")
        if browse.load_annotations(str(rec)) != []:
            bad.append("malformed sidecar did not degrade to no annotations")
    finally:
        if saved is None:
            sidecar.unlink(missing_ok=True)
        else:
            sidecar.write_text(saved)
    return (not bad, "a caption is drawn, uncounted, unlinked and uncitable", bad)


def _storage_unwrapped(page_text):
    """Lines of a page's script that touch localStorage outside a try. Storage throws outright
    in some privacy modes, and a page that cannot remember a preference must still work."""
    code = (ln.strip() for ln in page_text.splitlines())
    return [ln for ln in code
            if "localStorage." in ln and "try" not in ln and not ln.startswith(("//", "/*", "*"))]


def case_l_overview_hides_context_links_by_default(dists):
    """The overview starts with `cites` and Messages hidden, and says how it lays the record out.

    At 74 artifacts, 323 of c037_2's 404 derived edges were prose citations: context, not
    evidence, and drawn by default they buried the 81 edges that carry the evidential
    structure. With them hidden, c037_2's 22 Messages, whose 96 edges were all `cites`, were a
    third of the nodes and connected to nothing, so they start hidden too. The defaults live in
    the build (meta.default_hidden_rels, meta.default_hidden_types) so this test and the page
    read one value. The caption once said columns ran in publication order while the code laid
    them out by citation depth; a reader was told how to read a picture it was not.
    """
    want = {"default_hidden_rels": ["cites"], "default_hidden_types": ["Message"]}
    bad, checked = [], 0
    for rec, dist in dists.items():
        elements, meta = _overview_of(rec)
        page = (pathlib.Path(dist) / "index.html").read_text(encoding="utf-8")
        checked += 1
        data = json.loads(re.search(
            r'<script id="graph-data" type="application/json">(.*?)</script>', page, re.S).group(1))
        for key, value in want.items():
            if meta.get(key) != value:
                bad.append(f"{rec.name}: {key} is {meta.get(key)!r}, want {value!r}")
            if data["meta"].get(key) != value:
                bad.append(f"{rec.name}: the compiled page does not carry {key}")
            if f"DATA.meta.{key}" not in page:
                bad.append(f"{rec.name}: the page never reads the {key} it carries")
        for kind in ("mem", "type", "rel"):
            if f"chip('{kind}'" not in page:
                bad.append(f"{rec.name}: no legend toggle for {kind}")
        if 'data-ctx="show"' not in page or "DEFAULTS.forEach" not in page:
            bad.append(f"{rec.name}: no one-click restore for what starts hidden")
        header = re.search(r'<div class="sub">(.*?)</div>', page, re.S).group(1)
        if "citation depth" not in header or "publication order" in header:
            bad.append(f"{rec.name}: the caption does not describe the citation-depth layout")
        if "Messages" not in header:
            bad.append(f"{rec.name}: the caption does not say Messages start hidden")
        bad += [f"{rec.name}: unwrapped storage access: {ln[:80]}"
                for ln in _storage_unwrapped(page)]
    return (not bad, f"{checked} overview(s) start with cites and Messages hidden and describe "
            "their layout", bad)


_CAPPED = re.compile(r"max-height|overflow(-y)?\s*:\s*(auto|hidden|scroll)")


def case_m_verdict_is_never_height_capped(dists):
    """On an Argument's claim map, the whole verdict is shown, outside any height-capped box.

    The verdict, purpose and rationale once shared a 96px strip that scrolled; on c037_2's
    R1'' that showed about two lines of the verdict, the one thing a reader opens the page
    for. The verdict must sit in no box whose height is capped, purpose and rationale in
    sections a reader opens, and one control must expand the pane to its full height.

    Checked by reading the compiled page: the rules for the verdict's own box and each box
    around it (#intro, #verdictpanel, .vtext) must set no max-height and no scrolling overflow.
    """
    bad, checked = [], 0
    for rec, dist in dists.items():
        for a in browse.load_record(str(rec)):
            h = a["artifact"]
            if h["type"] != browse.ARGUMENT or not (h.get("verdict") or "").strip():
                continue
            page = (pathlib.Path(dist) / browse.page_name(h["name"])).read_text(encoding="utf-8")
            checked += 1
            verdict = html.escape(h["verdict"].strip())
            if f'<div class="vtext">{verdict}</div>' not in page:
                bad.append(f"{h['name']}: the verdict is not shown whole in the verdict pane")
            css = re.sub(r"/\*.*?\*/", "", re.search(r"<style>(.*?)</style>", page, re.S).group(1),
                         flags=re.S)
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                subjects = {part.strip().split()[-1] for part in sel.split(",") if part.strip()}
                if subjects & {"#intro", "#verdictpanel", ".vtext"} and _CAPPED.search(body):
                    bad.append(f"{h['name']}: '{sel.strip()}' caps the box the verdict is in")
            for key, label in (("purpose", "Purpose and stakes"), ("rationale", "Rationale")):
                if (h.get(key) or "").strip() and \
                        f'<details class="vsec"><summary>{label}</summary>' not in page:
                    bad.append(f"{h['name']}: {key} is not in a section a reader opens")
            if 'id="btn-intro"' not in page or 'aria-expanded="false"' not in page:
                bad.append(f"{h['name']}: no Expand control for the verdict pane")
            bad += [f"{h['name']}: unwrapped storage access: {ln[:80]}"
                    for ln in _storage_unwrapped(page)]
    return (not bad, f"{checked} Argument page(s) show the whole verdict, uncapped", bad)


def _page_of(dist, doc):
    """The page that carries an artifact's "Cited by": its own, or an Argument's reading page."""
    page = browse.page_name(doc["artifact"]["name"])
    if doc["artifact"]["type"] == "Argument":
        page = page.replace(".html", "_reading.html")
    return (dist / page).read_text()


def _cited_by(text):
    return text[text.index('id="cited-by"'):] if 'id="cited-by"' in text else ""


def case_n_cited_by_matches_a_direct_count(dists):
    """Every artifact's "Cited by" lists exactly the Grounds that address it (R1).

    The count is made directly from the record, Ground by Ground, and compared with the rows on
    the compiled page; on the rounds fixture the other relations must each have their group."""
    bad, pages, grounds = [], 0, 0
    for rec, dist in dists.items():
        docs = _docs(rec)
        names = {d["artifact"]["name"] for d in docs}
        want = {n: 0 for n in names}
        for d in docs:
            for o in d.get("objects", []):
                p = parse_address(o.get("citation", "")) if o.get("type") == "Ground" else None
                if p and p["root"] in names and p["root"] != d["artifact"]["name"]:
                    want[p["root"]] += 1
        for d in docs:
            text = _cited_by(_page_of(dist, d))
            pages += 1
            if not text:
                bad.append(f'{rec.name}/{d["artifact"]["name"]}: no "Cited by" section')
                continue
            got = text.count('<tr id="cb-')
            grounds += got
            if got != want[d["artifact"]["name"]]:
                bad.append(f'{rec.name}/{d["artifact"]["name"]}: {got} Ground row(s), the record '
                           f'has {want[d["artifact"]["name"]]}')
    dist = next(v for k, v in dists.items() if k.name == "_rounds_record")
    for name, group in (("fx_import_table", "Used as an input"),
                        ("fx_analysis_one", "Named as their producer"),
                        ("fx_result_one", "Cited in prose"), ("fx_arg_one", "Superseded by")):
        page = browse.page_name(name)
        if name == "fx_arg_one":
            page = page.replace(".html", "_reading.html")
        if f'<h3 class="cbh">{group} (' not in (dist / page).read_text():
            bad.append(f"rounds fixture: {name} has no {group!r} group")
    return (not bad, f"{pages} page(s) list the {grounds} Grounds the record says cite them",
            bad)


def case_o_cited_content_is_marked(dists):
    """Each cell, row, table and passage a Ground addresses is marked, and each mark's link
    reaches a row of "Cited by" on the same page (R2, N6)."""
    bad, marked = [], 0
    for rec, dist in dists.items():
        types = {d["artifact"]["name"]: d["artifact"]["type"] for d in _docs(rec)}
        for d in _docs(rec):
            for o in d.get("objects", []):
                p = parse_address(o.get("citation", "")) if o.get("type") == "Ground" else None
                if not p or not anchored(p) or types.get(p["root"]) in (None, "Argument"):
                    continue
                text = (dist / browse.page_name(p["root"])).read_text()
                frag = html.escape(browse.address_fragment(o["citation"]))
                if p["method"] == "text_span":
                    ok = re.search(f'<mark id="{re.escape(frag)}" title="Cited by [^"]*">'
                                   r'.*?</mark><a class="cmark"', text) is not None
                else:
                    ok = f'id="{frag}" class="cited"' in text
                marked += ok
                if not ok:
                    bad.append(f'{d["artifact"]["name"]}.{o["name"]} -> {frag[:60]} is not marked')
        for page in dist.glob("*.html"):
            text = page.read_text()
            for href in set(re.findall(r'class="cmark" href="#([^"]+)"', text)):
                if f'id="{href}"' not in text:
                    bad.append(f"{page.name}: a mark links to #{href[:50]}, which is not there")
    return (not bad, f"{marked} cited cell(s), row(s), table(s) and passage(s) marked, "
            "each linked to its Ground", bad)


def _columns(text, by_page):
    """Rounds page -> {column label: {artifact name}}, read from its links."""
    out = {}
    for sec in text.split('<section class="rcol')[1:]:
        label = re.search(r'aria-label="([^"]*)"', sec).group(1)
        out[label] = {by_page[h] for h in re.findall(r'<li class="ritem"><a href="([^"]+)"', sec)}
    return out


def case_p_rounds_come_from_addresses(dists):
    """The Rounds columns hold exactly what `serves_goals` names (R3), and only that: renaming
    every artifact changes nothing about where anything is placed or what cites it (N4)."""
    rec, dist = next((k, v) for k, v in dists.items() if k.name == "_rounds_record")
    bad = []

    def pages_of(names):
        m = {}
        for n in names:
            m[browse.page_name(n)] = n
            m[browse.page_name(n).replace(".html", "_reading.html")] = n
        return m

    docs = _docs(rec)
    names = [d["artifact"]["name"] for d in docs]
    cols = _columns((dist / "rounds.html").read_text(), pages_of(names))
    want = {"Corpus and unassigned": ROUNDS_EXPECTED["corpus"],
            "Goal 1": ROUNDS_EXPECTED["fx_goal_one"], "Goal 2": ROUNDS_EXPECTED["fx_goal_two"]}
    if cols != want:
        bad.append(f"columns {cols}, want {want}")
    text = (dist / "rounds.html").read_text()
    if text.count('shared &middot; also') != 2:
        bad.append("fx_closing, serving both goals, is not marked shared in both columns")
    goal_page = (dist / browse.page_name("fx_goal_one")).read_text()
    if "Serving this goal (5)" not in goal_page:
        bad.append("fx_goal_one's page does not list the 5 artifacts serving it")

    renamed_rec = dist.parent / "_rounds_renamed"
    new = renamed_copy(rec, renamed_rec)
    renamed_dist = dist.parent / "build__rounds_renamed"
    browse.compile_record(str(renamed_rec), str(renamed_dist), quiet=True)
    cols2 = _columns((renamed_dist / "rounds.html").read_text(), pages_of(new.values()))
    want2 = {k: {new[n] for n in v} for k, v in want.items()}
    if cols2 != want2:
        bad.append(f"after renaming, columns {cols2}, want {want2}")
    for d in docs:
        n = d["artifact"]["name"]
        d2 = json.loads((renamed_rec / f"{new[n]}.json").read_text())
        before = _cited_by(_page_of(dist, d)).count('<tr id="cb-')
        after = _cited_by(_page_of(renamed_dist, d2)).count('<tr id="cb-')
        if before != after:
            bad.append(f"{n}: {before} Ground row(s), {after} once renamed")
    return (not bad, "Rounds columns and Cited by come from addresses: the same under any "
            "names", bad)


def case_q_no_goals_no_rounds_page(dists):
    """A record without a ResearchGoal gets no Rounds page and no link to one; a record with
    one does (plan, risks: a community without goals would see an empty page)."""
    bad = []
    for rec, dist in dists.items():
        has_goal = any(d["artifact"]["type"] == "ResearchGoal" for d in _docs(rec))
        exists = (dist / "rounds.html").is_file()
        linked = 'href="rounds.html"' in (dist / "index.html").read_text()
        if has_goal != exists or has_goal != linked:
            bad.append(f"{rec.name}: goal={has_goal}, rounds.html={exists}, linked={linked}")
    return (not bad, "only a record with a goal has a Rounds page", bad)


_STICKY = re.compile(r"position\s*:\s*sticky")
_PADDING = re.compile(r"scroll-padding-top\s*:\s*(\d+)px")
HEADER_PX = 56  # an artifact page's header with a one-line title, measured at 1440px


def _rules(page):
    """A compiled page's CSS rules, as (set of selectors, body), comments removed."""
    m = re.search(r"<style>(.*?)</style>", page, re.S)
    css = re.sub(r"/\*.*?\*/", "", m.group(1) if m else "", flags=re.S)
    return [({s.strip() for s in sel.split(",")}, body)
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def case_r_link_targets_clear_the_sticky_header(dists):
    """A link to a place on a page lands below the page's sticky header, not under it.

    An artifact page's header is sticky. With no scroll padding, every in-page target (a
    Ground's row or cell, Cited by, Serving this goal, a mark's badge) landed 56px up, under a
    56px header, so a cited table row, about 27px tall, could not be seen at all.

    Checked by reading each compiled page: where a rule makes the header sticky, the page must
    pad its scroll by at least a one-line header in CSS, and its script must size the padding
    to the header, which grows when a long title wraps.
    """
    bad, checked = [], 0
    for rec, dist in dists.items():
        for p in sorted(pathlib.Path(dist).glob("*.html")):
            page = p.read_text(encoding="utf-8")
            rules = _rules(page)
            if not any("header" in sels and _STICKY.search(body) for sels, body in rules):
                continue
            checked += 1
            pads = [int(v) for sels, body in rules if "html" in sels for v in _PADDING.findall(body)]
            if not pads or max(pads) < HEADER_PX:
                bad.append(f"{rec.name}/{p.name}: a sticky header, and no scroll padding for it")
            if "scrollPaddingTop" not in page or "header.offsetHeight" not in page:
                bad.append(f"{rec.name}/{p.name}: the scroll padding is not sized to the header")
    if not checked:
        bad.append("no compiled page has a sticky header, so nothing was checked")
    return (not bad, f"{checked} page(s) with a sticky header keep link targets below it", bad)


def _lines(text, back=None):
    """Lineage page -> [[artifact name, ...] for each line], read from its list."""
    main = text[text.index('<main class="lines">'):]
    return [[(back or {}).get(i, i) for i in re.findall(r'<li id="a-([^"]+)">', sec)]
            for sec in main.split("<h2>Line ")[1:]]


def _drawn(text, back=None):
    """Lineage page -> {(earlier, later): the kind the link is drawn as}."""
    b = back or {}
    return {(b.get(f, f), b.get(t, t)): k for f, t, k in re.findall(
        r'<path data-from="([^"]+)" data-to="([^"]+)" class="lk-(\w+)', text)}


def case_s_lineage_lines_come_from_addresses(dists):
    """The Lineage page groups Arguments into lines through the links their addresses state,
    and only those (R5, F3): supersedes before a Ground under the primary Assertion before a
    prose citation; a Ground under another Assertion is no link; a prose link a longer chain
    implies is listed, not drawn; links between lines are drawn. Renaming every artifact
    changes nothing (N4). A record with no Argument gets no Lineage page and no link to one."""
    bad = []
    for rec, dist in dists.items():
        has_arg = any(d["artifact"]["type"] == "Argument" for d in _docs(rec))
        exists = (dist / "lineage.html").is_file()
        linked = 'href="lineage.html"' in (dist / "index.html").read_text()
        if has_arg != exists or has_arg != linked:
            bad.append(f"{rec.name}: Argument={has_arg}, lineage.html={exists}, linked={linked}")
    rec, dist = next((k, v) for k, v in dists.items() if k.name == "_lineage_record")
    text = (dist / "lineage.html").read_text()
    if _lines(text) != LINEAGE_EXPECTED:
        bad.append(f"lines {_lines(text)}, want {LINEAGE_EXPECTED}")
    if _drawn(text) != LINEAGE_DRAWN:
        bad.append(f"drawn {sorted(_drawn(text).items())}, want {sorted(LINEAGE_DRAWN.items())}")
    item = re.search(r'<li id="a-lx_r1ppp">.*?</li>', text, re.S).group(0)
    if "#a-lx_r2pp" in item:
        bad.append("a Ground under a side Assertion was taken for a link")
    item = re.search(r'<li id="a-lx_r1pp">.*?</li>', text, re.S).group(0)
    if 'Also links to <a href="#a-lx_r1">' not in item:
        bad.append("a link a longer chain implies is not listed under the graph")
    if "context, not evidence" not in text:
        bad.append("the page does not say a prose citation is context, not evidence")
    # an arrowhead is a path inside <defs>; a rule hiding the links' fill must not reach it
    for sels, body in _rules(text):
        if any(re.search(r"svg\s+path", sel) for sel in sels) and "fill:none" in body.replace(" ", ""):
            bad.append(f"'{', '.join(sorted(sels))}' hides the arrowheads' fill")
    markers = re.findall(r'<marker id="ah-\w+"[^>]*><path [^>]*fill="(#[0-9a-f]{6})"', text)
    if len(markers) != 3:
        bad.append(f"the arrowhead markers are missing or have no fill: {markers}")
    bad += _lineage_link_past_a_card()

    renamed_rec = dist.parent / "_lineage_renamed"
    new = renamed_copy(rec, renamed_rec)
    back = {v: k for k, v in new.items()}
    renamed_dist = dist.parent / "build__lineage_renamed"
    browse.compile_record(str(renamed_rec), str(renamed_dist), quiet=True)
    text2 = (renamed_dist / "lineage.html").read_text()
    if _lines(text2, back) != LINEAGE_EXPECTED or _drawn(text2, back) != LINEAGE_DRAWN:
        bad.append(f"after renaming: lines {_lines(text2, back)}, drawn {_drawn(text2, back)}")
    return (not bad, "Lineage lines and links come from addresses: the same under any names",
            bad)


def _lineage_link_past_a_card():
    """B cites A; C supersedes A and cites B. C follows B, and A -> C passes B in one lane,
    so it must arc below the lane, not run behind B where it reads as A -> B -> C. E, a line
    of its own, cites A: A -> E must leave through the gap between the lanes, not run behind
    B and C."""
    def art(n):
        return {"artifact": {"name": n, "type": "Argument"}, "objects": [], "relationships": []}
    links = {"B": [{"target": "A", "rel": "cites"}],
             "C": [{"target": "A", "rel": "supersedes"}, {"target": "B", "rel": "cites"}],
             "E": [{"target": "A", "rel": "cites"}]}
    lin = browse.lineage([art(n) for n in "ABCE"], links)
    nodes = {n: {"name": n, "title": f"Arg {n}", "opening": "", "grounds": 0, "tests": 0,
                 "created": "", "member": "m", "color": "#999", "href": f"{n}.html",
                 "map": f"{n}.html"} for n in "ABCE"}
    page = T.render_lineage_html(lin, nodes)
    bad = []
    if lin["lines"] != [["A", "B", "C"], ["E"]]:
        bad.append(f"a link past a card: lines {lin['lines']}, want [['A', 'B', 'C'], ['E']]")
    if not re.search(r'<path data-from="A" data-to="E" [^>]*data-route="between"', page):
        bad.append("A -> E, between lanes past B and C, does not leave through the gap")
    below = re.search(r'<path data-from="A" data-to="C" [^>]*data-route="below"[^>]* d="M[\d.]+,'
                      r'([\d.]+) C[\d.]+,([\d.]+)', page)
    if not below or float(below.group(2)) <= float(below.group(1)):
        bad.append("A -> C, past B in one lane, does not arc below the lane")
    if re.search(r'<path data-from="(A" data-to="B|B" data-to="C)"[^>]*data-route', page):
        bad.append("a link between neighbouring cards was routed over the lane")
    return bad


def case_t_contents_filters_and_searches(dists):
    """Contents has a chip per type and starts with Messages, AnalysisPlans, ResearchGoals and
    Data hidden, each a chip away; it searches an index holding each artifact's title, name,
    whole verdict and every Assertion's claim, across every type, hidden ones too (R9, R12).
    Its stored choices are read and written inside a try (N5)."""
    bad, checked = [], 0
    for rec, dist in dists.items():
        text = (dist / "contents.html").read_text()
        m = re.search(r'<script type="application/json" id="search-index">(.*?)</script>',
                      text, re.S)
        index = json.loads(m.group(1)) if m else {}
        docs = _docs(rec)
        for t in sorted({d["artifact"]["type"] for d in docs}):
            if f'<details class="sec" data-type="{t}" open>' not in text:
                bad.append(f"{rec.name}: no {t} section, or it starts folded")
            pressed = "false" if t in T.CONTENTS_HIDDEN else "true"
            if f'class="chip" data-type="{t}" aria-pressed="{pressed}"' not in text:
                bad.append(f"{rec.name}: the {t} chip does not start "
                           f"{'off' if pressed == 'false' else 'on'}")
        defaults = re.search(r"var DEFAULT_HIDDEN = (\{[^}]*\});", text)
        if not defaults or set(json.loads(defaults.group(1))) != set(T.CONTENTS_HIDDEN):
            bad.append(f"{rec.name}: the page does not start with {T.CONTENTS_HIDDEN} hidden")
        if "searching ? terms.every" not in text:
            bad.append(f"{rec.name}: a search does not look through hidden types")
        for d in docs:
            h = d["artifact"]
            want = [h.get("title") or h["name"], h["name"]]
            if h["type"] == "Argument":
                want += [h.get("verdict") or ""]
                want += [o.get("claim") or "" for o in d.get("objects", [])
                         if o.get("type") == "Assertion"]
            missing = [w for w in want if w and w not in index.get(h["name"], "")]
            checked += 1
            if missing:
                bad.append(f"{rec.name}/{h['name']}: the search index lacks {missing[0][:50]!r}")
        bad += [f"{rec.name}: unwrapped storage access: {ln[:80]}"
                for ln in _storage_unwrapped(text)]
    return (not bad, f"{checked} artifact(s) searchable by title, name, verdict and claims; "
            f"{', '.join(T.CONTENTS_HIDDEN)} start hidden", bad)


def case_u_wide_tables_put_cited_columns_first(dists):
    """A table shows its row key, then the columns a Ground cites (whole or by a cell), then
    the rest; every cell keeps its id and value; "Original column order" puts the stored
    order back; more than 12 columns brings a column picker; and the key column stays fixed
    as the table scrolls (R11, F7)."""
    bad = []
    hdr = ["key"] + [f"c{i}" for i in range(1, 14)]
    rows = [",".join(hdr)] + [",".join([k] + [f"{k}v{i}" for i in range(1, 14)])
                              for k in ("k1", "k2")]
    cited = {"t.col=c9": [("cb-a", "A · g_col")], "t.row=k2&col=c4": [("cb-b", "A · g_cell")]}
    out = T.csv_table("\n".join(rows), method="t", cited=cited)
    want = [0, 4, 9, 1, 2, 3, 5, 6, 7, 8, 10, 11, 12, 13]
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", out, re.S):
        got = [int(c) for c in re.findall(r'data-c="(\d+)"', tr)]
        if got != want:
            bad.append(f"a row is in order {got}, want {want}")
    for k in ("k1", "k2"):
        for i in range(1, 14):
            if f'id="t.row={k}&amp;col=c{i}"' not in out or not re.search(
                    f'id="t.row={k}&amp;col=c{i}"[^>]*>{k}v{i}<', out):
                bad.append(f"cell {k}/c{i} lost its id or value")
    if "Columns a Ground cites come first: c4, c9" not in out:
        bad.append("the cited columns are not named above the table")
    if 'class="colorder" data-for="tbl-t" aria-pressed="false"' not in out:
        bad.append("no Original column order control")
    if out.count('<input type="checkbox" data-c=') != 13:
        bad.append("a 14-column table has no picker for its 13 non-key columns")
    small = T.csv_table("key,a,b\nk1,1,2", method="s")
    if "tabletools" in small:
        bad.append("an uncited table of 3 columns grew controls")
    # two tables under one Content method share an id, so each control must find its own
    # table by position: the controls sit right before their table's wrapper
    two = out + T.csv_table("\n".join(rows), method="t", cited=cited)
    if two.count("<div class='tabletools'>") != 2 or len(re.findall(
            r"<div class='tabletools'>.*?</div></details></div><div class='tablewrap'>", two,
            re.S)) != 2:
        bad.append("a table's controls do not sit right before its own table")
    checked = 0
    for dist in dists.values():
        for p in dist.glob("*.html"):
            page = p.read_text()
            if "<table class='data'" not in page:
                continue
            checked += 1
            sticky = any("table.data tr > :first-child" in sels and _STICKY.search(body)
                         for sels, body in _rules(page))
            if not sticky or "scrollPaddingLeft" not in page:
                bad.append(f"{p.name}: the key column is not fixed, or a cell link lands under it")
                break
            if "tableAfter(b)" not in page or "getElementById(b.dataset.for)" in page:
                bad.append(f"{p.name}: a table control finds its table by an id two may share")
                break
    return (not bad, f"cited columns first, ids kept, picker over 12; {checked} page(s) with a "
            "table keep its key in view", bad)


def case_v_title_is_the_community(dists):
    """The pages are titled with the community of the session whose record copy they show,
    read from the context beside it; `--title` overrides it, and a record directory that is
    no session's copy keeps the generic title (R13)."""
    bad = []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="symposium-title-"))
    try:
        session = tmp / "session"
        (session / ".symposium").mkdir(parents=True)
        (session / ".symposium" / "context.json").write_text(
            json.dumps({"community": "c_demo", "handle": "lyra"}))
        rec = rounds_fixture_record(session / "record")
        if browse.community_name(rec) != "c_demo":
            bad.append(f"community_name read {browse.community_name(rec)!r}, want 'c_demo'")
        if browse.community_name(RECORDS[0]) is not None:
            bad.append("a record directory with no session context was given a community")
        for title, want in ((None, "c_demo"), ("Other", "Other")):
            out = tmp / f"dist-{want}"
            browse.main([str(rec), "--out", str(out), "--quiet",
                         *(["--title", title] if title else [])])
            for page in ("index.html", "contents.html", "rounds.html", "lineage.html"):
                h1 = re.search(r"<h1>(.*?)</h1>", (out / page).read_text(), re.S).group(1)
                if want not in h1:
                    bad.append(f"{page} (--title {title}): header {h1!r} lacks {want!r}")
        serve_src = (HERE / "serve.py").read_text()
        if "browse.community_name(record)" not in serve_src:
            bad.append("serve does not default its title to the community")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return (not bad, "pages are titled with the session's community, --title overrides", bad)


def case_w_overview_legend_says_what_each_type_is(dists):
    """The overview's legend gives every artifact type in the record its own shape, the shape
    its nodes are drawn with, and says what the type is and whether it can be evidence: the
    specification's and the profile's types in their own words, any other type as one neither
    defines."""
    bad, rows = [], 0
    for rec, dist in dists.items():
        arts = browse.load_record(str(rec))
        index = browse.build_index(arts)
        pages = {a["artifact"]["name"]: browse.page_name(a["artifact"]["name"]) for a in arts}
        els, meta = browse.build_overview(arts, index, browse.member_colors(arts), pages, {})
        legend = {t["type"]: t for t in meta["types"]}
        present = {a["artifact"]["type"] for a in arts}
        if set(legend) != present:
            bad.append(f"{rec.name}: legend types {sorted(legend)}, record types {sorted(present)}")
        shapes = [t["shape"] for t in meta["types"]]
        if len(set(shapes)) != len(shapes):
            bad.append(f"{rec.name}: two types share a shape: {shapes}")
        for n in els["nodes"]:
            t = legend.get(n["data"].get("ntype"))
            if t and n["data"]["shape"] != t["shape"]:
                bad.append(f"{rec.name}: {n['data']['id']} is drawn {n['data']['shape']}, its "
                           f"type's legend says {t['shape']}")
                break
        for t in meta["types"]:
            rows += 1
            want = browse.TYPE_MEANING.get(t["type"], browse.UNDEFINED_TYPE_MEANING)
            if (t["meaning"], t["evidence"]) != want or not t["meaning"]:
                bad.append(f"{rec.name}: {t['type']} is described as {t['meaning']!r}")
        page = (dist / "index.html").read_text()
        if "shapeIcon(t.shape" not in page or '"types": [' not in page:
            bad.append(f"{rec.name}: the overview does not draw a row per type")
    return (not bad, f"{rows} type row(s), each with its own shape and what the type is", bad)


CASES = [
    ("every Ground lands on the content it names", case_a_grounds_land),
    ("an Argument's prose is readable, not letterboxed", case_f_argument_is_readable),
    ("prose is rendered as prose, tables as tables", case_b_prose_is_not_a_table),
    ("an artifact's Content Objects are shown to the reader", case_c_content_section),
    ("a grounded quote is anchored on every rendering path", case_d_marking_paths),
    ("a quoted comma does not shift a row's cells", case_e_quoted_commas),
    ("a citing artifact is never in the column of what it cites", case_g_citation_edges_span_columns),
    ("a hand-placed node survives a rebuild", case_h_pins_survive_a_rebuild),
    ("an Argument page restores moved nodes on load", case_i_claim_positions_restore_on_load),
    ("an Artifact's own Objects and relationships are shown", case_j_internal_structure_is_shown),
    ("a presenter caption is not mistaken for an artifact", case_k_annotations_are_not_artifacts),
    ("the overview starts with context links and Messages hidden", case_l_overview_hides_context_links_by_default),
    ("an Argument's verdict is never height-capped", case_m_verdict_is_never_height_capped),
    ("every page's Cited by matches a direct count", case_n_cited_by_matches_a_direct_count),
    ("cited content is marked and linked to its Ground", case_o_cited_content_is_marked),
    ("Rounds come from serves_goals addresses, not names", case_p_rounds_come_from_addresses),
    ("only a record with a goal has a Rounds page", case_q_no_goals_no_rounds_page),
    ("a link target lands below the sticky header", case_r_link_targets_clear_the_sticky_header),
    ("Lineage lines come from addresses, not names", case_s_lineage_lines_come_from_addresses),
    ("Contents hides four types at first, and searches every type",
     case_t_contents_filters_and_searches),
    ("wide tables show cited columns first, key fixed", case_u_wide_tables_put_cited_columns_first),
    ("pages are titled with the session's community", case_v_title_is_the_community),
    ("the overview's legend says what each type is", case_w_overview_legend_says_what_each_type_is),
]


def run():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="symposium-browser-"))
    try:
        dists = compile_all(tmp)
        ok = 0
        for label, fn in CASES:
            good, detail, bad = fn(dists)
            ok += good
            print(f"  [{'ok ' if good else 'FAIL'}] {label}")
            print(f"         {detail}")
            for b in bad[:6]:
                print(f"         - {b}")
        print(f"\n{ok}/{len(CASES)} browser cases behaved as specified")
        return 0 if ok == len(CASES) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run())
