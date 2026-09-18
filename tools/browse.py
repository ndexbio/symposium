#!/usr/bin/env python3
"""Compile a Symposium CommunityRecord into a static, navigable browser.

    python browse.py ../examples/record --out dist

This file produces the element sets the page templates consume; the presentation itself
lives in `templates.py`.

Two facts about the specification shape everything here:

  * **All relationships are internal to one Artifact.** Every cross-artifact edge on
    these pages is DERIVED, by resolving an address held in a property value: a Ground's
    `citation`, a provenance field, or a markdown link in prose. There is no such thing
    as a stored cross-artifact edge to read.

  * **What a Ground claims is recorded by the presence of a `criterion`, not by a type.**
    A Ground with one asserts the material was used as a test that could have counted
    against the claim. That distinction is the single most consequential thing on the
    page, so it is drawn, labelled, and counted.

The validator is imported, never reimplemented: independence between Grounds,
unverifiable references and bare prose citations are all things `validate` already
decides, and a browser that computed them separately would eventually disagree with the
gate — which is the one thing a record's reader must be able to rely on.

**The overview is laid out by citation depth, not by publication time.** A citing artifact
is always at least one column away from anything it cites, so no derived edge is vertical
and none is hidden behind the nodes between its endpoints. Layers wrap into sub-columns
rather than growing without limit, which keeps a deep record from being drawn as a long
horizontal chain. `conformance.py` enforces the column rule.

**A reader's own arrangement is kept in a sidecar, not in the record.** Dragging nodes on
the overview and pressing *Save layout* downloads `.browser_layout.json`; put that file in
the record directory and every later build honours those positions, laying out only the
nodes it does not mention. It is a viewing preference, so it lives beside the artifacts and
never inside one — the gate, the validator and the mirror comparison do not see it, and
deleting it restores the computed layout.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import math
import os
import pathlib
import re
import shutil
import sys
from collections import defaultdict

from validate import (CITATION_RE, build_index, method_of,          # noqa: E402
                         parse_address, parse_instant, resolve, validate)
import templates as T
import figures as F                                              # noqa: E402

ARGUMENT = "Argument"
NON_GROUNDABLE_TYPES = {"Analysis", "NonGroundable", "Message"}

#: Artifact properties whose value is an address or a list of them (spec §1.5, §2.5). These
#: carry the record's formal provenance, so they are rendered as links rather than as text.
ADDRESS_PROPS = {"produced_by", "inputs", "supersedes", "extracted_from", "recipients",
                 "serves_goals"}

# There is no verdict vocabulary. An Argument holds ONE free-text verdict, judging its
# primary Assertion for a stated purpose, so a verdict is read rather than tallied:
# it belongs in the header of the page, and Assertion nodes carry no verdict encoding
# at all. A closed set would have let the browser colour claims by verdict and count
# them, which is exactly the cross-Argument comparison the specification disclaims.

_MEMBER_PALETTE = ["#2563eb", "#0d9488", "#c2410c", "#7c3aed", "#be123c",
                   "#0891b2", "#4d7c0f", "#a16207"]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def load_record(record_dir):
    """Every canonical artifact in a directory, oldest first.

    Filters on STRUCTURE, not on filename: a mirror also holds manifest.json and
    dotfiles, and `Path.glob('*.json')` matches those too. Globbing blindly crashed a
    member agent's session during a live test.
    """
    arts = []
    for path in sorted(pathlib.Path(record_dir).glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # Same reasoning as validate_record.load: a dotfile here is state or a saved
            # layout, never an Artifact, and a hand-edited one must not break the build.
            if path.name.startswith("."):
                continue
            raise SystemExit(f"ERROR: {path} is not valid JSON: {exc}")
        if isinstance(doc, dict) and isinstance(doc.get("artifact"), dict) \
                and doc["artifact"].get("name") and doc["artifact"].get("type"):
            arts.append(doc)
    arts.sort(key=lambda a: (a["artifact"].get("created") or "", a["artifact"]["name"]))
    return arts


def member_colors(artifacts):
    members = sorted({a["artifact"].get("published_by", "").lstrip("@") for a in artifacts} - {""})
    return {m: _MEMBER_PALETTE[i % len(_MEMBER_PALETTE)] for i, m in enumerate(members)}


def run_validator(artifacts, members):
    """name -> findings. Each artifact is judged against the rest of the record, which
    is what the gate did when it accepted it."""
    out = {}
    for i, a in enumerate(artifacts):
        rest = artifacts[:i] + artifacts[i + 1:]
        try:
            out[a["artifact"]["name"]] = validate(a, record=rest, members=members)
        except Exception as exc:                       # a browser must render a broken record
            out[a["artifact"]["name"]] = [{"check": "VALIDATOR", "level": "REVIEW",
                                           "msg": f"could not be validated: {exc}"}]
    return out


# --------------------------------------------------------------------------- #
# Addresses
# --------------------------------------------------------------------------- #

def page_name(artifact_name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", artifact_name) + ".html"


def address_fragment(addr):
    """The anchor an address resolves to on its artifact's page.

    Artifact pages give every CSV cell and every grounded-on passage an id of exactly
    this shape, so following a Ground lands on the value it names rather than on the
    top of a table — which is the difference between a record you can check and a
    record you can only read.
    """
    p = parse_address(addr)
    if not p:
        return ""
    if p["method"] and p["ref"]:
        return f'{p["method"]}.{p["ref"]}'
    return p["segs"][0] if p["segs"] else ""


def pretty_address(addr, index):
    """A human-sized name for addressed content. The address stays available in full;
    this is what gets drawn beside the node, so it has to say what was pointed at."""
    p = parse_address(addr)
    if not p:
        return addr
    root = p["root"]
    title = (index.get(root, {}).get("header", {}) or {}).get("title") or root
    short = title
    segs, method, ref = p["segs"], p["method"], p["ref"] or ""

    if method == "csv":
        row = re.search(r"row=([^&]*)", ref)
        col = re.search(r"col=([^&]*)", ref)
        cell = " / ".join(x.group(1) for x in (row, col) if x)
        return f"{short} · {cell}" if cell else short
    if method == "text_span":
        q = re.search(r'quote="([^"]*)"', ref)
        if q:
            t = q.group(1)
            return f'{short} · "{t}"'
        return f"{short} · passage"
    if method in ("rest", "download"):
        return f"{short} · {method}"
    if len(segs) == 1:
        return f"{short} · {segs[0]}"
    if segs:
        return f"{short} · {'.'.join(segs)}"
    return short


def cited_addresses(doc):
    """Addresses cited in prose, in the profile's markdown-link form (CANONICAL.md 3.1).

    Bare `@name` in prose is deliberately NOT collected: the validator reports it as a
    REVIEW because it cannot be told apart from an email address, and a browser that
    guessed would be asserting something the gate refused to assert.
    """
    out = []
    h = doc["artifact"]
    scopes = [h] + [o for o in doc.get("objects", [])]
    for d in scopes:
        for k, v in d.items():
            if not isinstance(v, str) or k in ("citation", "published_by", "produced_by",
                                               "extracted_from"):
                continue
            for m in CITATION_RE.finditer(v):
                out.append(m.group(1) or m.group(2))
    return out


# --------------------------------------------------------------------------- #
# Claim map for one Argument
# --------------------------------------------------------------------------- #

def _ground_facts(g, index, argument_name):
    """What the record can say, structurally, about one Ground."""
    addr = g.get("citation", "")
    p = parse_address(addr)
    root = p["root"] if p else ""
    rec = index.get(root, {})
    ok, info, _ = resolve(addr, index, set())
    node_type = info.get("node_type") if ok and info else None
    method = (info or {}).get("method")
    return {
        "address": addr,
        "root": root,
        "kind": "test" if g.get("criterion") else "evidential",
        # An address that lands on an Assertion in ANOTHER Argument takes that author's
        # conclusion as testimony (spec 2.2.4) — a different epistemic act from reading
        # a measurement, and invisible unless the browser says so.
        "testimony": bool(node_type == "Assertion" and root != argument_name),
        # `rest` and `download` are groundable but the gate can verify nothing about
        # them. This is the point at which verification becomes trust.
        "unverifiable": method in ("rest", "download"),
        "target_type": rec.get("type"),
    }


def build_claim_graph(doc, index, findings, colors, pages):
    """-> (collapsed_elements, full_elements, meta)"""
    h = doc["artifact"]
    name = h["name"]
    owner = h.get("published_by", "").lstrip("@")
    color = colors.get(owner, "#9ca3af")
    objs = {o["name"]: o for o in doc.get("objects", []) if o.get("name")}
    rels = doc.get("relationships", [])

    assertions = {n: o for n, o in objs.items() if o.get("type") == "Assertion"}
    grounds = {n: o for n, o in objs.items() if o.get("type") == "Ground"}
    assumptions = {n: o for n, o in objs.items() if o.get("type") == "Assumption"}

    out = defaultdict(list)                     # assertion -> [(rel, target)]
    for r in rels:
        out[r.get("source")].append((r.get("rel"), r.get("target")))

    # findings that name an Object, so a claim can carry what the checker said about it
    per_object = defaultdict(list)
    for f in findings:
        for m in re.finditer(r"'([A-Za-z0-9_]+)'", f.get("msg", "")):
            if m.group(1) in objs:
                per_object[m.group(1)].append(f)

    nodes, edges, full_nodes, full_edges = [], [], [], []
    source_ids, shared = {}, defaultdict(set)
    n_unverifiable = 0

    def source_node(gf, into):
        """A node for the content a Ground addresses — one per distinct address, so two
        Grounds on the same cell visibly converge instead of drawing two leaves."""
        nonlocal n_unverifiable
        sid = "src:" + gf["address"]
        shared[gf["root"]].add(into)
        if sid in source_ids:
            return sid
        source_ids[sid] = True
        external_assertion = gf["testimony"]
        target_owner = (index.get(gf["root"], {}).get("header", {}) or {}).get(
            "published_by", "").lstrip("@")
        if gf["unverifiable"]:
            n_unverifiable += 1
        label = pretty_address(gf["address"], index)
        d = {
            "id": sid, "ntype": "External" if external_assertion else "Source",
            "label": label, "name": label,
            "owner": target_owner, "owner_color": colors.get(target_owner, "#9ca3af"),
            "unverifiable": gf["unverifiable"],
            "full": {"name": label, "address": gf["address"], "artifact": gf["root"],
                     "method": (parse_address(gf["address"]) or {}).get("method"),
                     "type": gf["target_type"]},
            "tooltip": gf["address"],
        }
        if gf["root"] in pages:
            d["nav_file"] = pages[gf["root"]]
            d["navigable"] = True
            frag = address_fragment(gf["address"])
            if frag:
                d["nav_frag"] = frag
        for bag in (nodes, full_nodes):
            bag.append({"data": dict(d)})
        return sid

    # ---- assertions ---------------------------------------------------------
    for an, a in assertions.items():
        my = out.get(an, [])
        claim = a.get("claim", "")
        label = claim
        gs = []
        for rel, t in my:
            if rel != "grounded_by" or t not in grounds:
                continue
            g = grounds[t]
            gf = _ground_facts(g, index, name)
            sid = source_node(gf, an)
            gs.append({"source": pretty_address(gf["address"], index),
                       "address": gf["address"], "kind": gf["kind"],
                       "criterion": g.get("criterion"), "rationale": g.get("rationale"),
                       "testimony": gf["testimony"], "unverifiable": gf["unverifiable"],
                       "_ground": t, "_sid": sid, "_facts": gf})
        us = [{"id": t, "rationale": assumptions[t].get("rationale")}
              for rel, t in my if rel == "assumes" and t in assumptions]
        data = {
            "id": an, "ntype": "Assertion", "label": label,
            "owner": owner, "owner_color": color,
            "groundings": [{k: v for k, v in g.items() if not k.startswith("_")} for g in gs],
            "assumptions": us,
            "findings": [{"check": f["check"], "level": f["level"], "msg": f["msg"]}
                         for f in per_object.get(an, [])],
            "full": {"claim": a.get("claim"), "scope": a.get("scope")},
            "primary": an == h.get("primary_assertion"),
            "tooltip": (("PRIMARY — " if an == h.get("primary_assertion") else "") + claim),
        }
        nodes.append({"data": data})
        full_nodes.append({"data": {k: v for k, v in data.items()
                                    if k not in ("groundings", "assumptions")}})

        # collapsed edges: assertion -> what it rests on
        for g in gs:
            edges.append({"data": {
                "id": f"e_{an}_{g['_ground']}", "source": an, "target": g["_sid"],
                "rel": "grounded_by", "kind": g["kind"], "testimony": g["testimony"],
                "unverifiable": g["unverifiable"],
                "full": {"address": g["address"], "criterion": g.get("criterion"),
                         "rationale": g.get("rationale")},
                "tooltip": ("test — " if g["kind"] == "test" else "evidential — ")
                           + (g.get("rationale") or "")}})
        for u in us:
            edges.append({"data": {"id": f"e_{an}_{u['id']}", "source": an, "target": u["id"],
                                   "rel": "assumes", "tooltip": u.get("rationale") or ""}})
        for rel, t in my:
            if rel == "depends_on" and t in assertions:
                e = {"data": {"id": f"e_{an}_{rel}_{t}", "source": an, "target": t, "rel": rel,
                              "tooltip": rel + " → " + (assertions[t].get("claim") or t)}}
                edges.append(e)
                full_edges.append({"data": dict(e["data"])})

        # full graph: nothing folded
        for g in gs:
            full_edges.append({"data": {
                "id": f"f_{an}_{g['_ground']}", "source": an, "target": g["_ground"],
                "rel": "grounded_by", "kind": g["kind"], "testimony": g["testimony"]}})
            full_edges.append({"data": {
                "id": f"f_{g['_ground']}_addr", "source": g["_ground"], "target": g["_sid"],
                "rel": "addresses"}})
        for u in us:
            full_edges.append({"data": {"id": f"f_{an}_{u['id']}", "source": an,
                                        "target": u["id"], "rel": "assumes"}})

    # ---- assumptions (drawn in BOTH modes — never folded) --------------------
    for un, u in assumptions.items():
        r = u.get("rationale", "")
        d = {"id": un, "ntype": "Assumption", "owner": owner, "owner_color": color,
             "label": r,
             "full": {"rationale": r}, "tooltip": "assumed: " + r}
        nodes.append({"data": dict(d)})
        full_nodes.append({"data": dict(d)})

    # ---- grounds exist only in the full graph --------------------------------
    for gn, g in grounds.items():
        full_nodes.append({"data": {
            "id": gn, "ntype": "Ground", "label": gn,
            "owner": owner, "owner_color": color,
            "kind": "test" if g.get("criterion") else "evidential",
            "full": {k: v for k, v in g.items() if k != "name"},
            "tooltip": ("test: " if g.get("criterion") else "evidential: ")
                       + (g.get("rationale") or "")}})

    # ---- prose citations ----------------------------------------------------
    for addr in cited_addresses(doc):
        p = parse_address(addr)
        if not p or p["root"] not in pages or p["root"] == name:
            continue
        cid = "cite:" + p["root"]
        if not any(n["data"]["id"] == cid for n in nodes):
            title = (index.get(p["root"], {}).get("header", {}) or {}).get("title") or p["root"]
            tgt_owner = (index.get(p["root"], {}).get("header", {}) or {}).get(
                "published_by", "").lstrip("@")
            d = {"id": cid, "ntype": "Source", "label": "cited: " + title,
                 "name": title, "owner": tgt_owner,
                 "owner_color": colors.get(tgt_owner, "#9ca3af"),
                 "nav_file": pages[p["root"]], "navigable": True,
                 "full": {"name": title, "address": addr, "artifact": p["root"]},
                 "tooltip": "cited in prose — a reference, never evidence: " + addr}
            nodes.append({"data": dict(d)})
            full_nodes.append({"data": dict(d)})
        prim = h.get("primary_assertion")
        if prim in assertions:
            eid = f"e_cite_{prim}_{p['root']}"
            if not any(e["data"]["id"] == eid for e in edges):
                edges.append({"data": {"id": eid, "source": prim, "target": cid, "rel": "cites",
                                       "tooltip": "cited in prose: " + addr}})

    _layout_claim(nodes, edges, h.get("primary_assertion"))
    _layout_full(full_nodes, full_edges)

    shared_count = sum(1 for r, into in shared.items() if len(into) > 1)
    by_type = defaultdict(int)
    for n in nodes:
        by_type[n["data"]["ntype"]] += 1

    meta = {
        "title": h.get("title") or name,
        "review_id": name,
        "member": owner,
        "member_color": color,
        "created": h.get("created") or "(unstamped)",
        "genre_line": "critic" if "critic" in name else "",
        # The judgment is a property of the Argument, so it is page furniture
        # rather than a node encoding. Free text, shown as authored.
        "verdict": h.get("verdict", ""),
        "purpose": h.get("purpose", ""),
        "rationale": h.get("rationale", ""),
        "spec_version": h.get("specification_version", ""),
        "supersedes": h.get("supersedes") or [],
        "supersedes_rationale": h.get("supersedes_rationale", ""),
        "members": {owner: color},
        "counts": {
            "nodes_total": len(nodes), "edges_total": len(edges),
            "nodes_by_type": dict(by_type),
            "source_nodes": by_type.get("Source", 0) + by_type.get("External", 0),
            "folded_grounds": len(grounds),
            "shared_source_count": shared_count,
            "unverifiable": n_unverifiable,
            "findings": len(findings),
        },
        "full_elements": {"nodes": full_nodes, "edges": full_edges},
        "frag_map": {n["data"]["id"]: n["data"]["id"] for n in nodes},
        "navigable_nodes": sum(1 for n in nodes if n["data"].get("navigable")),
        "addr_pages": pages,
    }
    for n in nodes:
        m = n["data"]
        if m.get("owner") and m["owner"] not in meta["members"]:
            meta["members"][m["owner"]] = m.get("owner_color", "#9ca3af")
    return {"nodes": nodes, "edges": edges}, {"nodes": full_nodes, "edges": full_edges}, meta


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #

# Assertion columns are wide enough that a leaf column can sit BETWEEN two of them
# without either set of labels touching: leaves hang _LEAF_DX left of their consumer,
# leaving _DX - _LEAF_DX of clear space before the next assertion column.
_DX, _DY, _LEAF_DX, _LEAF_DY = 400.0, 150.0, 220.0, 78.0


def _layout_claim(nodes, edges, primary):
    """Assertions on a dependency spine, primary at the RIGHT; everything an assertion
    rests on sits to its left. Positions are precomputed and handed to Cytoscape as a
    `preset`, so the picture is identical on every reload — a record people are reading
    together should not rearrange itself under them."""
    by_id = {n["data"]["id"]: n["data"] for n in nodes}
    assertions = [i for i, d in by_id.items() if d["ntype"] == "Assertion"]
    dep = defaultdict(list)
    for e in edges:
        if e["data"]["rel"] == "depends_on":
            dep[e["data"]["source"]].append(e["data"]["target"])

    depth = {}

    def walk(i, seen):
        if i in depth:
            return depth[i]
        if i in seen:
            return 0
        seen = seen | {i}
        d = 0
        for t in dep.get(i, []):
            if t in by_id:
                d = max(d, walk(t, seen) + 1)
        depth[i] = d
        return d

    roots = [primary] if primary in by_id else []
    for i in assertions:
        walk(i, set())
    maxd = max(depth.values()) if depth else 0

    col = defaultdict(list)
    for i in sorted(assertions, key=lambda x: (depth.get(x, 0), x != primary, x)):
        col[depth.get(i, 0)].append(i)
    # depth here is the LONGEST dependency chain below an assertion, so the primary —
    # which everything else feeds — has the largest depth and sits rightmost. Reading
    # runs left to right into the claim being made, the same direction as the prose.
    for d, ids in col.items():
        for k, i in enumerate(ids):
            by_id[i]["_pos_claim"] = {"x": d * _DX, "y": (k - (len(ids) - 1) / 2) * _DY}

    # leaves (addressed content, assumptions, externals) hang left of their consumers
    consumers = defaultdict(list)
    for e in edges:
        if e["data"]["rel"] in ("grounded_by", "assumes", "cites"):
            consumers[e["data"]["target"]].append(e["data"]["source"])
    stack = defaultdict(list)
    for i, d in by_id.items():
        if d["ntype"] == "Assertion":
            continue
        cs = [c for c in consumers.get(i, []) if c in by_id and "_pos_claim" in by_id[c]]
        if cs:
            anchor = min(cs, key=lambda c: by_id[c]["_pos_claim"]["x"])
            ax, ay = by_id[anchor]["_pos_claim"]["x"], by_id[anchor]["_pos_claim"]["y"]
        else:
            ax, ay = -_DX, 0.0
        key = round(ax)
        stack[key].append((i, ay))
    for key, items in stack.items():
        items.sort(key=lambda t: t[1])
        for k, (i, ay) in enumerate(items):
            by_id[i]["_pos_claim"] = {"x": key - _LEAF_DX,
                                      "y": ay + (k - (len(items) - 1) / 2) * _LEAF_DY}
    for d in by_id.values():
        d.setdefault("_pos_claim", {"x": 0.0, "y": 0.0})
    return roots


_FULL_ORDER = {"Source": 0, "External": 0, "Ground": 1, "Assumption": 1,
               "Assertion": 2}


def _layout_full(nodes, edges):
    """Layered by Object type: addressed content, then the Objects that reach it, then
    the Assertions. Three columns —
    the judgment is no longer an Object, so it is no longer a column."""
    by_id = {n["data"]["id"]: n["data"] for n in nodes}
    col = defaultdict(list)
    for i, d in by_id.items():
        col[_FULL_ORDER.get(d["ntype"], 2)].append(i)
    for c, ids in sorted(col.items()):
        ids.sort()
        for k, i in enumerate(ids):
            by_id[i]["_pos_full"] = {"x": c * 260.0, "y": (k - (len(ids) - 1) / 2) * 60.0}
    for d in by_id.values():
        d.setdefault("_pos_full", {"x": 0.0, "y": 0.0})


# --------------------------------------------------------------------------- #
# Community overview
# --------------------------------------------------------------------------- #

_SHAPE = {"Argument": "round-rectangle", "NonGroundable": "hexagon", "Data": "rectangle",
          "ScientificPublication": "octagon", "Analysis": "diamond",
          "Model": "pentagon", "Message": "tag"}
_SESSION_GAP = 20 * 60
_ROW_DY, _BAND_GAP = 86.0, 54.0
# Within one session's type band, wrap into sub-columns rather than one long stack. A bulk
# publication — prepopulating the record, or any burst during the day — lands entirely inside
# one session, and a 33-artifact band drawn as a single file is a vertical strip narrower than
# a scrollbar: unreadable, and unimproved by "Fit", because there is nothing to fit across.
# Sub-columns sit closer together than sessions do, so a session still reads as one group.
#
# Five, not more: the overview is a timeline read left to right, so it has to stay LANDSCAPE.
# Wrapping at eight left the record 878 x 1462 in an 845 x 670 pane, which "Fit" solved by
# zooming to 0.4 — everything visible, every label unreadable. Fitting is not the same as
# being legible, and a tall graph in a wide pane cannot be both.
_BAND_MAX_ROWS = 5
_SUB_DX, _COL_GAP = 190.0, 150.0


# --------------------------------------------------------------------------- #
# Overview layout: layered by citation depth, not by clock
# --------------------------------------------------------------------------- #
#
# The overview used to place a node at x = its publication session and y = its type band.
# Nothing about what an artifact CITED entered the calculation, so a round's whole output
# shared one x and the citation edges inside that round ran vertically through a stack of
# nodes. A reader could see that an edge left one node and arrived at another only by
# tracing a line that passed behind four unrelated boxes on the way.
#
# The rule this enforces instead: a citing artifact is never in the same column as one it
# cites, and every derived edge therefore spans at least _MIN_DX horizontally.
#
# That rule is cheap to satisfy here because the record is a DAG by construction. Publication
# is serial and an artifact can only address something already accepted (spec 1.9), so the
# derived citation graph cannot contain a cycle and longest-path layering is well defined.
# It is also STABLE: adding artifacts later never reorders the layers already drawn, because
# an existing node's depth depends only on what it already cites.
#
# The obvious failure of pure depth layering is the opposite of the one being fixed. The
# evidential chain in this record is four acts deep — import, Analysis, its output Data, the
# Argument that grounds on it — and a strict column per depth draws the record as a long thin
# horizontal ribbon, which is exactly as unreadable as the vertical strip it replaced and for
# the same reason. So a layer is a BAND, not a column: once a layer holds more nodes than fit
# in _target_rows, it wraps into sub-columns inside its own band, and the band gets wider
# rather than the graph getting taller. _target_rows is derived from the node count so the
# whole picture stays near _ASPECT rather than running away along either axis.

_MIN_DX = 260.0          # hard floor on the horizontal span of any derived edge
_SUB_DX_L = 200.0        # sub-column spacing inside one layer's band
_ROW_DY_L = 118.0        # row spacing inside a layer; wide enough that a long
                         # `cites` edge can pass BETWEEN two rows rather than over a box
_ASPECT = 1.35           # target width:height; the pane is landscape, so >1


def _citation_layers(nodes, edges):
    """Longest-path layer per node over the derived edge set.

    Depth is measured along edges that carry evidential or referential weight. `supersedes`
    is deliberately NOT one of them: a v2 supersedes a v1 without depending on it, they are
    usually published far apart, and layering by it would push corrections rightward forever
    while saying nothing about what rests on what.
    """
    ids = [n["data"]["id"] for n in nodes]
    idset = set(ids)
    structural = {"produced_by", "inputs", "grounded_by", "testimony", "cites",
                  "extracted_from", "used_models"}
    # child -> parents it points at (the things it cites)
    parents = {i: set() for i in ids}
    for e in edges:
        d = e["data"]
        if d["rel"] not in structural:
            continue
        s, t = d["source"], d["target"]
        if s in idset and t in idset and s != t:
            parents[s].add(t)

    depth, visiting = {}, set()

    def walk(i):
        if i in depth:
            return depth[i]
        if i in visiting:                    # cannot happen in a valid record; do not hang
            return 0
        visiting.add(i)
        d = 0
        for p in parents[i]:
            d = max(d, walk(p) + 1)
        visiting.discard(i)
        depth[i] = d
        return d

    for i in ids:
        walk(i)
    return depth


def _layout_overview(nodes, edges, order_hint):
    """Place every overview node. Layer = citation depth; within a layer, wrap and order to
    keep edges short and crossings few.

    `order_hint` maps node id -> a tiebreak key (publication index), so that within a layer
    the original reading order is preserved wherever the crossing heuristic is indifferent.
    Time is still legible in the picture; it is simply no longer the thing that decides x.
    """
    by_id = {n["data"]["id"]: n["data"] for n in nodes}
    if not by_id:
        return {}
    depth = _citation_layers(nodes, edges)
    layers = defaultdict(list)
    for i, d in depth.items():
        layers[d].append(i)

    # How tall may one layer be before it wraps into sub-columns?
    #
    # Depth alone fixes a floor on the width: n_layers columns at _MIN_DX apart. The only
    # freedom left is height, so choose the number of rows that brings the finished picture
    # closest to _ASPECT, and only wrap into sub-columns once a layer exceeds it.
    #
    # Solving width/height = _ASPECT for the row count, with width >= n_layers * _MIN_DX and
    # height = rows * _ROW_DY_L, gives rows = width / (_ASPECT * _ROW_DY_L). A record whose
    # chains are long is therefore drawn TALL rather than being allowed to run away
    # horizontally, which is the failure mode a pure depth layering has.
    n_total = len(by_id)
    n_layers = max(len(layers), 1)
    base_w = n_layers * _MIN_DX
    target_rows = int(math.ceil(base_w / (_ASPECT * _ROW_DY_L)))
    # Never fewer rows than the fullest layer needs to avoid gratuitous sub-columns, and
    # never more than would leave most of the band empty.
    fullest = max((len(v) for v in layers.values()), default=1)
    target_rows = max(target_rows, min(fullest, int(math.ceil(n_total / max(n_layers, 1)))))
    target_rows = max(3, min(target_rows, 14))

    # Neighbour sets for the crossing heuristic, over the same structural edges used above.
    nbr = defaultdict(set)
    for e in edges:
        d = e["data"]
        s, t = d["source"], d["target"]
        if s in by_id and t in by_id and s != t:
            nbr[s].add(t)
            nbr[t].add(s)

    # Initial order inside each layer: publication order.
    for d in layers:
        layers[d].sort(key=lambda i: order_hint.get(i, 0))
    pos_in_layer = {}
    for d, ids in layers.items():
        for k, i in enumerate(ids):
            pos_in_layer[i] = float(k)

    # Barycentre sweeps, the standard Sugiyama crossing heuristic: order each layer by the
    # mean position of each node's neighbours in the layer being swept from, then re-index.
    #
    # Two details matter and are easy to get wrong. The barycentre is taken over ONE adjacent
    # layer per sweep — the one already fixed — not over both at once; averaging both ends
    # pulls a node toward the middle of the picture and undoes the previous pass. And the
    # re-index has to happen after the sort, so the next layer sees ranks rather than raw
    # barycentres, which is what makes successive sweeps converge instead of oscillate.
    def sweep(dirn):
        ordered = sorted(layers) if dirn > 0 else sorted(layers, reverse=True)
        for d in ordered:
            prev = d - dirn
            if prev not in layers:
                continue
            bary = {}
            for i in layers[d]:
                near = [pos_in_layer[j] for j in nbr[i] if depth.get(j) == prev]
                bary[i] = (sum(near) / len(near)) if near else pos_in_layer[i]
            layers[d].sort(key=lambda i: (bary[i], order_hint.get(i, 0)))
            for k, i in enumerate(layers[d]):
                pos_in_layer[i] = float(k)

    def score():
        """Objective: crossings over ALL edges, plus total vertical stretch.

        Counting crossings only between adjacent layers — the textbook Sugiyama measure — is
        the wrong objective for this graph. Only 30 of its 74 derived edges join neighbouring
        layers; the rest are `cites` edges that jump three, four or six layers at a time, and
        those long edges are exactly the ones that were unreadable in the first place. An
        ordering tuned on adjacent pairs alone can and does make the picture worse.

        So every edge is scored, whatever it spans, by testing each pair for an actual
        geometric crossing in (layer, row) space. Total row displacement is added with a small
        weight as a tiebreak, which keeps a chain of related artifacts roughly level instead
        of letting it zigzag between equally crossing-free orderings.
        """
        segs = []
        for e in edges:
            d = e["data"]
            s, t = d["source"], d["target"]
            if s in depth and t in depth and s != t:
                segs.append((depth[s], pos_in_layer[s], depth[t], pos_in_layer[t]))
        cross = 0
        for a in range(len(segs)):
            x1, y1, x2, y2 = segs[a]
            for b in range(a + 1, len(segs)):
                x3, y3, x4, y4 = segs[b]
                den = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
                if abs(den) < 1e-9:
                    continue
                ta = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / den
                tb = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / den
                if 0.02 < ta < 0.98 and 0.02 < tb < 0.98:
                    cross += 1
        stretch = sum(abs(s[1] - s[3]) for s in segs)
        return cross + 0.05 * stretch

    best = {i: pos_in_layer[i] for i in pos_in_layer}
    best_s = score()
    for _ in range(6):
        sweep(+1)
        sweep(-1)
        s = score()
        if s < best_s:
            best_s, best = s, {i: pos_in_layer[i] for i in pos_in_layer}

    # Greedy repair: try swapping adjacent nodes within a layer and keep any swap that
    # lowers the objective. The sweeps optimise neighbouring layers and are blind to the
    # long `cites` edges; this pass sees them, and on a record this size it is cheap.
    pos_in_layer = dict(best)
    for d in layers:
        layers[d].sort(key=lambda i: pos_in_layer[i])
    improved = True
    guard = 0
    while improved and guard < 40:
        improved = False
        guard += 1
        for d in sorted(layers):
            ids = layers[d]
            for k in range(len(ids) - 1):
                a, b = ids[k], ids[k + 1]
                pos_in_layer[a], pos_in_layer[b] = pos_in_layer[b], pos_in_layer[a]
                s = score()
                if s < best_s - 1e-9:
                    best_s = s
                    ids[k], ids[k + 1] = b, a
                    improved = True
                else:
                    pos_in_layer[a], pos_in_layer[b] = pos_in_layer[b], pos_in_layer[a]
    for d in layers:
        layers[d].sort(key=lambda i: (pos_in_layer[i], order_hint.get(i, 0)))
        for k, i in enumerate(layers[d]):
            pos_in_layer[i] = float(k)

    # Lay each layer out as a band: wrap at target_rows into sub-columns. A band's width is
    # its own, so a crowded layer widens the graph locally instead of stretching every layer.
    layer_x, x = {}, 0.0
    for d in sorted(layers):
        layer_x[d] = x
        subcols = max(1, -(-len(layers[d]) // target_rows))          # ceil
        width = (subcols - 1) * _SUB_DX_L
        x += width + _MIN_DX

    out = {}
    for d in sorted(layers):
        ids = layers[d]
        for k, i in enumerate(ids):
            sub, row = divmod(k, target_rows)
            rows_here = min(target_rows, len(ids) - sub * target_rows)
            out[i] = {"x": layer_x[d] + sub * _SUB_DX_L,
                      "y": (row - (rows_here - 1) / 2.0) * _ROW_DY_L}
    return out


def apply_pins(positions, pins):
    """Overlay saved manual positions on computed ones.

    Pins are a reader's own arrangement, held in a sidecar file beside the record and never
    inside an artifact. A pin for a node that has since left the record is ignored rather
    than being an error, so a stale pin file degrades quietly instead of breaking the build.
    Returns the set of ids that were actually pinned.
    """
    used = set()
    for name, p in (pins or {}).items():
        if name in positions and isinstance(p, dict) and "x" in p and "y" in p:
            try:
                positions[name] = {"x": float(p["x"]), "y": float(p["y"])}
                used.add(name)
            except (TypeError, ValueError):
                continue
    return used


def build_overview(artifacts, index, colors, pages, findings_by, pins=None, annotations=None):
    nodes, edges = [], []
    stamps = []
    for a in artifacts:
        t = parse_instant(a["artifact"].get("created"))
        stamps.append(t.timestamp() if t else None)

    # columns = publication order, broken into sessions wherever the record went quiet
    known = [s for s in stamps if s is not None]
    cols, cur = {}, 0
    prev = None
    for a, s in zip(artifacts, stamps):
        if s is not None and prev is not None and s - prev > _SESSION_GAP:
            cur += 1
        cols[a["artifact"]["name"]] = cur
        if s is not None:
            prev = s

    order = {t: i for i, t in enumerate(
        ["Report", "ScientificPublication", "Data", "Analysis", "Model", "Argument", "Message"])}

    # Type bands are sized to their busiest column, not fixed, so a column holding
    # three imports cannot push its third one down into the band below. Without this
    # the picture reads wrongly at exactly the moment it matters — a burst of imports.
    occupancy = defaultdict(int)
    for a in artifacts:
        occupancy[(cols[a["artifact"]["name"]], order.get(a["artifact"]["type"], 7))] += 1
    band_height = defaultdict(int)
    for (c, r), n in occupancy.items():
        band_height[r] = max(band_height[r], min(n, _BAND_MAX_ROWS))
    band_top, y = {}, 0.0
    for r in sorted(band_height):
        band_top[r] = y
        y += band_height[r] * _ROW_DY + _BAND_GAP

    # A session is as wide as its busiest band needs, so sessions never overlap however
    # lopsided the day was.
    sub_wide = defaultdict(int)
    for (c, r), n in occupancy.items():
        sub_wide[c] = max(sub_wide[c], -(-n // _BAND_MAX_ROWS))       # ceil
    col_x, x = {}, 0.0
    for c in sorted(set(cols.values())):
        col_x[c] = x
        x += max(sub_wide.get(c, 1), 1) * _SUB_DX + _COL_GAP

    rows = defaultdict(int)
    for a in artifacts:
        h = a["artifact"]
        name, typ = h["name"], h["type"]
        owner = h.get("published_by", "").lstrip("@")
        c = cols[name]
        r = order.get(typ, 7)
        rows[(c, r)] += 1
        title = h.get("title") or name
        fs = findings_by.get(name, [])
        nodes.append({"data": {
            "id": name, "ntype": typ, "label": title,
            "member": owner, "owner_color": colors.get(owner, "#9ca3af"),
            "shape": _SHAPE.get(typ, "ellipse"),
            "nav_file": pages.get(name),
            "page_kind": "claimmap" if typ == ARGUMENT else "evidence",
            "full": {"name": name, "type": typ, "title": h.get("title"),
                     "created": h.get("created"),
                     "object_count": len(a.get("objects", [])),
                     "import_method": h.get("import_method"),
                     "modeling_choices": h.get("modeling_choices"),
                     "procedure": h.get("procedure"),
                     "groundable": False if typ in NON_GROUNDABLE_TYPES else None},
            "tooltip": f"{typ} · {owner}\n{title}"
                       + (f"\n{len(fs)} checker finding(s)" if fs else ""),
            "_pos": {"x": 0.0, "y": 0.0},      # replaced below, once edges are known
        }})

    # Every edge here is DERIVED from an address in a property value; the record stores no
    # cross-artifact relationship. Grouped by (source, target, kind) and counted.
    agg = defaultdict(int)
    for a in artifacts:
        h = a["artifact"]
        src = h["name"]

        def link(addr, rel):
            p = parse_address(addr or "")
            if p and p["root"] in index and p["root"] != src:
                agg[(src, p["root"], rel)] += 1

        for k in ("produced_by", "extracted_from"):
            link(h.get(k), k)
        for k in ("inputs", "used_models", "outputs", "supersedes", "recipients"):
            for v in (h.get(k) or []):
                link(v, k)
        for o in a.get("objects", []):
            if o.get("type") == "Ground":
                addr = o.get("citation", "")
                p = parse_address(addr)
                tgt = index.get(p["root"]) if p else None
                is_testimony = False
                if tgt and p:
                    seg = p["segs"]
                    is_testimony = bool(seg and (tgt["objects"].get(seg[0], {}) or {}
                                                 ).get("type") == "Assertion")
                link(addr, "testimony" if is_testimony else "grounded_by")
        for addr in cited_addresses(a):
            link(addr, "cites")

    for (s, t, rel), n in sorted(agg.items()):
        edges.append({"data": {
            "id": f"o_{s}__{rel}__{t}", "source": s, "target": t, "rel": rel, "count": n,
            "label": rel if n == 1 else f"{rel} ×{n}",
            "_col": T.OVERVIEW_REL_COLORS.get(rel, "#94a3b8"),
            "cpd": 0 if s == t else 26,
            "span": 1,          # layer distance; filled in once positions are known
            "tooltip": f"{rel} ×{n}\n{s} → {t}\nderived from an address in a property value",
        }})

    # Positions are computed HERE, not in the node loop above, because layering needs the
    # derived edges and those are only known once every artifact has been read.
    order_hint = {a["artifact"]["name"]: k for k, a in enumerate(artifacts)}
    positions = _layout_overview(nodes, edges, order_hint)
    pinned = apply_pins(positions, pins)
    for n in nodes:
        p = positions.get(n["data"]["id"])
        if p:
            n["data"]["_pos"] = p
        n["data"]["_pinned"] = n["data"]["id"] in pinned

    # Curvature is set from how many columns an edge crosses. A short edge stays nearly
    # straight; a long one bows, and successive long edges between the same pair of columns
    # bow by different amounts so they separate instead of overprinting. The sign alternates
    # so that a bundle of long edges fans out on both sides of the straight line rather than
    # piling up on one.
    xs = sorted({round(p["x"]) for p in positions.values()})
    layer_of = {x: i for i, x in enumerate(xs)}
    fan = defaultdict(int)
    for e in edges:
        d = e["data"]
        ps, pt = positions.get(d["source"]), positions.get(d["target"])
        if not (ps and pt):
            continue
        span = abs(layer_of.get(round(ps["x"]), 0) - layer_of.get(round(pt["x"]), 0))
        d["span"] = span
        if d["source"] == d["target"]:
            d["cpd"] = 0
            continue
        key = (min(round(ps["x"]), round(pt["x"])), max(round(ps["x"]), round(pt["x"])))
        k = fan[key]
        fan[key] += 1
        base = 18 + 22 * max(span - 1, 0)
        d["cpd"] = (base + 16 * (k // 2)) * (1 if k % 2 == 0 else -1)
        d["tooltip"] += f"\nspans {span} column(s)"

    # Presenter captions. They are nodes so that they pan, zoom and export with the graph
    # rather than floating over it in screen coordinates, and they carry a distinct ntype so
    # nothing downstream mistakes one for an artifact: they are excluded from every count, are
    # not clickable, and have no edges.
    for k, ann in enumerate(annotations or []):
        nodes.append({"data": {
            "id": f"__annotation_{k}", "ntype": "Annotation", "label": ann["text"],
            "member": "", "owner_color": "#64748b", "shape": "round-rectangle",
            "nav_file": None, "page_kind": None, "full": None,
            "tooltip": "presenter annotation — not part of the record",
            "_pos": {"x": ann["x"], "y": ann["y"]}, "_pinned": True,
        }})

    by_member, by_type = defaultdict(int), defaultdict(int)
    for a in artifacts:
        by_member[a["artifact"].get("published_by", "").lstrip("@")] += 1
        by_type[a["artifact"]["type"]] += 1
    span = ""
    if known:
        lo = min(a["artifact"].get("created") or "" for a in artifacts)
        hi = max(a["artifact"].get("created") or "" for a in artifacts)
        span = f"{lo[:16].replace('T', ' ')} → {hi[11:16]}"
    meta = {
        "members": {m: colors.get(m, "#9ca3af") for m in by_member},
        "counts": {"artifacts": len(artifacts), "by_member": dict(by_member),
                   "by_type": dict(by_type), "cross_edges": len(edges),
                   "sessions": cur + 1, "time_span": span, "pinned": len(pinned)},
    }
    return {"nodes": nodes, "edges": edges}, meta


# --------------------------------------------------------------------------- #
# Artifact pages (everything that is not an Argument)
# --------------------------------------------------------------------------- #

def is_table_method(content):
    """Does this Content Object describe row/column addressing?

    `method_of` is the validator's, not a copy: a Content name carries an optional label in
    front of its method (`pooled_csv`, `control_rows_csv`), and a browser that derived the
    method by its own rule would eventually disagree with the gate about what an address
    means. The `addressing_method` fallback catches a Content whose name declares no known
    method — the validator REVIEWs that rather than refusing it, so it reaches these pages."""
    am = content.get("addressing_method") or ""
    return method_of(content.get("name", "")) == "csv" or ("row=" in am and "col=" in am)


def table_method_for(prop, methods):
    """Which declared Content addresses this property's table?

    The specification does not bind a Content Object to the property it describes: the
    binding lives in the address, `@artifact.<property>#<content>.row=...`, so the browser
    has to recover it. Members name the pair by a common stem — `pooled_effects` with
    `pooled_csv`, `control_rows` with `control_rows_csv`, `inventory` with `inventory_csv`
    — so the stem is what is matched, longest first, and a single table Content on the
    artifact needs no matching at all.

    Getting this wrong is not cosmetic. The cell ids written from it are what a Ground's
    address resolves to, and until this existed every table emitted ids under the literal
    name `csv`, so following a Ground into any artifact whose Content is named anything
    else landed the reader at the top of the page instead of on the value."""
    tables = [m for m in methods if is_table_method(m)]
    if not tables:
        return "csv"
    if len(tables) == 1:
        return tables[0]["name"]
    best, best_len = None, -1
    for m in tables:
        stem = m["name"][:-4] if m["name"].endswith("_csv") else m["name"]
        if not stem:
            continue
        if prop.startswith(stem) or stem.startswith(prop):
            if len(stem) > best_len:
                best, best_len = m["name"], len(stem)
    return best or tables[0]["name"]


def looks_tabular(value, declares_table, max_header=60):
    """Is this property value an embedded table, rather than prose that has commas in it?

    This used to be `"\\n" in v and "," in v.split("\\n")[0]`, which is true of almost every
    long prose property anyone writes. It rendered every `import_method` in the record as a
    table, and that is not a cosmetic fault: splitting prose on commas broke `4,364,823
    bytes` into three cells and `19,113 data rows` into two, so the page displayed numbers
    the artifact does not contain.

    Three conditions, all necessary. The artifact must DECLARE a row/column Content, because
    a table nobody can address is not what this section is for. The value must parse as
    rectangular CSV, which prose never does. And the header cells must be short, because a
    two-line description whose lines happen to carry equal numbers of commas is not a table
    with a 490-character column name."""
    if not declares_table or not isinstance(value, str) or "\n" not in value:
        return False
    try:
        rows = [r for r in csv.reader(io.StringIO(value)) if any(c.strip() for c in r)]
    except (csv.Error, ValueError):
        return False
    if len(rows) < 2 or len(rows[0]) < 2:
        return False
    if any(len(r) != len(rows[0]) for r in rows):
        return False
    return not any(len(c) > max_header for c in rows[0])

# A stable palette for community-defined Object types. The vocabulary outside an Argument is
# OPEN (spec 1.6): a Model declares whatever types its author needs, and this browser cannot
# know them in advance. So types are coloured by order of first appearance rather than from a
# fixed table, which keeps one artifact's colouring stable across rebuilds without pretending
# to know what `HostComplex` means.
_OBJ_PALETTE = ["#2563eb", "#0d9488", "#c2410c", "#7c3aed", "#b45309",
                "#db2777", "#4338ca", "#15803d", "#9f1239", "#0369a1"]
_OBJ_SHAPES = ["round-rectangle", "ellipse", "diamond", "hexagon", "pentagon",
               "octagon", "vee", "rhomboid"]


def internal_graph(doc):
    """The Objects an Artifact contains and the relationships among them.

    The specification's structural claim is that an Artifact IS a property graph (spec 1.7):
    Objects, and relationships among those Objects, all internal. For an Argument that graph is
    drawn by the claim map. For everything else it was not drawn at all — so a Model published
    as thirteen nodes and fifteen edges rendered as a page of prose with no way to see that
    `vatpase` existed, let alone what it connected to, while its own `graph` Content invited a
    reader to address `node=vatpase`.

    Content Objects are excluded. They describe how to reach the artifact's content and are
    already listed in "How to reach this content"; drawing them here would put the addressing
    scheme in the same picture as the subject matter.

    Returns None when there is nothing structural to draw, so a plain Data artifact with one
    Content Object does not get an empty graph pane.
    """
    objs = [o for o in doc.get("objects", []) if o.get("type") != "Content"]
    if not objs:
        return None
    rels = doc.get("relationships", []) or []
    names = {o["name"] for o in objs}

    types, shapes = {}, {}
    for o in objs:
        t = o.get("type") or "Object"
        if t not in types:
            types[t] = _OBJ_PALETTE[len(types) % len(_OBJ_PALETTE)]
            shapes[t] = _OBJ_SHAPES[len(shapes) % len(_OBJ_SHAPES)]

    nodes = []
    for o in objs:
        t = o.get("type") or "Object"
        label = o.get("title") or o["name"]
        # Every property the author wrote, minus the two already shown as the node's identity.
        # A Model's degrees of freedom live in these; a reader who cannot see them is reading a
        # diagram with the disclosure removed.
        props = {k: v for k, v in o.items() if k not in ("name", "type", "title")}
        nodes.append({"data": {
            "id": o["name"], "label": label, "otype": t,
            "color": types[t], "shape": shapes[t],
            "tooltip": f"{t} · {o['name']}" + (f"\n{o.get('description','')[:160]}"
                                               if o.get("description") else ""),
            "props": props,
            "oname": o["name"],
        }})

    # Relationship vocabulary is open too, so edges are keyed by their own `rel` and coloured
    # by first appearance. An edge naming an endpoint this Artifact does not contain is a
    # defect the validator reports; it is dropped here rather than drawn into nowhere.
    edges, rel_colors, dropped = [], {}, 0
    for i, r in enumerate(rels):
        rel = r.get("rel") or r.get("type") or "related"
        s, t = r.get("source"), r.get("target")
        if s not in names or t not in names:
            dropped += 1
            continue
        if rel not in rel_colors:
            rel_colors[rel] = _OBJ_PALETTE[(len(rel_colors) + 3) % len(_OBJ_PALETTE)]
        extra = {k: v for k, v in r.items() if k not in ("rel", "type", "source", "target")}
        tip = f"{s} --{rel}--> {t}"
        for k, v in extra.items():
            tip += f"\n{k}: {v}"
        edges.append({"data": {
            "id": f"r{i}_{s}__{rel}__{t}", "source": s, "target": t, "rel": rel,
            "label": rel.replace("_", " "), "color": rel_colors[rel],
            "tooltip": tip, "props": extra,
        }})

    return {
        "elements": {"nodes": nodes, "edges": edges},
        "legend": {"types": types, "shapes": shapes, "rels": rel_colors},
        "counts": {"objects": len(nodes), "relationships": len(edges), "dropped": dropped},
    }


def layout_internal(graph):
    """Positions for an Artifact's internal graph.

    The overview's layered layout assumes a DAG, which is guaranteed there by serial
    publication. Inside one Artifact there is no such guarantee: a Model may legitimately
    state a cycle — A activates B, B inhibits A — and a longest-path layering would either
    hang or silently misdraw it. So this walks breadth-first from the nodes nothing points at,
    which degrades gracefully on a cycle, and falls back to a ring when everything is cyclic.
    """
    nodes = graph["elements"]["nodes"]
    edges = graph["elements"]["edges"]
    ids = [n["data"]["id"] for n in nodes]
    indeg = {i: 0 for i in ids}
    out = defaultdict(list)
    for e in edges:
        s, t = e["data"]["source"], e["data"]["target"]
        out[s].append(t)
        indeg[t] = indeg.get(t, 0) + 1

    roots = [i for i in ids if indeg.get(i, 0) == 0] or [ids[0]]
    depth, seen = {}, set()
    frontier, d = list(roots), 0
    while frontier:
        nxt = []
        for i in frontier:
            if i in seen:
                continue
            seen.add(i)
            depth[i] = d
            for j in out.get(i, []):
                if j not in seen:
                    nxt.append(j)
        frontier, d = nxt, d + 1
    for i in ids:                       # anything only reachable inside a cycle
        depth.setdefault(i, d)

    cols = defaultdict(list)
    for i in ids:
        cols[depth[i]].append(i)
    DX, DY = 260.0, 104.0
    for c in cols:
        cols[c].sort()
    pos = {}
    for c, group in cols.items():
        for k, i in enumerate(group):
            pos[i] = {"x": c * DX, "y": (k - (len(group) - 1) / 2.0) * DY}
    for n in nodes:
        n["data"]["_pos"] = pos.get(n["data"]["id"], {"x": 0.0, "y": 0.0})
    return graph


def render_artifact_page(doc, index, colors, pages, findings, cyto, spans=None):
    h = doc["artifact"]
    name, typ = h["name"], h["type"]
    owner = h.get("published_by", "").lstrip("@")
    esc = html.escape

    spans = spans or {}

    def prose(text, prop=None):
        return T.md_to_html(str(text), pages, spans.get(prop) if prop else None)

    parts = []
    if typ in NON_GROUNDABLE_TYPES:
        parts.append('<div class="banner">Non-groundable by type (spec §2.1). Everything here '
                     'may be cited in prose and none of it may be used as a Ground.</div>')

    # The Artifact's own Objects and the relationships among them (spec §1.6, §1.7). An
    # Argument's structure is drawn by its claim map, so this is for everything else — most
    # visibly a Model, whose whole content is a graph and which until now rendered as prose
    # with its nodes and edges nowhere on the page.
    ig = internal_graph(doc)
    if ig and typ != ARGUMENT:
        layout_internal(ig)
        parts.append(T.internal_graph_section(ig, name, typ))

    # Spec §1.8.1 calls this Object type `Content`. It was `AddressingMethod` in an earlier
    # draft, and reading the old name here meant this table matched nothing and never
    # rendered — so every artifact page in the record silently omitted the one section that
    # says what may be cited and how to write the address.
    methods = [o for o in doc.get("objects", []) if o.get("type") == "Content"]
    if methods:
        rows = "".join(
            '<tr><td><code>{}</code></td><td>{}</td><td>{}</td></tr>'.format(
                esc(m["name"]),
                ('<span class="yes">groundable</span>' if m.get("groundable")
                 and typ not in NON_GROUNDABLE_TYPES else '<span class="no">addressable only</span>'),
                esc(m.get("description", "")))
            for m in methods)
        parts.append('<h2>How to reach this content</h2>'
                     '<p class="hint">An artifact with no addressing method is inert — nobody can '
                     'ground on a single value in it. A method marked <i>addressable only</i> can '
                     'be pointed at but not used as evidence.</p>'
                     f'<table class="methods"><tr><th>method</th><th></th><th>reference form</th></tr>'
                     f'{rows}</table>')

    # Properties whose value IS an address (spec §1.5, §2.5). They are the record's formal
    # provenance and its only machine-readable links between artifacts, and until this was
    # here they printed as literal `@name` text: a reader could see that a table was
    # produced by an Analysis and had no way to open it.
    def addr_link(a):
        a = str(a)
        root = a.lstrip("@").split("#")[0].split(".")[0]
        title = (index.get(root, {}).get("header", {}) or {}).get("title")
        if root not in pages:
            return f"<code>{esc(a)}</code>"          # a Member, or something unresolved
        label = esc(title) if title else f"<code>{esc(a)}</code>"
        return (f'<a href="{esc(pages[root])}">{label}</a> '
                f'<span class="hint"><code>{esc(a)}</code></span>')

    declares_table = any(is_table_method(m) for m in methods)
    for k, v in h.items():
        if k in ("name", "type", "specification_version", "published_by", "created", "title"):
            continue
        if k in ADDRESS_PROPS:
            vs = v if isinstance(v, list) else [v]
            parts.append(f"<h2>{esc(k)}</h2><ul>"
                         + "".join(f"<li>{addr_link(x)}</li>" for x in vs) + "</ul>")
        elif k == "code" and isinstance(v, str):
            # An Analysis carries its procedure's code verbatim. Run through the prose
            # renderer it lost every indent and every `#` comment line became a heading,
            # which is the one property where whitespace is the meaning. Grounded passages
            # are still marked: a Content may declare a `text_span` method over code.
            parts.append(f"<h2>{esc(k)}</h2>" + T.preformatted(v, spans.get(k)))
        elif isinstance(v, str) and looks_tabular(v, declares_table):
            parts.append(f"<h2>{esc(k)}</h2>"
                         + T.csv_table(v, method=table_method_for(k, methods)))
        elif isinstance(v, list):
            parts.append(f"<h2>{esc(k)}</h2><ul>"
                         + "".join(f"<li>{prose(x)}</li>" for x in v) + "</ul>")
        elif isinstance(v, str):
            parts.append(f"<h2>{esc(k)}</h2><div class='prose'>{prose(v, k)}</div>")
        else:
            parts.append(f"<h2>{esc(k)}</h2><div class='prose'><code>{esc(json.dumps(v))}</code></div>")

    if findings:
        items = "".join(
            '<div class="finding{}"><b>{}</b> — {}</div>'.format(
                " fail" if f["level"] == "FAIL" else "", esc(f["check"]), esc(f["msg"]))
            for f in findings)
        parts.append("<h2>Noted by the checker</h2>" + items)

    return T.ARTIFACT_TEMPLATE.format(
        title=esc(h.get("title") or name),
        name=esc(name), atype=esc(typ), member=esc(owner),
        member_color=esc(colors.get(owner, "#9ca3af")),
        created=esc(h.get("created") or "(unstamped)"),
        body="".join(parts),
        cyto_src=esc(cyto),
    )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def grounded_spans(artifacts):
    """artifact name -> {property: [(quote, citing artifact)]}.

    An imported source should show which of its passages the community has actually
    stood on. That is the importer's work made visible: whoever grounds on an import
    can reach only what was preserved, so seeing WHICH sentences carry weight is how
    you tell a good import from a lucky one.
    """
    out = defaultdict(lambda: defaultdict(list))
    for a in artifacts:
        for o in a.get("objects", []):
            if o.get("type") != "Ground":
                continue
            p = parse_address(o.get("citation", ""))
            if not p or p["method"] != "text_span" or not p["segs"]:
                continue
            q = re.search(r'quote="([^"]*)"', p["ref"] or "")
            if q:
                out[p["root"]][p["segs"][0]].append((q.group(1), a["artifact"]["name"]))
    return out


def evidence_table(doc, index, pages):
    """Every Ground of an Argument in one table, under the Assertion it bears on.

    The claim map folds nine Grounds into nine edges, so reading what an Argument
    actually stands on meant opening nine of them one at a time. A critic's first question
    of any Argument is what its Grounds reach and whether a criterion could have come out
    the other way; that question deserves a page, not a sequence of clicks.

    The columns are the ones the specification says carry the judgment: what was addressed,
    how it bears on the claim, and whether the author offered it as a test (§2.2.4)."""
    objs = {o["name"]: o for o in doc.get("objects", [])}
    rels = doc.get("relationships", [])
    esc = html.escape
    by_assertion = defaultdict(list)
    for r in rels:
        if (r.get("rel") or r.get("type")) == "grounded_by":
            g = objs.get(r.get("target"))
            if g:
                by_assertion[r.get("source")].append(g)
    if not by_assertion:
        return ""

    primary = doc["artifact"].get("primary_assertion", "")
    order = [primary] + [a for a in by_assertion if a != primary]
    rows = []
    for aname in order:
        grounds = by_assertion.get(aname)
        if not grounds:
            continue
        a = objs.get(aname, {})
        rows.append(
            '<tr class="assertion"><td colspan="3"><b>{}</b>{}<div class="hint">{}</div></td></tr>'
            .format(esc(a.get("claim", aname)),
                    ' <span class="pill-primary">primary</span>' if aname == primary else "",
                    "scope — " + esc(a.get("scope", "")) if a.get("scope") else ""))
        for g in grounds:
            addr = g.get("citation", "")
            root = addr.lstrip("@").split("#")[0].split(".")[0]
            frag = address_fragment(addr)
            if root in pages:
                href = pages[root] + (f"#{frag}" if frag else "")
                target = (f'<a href="{esc(href)}">{esc(pretty_address(addr, index))}</a>'
                          f'<div class="hint"><code>{esc(addr)}</code></div>')
            else:
                target = f"<code>{esc(addr)}</code>"
            crit = (f'<div class="crit"><b>Criterion.</b> {esc(g["criterion"])}</div>'
                    if g.get("criterion")
                    else '<div class="hint">No criterion: material built on, '
                         'not a test the claim survived.</div>')
            rows.append('<tr><td class="gname"><code>{}</code></td><td>{}</td>'
                        '<td>{}{}</td></tr>'.format(
                            esc(g["name"]), target, esc(g.get("rationale", "")), crit))
    return ('<h3 class="evh">What this Argument stands on</h3>'
            '<p class="hint">Every Ground, under the Assertion it bears on. A Ground with a '
            '<b>criterion</b> asserts the material was used as a test that could have counted '
            'against the claim; one without offers the material as something built upon '
            '(spec §2.2.4). Follow a target to land on the value itself.</p>'
            '<table class="evidence"><tr><th>Ground</th><th>addresses</th>'
            '<th>how it bears, and whether it was a test</th></tr>'
            + "".join(rows) + "</table>")


def render_reading_page(doc, index, pages, reading_name):
    """The Argument's prose and evidence, as a page that scrolls.

    Everything an author is required to write for a reader — `verdict`, `purpose`,
    `rationale` — plus every Ground under the Assertion it bears on. The claim map keeps the
    structure; this keeps the argument."""
    h = doc["artifact"]
    esc = html.escape
    parts = []
    if h.get("verdict"):
        parts.append('<h2 class="sec">Verdict</h2>'
                     f'<div class="verdict-lead">{esc(h["verdict"])}</div>')
    for label, key in (("Purpose and stakes", "purpose"), ("Rationale", "rationale"),
                       ("Description", "description"), ("Text", "text")):
        if h.get(key):
            parts.append(f'<h2 class="sec">{label}</h2>'
                         f'<div class="prose">{T.md_to_html(h[key], pages)}</div>')
    if h.get("supersedes"):
        parts.append('<h2 class="sec">Supersedes</h2><div class="prose">'
                     + ", ".join(f"<code>{esc(str(x))}</code>" for x in h["supersedes"])
                     + (f'<p>{esc(h.get("supersedes_rationale", ""))}</p>'
                        if h.get("supersedes_rationale") else "") + "</div>")
    parts.append(evidence_table(doc, index, pages))
    byline = "{} · {} · {}".format(
        (h.get("published_by") or "").lstrip("@"), (h.get("created") or "")[:16],
        ", ".join(h.get("authors") or []))
    return T.render_reading_html(h.get("title") or h["name"], byline,
                                 pages[h["name"]], "".join(parts))


def contents_entries(artifacts, colors, pages, findings_by):
    """Rows for the reading list: what a reader needs to decide whether to open a page.

    An Argument carries the first two sentences of its `verdict`, because a verdict is a
    judgment for a stated purpose and its opening clause is the thing a reader is looking
    for. Nothing else on this page is prose from the artifact: a title is the author's own
    summary and standing in for it here would be editorialising."""
    rows = []
    for a in artifacts:
        h = a["artifact"]
        name, typ = h["name"], h["type"]
        verdict = ""
        if typ == ARGUMENT and h.get("verdict"):
            parts = re.split(r"(?<=[.!?])\s+", h["verdict"].strip())
            verdict = " ".join(parts[:2])
        extra = []
        if typ == ARGUMENT:
            n = sum(1 for o in a.get("objects", []) if o.get("type") == "Ground")
            crit = sum(1 for o in a.get("objects", [])
                       if o.get("type") == "Ground" and o.get("criterion"))
            extra.append(f"{n} Ground(s), {crit} offered as a test")
        if h.get("supersedes"):
            extra.append(f"supersedes {len(h['supersedes'])}")
        if findings_by.get(name):
            extra.append(f"{len(findings_by[name])} checker finding(s)")
        # An Argument's entry here goes to the document, not to the graph. Someone arriving
        # from a contents page has come to read; the claim map is one click further on and
        # is linked from it. Arriving from the reference graph still lands on the map.
        href = (pages[name].replace(".html", "_reading.html") if typ == ARGUMENT
                else pages[name])
        rows.append({
            "name": name, "type": typ, "href": href,
            "title": h.get("title") or name,
            "member": h.get("published_by", "").lstrip("@"),
            "color": colors.get(h.get("published_by", "").lstrip("@"), "#9ca3af"),
            "created": h.get("created") or "", "verdict": verdict,
            "extra": " · ".join(extra),
        })
    return rows


PIN_FILE = ".browser_layout.json"


def load_pins(record_dir):
    """Read manual node positions saved beside the record.

    The file sits in the record directory next to the artifacts but is not one of them: it
    holds a reader's arrangement of the picture, which is a viewing preference and not part
    of the permanent record. `load_record` only reads canonical artifacts, so a dotfile here
    is invisible to the gate, to validation and to the mirror comparison.

    A missing or malformed file is not an error. The whole point of the feature is that the
    layout survives a rebuild; refusing to build because someone hand-edited the sidecar into
    invalid JSON would trade a cosmetic loss for a broken browser.
    """
    p = pathlib.Path(record_dir) / PIN_FILE
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print(f"  warning: ignoring unreadable {PIN_FILE}", file=sys.stderr)
        return {}
    pos = raw.get("positions") if isinstance(raw, dict) else None
    return pos if isinstance(pos, dict) else {}


def load_annotations(record_dir):
    """Free text the presenter has placed on the overview, from the same sidecar.

    An annotation is a caption on the picture, not a statement in the record: "more analytic
    work not shown" standing where a reader has hidden a section, a label over a cluster. It
    carries no address, nothing can cite it, and the gate never sees it — it lives beside the
    artifacts in the same dotfile as the manual positions, for the same reason and with the
    same failure behaviour.

    Returns a list of {text, x, y} with anything malformed dropped, because a mistyped caption
    must cost the caption and not the build.
    """
    p = pathlib.Path(record_dir) / PIN_FILE
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = raw.get("annotations") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for a in items:
        if not isinstance(a, dict):
            continue
        t = a.get("text")
        try:
            x, y = float(a["x"]), float(a["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(t, str) and t.strip():
            out.append({"text": t.strip()[:200], "x": x, "y": y})
    return out


def compile_record(record_dir, out_dir, cyto="vendor/cytoscape.min.js", title=None, quiet=False,
                   figures_dir=None):
    artifacts = load_record(record_dir)
    if not artifacts:
        raise SystemExit(f"ERROR: no canonical artifacts found in {record_dir}")
    colors = member_colors(artifacts)
    members = set(colors)
    index = build_index(artifacts)
    findings_by = run_validator(artifacts, members)
    spans = grounded_spans(artifacts)
    pages = {a["artifact"]["name"]: page_name(a["artifact"]["name"]) for a in artifacts}

    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    vendor_src = pathlib.Path(__file__).resolve().parent / "vendor" / "cytoscape.min.js"
    if vendor_src.is_file():
        (out / "vendor").mkdir(exist_ok=True)
        shutil.copy2(vendor_src, out / "vendor" / "cytoscape.min.js")

    n_arg = 0
    figs = []
    for a in artifacts:
        name = a["artifact"]["name"]
        fs = findings_by.get(name, [])
        if a["artifact"]["type"] == ARGUMENT:
            collapsed, _full, meta = build_claim_graph(a, index, fs, colors, pages)
            # The header's own prose is where the author says what the argument is doing
            # and cites the work it answers. It is not in the graph and would otherwise
            # be invisible on the page that most needs it.
            reading = page_name(name).replace(".html", "_reading.html")
            intro = ('<p><a href="{}"><b>Read this Argument as a document &rarr;</b></a> '
                     '<span class="hint">verdict, purpose, rationale and every Ground in '
                     'one place</span></p>'.format(html.escape(reading)))
            intro += "".join(T.md_to_html(a["artifact"][k], pages)
                             for k in ("description", "text") if a["artifact"].get(k))
            (out / pages[name]).write_text(
                T.render_claim_html(collapsed, meta, cyto, intro_html=intro), encoding="utf-8")
            (out / reading).write_text(
                render_reading_page(a, index, pages, reading), encoding="utf-8")
            if figures_dir:
                # Same precomputed positions as the page, so the figure IS the
                # picture the reader saw — only unelided and print-scaled.
                figs.append((re.sub(r"[^A-Za-z0-9._-]", "_", name),
                             F.render_claim_svg(collapsed, meta, title=meta["title"])))
            n_arg += 1
            if not quiet:
                c = meta["counts"]
                print(f"  Argument  {name:44s} {c['nodes_total']:3d} nodes / "
                      f"{c['edges_total']:3d} edges · {c['folded_grounds']} Ground(s)"
                      + (f" · {len(fs)} finding(s)" if fs else ""))
        else:
            (out / pages[name]).write_text(
                render_artifact_page(a, index, colors, pages, fs, cyto,
                                     spans.get(name, {})), encoding="utf-8")
            if not quiet:
                print(f"  {a['artifact']['type']:9s} {name}"
                      + (f"  · {len(fs)} finding(s)" if fs else ""))

    if figures_dir and figs:
        written = F.write_figures(figs, out / figures_dir)
        if not quiet:
            print(f"\n  {len(written)} figure(s) -> {out / figures_dir}")
            for w in written:
                print(f"    {w.name}")

    pins = load_pins(record_dir)
    annotations = load_annotations(record_dir)
    elements, meta = build_overview(artifacts, index, colors, pages, findings_by,
                                    pins=pins, annotations=annotations)
    meta["counts"]["findings"] = sum(len(v) for v in findings_by.values())
    meta["pin_file"] = PIN_FILE
    if not quiet and meta["counts"].get("pinned"):
        print(f"  {meta['counts']['pinned']} pinned position(s) from {PIN_FILE}")
    (out / "index.html").write_text(
        T.render_overview_html(elements, meta, cyto,
                               corpus_title=title or "community record"), encoding="utf-8")
    (out / "contents.html").write_text(
        T.render_contents_html(contents_entries(artifacts, colors, pages, findings_by),
                               corpus_title=title or "community record"), encoding="utf-8")

    manifest = {
        "artifacts": len(artifacts), "arguments": n_arg,
        "by_type": meta["counts"]["by_type"], "by_member": meta["counts"]["by_member"],
        "findings": meta["counts"]["findings"],
        "pages": pages,
    }
    (out / "browser_manifest.json").write_text(json.dumps(manifest, indent=2))
    if not quiet:
        c = meta["counts"]
        print(f"\n{c['artifacts']} artifacts, {c['cross_edges']} derived cross-artifact edges, "
              f"{c['findings']} checker finding(s) -> {out}/index.html")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("record_dir", nargs="?",
                    default=os.environ.get("SYMPOSIUM_MIRROR", "../examples/record"),
                    help="directory of canonical JSON (default: $SYMPOSIUM_MIRROR)")
    ap.add_argument("--out", default="dist", help="output directory (default: dist)")
    ap.add_argument("--title", default=None, help="title shown on the overview")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--figures", default=None, metavar="DIR",
                    help="also write one print-scaled SVG per Argument to DIR "
                         "(relative to --out): full labels, no chrome, preset layout")
    args = ap.parse_args(argv)
    compile_record(args.record_dir, args.out, title=args.title, quiet=args.quiet,
                   figures_dir=args.figures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
