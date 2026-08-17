"""Member-side sync — mirror the community record from NDEx into a local directory.

The gate grants every member READ on every accepted artifact, so that fan-out IS the
distribution mechanism: a member needs no git access to hold a current copy of the record.

Two things make this simple, and both come from the specification:

  * Artifacts are IMMUTABLE, so sync is purely additive. Nothing already local is ever
    re-fetched or revised. The only thing that changes about an artifact already held is the
    set of later artifacts pointing AT it — its backlinks.
  * `created` is stamped by the gate, so it is a total order over the record. New artifacts
    are applied in that order, which is what makes address resolution work: the permission
    map returns an unordered dict, and an Argument applied before the Data it grounds on
    would fail to resolve.

  export NDEX_LYRA_USER=agent_lyra  NDEX_LYRA_PASSWORD=…
  export SYMPOSIUM_MIRROR=./record  SYMPOSIUM_ADMIN=ndex-admin

  python sync.py --as LYRA            # one pass
  python sync.py --as LYRA --watch    # poll every SYMPOSIUM_POLL seconds (default 30)

Writes `manifest.json` into the mirror: a build counter plus the dirty set, recording what
changed on each pass.

The browser does NOT patch itself from this. `serve.py` watches the mirror directory and
recompiles the whole record whenever a file changes — a full pass is fast enough at any size
this event will reach, and a full pass cannot drift from the record the way a partial update
can. The manifest is a log of what moved, not a build instruction.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ndex_io import (RECORD_MARK, api, auth, extract_artifact, permission_map, whoami,
                     load_canonical_dir)
from validate import validate, passed, parse_address

MIRROR = Path(os.environ.get("SYMPOSIUM_MIRROR", "./record"))
ADMIN = os.environ.get("SYMPOSIUM_ADMIN", "ndex-admin")
POLL = int(os.environ.get("SYMPOSIUM_POLL", "30"))
STATE = ".sync_state.json"          # uuid -> artifact name, so summaries are fetched once


def load_state():
    p = MIRROR / STATE
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"seen": {}, "build": 0}


def save_state(st):
    (MIRROR / STATE).write_text(json.dumps(st, indent=2) + "\n")


def load_record():
    return load_canonical_dir(MIRROR)


def outbound(canonical):
    """Artifact names this artifact points at — the pages whose backlinks it changes."""
    h, out = canonical["artifact"], set()

    def add(v):
        p = parse_address(v) if isinstance(v, str) and v.startswith("@") else None
        if p:
            out.add(p["root"])

    for k in ("produced_by", "extracted_from"):
        add(h.get(k))
    for k in ("supersedes", "outputs", "inputs", "used_models", "recipients"):
        for v in (h.get(k) or []):
            add(v)
    for o in canonical.get("objects", []):
        if o.get("type") == "Ground":
            add(o.get("citation"))          # a Ground's evidence address (spec 2.2.4)
    return out - {h.get("name")}


def fetch_new(tok, state):
    """-> (list of {uuid, canonical} not yet held locally, reachable, why).

    `reachable` is separate from an empty list ON PURPOSE. Previously any failure — TLS
    handshake, bad credentials, HTTP error — returned [], `once` saw nothing added, and
    printed "up to date". A frozen mirror and a current one were indistinguishable in the
    output, the exit code, and in --watch, which swallowed it every 30 seconds.

    That is the exact state the instructions warn hardest about: validation is only as good as
    the record it can see, and a stale mirror approves an artifact that reuses a name someone
    else just took. The gate catches the collision hours later.
    """
    me = whoami(tok)
    if not me:
        return [], False, ("could not authenticate — this may be the credentials, but a TLS or "
                           "network fault looks identical here; run preflight.py to tell them "
                           "apart")
    # Paginated: the raw endpoint caps at 100 silently, which would freeze a member's mirror at
    # the hundredth network they can see and look exactly like a record that stopped growing.
    st, perms = permission_map(me["externalId"], tok)
    if st != 200 or not isinstance(perms, dict):
        return [], False, f"permission listing failed: HTTP {st}"

    held = set(state["seen"])
    found = []
    for uuid in perms:
        if uuid in held:
            continue
        st, s = api("GET", f"/v2/network/{uuid}/summary", tok)
        if st != 200 or not isinstance(s, dict):
            continue
        if s.get("owner") != ADMIN:
            state["seen"][uuid] = None          # our own submission: never a record artifact
            continue
        canonical, attrs, err = extract_artifact(uuid, tok)
        # An admin-owned network readable by us is EITHER an accepted record artifact OR a
        # rejection reply. Only the record mark distinguishes them; ownership does not.
        if not (attrs or {}).get(RECORD_MARK):
            state["seen"][uuid] = None
            if (attrs or {}).get("symposium_reply"):
                print(f"  reply from the gate: {s.get('name')} "
                      f"(re {attrs.get('symposium_in_reply_to', '?')}) — not part of the record")
            continue
        if err:
            print(f"  ! {s.get('name')}: {err}")
            continue
        found.append({"uuid": uuid, "canonical": canonical})
    return found, True, ""


def _root(addr):
    """Artifact name at the head of an address."""
    return str(addr).lstrip("@").split("#")[0].split(".")[0]


def bundles_of(found):
    """Group what arrived into publication units, the way gate.py forms them to accept.

    An Analysis and the Artifacts it produces are ONE act (spec 1.8) and carry mutual
    `outputs`/`produced_by` addresses, so neither validates alone. Validating them one at a
    time — which is what this did — defers whichever half is tried first for the sibling that
    has not been applied yet, then defers the other for the first. Nothing is ever marked seen,
    so the pair retries and fails on every pass, forever.

    That made every analysis bundle in the record permanently invisible in every member's
    mirror and browser: 13 artifacts across four accounts on 2026-08-07, including each
    member's own accepted work. Nothing needed republishing — they were accepted all along.

    A bundle sorts by its earliest `created` so the record's total order is preserved across
    bundles, which is what lets an Argument resolve the Data it grounds on.
    """
    groups = {}
    for f in found:
        h = f["canonical"]["artifact"]
        leader = _root(h["produced_by"]) if h.get("produced_by") else h["name"]
        groups.setdefault(leader, []).append(f)
    return sorted(groups.values(),
                  key=lambda g: min(x["canonical"]["artifact"].get("created") or "" for x in g))


def apply(found, state):
    """Validate and write, oldest first. -> (added, dirty, deferred)."""
    record = load_record()
    names = {r["artifact"]["name"] for r in record}
    members = {r["artifact"]["published_by"].lstrip("@") for r in record
               if r.get("artifact", {}).get("published_by")} | {ADMIN}
    members |= {f["canonical"]["artifact"].get("published_by", "@").lstrip("@") for f in found}

    # the gate's `created` is the record's total order; apply in it or addresses will not resolve
    found.sort(key=lambda f: f["canonical"]["artifact"].get("created") or "")

    added, dirty, deferred = [], set(), []
    for bundle in bundles_of(found):
        fresh = []
        for f in bundle:
            name = f["canonical"]["artifact"]["name"]
            if name in names:
                state["seen"][f["uuid"]] = name
            else:
                fresh.append(f)
        if not fresh:
            continue

        # Each member is validated against the record PLUS its siblings, so the mutual
        # outputs/produced_by addresses resolve — the same construction as gate.py.
        sibs = [f["canonical"] for f in fresh]
        results = [(f, validate(f["canonical"], record + [c for c in sibs if c is not f["canonical"]],
                                members)) for f in fresh]

        if not all(passed(fd) for _, fd in results):
            # One act: hold the whole unit rather than write half of it. Usually a dependency
            # that has not arrived yet — retry next tick rather than drop.
            for f, fd in results:
                if not passed(fd):
                    deferred.append((f["canonical"]["artifact"]["name"],
                                     [x["msg"] for x in fd if x["level"] == "FAIL"][:2]))
            continue

        for f in fresh:
            c = f["canonical"]
            name = c["artifact"]["name"]
            (MIRROR / f"{name}.json").write_text(json.dumps(c, indent=2) + "\n")
            state["seen"][f["uuid"]] = name
            record.append(c)
            names.add(name)
            added.append(name)
            dirty |= {name} | (outbound(c) & names)  # its own page + every page it points at
    return added, dirty, deferred


def write_manifest(state, added, dirty, total):
    state["build"] += 1
    (MIRROR / "manifest.json").write_text(json.dumps({
        "build": state["build"],
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifacts": total,
        "added": sorted(added),
        "dirty": sorted(dirty | {"index"}),
    }, indent=2) + "\n")


def once(tok, state):
    found, reachable, why = fetch_new(tok, state)
    if not reachable:
        held = len(load_record())
        print(f"! COULD NOT REACH THE SERVER — {why}")
        print(f"  Your mirror is UNCHANGED at {held} artifact(s) and may now be STALE.")
        print(f"  Do not publish against it: validation can only see the record it has, so a")
        print(f"  stale mirror will approve a name someone else has already taken.")
        return None
    added, dirty, deferred = apply(found, state)
    for name, why in deferred:
        print(f"  deferred {name}: {why[0] if why else 'unresolved'}")
    total = len(load_record())
    if added:
        write_manifest(state, added, dirty, total)
        print(f"  +{len(added)}: {', '.join(added)}")
        print(f"  build {state['build']}, {total} artifact(s), {len(dirty | {'index'})} page(s) dirty")
    save_state(state)
    return len(added)


def main(argv):
    if "--as" not in argv:
        print(__doc__)
        return 2
    _, tok = auth(argv[argv.index("--as") + 1])
    MIRROR.mkdir(parents=True, exist_ok=True)
    state = load_state()

    if "--watch" not in argv:
        n = once(tok, state)
        if n is None:
            return 1                       # unreachable: never report a stale mirror as fine
        if not n:
            print(f"  up to date — {len(load_record())} artifact(s)")
        return 0

    print(f"watching {MIRROR} (every {POLL}s) — ctrl-c to stop")
    misses = 0
    while True:
        try:
            if once(tok, state) is None:
                misses += 1
                if misses in (1, 5) or misses % 20 == 0:
                    print(f"  ({misses} consecutive failed poll(s) — the mirror is not being "
                          f"updated)")
            else:
                misses = 0
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"  ! sync error (will retry): {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
