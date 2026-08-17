#!/usr/bin/env python3
"""Create the community's accounts on a running record server.

    python3 bootstrap.py --community community.json
    python3 bootstrap.py --community community.json --dry-run
    python3 bootstrap.py --community community.json --show LYRA   # one member's credentials

A fresh NDEx instance accepts anonymous account creation on `POST /v2/user`, so the
first account needs no account — there is no chicken-and-egg problem on a server you
run yourself. That is also why the server is bound to localhost: an open signup
endpoint on a reachable port is an open signup endpoint.

NO PASSWORD IS EVER TYPED, PASTED, OR STORED IN THE REPOSITORY. This generates one per
account with `secrets`, sends it to the server once, and writes it to
`~/.ndex/symposium.env` with owner-only permissions — the same file the member tooling
reads. The roster file holds names and nothing else, so it can be committed. Handing a
member their credentials is `--show <PREFIX>`, which prints one account's two lines for
them to copy into their own machine's file.

Idempotent. An account that already exists is left alone: the server will not tell us
its password and this will not guess. If credentials for it are already in the file and
they authenticate, that is reported and nothing changes. If they are not, the account
name is already taken by something this tool cannot drive, and it says so rather than
overwriting a working account's entry with a password the server never accepted.

Standard library only, Python 3.9 or later. Nothing to install.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import secrets
import stat
import string
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SYMPOSIUM_BASE", "http://localhost:8080").rstrip("/")
CRED = pathlib.Path.home() / ".ndex" / "symposium.env"
ADMIN_PREFIX = "ADMIN"                       # gate.py authenticates as auth("ADMIN")
ALPHABET = string.ascii_letters + string.digits


def api(method, path, tok=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Accept": "application/json"}
    if tok:
        h["Authorization"] = f"Basic {tok}"
    if data:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode(errors="replace")
            return r.status, (json.loads(text) if text.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:200]
    except Exception as e:                                            # noqa: BLE001
        return 0, f"transport error: {e}"


def token(user, password):
    return base64.b64encode(f"{user}:{password}".encode()).decode()


def prefix_for(account):
    """`agent_lyra` -> LYRA. The tools take a prefix, not an account name."""
    tail = re.split(r"[_\-.]", account)[-1]
    return re.sub(r"[^A-Za-z0-9]", "", tail).upper() or account.upper()


def read_env():
    """KEY -> value from the credentials file, tolerating `export` and quotes."""
    if not CRED.exists():
        return {}
    out = {}
    for line in CRED.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        out[k.strip()] = v
    return out


def write_env(entries):
    """Merge `entries` into the credentials file, owner-readable only.

    Rewritten whole rather than appended to, so re-running does not accumulate a second
    entry for an account and leave the shell to decide which one wins.
    """
    CRED.parent.mkdir(parents=True, exist_ok=True)
    merged = read_env()
    merged.update(entries)
    body = ["# Symposium credentials. Readable only by you; never commit this file.",
            "# Written by server/bootstrap.py. Source it, or let tools/setup.py do that.",
            ""]
    for k in sorted(merged):
        body.append(f"export {k}={merged[k]}")
    CRED.write_text("\n".join(body) + "\n")
    CRED.chmod(stat.S_IRUSR | stat.S_IWUSR)


def create(account, password):
    """-> ('created' | 'exists' | error string)"""
    st, body = api("POST", "/v2/user", body={
        "userName": account, "password": password,
        "emailAddress": f"{account}@symposium.local",
        "firstName": account, "lastName": "Member", "isIndividual": True})
    if st in (200, 201):
        return "created"
    if st == 409:
        return "exists"
    return f"HTTP {st}: {body}"


def verify(account, password):
    st, body = api("GET", "/v2/user?valid=true", token(account, password))
    return st == 200 and isinstance(body, dict) and body.get("userName") == account


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--community", default="community.json",
                    help="roster file (default: community.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be created; contact the server only to check it is up")
    ap.add_argument("--show", metavar="PREFIX",
                    help="print one account's two credential lines, for handing to its owner")
    a = ap.parse_args(argv)

    if a.show:
        env = read_env()
        u, p = f"NDEX_{a.show.upper()}_USER", f"NDEX_{a.show.upper()}_PASSWORD"
        if u not in env or p not in env:
            print(f"! no entry for {a.show.upper()} in {CRED}")
            return 1
        print(f"export {u}={env[u]}\nexport {p}={env[p]}")
        return 0

    path = pathlib.Path(a.community)
    if not path.exists():
        print(f"! no roster at {path}. Copy community.example.json to community.json and edit it.")
        return 2
    try:
        cfg = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"! {path} is not valid JSON — {e}")
        return 2

    admin = cfg.get("admin")
    members = list(cfg.get("members") or [])
    if not admin:
        print(f"! {path} names no `admin`. The gate runs as that account.")
        return 2
    if not members:
        print(f"! {path} lists no `members`. A community of one has nobody to grant read to.")
        return 2

    accounts = [(ADMIN_PREFIX, admin)] + [(prefix_for(m), m) for m in members]
    seen = {}
    for pfx, acct in accounts:
        if pfx in seen:
            print(f"! '{acct}' and '{seen[pfx]}' both reduce to the prefix {pfx}, and the tools "
                  f"take a prefix. Rename one of them.")
            return 2
        seen[pfx] = acct

    st, _ = api("GET", "/v2/admin/status")
    if st != 200:
        print(f"! {BASE} is not answering (/v2/admin/status -> {st}).\n"
              f"  Start it with ./symposium_ndex.sh, or set SYMPOSIUM_BASE.")
        return 1
    print(f"server: {BASE}\ncredentials: {CRED}\n")

    if a.dry_run:
        for pfx, acct in accounts:
            print(f"  would ensure {acct:20} as NDEX_{pfx}_USER / NDEX_{pfx}_PASSWORD")
        return 0

    env, failed = read_env(), []
    for pfx, acct in accounts:
        uk, pk = f"NDEX_{pfx}_USER", f"NDEX_{pfx}_PASSWORD"
        known = env.get(pk) if env.get(uk) == acct else None
        if known and verify(acct, known):
            print(f"  {acct:20} exists, credentials verified")
            continue
        password = "".join(secrets.choice(ALPHABET) for _ in range(24))
        outcome = create(acct, password)
        if outcome == "created" and verify(acct, password):
            write_env({uk: acct, pk: password})
            env = read_env()
            print(f"  {acct:20} created, credentials written")
        elif outcome == "created":
            print(f"  {acct:20} ! created but would not authenticate — server may still be "
                  f"indexing; run this again in a few seconds")
            failed.append(acct)
        elif outcome == "exists":
            print(f"  {acct:20} ! the account exists and no working credentials for it are in\n"
                  f"  {'':20}   {CRED}. The server will not reveal a password. Either restore\n"
                  f"  {'':20}   that file, or choose a different account name in the roster.")
            failed.append(acct)
        else:
            print(f"  {acct:20} ! {outcome}")
            failed.append(acct)

    if failed:
        print(f"\n{len(failed)} account(s) not ready: {', '.join(failed)}")
        return 1

    roster = ",".join(m for _, m in accounts[1:])
    print(f"\nAll {len(accounts)} accounts ready. Two things follow.\n\n"
          f"  1. Every session needs the roster, so accepted Artifacts fan out to all of them:\n"
          f"       export SYMPOSIUM_MEMBERS={roster}\n\n"
          f"  2. Start the gate once to establish the record, then grant each member:\n"
          f"       cd ../tools && python3 gate.py --rebuild\n"
          + "".join(f"       python3 gate.py --grant {m}\n" for _, m in accounts[1:]) +
          f"\nHand a member their credentials with `bootstrap.py --show {accounts[1][0]}`.\n"
          f"Do not paste them into a chat with an assistant; a transcript is written down.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
