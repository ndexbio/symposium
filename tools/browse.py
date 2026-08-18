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
"""
from __future__ import annotations

import argparse
import html
import json
import os
import pathlib
import re
import shutil
import sys
from collections import defaultdict

from validate import (CITATION_RE, build_index, parse_address,     # noqa: E402
                         parse_instant, resolve, validate)
import templates as T
import figures as F                                              # noqa: E402

ARGUMENT = "Argument"
NON_GROUNDABLE_TYPES = {"Analysis", "NonGroundable", "Message"}

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


def build_overview(artifacts, index, colors, pages, findings_by):
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
            "_pos": {"x": col_x[c] + ((rows[(c, r)] - 1) // _BAND_MAX_ROWS) * _SUB_DX,
                     "y": band_top[r] + ((rows[(c, r)] - 1) % _BAND_MAX_ROWS) * _ROW_DY},
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
            "tooltip": f"{rel} ×{n}\n{s} → {t}\nderived from an address in a property value",
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
                   "sessions": cur + 1, "time_span": span},
    }
    return {"nodes": nodes, "edges": edges}, meta


# --------------------------------------------------------------------------- #
# Artifact pages (everything that is not an Argument)
# --------------------------------------------------------------------------- #

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

    methods = [o for o in doc.get("objects", []) if o.get("type") == "AddressingMethod"]
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

    for k, v in h.items():
        if k in ("name", "type", "specification_version", "published_by", "created", "title"):
            continue
        if isinstance(v, str) and "\n" in v and "," in v.split("\n")[0]:
            parts.append(f"<h2>{esc(k)}</h2>" + T.csv_table(v))
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
            intro = "".join(T.md_to_html(a["artifact"][k], pages)
                            for k in ("description", "text") if a["artifact"].get(k))
            (out / pages[name]).write_text(
                T.render_claim_html(collapsed, meta, cyto, intro_html=intro), encoding="utf-8")
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

    elements, meta = build_overview(artifacts, index, colors, pages, findings_by)
    meta["counts"]["findings"] = sum(len(v) for v in findings_by.values())
    (out / "index.html").write_text(
        T.render_overview_html(elements, meta, cyto,
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
