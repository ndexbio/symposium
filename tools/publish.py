"""Member-side publish tool — validate locally, then submit to the Symposium record.

The rule this exists to enforce: **nothing is uploaded that the gate would reject.** The
validator run here is the same code the admin gate runs, against the same record, so a local
ACCEPT means the gate will accept too. A rejection should be a surprise, not the workflow.

  export NDEX_LYRA_USER=agent_lyra  NDEX_LYRA_PASSWORD=…
  export SYMPOSIUM_MIRROR=./record          # git clone of the community record
  export SYMPOSIUM_ADMIN=ndex-admin

  python publish.py --as LYRA --role researcher --check  argument.json   # validate only
  python publish.py --as LYRA --role researcher          argument.json
  python publish.py --as LYRA --role analyst  run.json data.json         # one act, together
  python publish.py --roles                    # list the roles
  python publish.py --roles importer           # print one in full

A ROLE is not a MEMBER. One account operates in different roles in different sessions, and
every artifact is attributed to the Member either way (roles/). --role limits which
Artifact types this session may publish. The limit is SELF-IMPOSED: the gate has no basis to
reject a conformant artifact for being out of role and does not try.

Pull the mirror before publishing. Validation is only as good as the record it sees: a stale
mirror can miss a name collision or an address that has not landed yet.

Exit 0 = published (or --check passed). Exit 1 = nothing was uploaded.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import telemetry
from ndex_io import (auth, whoami, user_uuid, grant_read, to_cx2, upload_cx2,
                     load_canonical_dir)
from validate import (EMBED_REFUSE, EMBED_REVIEW, embedded_size, parse_instant, passed,
                         validate)

MIRROR = Path(os.environ.get("SYMPOSIUM_MIRROR", "./record"))
ADMIN = os.environ.get("SYMPOSIUM_ADMIN", "ndex-admin")
ROLES_DIR = Path(__file__).parent / "roles"
FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.S)


def load_roles():
    """-> {name: contract}. One markdown file per role; the contract is its first ```json fence.

    A directory rather than one roles.json, so that writing a role is copying a file rather than
    editing a shared one — no registry to update, no merge conflict, and no way to damage five
    other roles while editing a sixth. A fenced JSON block rather than front matter because this
    is standard-library-only Python: `json.loads` on the fence is exact, where a hand-rolled YAML
    parser would be a new way to be silently wrong about what a role permits.

    Prose in the file is for the agent to read. Only the fence is read here, and only
    `may_publish` and `must_not` are used at all.
    """
    out = {}
    if not ROLES_DIR.is_dir():
        print(f"! no roles directory at {ROLES_DIR}")
        return out
    for p in sorted(ROLES_DIR.glob("*.md")):
        m = FENCE.search(p.read_text())
        if not m:
            continue                       # README.md and anything else without a contract
        try:
            c = json.loads(m.group(1))
        except Exception as e:             # noqa: BLE001
            print(f"! {p.name}: contract block is not valid JSON — {e}")
            continue
        name = c.get("role") or p.stem
        if name != p.stem:
            print(f"! {p.name}: contract says role '{name}' but the file is named "
                  f"'{p.stem}' — using the filename")
            name = p.stem
        c.setdefault("must_not", [])
        c.setdefault("may_publish", [])
        c["_path"] = p
        out[name] = c
    return out


def load_record():
    if not MIRROR.exists():
        print(f"! mirror '{MIRROR}' does not exist — validation cannot check name collisions "
              f"or resolve addresses into the record. Clone/pull it, or set SYMPOSIUM_MIRROR.")
        return []
    return load_canonical_dir(MIRROR)


def root(addr):
    return str(addr).lstrip("@").split("#")[0].split(".")[0]


def main(argv):
    roles = load_roles()
    if "--roles" in argv:
        # `--roles <name>` prints one in full, so an agent never hand-parses a file to find its
        # own entry — the thing that made a single roles.json awkward to read.
        after = argv[argv.index("--roles") + 1:]
        want = after[0] if after and not after[0].startswith("-") else None
        if want:
            if want not in roles:
                print(f"! unknown role '{want}'. Known: {', '.join(roles)}")
                return 2
            print(roles[want]["_path"].read_text())
            return 0
        for name, r in sorted(roles.items()):
            print(f"  {name:12} {', '.join(r['may_publish'])}\n               {r['purpose']}")
        print(f"\n  python3 publish.py --roles <name>   print one in full "
              f"({ROLES_DIR.name}/<name>.md)")
        return 0
    if "--as" not in argv:
        print(__doc__)
        return 2
    prefix = argv[argv.index("--as") + 1]
    role = argv[argv.index("--role") + 1] if "--role" in argv else None
    if role is not None and role not in roles:
        print(f"! unknown role '{role}'. Known: {', '.join(roles)}")
        return 2
    check_only = "--check" in argv
    paths = [a for a in argv[1:] if a.endswith(".json")]
    if not paths:
        print("no artifact .json files given")
        return 2

    # `--check` uploads nothing and needs no network. It still needs to know WHO you are,
    # because the naming rule is checked against the account — but the username alone
    # settles that, so an unauthenticated --check is allowed and says so. This is what
    # lets someone read the repo and try the loop against the demonstration record before
    # they have been given credentials.
    tok = None
    if check_only and not os.environ.get(f"NDEX_{prefix}_PASSWORD"):
        account = os.environ.get(f"NDEX_{prefix}_USER")
        if not account:
            print(f"! set NDEX_{prefix}_USER (the account you are publishing as) — --check "
                  f"needs it to apply the naming rule. No password is required for --check.")
            return 2
        print(f"  note: no NDEX_{prefix}_PASSWORD set — validating as '{account}' without "
              f"authenticating. Nothing can be uploaded from this session.\n")
    else:
        user, tok = auth(prefix)
        me = whoami(tok)
        if not me:
            print(f"! {prefix} could not authenticate as a Symposium member")
            return 1
        account = me.get("userName")

    arts = []
    for p in paths:
        try:
            arts.append(json.loads(Path(p).read_text()))
        except Exception as e:
            print(f"! {p}: not readable as JSON — {e}")
            return 1

    record = load_record()
    record_names = {r["artifact"]["name"] for r in record if r.get("artifact", {}).get("name")}
    members = {r["artifact"]["published_by"].lstrip("@") for r in record
               if r.get("artifact", {}).get("published_by")}
    members |= {account, ADMIN} | {m.strip() for m in
                                   os.environ.get("SYMPOSIUM_MEMBERS", "").split(",") if m.strip()}

    allowed = set(roles[role]["may_publish"]) if role else None
    # The log path is printed every run because it has to be HANDED OVER at the end of the
    # session — there is no shared filesystem, so nothing collects it automatically.
    print(f"publishing as {account}"
          + (f", role {role} ({', '.join(sorted(allowed))})" if role else ", NO ROLE SET")
          + f" — record holds {len(record)} artifact(s)")
    print(f"  event log: {telemetry.LOG}  (hand this file over at the end of the session)\n")
    if not role:
        print("  note: no --role given, so no type limit is applied this session\n")

    # The gate stamps `created` on acceptance; a provisional stamp here lets the local run
    # exercise the ordering checks. It is stripped again before upload.
    #
    # It must be strictly LATER than everything in the record — the gate stamps at accept
    # time, which is always after this — or an artifact published in the same second as its
    # own dependency fails locally for something the gate would allow. And it increments
    # across the files given, so `publish.py data.json argument.json` models the order the
    # gate will accept them in.
    stamps = [t for t in (parse_instant(r["artifact"].get("created")) for r in record) if t]
    base = datetime.now(timezone.utc)
    if stamps:
        base = max(base, max(stamps))
    for i, a in enumerate(arts, start=1):
        a["artifact"]["created"] = (base + timedelta(seconds=i)).isoformat(timespec="seconds")

    # Three refusals that must not be pooled: the naming rule and the role limit are this
    # tool declining, the validator is the SPECIFICATION declining. Only the last says
    # anything about whether the specification is workable, so the log keeps them apart.
    fatal = False
    verdicts = {}
    for a in arts:
        h = a["artifact"]
        name = h.get("name", "<unnamed>")
        kinds = set()
        if not str(name).startswith(f"{account}_"):
            print(f"  {name}: FAIL  name must be prefixed '{account}_' (profile naming rule)")
            fatal = True
            kinds.add("naming")
        if allowed is not None and h.get("type") not in allowed:
            print(f"  {name}: FAIL  role '{role}' may not publish a {h.get('type')} "
                  f"(allowed: {', '.join(sorted(allowed))})")
            for line in roles[role].get("must_not", []):
                print(f"           {line}")
            fatal = True
            kinds.add("role")
        # one session holds one role, so the role segment partitions the namespace and keeps
        # two concurrent sessions of the same Member from colliding on a name
        if role and f"_{role}_" not in str(name):
            print(f"  {name}: note  name does not carry the role segment "
                  f"('{account}_{role}_<topic>_v1'); concurrent sessions may collide")
        # An operational guardrail, not a specification rule — which is why it lives here and
        # not in the validator, and why the validator only ever says REVIEW about size. There
        # is no path for the admin to put agent-generated data on the file store during the
        # event, so a result that will not embed cannot be published at all. Better to learn
        # that here, with the analysis still in hand, than as an HTTP 413 at the gate.
        total, props = embedded_size(a)
        if total > EMBED_REFUSE:
            biggest = (f"\n           largest property: '{props[0][1]}' on {props[0][0]}, "
                       f"{props[0][2] // 1024} KB" if props else "")
            print(f"  {name}: FAIL  embedded payload is {total // 1024} KB, over the "
                  f"{EMBED_REFUSE // 1024} KB limit{biggest}\n"
                  f"           Results are always embedded in this event — there is no path to "
                  f"publish bulk data\n           to the file store. Narrow the analysis so the "
                  f"result is one a reader can read, or\n           defer it and say so in the "
                  f"session report.")
            fatal = True
            kinds.add("size")
        sibs = [x for x in arts if x is not a]
        findings = validate(a, record + sibs, members)
        ok = passed(findings)
        # a conformant artifact can still be out of role: two separate verdicts, kept apart
        print(f"  {name}: spec {'ok' if ok else 'FAIL'}")
        for x in findings:
            print(f"      [{x['level']:6} {x['check']:9}] {x['msg']}")
        if not ok:
            kinds.add("spec")
        fatal = fatal or not ok
        verdicts[id(a)] = (name, h.get("type"), findings, kinds)

    # An output names its Analysis with `produced_by` and is found by search (spec 2.5), so an
    # Analysis is complete on its own and it is the OUTPUT that can arrive too early. Publishing
    # one whose Analysis is nowhere fails above on the address; this says what to do about it
    # rather than leaving a resolution error to be read as a typo.
    here = {a["artifact"]["name"] for a in arts}
    for a in arts:
        h = a["artifact"]
        producer = root(h["produced_by"]) if h.get("produced_by") else None
        if producer and producer not in here and producer not in record_names:
            print(f"\n  note: {h['name']} cites Analysis '{producer}', which is not in this "
                  f"submission\n        and not in the record. An Analysis is published before "
                  f"its outputs (spec 2.5) —\n        publish them in one act: "
                  f"`publish.py --as … {producer}.json {h['name']}.json`")

    # Every attempt is logged, passing ones included: the question this answers is how many
    # rounds an artifact took to become publishable, and that is uncountable if only the
    # failures are recorded.
    action = "check" if check_only else "publish"
    for a in arts:
        name, atype, findings, kinds = verdicts[id(a)]
        telemetry.emit(account, action, "refused" if kinds else "passed",
                       artifact=name, atype=atype, role=role,
                       findings=findings, refusal=kinds)
    if fatal:
        print("\nnothing uploaded — fix the failures above and retry")
        return 1
    if check_only:
        print("\n--check: validation passed; nothing uploaded")
        return 0

    admin_uuid = user_uuid(ADMIN, tok)
    if not admin_uuid:
        print(f"\n! cannot resolve admin account '{ADMIN}' — aborting before upload")
        return 1

    print()
    for a in arts:
        a["artifact"]["created"] = None            # the gate owns the timestamp
        name = a["artifact"]["name"]
        st, uuid = upload_cx2(to_cx2(a), tok)
        if st not in (200, 201):
            print(f"  {name}: upload FAILED — HTTP {st} {uuid}")
            return 1
        # The grant IS the submission signal: without it the admin cannot see the network
        # at all, so an upload without a grant is not a submission.
        if not grant_read(uuid, admin_uuid, tok):
            print(f"  {name}: uploaded {uuid} but the READ grant to {ADMIN} FAILED — "
                  f"the gate cannot see it. Grant it manually or delete and retry.")
            return 1
        telemetry.emit(account, "publish", "submitted", artifact=name,
                       atype=a["artifact"].get("type"), role=role,
                       findings=verdicts[id(a)][2], network=uuid)
        print(f"  {name}: submitted  {uuid}  (READ granted to {ADMIN})")

    print(f"\n{len(arts)} artifact(s) submitted. The gate stamps `created` on acceptance and "
          f"copies to the record;\nrejections arrive as a NonGroundable network readable by "
          f"{account}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
