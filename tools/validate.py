"""Conformance validator for the Symposium specification, canonical JSON profile.

Pure functions over canonical JSON — no network, no NDEx. An agent runs this locally before
submitting; the admin gate runs the identical code before accepting. Same verdict both times.

  python validate.py <candidate.json> [record_dir/]

Severity:
  FAIL   - a MUST is violated. The gate rejects.
  REVIEW - surfaced for a human, never gates. Marks where verification becomes trust.

Conforms to spec/symposium_specification.md and tools/CANONICAL.md.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SPEC_VERSION = "1.0"
ARTIFACT_TYPES = {"Argument", "Data", "ScientificPublication", "Analysis", "Model",
                  "NonGroundable", "Message"}
NON_GROUNDABLE_TYPES = {"Analysis", "NonGroundable", "Message"}            # spec 2.1
# Model is groundable (spec 2.6): whether its content is genuinely evidential is a judgment
# for the Ground's rationale and the Argument's rationale, not a type-level prohibition.
ARGUMENT_OBJECTS = {"Assertion", "Ground", "Assumption", "Content"}
RELS = {"depends_on", "grounded_by", "assumes"}
REL_TARGET_TYPE = {"depends_on": "Assertion", "grounded_by": "Ground",
                   "assumes": "Assumption"}
BASIS_RELS = {"depends_on", "grounded_by", "assumes"}
STD_METHODS = {"text_span", "csv", "rest", "download", "graph"}
VERIFIABLE_METHODS = {"text_span", "csv", "graph"}                         # gate can check content

# ---------------------------------------------------------------- embedded payload size
# The server ceiling is between 814 KB and 1.5 MB (measured; above it the upload is a 413),
# but that is not the limit that matters. In this profile embedded content lives in a string
# property, NOT in the CX2 nodes, so nothing can query it — an agent reading one row loads the
# whole artifact into context. The binding limit is therefore what a reader can actually read.
#
# 50 KB is roughly 12k tokens: a few hundred rows, or the Results section of a paper. Past it,
# the honest fix is almost never a bigger payload — it is a narrower analysis.
#
# REVIEW, never FAIL. Size is a judgment about whether an analysis was focused, and the
# validator does not encode judgment as vocabulary; it says what it sees and a human reads it.
# The hard refusal lives in publish.py, where it is an operational guardrail rather than a
# statement about the record.
EMBED_REVIEW = 50 * 1024
EMBED_REFUSE = 250 * 1024

NAME_FORBIDDEN = re.compile(r"[.#]")
CITATION_RE = re.compile(r"\]\(\s*(?:<(@[^>]+)>|(@[^)\s]+))\s*\)")
CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
HEADER_REQUIRED = ("name", "type", "created", "published_by", "specification_version")


def finding(check, level, msg):
    return {"check": check, "level": level, "msg": msg}


# --------------------------------------------------------------------------- addresses
def parse_address(addr):
    """@artifact[.seg][.seg][#method.ref] | @member  ->  dict or None if malformed."""
    if not isinstance(addr, str) or not addr.startswith("@"):
        return None
    base, sep, schema = addr.partition("#")
    method = ref = None
    if sep:
        method, _, ref = schema.partition(".")
        if not method:
            return None
    segs = base[1:].split(".")
    if not segs or not segs[0]:
        return None
    return {"root": segs[0], "segs": segs[1:], "method": method, "ref": ref, "raw": addr}


def _csv_rows(text):
    try:
        return list(csv.DictReader(io.StringIO(text)))
    except Exception:
        return None


def _count_overlapping(hay, needle):
    n, i = 0, 0
    while needle:
        j = hay.find(needle, i)
        if j < 0:
            return n
        n, i = n + 1, j + 1
    return n


def parse_instant(s):
    if not s:
        return None
    t = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        t += "T00:00:00+00:00"
    elif t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


# --------------------------------------------------------------------------- corpus index
def build_index(artifacts):
    """name -> {type, created, header, objects{name:obj}, methods{name:obj}}"""
    idx = {}
    for a in artifacts:
        h = a.get("artifact", {})
        objs = {o.get("name"): o for o in a.get("objects", []) if o.get("name")}
        idx[h.get("name")] = {
            "type": h.get("type"), "created": h.get("created"), "header": h,
            "objects": objs, "art": a,
            "methods": {n: o for n, o in objs.items() if o.get("type") == "Content"},
        }
    return idx


def resolve(addr, index, members):
    """-> (ok, info, reason). info carries what the caller needs for groundability."""
    p = parse_address(addr)
    if p is None:
        return False, None, f"malformed address {addr!r}"
    root = p["root"]

    if root in members and not p["segs"] and not p["method"]:
        return True, {"kind": "member", "name": root}, ""
    if root in members:
        return False, None, f"a Member address exposes no internal structure (spec 1.7): {addr}"
    if root not in index:
        return False, None, f"no artifact named '{root}'"

    rec = index[root]
    segs, method = p["segs"], p["method"]
    obj = prop = None

    if len(segs) == 0:
        kind = "artifact"
    elif len(segs) == 1:
        if segs[0] in rec["objects"]:
            obj, kind = segs[0], "object"
        elif segs[0] in rec["header"]:
            prop, kind = segs[0], "property"
        else:
            return False, None, f"'{segs[0]}' is neither an Object nor a property of '{root}'"
    elif len(segs) == 2:
        if segs[0] not in rec["objects"]:
            return False, None, f"'{segs[0]}' is not an Object of '{root}'"
        if segs[1] not in rec["objects"][segs[0]]:
            return False, None, f"'{segs[1]}' is not a property of Object '{segs[0]}'"
        obj, prop, kind = segs[0], segs[1], "object_property"
    else:
        return False, None, f"address has too many segments: {addr}"

    info = {"kind": kind, "artifact": root, "object": obj, "property": prop,
            "method": method, "ref": p["ref"], "rec": rec,
            "node_type": rec["objects"][obj]["type"] if obj else None}

    if method:
        if method not in rec["methods"]:
            return False, None, f"'{root}' declares no Content Object named '{method}'"
        info["method_obj"] = rec["methods"][method]
    return True, info, ""


def _verify_graph(rec, ref):
    """`node=<object>` / `edge=<source>|<rel>|<target>` against the Artifact's own graph.

    A Model is a property graph (spec 1.7), so an element of one is addressable the way a cell
    of a table is, and just as checkable: the gate reads the Artifact it already holds."""
    parts = dict(kv.split("=", 1) for kv in (ref or "").split("&") if "=" in kv)
    if "node" in parts:
        if parts["node"] not in rec["objects"]:
            return [finding("ADDRESS", "FAIL",
                            f"graph node '{parts['node']}' is not an Object of this Artifact")]
        return []
    if "edge" in parts:
        bits = parts["edge"].split("|")
        if len(bits) != 3:
            return [finding("ADDRESS", "FAIL",
                            "graph edge reference is <source>|<rel>|<target>")]
        s, r, t = bits
        rels = (rec.get("art") or {}).get("relationships", [])
        if not any(e.get("source") == s and e.get("rel") == r and e.get("target") == t for e in rels):
            return [finding("ADDRESS", "FAIL",
                            f"no relationship {s} -{r}-> {t} in this Artifact")]
        return []
    return [finding("ADDRESS", "FAIL",
                    "graph reference needs node=<name> or edge=<source>|<rel>|<target>")]


def verify_content(info):
    """Machine-verify text_span / csv / graph references against embedded content. -> [findings]"""
    out, m, ref = [], info.get("method"), info.get("ref")
    if m not in VERIFIABLE_METHODS:
        return out
    if not ref:
        return out                    # no reference string: the address names all of the content
    rec, prop = info["rec"], info.get("property")
    if m == "graph":
        return _verify_graph(rec, ref)
    if prop is None:
        out.append(finding("ADDRESS", "FAIL",
                           f"method '{m}' must address a property (…artifact.<property>#{m}.…): {info}"))
        return out
    src = (rec["objects"][info["object"]] if info.get("object") else rec["header"]).get(prop)
    if not isinstance(src, str):
        out.append(finding("ADDRESS", "FAIL", f"property '{prop}' holds no text to address"))
        return out

    if m == "csv":
        parts = dict(kv.split("=", 1) for kv in (ref or "").split("&") if "=" in kv)
        row, col = parts.get("row"), parts.get("col")
        rows = _csv_rows(src)
        if rows is None or not rows:
            out.append(finding("ADDRESS", "FAIL", f"property '{prop}' is not parseable CSV"))
            return out
        cols = list(rows[0].keys())
        if col is not None and col not in cols:
            out.append(finding("ADDRESS", "FAIL", f"col '{col}' not in {cols}"))
        if row is None:
            out.append(finding("ADDRESS", "FAIL", "csv reference needs row=<key>"))
        else:
            key = cols[0]
            if not any(r.get(key) == row for r in rows):
                out.append(finding("ADDRESS", "FAIL", f"row '{row}' not found in column '{key}'"))
    elif m == "text_span":
        mm = re.match(r'\s*quote="((?:[^"\\]|\\.)*)"(.*)$', ref or "")
        if not mm:
            out.append(finding("ADDRESS", "FAIL", 'text_span reference needs quote="…"'))
            return out
        q = re.sub(r"\\(.)", r"\1", mm.group(1))
        extra = dict(kv.split("=", 1) for kv in mm.group(2).lstrip("&").split("&") if "=" in kv)
        n = _count_overlapping(src, q)
        if n == 0:
            out.append(finding("ADDRESS", "FAIL", f"quote not found in '{prop}': {q[:50]!r}"))
        elif n > 1:
            nth, near = extra.get("nth"), (extra.get("near") or "").strip('"')
            if nth is not None:
                if not (nth.isdigit() and 1 <= int(nth) <= n):
                    out.append(finding("ADDRESS", "FAIL", f"&nth={nth} out of range (quote matches {n})"))
            elif near:
                near = re.sub(r"\\(.)", r"\1", near)
                if q not in near:
                    out.append(finding("ADDRESS", "FAIL", "&near must contain the quote"))
                elif _count_overlapping(src, near) != 1:
                    out.append(finding("ADDRESS", "FAIL", "&near context is not unique"))
            else:
                out.append(finding("ADDRESS", "FAIL",
                                   f"quote matches {n} spans; add &nth= or a unique &near="))
    return out


def groundable(info, citing_artifact):
    """Trust firewall (spec 2.2.4). -> (ok, level, reason)"""
    if info["kind"] == "member":
        return False, "FAIL", "a Member is not groundable (spec 2.2.4)"
    if info["artifact"] == citing_artifact:
        return False, "FAIL", "a Ground may not address content inside its own Argument (spec 2.2)"
    rec = info["rec"]
    if rec["type"] in NON_GROUNDABLE_TYPES:
        return False, "FAIL", f"{rec['type']} is a non-groundable Artifact type (spec 2.1)"
    if info.get("node_type") == "Content":
        return False, "FAIL", "Content Objects are not themselves groundable (spec 2.2.4)"
    if info.get("node_type") == "Assertion":
        return True, None, ""                                   # an Assertion in another Argument
    m = info.get("method_obj")
    if m is None:
        return False, "FAIL", ("names no Content Object; groundable content must be reached by a "
                               "method the Artifact declares (spec 2.2.4)")
    if m.get("groundable") is not True:
        return False, "FAIL", f"Content Object '{info['method']}' is not declared groundable"
    if info["method"] in ("rest", "download"):
        return True, "REVIEW", (f"grounds via '{info['method']}' — content is outside the record and "
                                f"cannot be machine-verified; verifiability is trust-based")
    return True, None, ""


# --------------------------------------------------------------------------- per-artifact
def check_structure(a):
    f, h = [], a.get("artifact")
    if not isinstance(h, dict):
        return [finding("STRUCT", "FAIL", "missing 'artifact' header object")]
    for k in HEADER_REQUIRED:
        if k not in h:
            f.append(finding("STRUCT", "FAIL", f"header missing required '{k}' (spec 1.4)"))
    name = h.get("name")
    if isinstance(name, str):
        if NAME_FORBIDDEN.search(name) or name.startswith("@"):
            f.append(finding("STRUCT", "FAIL", f"name '{name}' contains a delimiter (. # @)"))
        # A Member-name prefix segment must be present. Hyphens are permitted in it because
        # NDEx account names may contain them — `ndex-admin` is one — and excluding them
        # would bar the admin from naming its own artifacts after its own account. This
        # check is structural only: that the NAME MATCHES THE PUBLISHING ACCOUNT is enforced
        # where the account is actually known, in publish.py and at the gate.
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9-]*_", name):
            f.append(finding("NAMING", "FAIL", f"name '{name}' lacks the '<agent>_' prefix (profile rule)"))
    if h.get("specification_version") != SPEC_VERSION:
        f.append(finding("STRUCT", "FAIL",
                         f"specification_version {h.get('specification_version')!r} != '{SPEC_VERSION}'"))
    if h.get("type") not in ARTIFACT_TYPES:
        f.append(finding("STRUCT", "REVIEW", f"type '{h.get('type')}' is not defined by the spec"))
    pb = h.get("published_by")
    if not (isinstance(pb, str) and pb.startswith("@") and "." not in pb):
        f.append(finding("STRUCT", "FAIL", f"published_by must be a bare Member address, got {pb!r}"))
    if h.get("supersedes") and not (h.get("supersedes_rationale") or "").strip():
        f.append(finding("STRUCT", "FAIL", "supersedes present without supersedes_rationale (spec 1.4)"))

    objs = a.get("objects", [])
    names = [o.get("name") for o in objs]
    for d in {n for n in names if names.count(n) > 1}:
        f.append(finding("STRUCT", "FAIL", f"duplicate Object name '{d}'"))
    for o in objs:
        if not o.get("name") or not o.get("type"):
            f.append(finding("STRUCT", "FAIL", f"Object missing name/type: {o}"))
        # spec 1.7.1: Object names must not collide with the Artifact's property names
        if o.get("name") in h:
            f.append(finding("STRUCT", "FAIL",
                             f"Object name '{o['name']}' collides with an Artifact property (spec 1.7.1)"))
    known = set(names)
    # The relationship vocabulary is closed for Arguments and open everywhere else. spec 2.2
    # names the three relationships an Argument may use; spec 1.7 places no vocabulary on
    # relationships in general, because an Artifact is a property graph and a Model of a
    # pathway or a hierarchy carries edges this specification has no business naming.
    for r in a.get("relationships", []):
        rel = r.get("rel")
        if not isinstance(rel, str) or not rel.strip():
            f.append(finding("STRUCT", "FAIL", f"relationship missing 'rel': {r}"))
        elif h.get("type") == "Argument" and rel not in RELS:
            f.append(finding("STRUCT", "FAIL",
                             f"'{rel}' is not a relationship an Argument may use; spec 2.2 defines "
                             f"{', '.join(sorted(RELS))}"))
        for end in ("source", "target"):
            v = r.get(end)
            if v not in known:
                f.append(finding("STRUCT", "FAIL",
                                 f"{r.get('rel')} {end} '{v}' is not an Object of this Artifact "
                                 f"(relationships never leave the Artifact; spec 1.6)"))
    return f


def check_type_specific(a):
    f, h = [], a["artifact"]
    t, objs = h.get("type"), {o["name"]: o for o in a.get("objects", []) if o.get("name")}
    req = {"Analysis": ("procedure",), "Model": ("modeling_choices",),
           "Message": ("recipients", "text")}.get(t, ())
    for k in req:
        if not h.get(k) and h.get(k) != []:
            f.append(finding("TYPE", "FAIL", f"{t} requires '{k}'"))
    if t == "Analysis" and "outputs" in h:
        f.append(finding("TYPE", "REVIEW",
                         "'outputs' is not an Analysis property; outputs cite the Analysis "
                         "with produced_by, so they are found by search (spec 2.5)"))
    if t == "NonGroundable" and not any(str(h.get(k, "")).strip()
                                        for k in ("text", "description", "title")):
        f.append(finding("TYPE", "REVIEW",
                         "NonGroundable has no required content property, but should carry at "
                         "least one expressing meaningful content, such as 'text' (spec 2.7)"))
    if t == "ScientificPublication":
        for k in ("import_method", "authors"):
            if not h.get(k):
                f.append(finding("TYPE", "FAIL", f"ScientificPublication is imported by definition; '{k}' required"))
    if t == "Argument":
        # The judgment is a property of the Argument, not of each Assertion: one
        # verdict, for one stated purpose, on the primary Assertion (spec 2.2.2).
        for k in ("authors", "verdict", "rationale", "purpose", "primary_assertion"):
            if not h.get(k):
                f.append(finding("TYPE", "FAIL", f"Argument requires '{k}' (spec 2.2)"))
    if bool(h.get("extracted_from")) != bool(h.get("extraction_method")):
        f.append(finding("TYPE", "FAIL", "extracted_from and extraction_method must appear together"))

    for o in a.get("objects", []):
        ot = o.get("type")
        if t == "Argument" and ot not in ARGUMENT_OBJECTS:
            f.append(finding("TYPE", "FAIL", f"Object type '{ot}' not permitted in an Argument"))
        # Outside an Argument the Object vocabulary is open (spec 1.6): a Model of a pathway
        # holds nodes for life-cycle stages and effectors, and the specification's own Gene
        # Ontology example (spec 2.6) is a Model whose internal annotations a Ground cites.
        # Restricting every non-Argument Artifact to Content Objects made the Model type
        # unusable for the thing it exists to hold.
        need = {"Assertion": ("claim", "scope"),
                "Ground": ("citation", "rationale"), "Assumption": ("rationale",),
                "Content": ("description", "addressing_method")}.get(ot, ())
        for k in need:
            if not str(o.get(k, "")).strip():
                f.append(finding("TYPE", "FAIL", f"{ot} '{o.get('name')}' missing '{k}'"))
        if ot == "Content":
            if not isinstance(o.get("groundable"), bool):
                f.append(finding("TYPE", "FAIL",
                                 f"Content Object '{o.get('name')}' groundable must be a boolean, "
                                 f"got {o.get('groundable')!r} (spec 1.8.1)"))
            if o.get("name") not in STD_METHODS:
                f.append(finding("TYPE", "REVIEW",
                                 f"Content Object '{o.get('name')}' is outside the profile's standard set"))
            if o.get("name") in ("rest", "download") and not o.get("access_method"):
                f.append(finding("TYPE", "FAIL", f"method '{o.get('name')}' requires access_method"))
        if ot == "Content" and h.get("type") in NON_GROUNDABLE_TYPES and o.get("groundable") is True:
            f.append(finding("TYPE", "FAIL",
                             f"{h['type']} is non-groundable; its methods are addressable only (spec 2.1)"))
    return f


def check_argument(a):
    """The Argument structural constraints (spec 2.2)."""
    f, h = [], a["artifact"]
    if h.get("type") != "Argument":
        return f
    objs = {o["name"]: o for o in a.get("objects", []) if o.get("name")}
    rels = a.get("relationships", [])
    A = {n for n, o in objs.items() if o["type"] == "Assertion"}
    G = {n for n, o in objs.items() if o["type"] == "Ground"}
    U = {n for n, o in objs.items() if o["type"] == "Assumption"}

    if not A:
        f.append(finding("C-ARG", "FAIL", "an Argument contains at least one Assertion"))
    pa = h.get("primary_assertion")
    if pa not in A:
        f.append(finding("C-ARG", "FAIL", f"primary_assertion '{pa}' does not name an owned Assertion"))

    for r in rels:
        want = REL_TARGET_TYPE.get(r.get("rel"))
        src, tgt = r.get("source"), r.get("target")
        if src in objs and objs[src]["type"] != "Assertion":
            f.append(finding("C-ARG", "FAIL", f"{r['rel']} must originate at an Assertion, got {objs[src]['type']}"))
        if want and tgt in objs and objs[tgt]["type"] != want:
            f.append(finding("C-ARG", "FAIL", f"{r['rel']} must target a {want}, got {objs[tgt]['type']}"))

    # Ground / Assumption bear on exactly one Assertion
    for kind, names, rel in (("Ground", G, "grounded_by"), ("Assumption", U, "assumes")):
        cnt = {}
        for r in rels:
            if r.get("rel") == rel:
                cnt[r["target"]] = cnt.get(r["target"], 0) + 1
        for n in sorted(names):
            c = cnt.get(n, 0)
            if c == 0:
                f.append(finding("C-ARG", "FAIL",
                                 f"{kind} '{n}' bears on no Assertion — connect it with `{rel}` "
                                 f"from the Assertion it supports, or remove it"))
            elif c != 1:
                # The remedy is not obvious from the count alone, and authors reasonably write one
                # shared assumption for several Assertions. Say what to do and why (spec 2.2.4).
                f.append(finding("C-ARG", "FAIL",
                                 f"{kind} '{n}' bears on {c} Assertions (must be exactly 1) — give "
                                 f"each Assertion its OWN {kind}, e.g. '{n}_1', '{n}_2'. Its "
                                 f"rationale explains what THAT Assertion rests "
                                 f"on, so one shared between two would have to mean two things at "
                                 f"once. Where both rest on the same material the addresses "
                                 f"coincide and the rationales differ, and that difference is the "
                                 f"information worth recording (spec 2.2.4)"))

    # every Assertion has a basis
    basis = {r["source"] for r in rels if r.get("rel") in BASIS_RELS}
    for n in sorted(A - basis):
        f.append(finding("C-ARG", "FAIL",
                         f"Assertion '{n}' has no basis — needs a depends_on, grounded_by, or assumes (spec 2.2.3)"))

    # depends_on DAG, primary and alternatives are roots
    dep = {}
    for r in rels:
        if r.get("rel") == "depends_on":
            dep.setdefault(r["source"], []).append(r["target"])
    if _cyclic(dep):
        f.append(finding("C-ARG", "FAIL", "the depends_on graph contains a cycle"))
    depended_on = {t for ts in dep.values() for t in ts}
    if pa in depended_on:
        f.append(finding("C-ARG", "FAIL", f"no Assertion may depend on the primary Assertion '{pa}'"))
    return f


def _ancestry(name, index, seen=None):
    """Artifacts `name` descends from, through DECLARED provenance (spec 2.5, 2.2).

    Follows produced_by -> Analysis -> inputs/used_models, and extracted_from, transitively.
    `supersedes` is excluded: it states replacement and conveys no evidential support."""
    if seen is None:
        seen = set()
    if name in seen or name not in index:
        return seen
    seen.add(name)
    h = index[name]["header"]
    nxt = [h[k] for k in ("produced_by", "extracted_from") if h.get(k)]
    for k in ("inputs", "used_models"):
        nxt += list(h.get(k) or [])
    for a in nxt:
        p = parse_address(a)
        if p:
            _ancestry(p["root"], index, seen)
    return seen


def check_independence(a, index):
    """Grounds on one Assertion that rest on a common source are not independent evidence.

    A structural FACT, never a verdict: two cells of one large dataset may be genuinely
    independent measurements, while three sentences of one abstract are not. The checker
    reports the shared source; whether independence survives it is the author's judgment,
    and belongs in the Argument's `rationale` (spec 2.2.4).

    One finding per Assertion — three Grounds on one artifact is one fact, not three pairs."""
    f, h = [], a["artifact"]
    if h.get("type") != "Argument":
        return f
    objs = {o["name"]: o for o in a.get("objects", []) if o.get("name")}
    idx = dict(index)
    idx.setdefault(h.get("name"), {"header": h})            # so self-provenance resolves

    by_assertion = {}
    for r in a.get("relationships", []):
        if r.get("rel") != "grounded_by":
            continue
        g = objs.get(r.get("target"), {})
        p = parse_address(g.get("citation", ""))
        if p:
            by_assertion.setdefault(r["source"], []).append((r["target"], p["root"]))

    for assertion, grounds in sorted(by_assertion.items()):
        if len(grounds) < 2:
            continue
        same = {}
        for gname, root in grounds:
            same.setdefault(root, []).append(gname)
        shared_carrier = {r: gs for r, gs in same.items() if len(gs) > 1}
        if shared_carrier:
            for root, gs in sorted(shared_carrier.items()):
                f.append(finding("INDEPENDENCE", "REVIEW",
                                 f"Assertion '{assertion}': Grounds {', '.join(sorted(gs))} all address "
                                 f"'{root}'. Their agreement is not independent corroboration unless the "
                                 f"evaluation says why (spec 2.2.4)"))
            continue                                        # same carrier subsumes shared ancestry
        anc = {gname: _ancestry(root, idx) for gname, root in grounds}
        reported = set()
        for i, (gi, ai) in enumerate(sorted(anc.items())):
            for gj, aj in sorted(anc.items())[i + 1:]:
                common = (ai & aj) - {r for _, r in grounds}
                key = tuple(sorted((gi, gj)))
                if common and key not in reported:
                    reported.add(key)
                    f.append(finding("INDEPENDENCE", "REVIEW",
                                     f"Assertion '{assertion}': Grounds {gi} and {gj} address different "
                                     f"Artifacts that both descend from {', '.join(sorted(common))}; their "
                                     f"agreement is not independent corroboration (spec 2.2.4)"))
    return f


def _cyclic(g):
    seen, stack = set(), set()

    def go(n):
        seen.add(n); stack.add(n)
        for m in g.get(n, []):
            if m in stack or (m not in seen and go(m)):
                return True
        stack.discard(n)
        return False

    return any(n not in seen and go(n) for n in list(g))


# --------------------------------------------------------------------------- corpus level
def check_corpus(a, index, members, record_names):
    f, h = [], a["artifact"]
    name, t = h.get("name"), h.get("type")
    mine = parse_instant(h.get("created"))
    objs = {o["name"]: o for o in a.get("objects", []) if o.get("name")}

    if name in record_names:
        f.append(finding("UNIQUE", "FAIL", f"name '{name}' is already in the record; names are never reused"))

    def check_addr(addr, ctx, evidential, ordered=True):
        ok, info, why = resolve(addr, index, members)
        if not ok:
            f.append(finding("ADDRESS", "FAIL", f"{ctx}: {why}"))
            return
        if info["kind"] == "member":
            # Members sit outside the temporal ordering, but are never evidence (spec 2.2.4).
            if evidential:
                f.append(finding("GROUND", "FAIL", f"{ctx}: a Member is not groundable (spec 2.2.4)"))
            return
        theirs = parse_instant(info["rec"]["created"])
        if info["artifact"] == name:
            pass                          # intra-Artifact reference: created in one act (spec 1.8)
        elif not ordered:
            pass                          # Analysis <-> its outputs: one act, mutual (spec 1.8, 2.5)
        elif mine and theirs and theirs >= mine:
            f.append(finding("ORDER", "FAIL",
                             f"{ctx}: '{info['artifact']}' ({info['rec']['created']}) is not strictly "
                             f"earlier than '{name}' ({h.get('created')}) — spec 1.8"))
        if evidential:
            g_ok, lvl, reason = groundable(info, name)
            if not g_ok:
                f.append(finding("GROUND", "FAIL", f"{ctx}: {reason}"))
                return
            if lvl == "REVIEW":
                f.append(finding("GROUND", "REVIEW", f"{ctx}: {reason}"))
        f.extend(finding(x["check"], x["level"], f"{ctx}: {x['msg']}") for x in verify_content(info))

    # `outputs` and `produced_by` are the single-act exception to temporal ordering (spec 1.8)
    if h.get("produced_by"):
        check_addr(h["produced_by"], "header produced_by", False, ordered=False)
        # spec 2.5: a produced_by citation must resolve to an existing ANALYSIS. Resolving to
        # some other Artifact is the failure the rule exists to catch, because the point of the
        # property is that the procedure is on the record and inspectable, and a Data Artifact
        # pointing at another Data Artifact records no procedure at all.
        ok, info, _ = resolve(h["produced_by"], index, members)
        if ok and info.get("kind") != "member" and info["rec"]["type"] != "Analysis":
            f.append(finding("TYPE", "FAIL",
                             f"header produced_by: '{info['artifact']}' is a {info['rec']['type']}, "
                             f"not an Analysis (spec 2.5)"))
    if h.get("extracted_from"):
        check_addr(h["extracted_from"], "header extracted_from", False)
    def each_address(hk, ordered=True):
        """Walk a header field that holds a LIST of addresses.

        A string is iterable, so `for v in h[hk]` walked it CHARACTER BY CHARACTER and reported
        `malformed address 'e'` once per letter — around twenty findings for one mistake, not
        one of them naming the actual error. On 2026-08-07 that was 42% of every local
        validation failure logged during a trial run, and the second largest cost in the whole
        publishing loop after a stale mirror.
        """
        v = h.get(hk)
        if v is None or v == []:
            return
        if isinstance(v, str):
            f.append(finding("STRUCT", "FAIL",
                             f"header {hk} must be a LIST of addresses, not a string — "
                             f'write ["{v}"] rather than "{v}"'))
            return
        if not isinstance(v, list):
            f.append(finding("STRUCT", "FAIL",
                             f"header {hk} must be a list of addresses, got {type(v).__name__}"))
            return
        for a in v:
            check_addr(a, f"header {hk}", False, ordered=ordered)

    each_address("outputs", ordered=False)
    for hk in ("supersedes", "inputs", "used_models", "recipients"):
        each_address(hk)

    for n, o in objs.items():
        if o["type"] == "Ground":
            check_addr(o.get("citation", ""), f"Ground '{n}'", True)

    # prose citations: markdown link form only (profile 3.1)
    for scope, d in [("header", h)] + [(f"Object '{n}'", o) for n, o in objs.items()]:
        for k, v in d.items():
            if not isinstance(v, str) or k in ("citation", "published_by", "produced_by", "extracted_from"):
                continue
            # A backtick code span is a literal, not prose. A Content Object's
            # `addressing_method` has to SHOW the form of an address, and that form contains an
            # `@name`; treating the template as a citation reported every well-written
            # addressing method as a defect and told the author to turn the example into a link.
            v = CODE_SPAN_RE.sub(" ", v)
            for m in CITATION_RE.finditer(v):
                check_addr(m.group(1) or m.group(2), f"{scope}.{k} citation", False)
            bare = re.findall(r"(?<![\w(<])@[A-Za-z0-9_]+", CITATION_RE.sub("", v))
            for b in set(bare):
                f.append(finding("CITATION", "REVIEW",
                                 f"{scope}.{k}: bare '{b}' is not in markdown link form and cannot be "
                                 f"validated — write [text]({b}) (profile 3.1)"))
    return f


def embedded_size(a):
    """-> (total serialized bytes, [(where, property, bytes)] largest first).

    Total is the serialized canonical JSON, because that is what is uploaded, what the gate
    copies into the record, and what an agent has to hold in context to read any part of it.
    """
    try:
        total = len(json.dumps(a))
    except Exception:                                          # noqa: BLE001
        return 0, []
    props = []
    h = a.get("artifact") or {}
    for k, v in h.items():
        if isinstance(v, str) and len(v) > 1024:
            props.append(("artifact", k, len(v)))
    for o in (a.get("objects") or []):
        if not isinstance(o, dict):
            continue
        for k, v in o.items():
            if isinstance(v, str) and len(v) > 1024:
                props.append((o.get("name", "?"), k, len(v)))
    props.sort(key=lambda p: -p[2])
    return total, props


def check_size(a):
    """Embedded payload size. REVIEW only — see EMBED_REVIEW."""
    total, props = embedded_size(a)
    if total <= EMBED_REVIEW:
        return []
    where = (f"; largest is '{props[0][1]}' on {props[0][0]} at {props[0][2] // 1024} KB"
             if props else "")
    return [finding("SIZE", "REVIEW",
                    f"embedded payload is {total // 1024} KB{where}. Embedded content is not "
                    f"queryable in this profile — a reader loads all of it to read any of it. "
                    f"Above ~{EMBED_REVIEW // 1024} KB the fix is usually a narrower analysis, "
                    f"not a bigger artifact.")]


def validate(candidate, record=(), members=()):
    """-> list of findings for `candidate`, validated against the accepted `record`."""
    f = check_structure(candidate)
    if any(x["level"] == "FAIL" and x["check"] == "STRUCT" and "header" in x["msg"] for x in f):
        return f                                              # header too broken to continue
    # The candidate joins the resolution index so intra-Artifact addresses resolve (spec 1.8
    # permits self-reference); uniqueness is still judged against the record alone.
    record_names = {r["artifact"]["name"] for r in record if r.get("artifact", {}).get("name")}
    index = build_index(list(record) + [candidate])
    f += check_type_specific(candidate)
    f += check_argument(candidate)
    f += check_corpus(candidate, index, set(members), record_names)
    f += check_independence(candidate, index)
    f += check_size(candidate)
    return f


def passed(findings):
    return not any(x["level"] == "FAIL" for x in findings)


def report(findings, name=""):
    fails = [x for x in findings if x["level"] == "FAIL"]
    revs = [x for x in findings if x["level"] == "REVIEW"]
    print(f"{name}: {'ACCEPT' if not fails else f'REJECT ({len(fails)} failures)'}"
          f"{f' +{len(revs)} review' if revs else ''}")
    for x in fails + revs:
        print(f"   [{x['level']:6} {x['check']:8}] {x['msg']}")
    return not fails


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cand = json.loads(Path(argv[1]).read_text())
    rec = [json.loads(p.read_text()) for p in Path(argv[2]).glob("*.json")] if len(argv) > 2 else []
    members = {h["artifact"]["published_by"].lstrip("@") for h in rec if h.get("artifact", {}).get("published_by")}
    members |= {cand.get("artifact", {}).get("published_by", "@").lstrip("@")}
    return 0 if report(validate(cand, rec, members), cand.get("artifact", {}).get("name", argv[1])) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
