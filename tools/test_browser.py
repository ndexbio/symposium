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

import browse                                                          # noqa: E402
import templates as T                                                  # noqa: E402
from validate import parse_address                                     # noqa: E402

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

#: Which addresses the browser is expected to anchor, decided from the REFERENCE and never
#: from the method's name. A Content Object may be called anything — this record's are
#: `pooled_csv`, `control_rows_csv`, `inventory_csv` — and a check that looked for the name
#: `csv` would have been blind to the fault that shipped, which is that cell ids were
#: written under `csv` whatever the Content was called. `rest` names content held outside
#: the record and `graph` addresses a Model's nodes and edges; neither has a page rendering
#: yet, so a Ground through one is expected not to land.
ANCHORED_REF = re.compile(r"\brow=|\bquote=")


def compile_all(tmp):
    out = {}
    for rec in RECORDS + [fixture_record(tmp / "_fixture_record")]:
        d = tmp / ("build_" + rec.name)
        browse.compile_record(str(rec), str(d), quiet=True)
        out[rec] = d
    return out


def case_a_grounds_land(dists):
    """Every Ground whose method the browser anchors must find its anchor."""
    bad, total = [], 0
    for rec, dist in dists.items():
        for fn in sorted(rec.glob("*.json")):
            if fn.name.startswith("."):
                continue
            doc = json.loads(fn.read_text())
            for o in doc.get("objects", []):
                if o.get("type") != "Ground":
                    continue
                p = parse_address(o.get("citation", ""))
                if not p or not p["ref"] or not ANCHORED_REF.search(p["ref"]):
                    continue
                total += 1
                page = dist / browse.page_name(p["root"])
                frag = html.escape(f'{p["method"]}.{p["ref"]}')
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

    The claim map puts prose in a fixed 96-pixel strip beside the graph; on this record's
    one Argument that was 95 pixels of 26,019, so the verdict, purpose and rationale an
    author is required to write were four tenths of one per cent visible. A reader must be
    able to reach all of it without scrolling a letterbox."""
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
