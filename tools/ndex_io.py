"""Shared NDEx transport for the Symposium tooling.

Canonical JSON in, CX2 on the wire. Nothing here interprets the specification — it moves
artifacts to and from the community's NDEx server and does nothing else. Both the member-side
publish tool and the admin gate import this; neither owns it.

Credentials come from the environment, never from argv (a command line is visible in `ps`).
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
import urllib.error
import urllib.request

BASE = os.environ.get("SYMPOSIUM_BASE", "http://localhost:8080").rstrip("/")
CANONICAL_ATTR = "symposium_canonical"

# Network attributes that say what ROLE a network plays. A member's permission map contains
# their own submissions, the admin's accepted record copies, AND the admin's rejection
# replies -- all readable, all admin-owned in the latter two cases. Ownership alone cannot
# tell them apart, so the role is stamped explicitly.
SUBMIT_MARK = "symposium_submission"   # a member's bid for publication
RECORD_MARK = "symposium_record"       # an accepted artifact: THE community record
REPLY_MARK = "symposium_reply"         # an admin rejection notice: NOT part of the record
TELEMETRY_MARK = "symposium_telemetry"  # a member's event log: NOT an artifact, NOT the record
TELEMETRY_ATTR = "symposium_events"     # the log itself, JSONL in one attribute

# Reserved name segment for telemetry networks. The gate skips these on the cheap summary it
# already has, before downloading anything — a log pushed every cycle would otherwise be
# re-fetched in full on every pass. The mark is checked as well, so an oddly-named log is
# still skipped; the name is the optimisation, the mark is the guarantee.
TELEMETRY_SEGMENT = "_TELEMETRY_"

# A session's own closing report: what it published, what refused it, what it could not say.
# Owned by the Member, granted to the admin, and readable back by its author as a memory of
# earlier sessions. Like telemetry it is NOT an Artifact and never enters the record.
REPORT_MARK = "symposium_report"
REPORT_ATTR = "symposium_report_text"
REPORT_SEGMENT = "_REPORT_"

# Everything the gate must not mistake for a bid for publication. The segments are checked on
# the cheap summary before anything is downloaded; the marks are the guarantee afterwards.
NON_ARTIFACT_MARKS = (TELEMETRY_MARK, REPORT_MARK)
NON_ARTIFACT_SEGMENTS = (TELEMETRY_SEGMENT, REPORT_SEGMENT)


def auth(prefix):
    """-> (username, basic-token) from NDEX_<PREFIX>_USER / _PASSWORD."""
    u = os.environ.get(f"NDEX_{prefix}_USER")
    p = os.environ.get(f"NDEX_{prefix}_PASSWORD")
    if not u or not p:
        sys.exit(f"missing NDEX_{prefix}_USER / NDEX_{prefix}_PASSWORD in the environment")
    return u, base64.b64encode(f"{u}:{p}".encode()).decode()


def api(method, path, tok, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Authorization": f"Basic {tok}", "Accept": "application/json"}
    if data:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            t = r.read().decode(errors="replace")
            return r.status, (t if raw else (json.loads(t) if t.strip() else None))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300]
    except Exception as e:
        return 0, f"transport error: {e}"


def whoami(tok):
    st, b = api("GET", "/v2/user?valid=true", tok)
    return (b or {}) if st == 200 and isinstance(b, dict) else {}


PERMISSION_PAGE = 200


def permission_map(user_uuid_, tok, extra=""):
    """The WHOLE of a user's network permission listing. -> (status, {uuid: level}).

    `/v2/user/<id>/permission?type=NETWORK` returns at most 100 entries and says NOTHING about
    having truncated: no total, no next-page link, no flag. Callers that simply read the result
    saw the first 100 networks and treated that as everything.

    That is the same silent-drop failure the permission map was adopted to AVOID. Search-based
    discovery was abandoned because a private network has `indexLevel: NONE` and never appears
    in /v2/search/network — but the replacement had its own cap, and it bit on 2026-08-07 the
    moment the admin could see more than 100 networks: `agent_lyra`'s Data artifact was
    uploaded, granted to the admin, and correctly present in the network's own permission map,
    yet absent from the admin's listing. The gate deferred its bundle forever, waiting for a
    submission that had in fact arrived. Members beyond the first 100 would have gone the same
    way, one by one, with no error anywhere.

    `start` is a PAGE index, not a row offset. A short page means the end.
    """
    out, page = {}, 0
    while True:
        st, b = api("GET", f"/v2/user/{user_uuid_}/permission?type=NETWORK{extra}"
                           f"&start={page}&size={PERMISSION_PAGE}", tok)
        if st != 200 or not isinstance(b, dict):
            return (st, out if out else None)
        out.update(b)
        if len(b) < PERMISSION_PAGE:
            return 200, out
        page += 1


def user_uuid(username, tok):
    st, b = api("GET", f"/v2/user?username={username}", tok)
    return b.get("externalId") if st == 200 and isinstance(b, dict) else None


def grant_read(network_uuid, user_uuid_, tok):
    st, _ = api("PUT", f"/v2/network/{network_uuid}/permission"
                       f"?userid={user_uuid_}&permission=READ", tok)
    return st in (200, 204)


def to_cx2(canonical, marks=None):
    """Canonical JSON -> CX2. `marks` are role attributes (see SUBMIT_MARK/RECORD_MARK/REPLY_MARK).

    Two modes are anticipated (see CANONICAL.md §7). This is PROJECTION mode: the
    Artifact's content lives in the canonical JSON, and nodes/edges are derived from its
    Objects and relationships so the network is viewable in NDEx. The `symposium_canonical`
    attribute is authoritative — a consumer validates that, never the reconstructed graph.

    SUBSTRATE mode, where the graph itself is the content (a large interactome, a cell-structure
    hierarchy), inverts this and is not implemented here."""
    marks = dict(marks if marks is not None else {SUBMIT_MARK: True})
    h = canonical["artifact"]
    objs = canonical.get("objects", [])
    ids = {o["name"]: i for i, o in enumerate(objs)}
    nodes = [{"id": ids[o["name"]], "v": {"name": o["name"], "type": o.get("type", "")}}
             for o in objs]
    edges = [{"id": i, "s": ids[r["source"]], "t": ids[r["target"]],
              "v": {"interaction": r["rel"]}}
             for i, r in enumerate(canonical.get("relationships", []))
             if r.get("source") in ids and r.get("target") in ids]
    return [
        {"CXVersion": "2.0", "hasFragments": False},
        {"metaData": [{"name": "attributeDeclarations", "elementCount": 1},
                      {"name": "networkAttributes", "elementCount": 1},
                      {"name": "nodes", "elementCount": len(nodes)},
                      {"name": "edges", "elementCount": len(edges)}]},
        {"attributeDeclarations": [{
            "networkAttributes": dict(
                {"name": {"d": "string"}, "description": {"d": "string"},
                 CANONICAL_ATTR: {"d": "string"},
                 "symposium_artifact_name": {"d": "string"},
                 "symposium_artifact_type": {"d": "string"}},
                **{k: {"d": "boolean" if isinstance(v, bool) else "string"}
                   for k, v in marks.items()}),
            "nodes": {"name": {"d": "string"}, "type": {"d": "string"}},
            "edges": {"interaction": {"d": "string"}}}]},
        {"networkAttributes": [dict(
            {"name": h["name"],
             "description": h.get("title") or h.get("description", "") or "",
             "symposium_artifact_name": h["name"],
             "symposium_artifact_type": h.get("type", ""),
             CANONICAL_ATTR: json.dumps(canonical)}, **marks)]},
        {"nodes": nodes},
        {"edges": edges},
        {"status": [{"error": "", "success": True}]},
    ]


def to_cx2_blob(name, description, payload, marks=None, attr=None):
    """An opaque payload as a CX2 network — used for the event log, never for an Artifact.

    This is NOT a projection of anything: there is no canonical JSON, no Objects, and
    deliberately no `symposium_canonical` attribute, because a telemetry network is not a bid
    for publication and must never be mistaken for one. It carries the log verbatim in a
    single attribute and one placeholder node, since an entirely empty network is not
    something this deployment has been tested to accept.
    """
    marks = dict(marks or {TELEMETRY_MARK: True})
    attr = attr or TELEMETRY_ATTR
    return [
        {"CXVersion": "2.0", "hasFragments": False},
        {"metaData": [{"name": "attributeDeclarations", "elementCount": 1},
                      {"name": "networkAttributes", "elementCount": 1},
                      {"name": "nodes", "elementCount": 1},
                      {"name": "edges", "elementCount": 0}]},
        {"attributeDeclarations": [{
            "networkAttributes": dict(
                {"name": {"d": "string"}, "description": {"d": "string"},
                 attr: {"d": "string"}},
                **{k: {"d": "boolean" if isinstance(v, bool) else "string"}
                   for k, v in marks.items()}),
            "nodes": {"name": {"d": "string"}, "type": {"d": "string"}}}]},
        {"networkAttributes": [dict(
            {"name": name, "description": description, attr: payload}, **marks)]},
        {"nodes": [{"id": 0, "v": {"name": name, "type": "SessionOutput"}}]},
        {"edges": []},
        {"status": [{"error": "", "success": True}]},
    ]


def extract_blob(network_uuid, tok, attr=TELEMETRY_ATTR):
    """-> (payload_string, network_attributes, None) or (None, na, reason)."""
    st, txt = api("GET", f"/v3/networks/{network_uuid}", tok, raw=True)
    if st != 200:
        return None, None, f"cannot read network: HTTP {st}"
    try:
        for asp in json.loads(txt):
            if "networkAttributes" in asp:
                na = asp["networkAttributes"][0]
                if attr not in na:
                    return None, na, f"network carries no '{attr}' attribute"
                return na[attr], na, None
    except Exception as e:                                     # noqa: BLE001
        return None, None, f"malformed CX2: {e}"
    return None, None, "no networkAttributes aspect"


def upload_cx2(aspects, tok):
    """-> (status, uuid-or-error)."""
    body = json.dumps(aspects).encode()
    bd = "----symposium"
    parts = (f'--{bd}\r\nContent-Disposition: form-data; name="CXNetworkStream"; '
             f'filename="n.cx2"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    parts += body + f"\r\n--{bd}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/v3/networks", data=parts, method="POST",
        headers={"Authorization": f"Basic {tok}",
                 "Content-Type": f"multipart/form-data; boundary={bd}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode())["uuid"]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300]
    except Exception as e:
        return 0, f"transport error: {e}"


def extract_artifact(network_uuid, tok):
    """-> (canonical_dict, network_attributes, None) or (None, None, reason)."""
    st, txt = api("GET", f"/v3/networks/{network_uuid}", tok, raw=True)
    if st != 200:
        return None, None, f"cannot read network: HTTP {st}"
    try:
        for asp in json.loads(txt):
            if "networkAttributes" in asp:
                na = asp["networkAttributes"][0]
                if CANONICAL_ATTR not in na:
                    return None, na, f"network carries no '{CANONICAL_ATTR}' attribute"
                return json.loads(na[CANONICAL_ATTR]), na, None
    except Exception as e:
        return None, None, f"malformed CX2 or canonical JSON: {e}"
    return None, None, "no networkAttributes aspect"


def extract_canonical(network_uuid, tok):
    """-> (canonical_dict, None) or (None, reason)."""
    c, _, err = extract_artifact(network_uuid, tok)
    return c, err


def load_canonical_dir(path):
    """Every canonical artifact in a mirror directory.

    Filters on STRUCTURE, not filename: a mirror also holds sync's `manifest.json` and
    `.sync_state.json`, and `Path.glob("*.json")` matches dotfiles. Anything without an
    "artifact" header is not an artifact and is skipped rather than crashing the caller.
    """
    out = []
    for p in sorted(Path(path).glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception as e:
            print(f"  ! mirror file {p.name} is unreadable: {e}")
            continue
        if isinstance(d, dict) and isinstance(d.get("artifact"), dict):
            out.append(d)
    return out
