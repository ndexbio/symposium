"""Symposium admin gate — discover, validate, accept-or-reject on the community's server.

The publication loop, exactly as smoke-tested 2026-08-05:

  member  : uploads CX2 (canonical JSON in the `symposium_canonical` network attribute),
            then grants ndex-admin READ.  Without the grant the admin cannot see it at all.
  admin   : polls granted networks -> extracts canonical -> validates (validate)
            ACCEPT : stamp `created`, copy into the record, fan out READ to every member,
                     write canonical JSON to the mirror repo, index the name
            REJECT : upload a reply artifact naming the failures; the member polls for it

Four server facts this is built around, all established empirically on build ac3ee:
  * group-principal sharing is broken, so read access fans out as user->user grants
  * folders are navigation only, and the folder REST API is absent (every path 404s inside
    a 500) — bundling is declared by the artifacts, not by a folder
  * a freshly uploaded private network has `indexLevel: NONE` and never appears in
    /v2/search/network, so discovery uses the permission map, not search
  * NDEx search TOKENISES and cannot do exact-name matching, so name uniqueness lives in the
    mirror repo index, never in a server query

Credentials come from the environment; nothing is passed on the command line.

  NDEX_ADMIN_USER / NDEX_ADMIN_PASSWORD        the gate's own account
  SYMPOSIUM_MEMBERS=agent_lyra,agent_vega,…    members who receive read access

  python gate.py --once            one pass
  python gate.py --dry-run         validate and report; publish nothing
  python gate.py --verify          report mirror vs server; repair nothing, publish nothing
  python gate.py --rebuild         rebuild the mirror from the server, then exit
  python gate.py --grant <member>  give a NEW member READ on everything already accepted

THE MIRROR IS A CACHE, NOT THE RECORD. Every accepted artifact is uploaded as an
admin-owned network carrying its whole canonical JSON, and the account listing returns that
JSON complete — verified against a 236 KB embedded payload. So the record travels with the
symposium rather than with this machine, and a lost mirror is recoverable in one call.

What a lost mirror WOULD cost is name uniqueness, and therefore immutability: the gate refuses
a name already in the record by consulting the mirror, so a mirror missing artifacts will
silently accept duplicates. Every run therefore checks the mirror against the server before
doing anything else — but as a CACHE CHECK, not a proof of equality.

  Measured on this deployment 2026-08-06: a network summary carries every network attribute
  as a `property`, so a summary costs the SAME as a full fetch — 239,715 bytes of summary for
  a 232 KB artifact against 239,570 bytes of full network. There is no metadata-only endpoint;
  `/v3/networks/{uuid}/summary` carries the properties too. Anything that walks summaries is
  moving the whole record.

  So the staleness check is the permission map instead: ~47 bytes per network, one call.
  It answers exactly the question that matters — does the server hold a record copy whose
  UUID this mirror does not know — and it is sound ONLY because artifacts are immutable and
  this gate is their only writer, so UUID equality implies content equality.

A gap is REPAIRED, not refused: the missing artifacts are fetched individually and written to
the mirror, and the run continues. Refusing was the old behaviour and it stopped the gate
mid-run, which is the worst moment to stop it. The run aborts only if a repair FAILS,
which is the state in which a duplicate name could genuinely slip through.

A UUID counts as known only if its artifact is actually present in the mirror directory. That
is what makes a deleted or half-restored mirror repair itself rather than trust its own
bookkeeping.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import telemetry
from ndex_io import (BASE, CANONICAL_ATTR, NON_ARTIFACT_MARKS, NON_ARTIFACT_SEGMENTS,
                     RECORD_MARK, REPLY_MARK, auth, api as _api, extract_artifact,
                     extract_canonical, grant_read as _grant, permission_map, to_cx2,
                     upload_cx2 as _upload, user_uuid, load_canonical_dir)
from validate import validate, passed, parse_instant

MIRROR = Path(os.environ.get("SYMPOSIUM_MIRROR", "./record"))
DRY = "--dry-run" in sys.argv

ADMIN_USER, ADMIN_TOK = auth("ADMIN")
MEMBERS = [m.strip() for m in os.environ.get("SYMPOSIUM_MEMBERS", "").split(",") if m.strip()]


def api(method, path, body=None, raw=False, tok=None):
    return _api(method, path, tok or ADMIN_TOK, body=body, raw=raw)


def upload_cx2(aspects, tok=None):
    return _upload(aspects, tok or ADMIN_TOK)


def _extract(uuid):
    return extract_canonical(uuid, ADMIN_TOK)


def _extract_full(uuid):
    """-> (canonical, network_attributes, err). The attributes are needed to read the role
    marks, which is how an event log is told apart from a submission for certain."""
    return extract_artifact(uuid, ADMIN_TOK)


def _marked(attrs, mark):
    """Is a role mark set? CX2 gives real booleans; a summary's `properties` gives the strings
    "true"/"false", and a bare truthiness test would read "false" as set."""
    return str((attrs or {}).get(mark, "")).lower() == "true"


def _from_summary(uuid, props):
    """Canonical JSON out of a summary already in hand, falling back to a full fetch.

    A summary carries every network attribute, so the submission has ALREADY been downloaded
    by the time discovery has classified it; fetching the network again doubles the cost of
    every new submission for nothing.

    The fallback is not decoration. Completeness of the canonical property in a summary is
    verified only up to ~236 KB, and a truncated payload would fail to parse rather than parse
    wrongly — so a parse failure means "fetch it properly", never "reject it".
    """
    raw = (props or {}).get(CANONICAL_ATTR)
    if raw:
        try:
            return json.loads(raw), props, None
        except Exception:                                      # noqa: BLE001
            pass
    return _extract_full(uuid)


# --------------------------------------------------------------------------- mirror repo
STATE = ".gate_state.json"      # the gate's UUID bookkeeping; never the record


def load_record():
    MIRROR.mkdir(parents=True, exist_ok=True)
    return load_canonical_dir(MIRROR)


def load_state():
    """UUID bookkeeping, and nothing else.

    `record`   admin-owned record copies      uuid -> artifact name
    `other`    admin-owned but not the record uuid -> reason (rejection replies, strays)
    `granted`  submissions already disposed of uuid -> what happened

    Every one of these is an optimisation and none of them is authoritative: losing this file
    costs one expensive pass, not correctness. `record` in particular is cross-checked against
    the mirror directory on every run, so it cannot vouch for an artifact that is not there.
    """
    try:
        s = json.loads((MIRROR / STATE).read_text())
    except Exception:                                          # noqa: BLE001
        s = {}
    return {"record": s.get("record") or {}, "other": s.get("other") or {},
            "granted": s.get("granted") or {}}


def save_state(state):
    (MIRROR / STATE).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def write_index(state):
    """Rewrite index.jsonl from the mirror. Derived, never appended.

    It used to be appended to as artifacts were accepted, which made it the one thing in this
    design that could drift from the record it described — exactly what a catalog artifact was
    rejected for. Rewriting it from the mirror at this scale costs nothing and cannot drift.
    """
    rows = []
    for c in load_canonical_dir(MIRROR):
        h = c["artifact"]
        rows.append({"name": h.get("name"), "type": h.get("type"),
                     "created": h.get("created"),
                     "network": next((u for u, n in state["record"].items()
                                      if n == h.get("name")), None)})
    rows.sort(key=lambda r: (r["created"] or "", r["name"] or ""))
    with (MIRROR / "index.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def write_record(canonical, uuid, state):
    p = MIRROR / f"{canonical['artifact']['name']}.json"
    p.write_text(json.dumps(canonical, indent=2) + "\n")
    state["record"][uuid] = canonical["artifact"]["name"]
    write_index(state)
    save_state(state)
    return p


# --------------------------------------------------------------------------- discovery
def discover(state):
    """Submissions the admin can see, driven by the grant itself.

    NOT by search: on this deployment a freshly uploaded private network has
    `indexLevel: NONE` and simply does not appear in /v2/search/network, so search-based
    discovery silently drops submissions. The permission map is exact and immediate — a
    member's grant IS the submission signal.

    The permission map costs ~47 bytes per network; a summary costs the WHOLE network, because
    every attribute rides along in `properties`. So a UUID already disposed of is skipped
    before its summary is fetched. Without that, every submission ever made and every event
    log ever pushed is re-downloaded in full on every pass — and a rejected submission is
    re-validated and re-rejected on every pass, posting a fresh reply network each time.

    A DEFERRED submission is deliberately not recorded as seen: it has to be looked at again
    when its sibling arrives.
    """
    st, me = api("GET", "/v2/user?valid=true")
    if st != 200:
        print(f"  ! cannot resolve admin account: HTTP {st}")
        return []
    # Paginated: the raw endpoint caps at 100 and does not say so, which silently hid every
    # submission past the hundredth network the admin could see. See ndex_io.permission_map.
    st, perms = permission_map(me["externalId"], ADMIN_TOK, "&permission=READ")
    if st != 200 or not isinstance(perms, dict):
        print(f"  ! permission listing failed: HTTP {st}")
        return []
    subs = []
    for uuid, level in perms.items():
        if level != "READ":
            continue                       # ADMIN/WRITE = our own record copies and replies
        if uuid in state["granted"]:
            continue                       # already accepted, rejected, or ruled out
        st, s = api("GET", f"/v2/network/{uuid}/summary")
        if st != 200 or not isinstance(s, dict):
            print(f"  ! summary {uuid[:8]} failed: HTTP {st}")
            continue                       # transient: never recorded as seen
        if s.get("owner") == ADMIN_USER:
            state["granted"][uuid] = "admin-owned"
            continue
        # A member's event log and its closing session report both arrive through this same
        # channel and neither is a bid for publication. Recorded as seen so the summary — which
        # carries the entire log — is paid for once and never again. Silently: neither is an
        # error, and a line per push per cycle is how a real failure gets missed at three o'clock.
        if any(seg in (s.get("name") or "") for seg in NON_ARTIFACT_SEGMENTS):
            state["granted"][uuid] = "non-artifact (name segment)"
            continue
        subs.append({"uuid": uuid, "name": s.get("name"), "owner": s.get("owner"),
                     "props": {p.get("predicateString"): p.get("value")
                               for p in (s.get("properties") or [])}})
    return subs


def grant_read(uuid, member_uuid):
    return _grant(uuid, member_uuid, ADMIN_TOK)


def member_uuids():
    out = {}
    for m in MEMBERS:
        u = user_uuid(m, ADMIN_TOK)
        if u:
            out[m] = u
        else:
            print(f"  ! cannot resolve member '{m}'")
    return out


def server_record():
    """Every accepted artifact, from the admin's own account. -> {name: (uuid, canonical)}

    ONE listing call. Network summaries carry `properties`, and the record copies stamp the
    whole canonical JSON into `symposium_canonical` — complete, not truncated, confirmed
    against a 236 KB embedded table. Rejection replies live in the same account and are
    excluded by their mark.

    Search is not used and must not be: this deployment tokenises names and cannot match one
    exactly, which is the whole reason name uniqueness never lived in a server query.
    """
    st, me = _api("GET", "/v2/user?valid=true", ADMIN_TOK)
    if st != 200 or not isinstance(me, dict):
        return None, f"cannot resolve admin account: HTTP {st}"
    st, nets = _api("GET", f"/v2/user/{me['externalId']}/networksummary", ADMIN_TOK)
    if st != 200 or not isinstance(nets, list):
        return None, f"cannot list admin networks: HTTP {st}"
    out = {}
    for n in nets:
        props = {p.get("predicateString"): p.get("value")
                 for p in (n.get("properties") or [])}
        if str(props.get(RECORD_MARK, "")).lower() != "true":
            continue                                   # a rejection reply, or something else
        raw = props.get(CANONICAL_ATTR)
        if not raw:
            continue
        try:
            canonical = json.loads(raw)
        except Exception:                              # noqa: BLE001
            continue
        name = canonical.get("artifact", {}).get("name") or n.get("name")
        out[name] = (n.get("externalId"), canonical)
    return out, None


def admin_owned_uuids():
    """Every network this account owns, as a UUID set. -> (uuids, err)

    ~47 bytes per network, one call, and it is the ONLY cheap thing on this deployment: a
    network summary carries all of its attributes, so walking summaries moves the whole record
    (measured: 239,715 bytes of "summary" for a 232 KB artifact). The permission map carries
    no attributes at all.
    """
    st, me = _api("GET", "/v2/user?valid=true", ADMIN_TOK)
    if st != 200 or not isinstance(me, dict):
        return None, f"cannot resolve admin account: HTTP {st}"
    st, perms = _api("GET", f"/v2/user/{me['externalId']}/permission"
                            f"?type=NETWORK&permission=ADMIN", ADMIN_TOK)
    if st != 200 or not isinstance(perms, dict):
        return None, f"cannot list admin-owned networks: HTTP {st}"
    return set(perms), None


def checkpoint(record, state, repair=True):
    """Cheap staleness check, then repair. -> (ok, added, unresolved, extra)

    `ok` is None if the server could not be reached at all — a different thing from a stale
    mirror, and not a reason to distrust what is already held.

    A UUID is KNOWN only if the artifact it maps to is actually a file in the mirror. Trusting
    the state file alone would let a mirror that lost its .json files still claim to know every
    name, and name uniqueness is exactly what the mirror is for.
    """
    names = {r["artifact"]["name"] for r in record if r.get("artifact", {}).get("name")}
    server, err = admin_owned_uuids()
    if server is None:
        print(f"  ! cannot reach the server to check the mirror: {err}")
        return None, [], [], set()

    known = {u for u, n in state["record"].items() if n in names} | set(state["other"])
    unknown = server - known
    extra = {n for u, n in state["record"].items() if u not in server and n in names}

    if not repair:                          # --verify reports; it does not touch the mirror
        return (not unknown), [], sorted(unknown), extra

    # Drop bookkeeping for artifacts that are no longer in the mirror, so a restored-from-
    # backup mirror does not carry a stale claim about what it holds.
    for u in [u for u, n in state["record"].items() if n not in names]:
        state["record"].pop(u)

    added, unresolved = [], []
    for uuid in sorted(unknown):
        canonical, na, ferr = _extract_full(uuid)
        if ferr or not canonical:
            # Could be a rejection reply or a stray, which carry no canonical JSON and are not
            # a gap; could equally be a network that failed to read. Tell them apart on the
            # role mark, which a reply always carries.
            if _marked(na, REPLY_MARK) or any(_marked(na, m) for m in NON_ARTIFACT_MARKS):
                state["other"][uuid] = "reply-or-non-artifact"
                continue
            unresolved.append(uuid)
            print(f"  ! cannot read admin-owned network {uuid[:8]}: {ferr or 'no canonical JSON'}")
            continue
        if not _marked(na, RECORD_MARK):
            state["other"][uuid] = "admin-owned, not marked as record"
            continue
        name = canonical.get("artifact", {}).get("name")
        if not name:
            state["other"][uuid] = "canonical JSON carries no artifact name"
            continue
        (MIRROR / f"{name}.json").write_text(json.dumps(canonical, indent=2) + "\n")
        state["record"][uuid] = name
        names.add(name)
        record.append(canonical)
        added.append(name)
    if added:
        write_index(state)
    save_state(state)
    return (not unresolved), added, unresolved, extra


def grant_backfill(member):
    """Give a member READ on every artifact already in the record. -> exit code

    Read access fans out at ACCEPT time, to whoever was in SYMPOSIUM_MEMBERS when the gate ran.
    A Member added later therefore holds grants on nothing published before they existed — and
    because discovery is the permission map, `sync.py` reports an empty record rather than an
    error. It looks exactly like a broken install.

    So adding a Member is two steps: create the account, then run this. It is idempotent.
    """
    # A newly created account is NOT immediately visible to /v2/user?username=. Observed
    # 2026-08-06: an account created and reported as isVerified:true still resolved as absent
    # when the grant was attempted moments later, and resolved normally minutes afterwards.
    # This is the same class of lag as the ~2s a fresh network takes to become readable, and it
    # arrives at exactly the wrong moment — right after someone creates an account, when
    # "no such account" reads as "the creation silently failed."
    uuid = None
    for attempt in range(6):
        uuid = user_uuid(member, ADMIN_TOK)
        if uuid:
            if attempt:
                print(f"  ('{member}' resolved on attempt {attempt + 1} — new accounts take a "
                      f"moment to become visible)")
            break
        if attempt < 5:
            time.sleep(5)
    if not uuid:
        print(f"! '{member}' does not resolve on {BASE} after 30s of retries.\n"
              f"  If you have JUST created it, wait a minute and run this again — a new account\n"
              f"  is not immediately visible, and this failure looks identical to one that\n"
              f"  never got created.\n"
              f"  If it persists, the account does not exist. Self-signup is disabled on this\n"
              f"  deployment, so an administrator has to create it.")
        return 1
    server, err = server_record()
    if server is None:
        print(f"! {err}")
        return 1
    ok = fail = 0
    for name, (net, _canonical) in sorted(server.items()):
        if grant_read(net, uuid):
            ok += 1
        else:
            fail += 1
            print(f"  ! could not grant READ on {name}")
    print(f"granted {member} READ on {ok} artifact(s)" + (f", {fail} FAILED" if fail else ""))
    if fail:
        return 1
    print(f"\nAdd them to the gate's environment so future acceptances include them:\n"
          f"    export SYMPOSIUM_MEMBERS={','.join(sorted(set(MEMBERS) | {member}))}")
    return 0


def rebuild_mirror():
    """Write the server's record back into the mirror. Never deletes anything local.

    This is the one place a whole-account listing is the right call: it is the recovery path,
    it runs once, and it genuinely needs every artifact's content. The per-run staleness check
    uses `checkpoint()` instead — see the module docstring for why the difference matters.
    """
    server, err = server_record()
    if server is None:
        print(f"! {err}")
        return 1
    MIRROR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    state["record"] = {}
    for name, (uuid, canonical) in sorted(server.items()):
        (MIRROR / f"{name}.json").write_text(json.dumps(canonical, indent=2) + "\n")
        state["record"][uuid] = name
    write_index(state)
    save_state(state)
    print(f"rebuilt {MIRROR} from the server: {len(server)} artifact(s), "
          f"index.jsonl and {STATE} rewritten")
    return 0


# --------------------------------------------------------------------------- accept / reject
def _root(addr):
    """Artifact name at the head of an address."""
    return str(addr).lstrip("@").split("#")[0].split(".")[0]


def order_submissions(subs, record_names):
    """Order the pending submissions for serial acceptance.

    Publication is strictly serial (spec 1.9, 2.5). Every artifact receives its own
    `created` and is validated against the record as it stands at that moment. There are no
    publication units, no shared timestamps and no all-or-nothing groups: this function
    decides only the ORDER in which a pass considers what is pending, so that an artifact is
    stamped after anything it addresses.

    Bundling used to live here. It is gone because it created the one thing spec 1.9 says
    cannot happen — two artifacts with an identical `created`, which are therefore not
    earlier than one another and cannot refer to each other. Making that publishable at all
    required an ordering exemption on `produced_by`, and the exemption then suppressed the
    ordering check on the very property most in need of it.

    An output names its Analysis with `produced_by` and that address must resolve (spec 2.5).
    An output whose Analysis is neither in the record nor pending in this pass is DEFERRED
    rather than rejected: the member may not have published it yet, and the correct order is
    the Analysis first.

    -> (ordered, deferred) where deferred is [(submission, [missing names])]"""
    by_name = {s["canonical"]["artifact"]["name"]: s for s in subs}

    def refs(sub):
        c = sub["canonical"]
        h = c["artifact"]
        out = set()
        for k in ("produced_by", "extracted_from"):
            if h.get(k):
                out.add(_root(h[k]))
        for k in ("supersedes", "inputs", "recipients"):
            for v in (h.get(k) or []):
                out.add(_root(v))
        for o in c.get("objects", []):
            if o.get("type") == "Ground":
                # A Ground's evidence address. Reading the wrong key here does not fail --
                # it returns "" for every Ground -- and the ordering below then ignores
                # every evidential reference in the pass, silently stamping an Argument
                # `created` before the Data it grounds on. Covered by test_gate.py case E.
                out.add(_root(o.get("citation", "")))
        return out - {h["name"]}

    pending, deferred = [], []
    for sub in subs:
        pb = sub["canonical"]["artifact"].get("produced_by")
        if pb:
            lead = _root(pb)
            if lead not in record_names and lead not in by_name:
                deferred.append((sub, [lead]))
                continue
        pending.append(sub)

    # Ready = nothing this submission references is still sitting unplaced. References to
    # artifacts already in the record, or to names not submitted at all, do not block: the
    # validator decides whether those resolve, not the ordering.
    ordered, placed = [], set(record_names)
    while pending:
        unplaced = {x["canonical"]["artifact"]["name"] for x in pending} - placed
        ready = [x for x in pending if not (refs(x) & unplaced)]
        if not ready:                  # a cycle among submissions; fall back to given order
            ready = pending[:1]
        for x in ready:
            ordered.append(x)
            placed.add(x["canonical"]["artifact"]["name"])
            pending.remove(x)
    return ordered, deferred


def accept(canonical, record, muuids, state, stamp=None, submission_uuid=None):
    name = canonical["artifact"]["name"]
    canonical["artifact"]["created"] = stamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if DRY:
        print(f"    (dry-run) would accept {name}")
        return True
    st, uuid = upload_cx2(to_cx2(canonical, marks={RECORD_MARK: True}))
    if st not in (200, 201):
        print(f"    ! record copy failed: HTTP {st} {uuid}")
        return False
    for m, mu in muuids.items():
        if mu and not grant_read(uuid, mu):
            print(f"    ! could not grant READ to {m}")
    write_record(canonical, uuid, state)
    if submission_uuid:
        state["granted"][submission_uuid] = f"accepted as {name}"
    print(f"    ACCEPTED -> record {uuid}, {len(muuids)} read grants, mirrored")
    return True


def reject(canonical, submitted_name, findings, owner, muuids):
    fails = [f"{x['check']}: {x['msg']}" for x in findings if x["level"] == "FAIL"]
    reply_name = f"{ADMIN_USER}_REPLY_{submitted_name}"
    reply = {"artifact": {"name": reply_name.replace("-", "_"), "type": "NonGroundable",
                          "specification_version": "1.0", "published_by": f"@{ADMIN_USER}",
                          "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "text": "REJECTED\n\nin_reply_to: " + submitted_name + "\n\n"
                                  + "\n".join(f"- {x}" for x in fails)},
             "objects": [], "relationships": []}
    print(f"    REJECTED ({len(fails)} failures)")
    for x in fails[:6]:
        print(f"      - {x[:150]}")
    if DRY:
        return
    st, uuid = upload_cx2(to_cx2(reply, marks={REPLY_MARK: True,
                                                 "symposium_in_reply_to": submitted_name}))
    if st in (200, 201):
        mu = muuids.get(owner)
        if mu:
            grant_read(uuid, mu)
        print(f"    reply posted -> {uuid} (readable by {owner})")
    else:
        print(f"    ! reply upload failed: HTTP {st} {uuid}")


def run_once():
    record = load_record()
    state = load_state()
    members = set(MEMBERS) | {ADMIN_USER}
    muuids = member_uuids()
    print(f"gate: record holds {len(record)} artifact(s); members {sorted(members)}"
          + ("  [DRY RUN]" if DRY else ""))

    # The mirror is how name uniqueness is enforced, so a mirror behind the server means this
    # run could accept a name that already exists. Repair the gap and carry on; abort only if
    # the repair fails, which is the only state in which a duplicate could actually slip in.
    ok, added, unresolved, extra = checkpoint(record, state)
    if added:
        print(f"  mirror was behind by {len(added)}; fetched and repaired: "
              f"{', '.join(sorted(added)[:5])}" + (" …" if len(added) > 5 else ""))
    if unresolved:
        print(f"  ! could not repair {len(unresolved)} admin-owned network(s): "
              f"{', '.join(u[:8] for u in unresolved[:5])}")
        print("  Name uniqueness is checked against the mirror, so running now could accept a "
              "duplicate\n  name into an immutable record. Fix it first:\n"
              "      python gate.py --rebuild")
        return 1
    if extra:
        print(f"  note: {len(extra)} artifact(s) in the mirror are not on the server "
              f"(deleted there?): {', '.join(sorted(extra)[:5])}")
    names = {r["artifact"]["name"] for r in record if r.get("artifact", {}).get("name")}

    raw = discover(state)
    print(f"gate: {len(raw)} new submission(s)\n")

    # Everything below marks a submission as seen only when its disposition is FINAL. A
    # transport failure is not final; a malformed name is.
    subs = []
    for s in raw:
        if s["name"] in names:
            print(f"  {s['name']}: already in the record — skipping")
            state["granted"][s["uuid"]] = "already in the record"
            continue
        canonical, na, err = _from_summary(s["uuid"], s.get("props"))
        if any(_marked(na, m) for m in NON_ARTIFACT_MARKS):
            state["granted"][s["uuid"]] = "non-artifact (role mark)"
            continue                       # a log or a report, whatever it is called
        if err:
            print(f"  {s['name']}: ! {err}")
            continue
        declared = canonical.get("artifact", {}).get("name")
        if declared != s["name"]:
            print(f"  {s['name']}: ! network name != artifact.name '{declared}'")
            state["granted"][s["uuid"]] = "network name != artifact.name"
            continue
        if not declared.startswith(f"{s['owner']}_"):
            print(f"  {declared}: ! name is not prefixed with the owner '{s['owner']}_'")
            state["granted"][s["uuid"]] = "name not prefixed with the owner"
            continue
        s["canonical"] = canonical
        subs.append(s)

    ordered, deferred = order_submissions(subs, names)
    # NOT `members`: that name holds the member-name set built above, and rebinding it here to a
    # list of submissions made every later validate() call raise `unhashable type: 'dict'`. The
    # gate then exited 1 on every pass and published nothing. It stayed hidden all day because it
    # needs a pass that has BOTH a deferral and something to validate.
    for waiting, missing in deferred:
        print(f"  DEFERRED {waiting['name']}\n    waiting for: {', '.join(missing)} "
              f"(an Analysis is published before its outputs, spec 2.5)")
        telemetry.emit("gate", "gate_defer", "deferred", artifact=waiting["name"],
                       atype=waiting["canonical"]["artifact"].get("type"),
                       submitter=waiting["owner"], waiting_for=sorted(missing))

    # Stamps must strictly increase from one artifact to the next. `order_submissions` already
    # orders them so one is accepted before anything addressing it, but ordering the ACCEPTS is
    # not enough: the ORDER check requires a Ground's target to be strictly EARLIER than the
    # artifact grounding on it, and at `timespec="seconds"` two artifacts processed in the same
    # wall-clock second get the same stamp. On 2026-08-07 that rejected the first
    # participant-built Argument in the record — it grounded on Data the gate had stamped in the
    # same second, in the same pass. A member cannot avoid this, because the gate owns `created`;
    # the gate was rejecting a correctly ordered submission for its own clock resolution. Seeded
    # from the record so the guarantee survives a restart.
    seen = [parse_instant(c.get("artifact", {}).get("created")) for c in record]
    prev = max([d for d in seen if d], default=None)

    for m in ordered:
        # One artifact, one stamp, one verdict. Nothing in this loop may make two artifacts
        # share a `created`: spec 1.9 says artifacts with an identical stamp are not earlier
        # than one another and cannot refer to each other, so a tie is not a convenience, it
        # is a pair of artifacts that can never cite each other for the life of the record.
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if prev is not None and now <= prev:
            now = prev + timedelta(seconds=1)
        prev = now
        stamp = now.isoformat(timespec="seconds")
        canonical = m["canonical"]
        canonical["artifact"]["created"] = stamp
        print(f"  {canonical['artifact']['name']}")

        f = validate(canonical, record, members)
        if passed(f):
            for x in f:
                print(f"    [REVIEW {x['check']}] {x['msg'][:110]}")
            if accept(canonical, record, muuids, state, stamp=stamp, submission_uuid=m["uuid"]):
                record.append(canonical)
                names.add(canonical["artifact"]["name"])
                # REVIEW findings are logged at the moment of acceptance because they are the
                # validator signal that SURVIVES into the record — the same findings can be
                # recomputed tomorrow, but not the fact that the gate saw them and accepted.
                telemetry.emit("gate", "gate_accept", "accepted",
                               artifact=canonical["artifact"]["name"],
                               atype=canonical["artifact"].get("type"),
                               submitter=m["owner"], findings=f)
        else:
            reject(canonical, m["name"], f, m["owner"], muuids)
            # Final: this network will never become acceptable, and a member fixing it uploads
            # a NEW one. Without this the same submission is re-rejected every pass and a fresh
            # reply network is posted each time.
            if not DRY:
                state["granted"][m["uuid"]] = "rejected"
            telemetry.emit("gate", "gate_reject", "rejected", artifact=m["name"],
                           atype=canonical["artifact"].get("type"),
                           submitter=m["owner"], findings=f, refusal=["spec"])
    # A dry run reports; it must not write. `gate_loop.py` holds this file and §4 of the handoff
    # tells the operator to run `--dry-run` while the loop is live: if a dry run's stale copy of
    # `state` lands between the loop's read and write, the loop's newest grants are lost and an
    # already-accepted submission is re-processed next pass, which fails UNIQUE and posts a
    # rejection reply for work that is in fact in the record.
    if not DRY:
        save_state(state)
    return 0


if __name__ == "__main__":
    if "--grant" in sys.argv:
        i = sys.argv.index("--grant") + 1
        if i >= len(sys.argv):
            sys.exit("usage: python gate.py --grant <member-account>")
        sys.exit(grant_backfill(sys.argv[i]))
    if "--rebuild" in sys.argv:
        sys.exit(rebuild_mirror())
    if "--verify" in sys.argv:
        # Reports, repairs nothing: --verify is what you run when you want to know, and it
        # should not change the thing it is reporting on.
        rec = load_record()
        st_ = load_state()
        ok, _added, unresolved, extra = checkpoint(rec, st_, repair=False)
        if ok is None:
            sys.exit(2)
        print(f"mirror {MIRROR}: {len(rec)} artifact(s)")
        print(f"  on the server, unknown to the mirror: "
              f"{[u[:8] for u in unresolved] or 'none'}")
        print(f"  in the mirror only (not on the server): {sorted(extra) or 'none'}")
        print("OK" if ok else
              "MIRROR IS BEHIND THE SERVER — the next run repairs it, or: python gate.py --rebuild")
        sys.exit(0 if ok else 1)
    sys.exit(run_once())
