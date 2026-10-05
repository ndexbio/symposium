"""Member-side publish tool — validate locally, then submit to the Symposium record.

The rule this exists to enforce: **nothing is uploaded that the gate would reject.** The
validator run here is the same code the admin gate runs, against the same record, so a local
ACCEPT means the gate will accept too. A rejection should be a surprise, not the workflow.

Run it as `/symposium publish …`, in the session's working directory: the context there
(`/symposium setup` or `bootstrap`) says who you are and which community you publish to, and
`./record` beside it is your copy of the record (`/symposium sync` keeps it current).

  python publish.py --role researcher --check  argument.json   # validate only
  python publish.py --role researcher          argument.json
  python publish.py --role analyst          run.json           # then, once accepted:
  python publish.py --role analyst          data.json          # ...its output
  python publish.py --roles                    # list the roles
  python publish.py --roles importer           # print one in full

A ROLE is not a MEMBER. One account operates in different roles in different sessions, and
every artifact is attributed to the Member either way (roles/). --role limits which
Artifact types this session may publish. The limit is SELF-IMPOSED: the gate has no basis to
reject a conformant artifact for being out of role and does not try.

It syncs first, every time, `--check` included: validation is only as good as the record it
sees, and a stale copy can miss a name collision or an address that has not landed yet. So the
data server must be reachable; when it is not, nothing is checked and nothing is submitted.

Exit 0 = published (or --check passed). Exit 1 = nothing was uploaded.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import telemetry
from data_io import SUBMISSION_MARK, DataError, Mirror, SymposiumData
from sync import Sync
from validate import (
    EMBED_REFUSE,
    embedded_size,
    parse_instant,
    passed,
    validate,
)

MIRROR = Mirror()
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
    `may_publish`, `may_import` and `must_not` are used at all.

    `may_import` is separate from `may_publish` because importing is not a type. An import is
    a Data artifact and Data is what an analyst is meant to publish; what marks it is
    `import_method` (spec 1.10). Only `importer` claims it, and absent means no.
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
        # Absent means no: a role that does not claim the importer's job does not get it by
        # omission, which is what let three imports through under `analyst` and `researcher`.
        c.setdefault("may_import", False)
        c["_path"] = p
        out[name] = c
    return out


def load_record():
    if not MIRROR.exists():
        print(f"! no record copy at '{MIRROR.root}/' — validation cannot check name collisions "
              f"or resolve addresses into the record. Run `/symposium sync` here first.")
        return []
    return MIRROR.load()


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
    role = argv[argv.index("--role") + 1] if "--role" in argv else None
    if role is not None and role not in roles:
        print(f"! unknown role '{role}'. Known: {', '.join(roles)}")
        return 2
    check_only = "--check" in argv
    paths = [a for a in argv[1:] if a.endswith(".json")]
    if not paths:
        print("no artifact .json files given")
        return 2
    # ONE ARTIFACT PER SUBMISSION. Publication is strictly serial: the gate stamps one
    # `created` per artifact and validates each against the record as it stands at that
    # moment (spec 1.9). Submitting several at once used to be allowed and is not, because
    # it made the member's local ordering and the gate's stamped ordering two different
    # things — a citation between two artifacts in the same call passed `--check`, which
    # stamped them a second apart in argument order, and was then refused by the gate,
    # which stamped them as one act. An Analysis and its outputs are published one at a
    # time, the Analysis first, each waiting for acceptance (spec 2.5).
    if len(paths) > 1:
        print(f"! {len(paths)} artifacts given; publication is strictly serial and takes one.\n"
              f"  Publish them one at a time, in the order their addresses require, waiting for\n"
              f"  the gate to accept each before submitting the next. An Analysis goes before\n"
              f"  the artifacts it produced (spec 2.5).\n"
              f"  Given: {', '.join(Path(p).name for p in paths)}")
        return 2

    # WHO you are comes from this directory's context. Then a sync pass, `--check` included:
    # validation runs against the record as it stands NOW, and against every member (the
    # roster and the admin, fetched live), exactly as the gate will.
    data = SymposiumData()
    try:
        account = data.context()["handle"]
    except DataError as e:
        print(f"! {e}")
        return 2
    sync = Sync(data, quiet=True)
    if sync.once(sync.load_state()) is None:
        print("! the data server could not be reached — nothing was checked and nothing was "
              "submitted.\n  Validation needs the current record and roster; try again once "
              "it answers.")
        return 1

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
    members |= {account} | sync.members

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
    # own dependency fails locally for something the gate would allow.
    #
    # There is exactly one artifact, so there is exactly one stamp, and this reproduces what
    # the gate will do: validate this artifact against the record as it stands. That identity
    # is what makes the guarantee in MEMBER-AGENT-INSTRUCTIONS §3 true — a `--check` pass
    # means the gate will accept. It stopped being true when a call could carry several
    # artifacts, because only the gate knew what `created` each would get.
    stamps = [t for t in (parse_instant(r["artifact"].get("created")) for r in record) if t]
    base = datetime.now(timezone.utc)
    if stamps:
        base = max(base, max(stamps))
    arts[0]["artifact"]["created"] = (base + timedelta(seconds=1)).isoformat(timespec="seconds")

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
        # IMPORTING IS A SEPARATE ACT FROM PUBLISHING A TYPE. `may_publish` cannot express it:
        # an import is a Data artifact, and Data is exactly what an analyst is meant to
        # publish. What distinguishes them is `import_method`, which spec 1.10 requires on
        # anything rendered from outside the record. The fidelity policy draws a line between
        # the importer's job and the analyst's, and without this check that line was invisible
        # at the moment it was crossed — three imports in this deployment's first run were
        # published by sessions holding `analyst` and `researcher`, one of them by a Member
        # whose own role file told her to ask an importer first.
        if allowed is not None and h.get("import_method") \
                and not roles[role].get("may_import", False):
            print(f"  {name}: FAIL  role '{role}' may not import — this artifact carries "
                  f"`import_method`.\n"
                  f"           Rendering outside material into the record is the importer's "
                  f"act and its own\n           job (policy/import-fidelity.md). Publish it "
                  f"from an `--role importer` session,\n           or ask the Member holding "
                  f"that role.")
            fatal = True
            kinds.add("role")
        # one session holds one role, so the role segment partitions the namespace and keeps
        # two concurrent sessions of the same Member from colliding on a name
        if role and f"_{role}_" not in str(name):
            print(f"  {name}: note  name does not carry the role segment "
                  f"('{account}_{role}_<topic>_v1'); concurrent sessions may collide")
        # An operational guardrail, not a specification rule — which is why it lives here and
        # not in the validator, and why the validator only ever says REVIEW about size. An
        # artifact stays small JSON that a reader can read; anything larger belongs in the file
        # store, cited from a `download` Content. Better to learn that here, with the analysis
        # still in hand.
        total, props = embedded_size(a)
        if total > EMBED_REFUSE:
            biggest = (f"\n           largest property: '{props[0][1]}' on {props[0][0]}, "
                       f"{props[0][2] // 1024} KB" if props else "")
            print(f"  {name}: FAIL  embedded payload is {total // 1024} KB, over the "
                  f"{EMBED_REFUSE // 1024} KB limit{biggest}\n"
                  f"           Store the full output in the file store (`/symposium data put "
                  f"<file> --collection files`)\n           and cite it from a `download` "
                  f"Content; embed only what a reader needs to read here.")
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
            print(f"\n  note: {h['name']} cites Analysis '{producer}', which is not in the "
                  f"record.\n        An Analysis is published before its outputs (spec 2.5), and "
                  f"publication is serial —\n        publish `{producer}.json` first, wait for the "
                  f"gate to accept it, then\n        run `/symposium sync` and publish this one.")

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

    print()
    for a in arts:
        a["artifact"]["created"] = None            # the gate owns the timestamp
        name = a["artifact"]["name"]
        # A submission is a file in the community's `inbox`, readable by its submitter and the
        # admin. Its name carries the moment of submission, so a resubmission after a
        # rejection is a new file; the gate finds it by its mark.
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        try:
            put = data.put_json(a, "inbox", f"{name}@{when}", {SUBMISSION_MARK: True})
        except DataError as e:
            print(f"  {name}: submission FAILED — {e}")
            return 1
        telemetry.emit(account, "publish", "submitted", artifact=name,
                       atype=a["artifact"].get("type"), role=role,
                       findings=verdicts[id(a)][2], submission=put["citation"])
        print(f"  {name}: submitted  {put['citation']}")

    print(f"\n{len(arts)} artifact(s) submitted. The gate stamps `created` on acceptance and "
          f"adds it to the record;\na rejection arrives as a reply only {account} can read "
          f"(`/symposium sync` lists it).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
