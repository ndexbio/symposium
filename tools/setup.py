#!/usr/bin/env python3
"""One-time setup for a Symposium participant. Safe for an assistant to run.

    python3 setup.py --as VEGA
    python3 setup.py --as VEGA --workdir ~/symposium-work
    python3 setup.py --as VEGA --diagnose      # why won't it authenticate?

Safe to run again at any time — it is idempotent, and re-running it is how you check that a
setup still works.

Creates a working directory, writes `env.sh` into it, checks that the credentials work, and
pulls a first copy of the record. Everything after this is `source <workdir>/env.sh` and one
command.

WHY THIS EXISTS
---------------
Without it, every command in a session has to carry this prefix:

    source ~/.ndex/symposium.env && export SYMPOSIUM_MIRROR=… SYMPOSIUM_LOG=… \\
      SYMPOSIUM_MEMBERS=… && cd …/tools && …

Four things to get right, on every call, and one of them fails SILENTLY: point
`SYMPOSIUM_MIRROR` at the wrong place and validation runs against an empty record, so the
name-collision and address-resolution checks pass without checking anything. `env.sh` sets all
of it once.

THIS SCRIPT NEVER SEES YOUR PASSWORD
------------------------------------
It creates the credentials file with PLACEHOLDERS and tells you which lines to edit. You put
the password in, in your own editor. This script only ever reads the file back to check that
authentication works, and prints the account name it authenticated as — never the value.

**Do not paste your password into a chat with your assistant.** It would be recorded in the
transcript, and possibly in logs, permanently. There is no step here that requires it.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import stat
import subprocess
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
CRED = pathlib.Path.home() / ".ndex" / "symposium.env"
PLACEHOLDER = "REPLACE_ME"
# The community's roster. Every Member here receives READ on each accepted Artifact, so
# it is a property of the community rather than a default anyone can usefully guess.
DEFAULT_MEMBERS = os.environ.get("SYMPOSIUM_MEMBERS", "")
ADMIN = "ndex-admin"


def _entries(text):
    """KEY -> value from a shell env file. Handles `export KEY=value` and quoted values.

    The `export` prefix is not decoration: the credentials file this reads is SOURCED by
    env.sh, and the form Dexter distributes uses `export`. A parser that only understood
    bare KEY=value silently reported a correctly-filled file as still holding placeholders.
    """
    out = {}
    for line in text.splitlines():
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


def ensure_credentials(prefix):
    """-> (ok, message). Creates the file with placeholders; never writes a real secret."""
    user_var, pass_var = f"NDEX_{prefix}_USER", f"NDEX_{prefix}_PASSWORD"
    if not CRED.exists():
        CRED.parent.mkdir(parents=True, exist_ok=True)
        CRED.write_text(f"# Symposium credentials. Readable only by you.\n"
                        f"# Replace {PLACEHOLDER} with the values you were given.\n"
                        f"export {user_var}={PLACEHOLDER}\nexport {pass_var}={PLACEHOLDER}\n")
        CRED.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return False, f"created {CRED} with placeholders"

    CRED.chmod(stat.S_IRUSR | stat.S_IWUSR)          # tighten it whatever it was
    have = _entries(CRED.read_text())
    missing = [v for v in (user_var, pass_var) if v not in have]
    if missing:
        with CRED.open("a") as fh:
            for v in missing:
                fh.write(f"export {v}={PLACEHOLDER}\n")
        return False, f"added {', '.join(missing)} to {CRED} as placeholders"
    if any(have[v] in ("", PLACEHOLDER) for v in (user_var, pass_var)):
        return False, f"{CRED} still contains placeholders"
    return True, f"{CRED} has {user_var} and {pass_var}"


def load_credentials(prefix):
    """Load the credentials file into os.environ, OVERRIDING what is already there.

    Overriding, not setdefault. The whole documented recovery loop is "edit the file and run
    this again" — and a participant does that in the terminal they are already in, which has
    very often already sourced the old file. With setdefault, the stale value in the shell wins,
    the edit appears to do nothing, and the error tells them to check a file that is now
    correct. That is a loop with no exit, hit at the exact moment someone is already unsure
    whether they typed their password right.

    -> a note if the shell disagreed with the file, so the participant knows their CURRENT
    shell is stale even though this run succeeded. Values are never printed.
    """
    if not CRED.exists():
        return None
    stale = []
    for k, v in _entries(CRED.read_text()).items():
        if k in os.environ and os.environ[k] != v:
            stale.append(k)
        os.environ[k] = v
    mine = [k for k in stale if k.startswith(f"NDEX_{prefix}_")]
    if mine:
        return (f"note: {', '.join(mine)} already had a DIFFERENT value in this shell; the "
                f"file wins here, but that shell is stale — open a new terminal, or re-source "
                f"the file, before running anything else")
    return None


def diagnose(prefix):
    """Say why authentication is failing, without printing a secret. -> exit code

    Everything here reports SHAPE, never value: length, whether the characters are ordinary,
    whether something invisible is on the end. Invisible trailing characters are the whole
    reason this exists — a carriage return or a trailing space survives a copy-paste, shows up
    in `env` as nothing at all, and makes a correct-looking password fail.
    """
    import unicodedata
    user_var, pass_var = f"NDEX_{prefix}_USER", f"NDEX_{prefix}_PASSWORD"

    def shape(v):
        if v is None:
            return "absent"
        odd = [f"U+{ord(c):04X}" for c in v if not c.isprintable() or ord(c) > 126]
        bits = [f"{len(v)} chars"]
        if v != v.strip():
            bits.append("!! LEADING/TRAILING WHITESPACE")
        if odd:
            bits.append(f"!! non-printable or non-ASCII: {', '.join(sorted(set(odd))[:4])}")
        if any(unicodedata.category(c) == "Pi" or c in "‘’“”" for c in v):
            bits.append("!! smart quotes")
        return ", ".join(bits)

    def fingerprint(v):
        """Six hex characters derived from a value, for comparing the SAME credential across
        two machines by eye. Compare it yourself; do not send it to anyone. Matching lengths
        prove nothing — two 7-character passwords differing by one transposed key look
        identical in every other line of this report."""
        if not v:
            return "--------"
        import hashlib
        return hashlib.sha256(("symposium-fingerprint:" + v).encode()).hexdigest()[:6]

    tls_ok, tls_msg = check_tls()
    print(f"python       {tls_msg if tls_ok else tls_msg.splitlines()[0]}")
    if not tls_ok:
        print("\n".join(tls_msg.splitlines()[1:]))
    print(f"server       {BASE_URL()}")
    for var in ("SYMPOSIUM_BASE", "NDEX_BASE"):
        if os.environ.get(var):
            print(f"  ! {var} is set to {os.environ[var]!r} — that overrides the default server")
    print(f"file         {CRED}  ({'exists' if CRED.exists() else 'MISSING'})")
    f = _entries(CRED.read_text()) if CRED.exists() else {}
    for var in (user_var, pass_var):
        fv, ev = f.get(var), os.environ.get(var)
        print(f"\n  {var}")
        print(f"    in file   {shape(fv)}   fingerprint {fingerprint(fv)}")
        print(f"    in shell  {shape(ev)}   fingerprint {fingerprint(ev)}")
        if fv is not None and ev is not None and fv != ev:
            print(f"    !! THEY DIFFER — the shell is stale; open a new terminal")
    if f.get(user_var) and not f[user_var].startswith("agent_"):
        print(f"\n  !! {user_var} is {f[user_var]!r}, which does not look like an account name.\n"
              f"     It should be the account (e.g. agent_lyra), not the prefix ({prefix}).")

    print("\n  Compare the fingerprints with the SAME command on a machine where this account\n"
          "  works. Same value -> same six characters. Matching LENGTHS prove nothing: two\n"
          "  7-character passwords differing by one transposed key look identical everywhere\n"
          "  else in this report. Compare them yourself — do not send them to anyone.")
    print("\nauthentication")
    for label, vals in (("file", f), ("shell", os.environ)):
        u, p = vals.get(user_var), vals.get(pass_var)
        if not u or not p:
            print(f"  {label:6s} incomplete")
            continue
        acct, status, detail = authenticate(prefix, u, p)
        if status == 200 and acct:
            print(f"  {label:6s} OK — {acct}")
        elif status == 0:
            print(f"  {label:6s} SERVER UNREACHABLE (no HTTP response at all)")
            print(f"         {detail}")
            print(f"         The credentials were never sent. This is a NETWORK problem — "
                  f"nothing here\n         is wrong with your password.")
        else:
            print(f"  {label:6s} HTTP {status}" + (" — credentials rejected" if status == 401 else ""))
            if detail:
                print(f"         {detail[:160]}")
    return 0


def BASE_URL():
    sys.path.insert(0, str(TOOLS))
    import ndex_io
    return ndex_io.BASE


def check_tls():
    """-> (ok, message). Is THIS interpreter able to speak TLS to a modern server?

    macOS ships /usr/bin/python3 linked against LibreSSL 2.8.3, which cannot complete a
    handshake with an HTTPS server: it answers `sslv3 alert handshake failure`
    and the request dies before any credential is sent. On a Mac where nothing else is
    installed, `python3` IS that interpreter, so the toolchain fails on the very first command
    for a reason that has nothing to do with the toolchain.

    Checked before authenticating, because the failure otherwise surfaces as an
    authentication problem and sends people to re-check a correct password.
    """
    import ssl
    lib = ssl.OPENSSL_VERSION
    if not lib.startswith("LibreSSL"):
        return True, f"python {sys.version.split()[0]}, {lib}"

    # Reuse preflight's discovery rather than a second hardcoded list — the first participant
    # to try this installs with Anaconda, which none of the Homebrew paths would have found.
    try:
        sys.path.insert(0, str(TOOLS))
        from preflight import candidates
        cands = candidates()
    except Exception:                                          # noqa: BLE001
        cands = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
    alts = []
    for cand in cands[:8]:
        if not pathlib.Path(cand).exists() or pathlib.Path(cand).resolve() == pathlib.Path(sys.executable).resolve():
            continue
        try:
            out = subprocess.run([cand, "-c", "import ssl,sys;"
                                  "print(sys.version.split()[0], ssl.OPENSSL_VERSION)"],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:                                      # noqa: BLE001
            continue
        if out and "LibreSSL" not in out:
            alts.append((cand, out))
        if len(alts) >= 3:
            break

    msg = [f"python {sys.version.split()[0]} is linked against {lib}.",
           "",
           "  That TLS stack cannot complete a handshake with this server. The request fails",
           "  with `sslv3 alert handshake failure` BEFORE your username or password is sent,",
           "  so this is not a credential problem and re-typing your password will not help.",
           "",
           "  This is macOS's built-in python3. You need a different one."]
    if alts:
        msg += ["", "  Working interpreters already on this machine — use one of these:"]
        for path, ver in alts:
            msg.append(f"      {path}     ({ver})")
        msg += ["", f"  For example:", f"      {alts[0][0]} tools/setup.py --as <PREFIX>"]
    else:
        msg += ["", "  None found on this machine. Install one:",
                "      brew install python@3.12                  # Homebrew",
                "      conda create -n symposium python=3.12     # Anaconda",
                "  or download from python.org and run its Install Certificates.command.",
                "",
                "  Or just run:  python3 tools/preflight.py  — it searches harder."]
    return False, "\n".join(msg)


def authenticate(prefix, user=None, password=None):
    """-> (account, status, detail). Prints nothing.

    `status` distinguishes the three outcomes that were previously one message:
      200  authenticated
      401  the server was reached and REJECTED the credentials
      0    the server was never reached at all — DNS, TLS, proxy, no network

    That last case is the one that mattered. `ndex_io.api` returns status 0 on any transport
    exception, and reporting it as "the server did not accept those credentials" sends someone
    to re-check a password that is perfectly correct. It is also exactly what a second machine
    on a different network produces.
    """
    sys.path.insert(0, str(TOOLS))
    try:
        import ndex_io
    except Exception as e:                                     # noqa: BLE001
        return None, None, f"cannot import the toolchain from {TOOLS}: {e}"
    if user and password:
        import base64
        tok = base64.b64encode(f"{user}:{password}".encode()).decode()
    else:
        try:
            _, tok = ndex_io.auth(prefix)
        except SystemExit as e:
            return None, None, str(e)
    st, body = ndex_io.api("GET", "/v2/user?valid=true", tok, raw=True)
    if st == 200:
        try:
            return json.loads(body).get("userName"), 200, ""
        except Exception:                                      # noqa: BLE001
            return None, 200, "the server returned something that is not JSON"
    return None, st, str(body)[:200]


def auth_message(status, detail, prefix):
    """The human explanation for a non-200. Kept apart so --diagnose and setup agree."""
    if status == 0:
        return (f"CANNOT REACH THE SERVER — this is a network problem, not a credential "
                f"problem.\n"
                f"               Your username and password were never sent anywhere. Check "
                f"that this\n"
                f"               machine can reach {BASE_URL()} at all — a VPN, a proxy, a "
                f"firewall or\n"
                f"               simply being offline all produce this. Try:\n"
                f"                   curl -sS -o /dev/null -w '%{{http_code}}\\n' "
                f"{BASE_URL()}/v2/user\n"
                f"               Underlying error: {detail}")
    if status == 401:
        return (f"the server was reached and REJECTED these credentials (HTTP 401).\n"
                f"               The password is wrong, or the username is not the account "
                f"name.\n"
                f"               Run: python3 setup.py --as {prefix} --diagnose")
    return (f"the server answered HTTP {status}, which is neither success nor a rejection.\n"
            f"               {detail}")


def write_env(workdir, prefix, account, members):
    env = workdir / "env.sh"
    env.write_text(f"""# Symposium session environment for {account}. Written by setup.py.
# Use it at the start of every shell command:
#
#     source {env}
#     "$SYMPOSIUM_PY" "$SYMPOSIUM_TOOLS/publish.py" --as {prefix} --role importer --check art.json
#
# SYMPOSIUM_PY is the interpreter that was verified to reach the server when this file was
# written. Use it rather than `python3`: on a Mac `python3` is often the built-in one, which
# cannot complete the TLS handshake — and the failure looks like a rejected password.
#
# Do not edit SYMPOSIUM_MIRROR to point somewhere else. Validation is only as good as the
# record it can see: aimed at an empty directory it approves duplicate names and unresolvable
# addresses without complaint.

set -a
. "{CRED}"
set +a

export SYMPOSIUM_PY="{sys.executable}"
export SYMPOSIUM_TOOLS="{TOOLS}"
export SYMPOSIUM_MIRROR="{workdir / 'record'}"
export SYMPOSIUM_LOG="{workdir / 'events.jsonl'}"
export SYMPOSIUM_MEMBERS="{members}"
export SYMPOSIUM_ADMIN="{ADMIN}"
export SYMPOSIUM_PREFIX="{prefix}"
export SYMPOSIUM_ACCOUNT="{account}"
""")
    env.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return env


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--as", dest="prefix", required=True,
                    help="your credential prefix, e.g. VEGA (not your account name)")
    ap.add_argument("--workdir", default="~/symposium-work",
                    help="where your artifacts, mirror and log live (default: ~/symposium-work)")
    ap.add_argument("--members", default=DEFAULT_MEMBERS)
    ap.add_argument("--diagnose", action="store_true",
                    help="explain why authentication is failing; prints no secrets")
    args = ap.parse_args(argv)
    prefix = args.prefix.upper()

    print(f"Symposium setup — credential prefix {prefix}\n")

    tls_ok, tls_msg = check_tls()
    print(f"  python       {tls_msg if tls_ok else tls_msg.splitlines()[0]}")
    if not tls_ok:
        print("\n".join(tls_msg.splitlines()[1:]))
        return 1
    if args.diagnose:
        return diagnose(prefix)

    # 1. credentials --------------------------------------------------------------------
    ok, msg = ensure_credentials(prefix)
    print(f"  credentials  {msg}")
    if not ok:
        print(f"""
  ---------------------------------------------------------------------------
  STOP HERE. This is the one step that is yours, not your assistant's.

  Open this file in an editor:

      {CRED}

  Replace {PLACEHOLDER} on these two lines with the values you were given:

      export NDEX_{prefix}_USER={PLACEHOLDER}
      export NDEX_{prefix}_PASSWORD={PLACEHOLDER}

  Save it, then run this command again.

  Do NOT paste your password into the chat. Nothing here needs it, and a chat
  transcript keeps it.
  ---------------------------------------------------------------------------""")
        return 2

    # 2. authenticate -------------------------------------------------------------------
    note = load_credentials(prefix)
    if note:
        print(f"  environment  {note}")
    account, status, detail = authenticate(prefix)
    if status != 200 or not account:
        print(f"  account      ! {auth_message(status, detail, prefix) if status is not None else detail}")
        return 1
    print(f"  account      authenticated as {account}")

    # 3. working directory --------------------------------------------------------------
    workdir = pathlib.Path(args.workdir).expanduser().resolve()
    (workdir / "record").mkdir(parents=True, exist_ok=True)
    print(f"  workdir      {workdir}")

    env = write_env(workdir, prefix, account, args.members)
    print(f"  env.sh       {env}")

    # 4. first sync ---------------------------------------------------------------------
    r = subprocess.run([sys.executable, str(TOOLS / "sync.py"), "--as", prefix],
                       env={**os.environ,
                            "SYMPOSIUM_MIRROR": str(workdir / "record"),
                            "SYMPOSIUM_ADMIN": ADMIN},
                       capture_output=True, text=True)
    # Structural count, not a glob: the mirror also holds manifest.json and .sync_state.json,
    # and reporting "48 artifacts" for a 46-artifact record is a number someone will later try
    # to reconcile.
    import ndex_io
    held = len(ndex_io.load_canonical_dir(workdir / "record"))
    if r.returncode != 0:
        print(f"  record       ! sync failed:\n{(r.stdout + r.stderr).strip()[:400]}")
        return 1
    print(f"  record       {held} artifact(s) in {workdir / 'record'}")

    print(f"""
Done. From now on, every command starts the same way:

    source {env}

Then, from {workdir} — note "$SYMPOSIUM_PY", not python3:

    "$SYMPOSIUM_PY" "$SYMPOSIUM_TOOLS/sync.py"    --as {prefix}
    "$SYMPOSIUM_PY" "$SYMPOSIUM_TOOLS/publish.py" --as {prefix} --roles

To see the record in a browser:

    "$SYMPOSIUM_PY" "$SYMPOSIUM_TOOLS/serve.py" "$SYMPOSIUM_MIRROR" --port 8760

env.sh records the interpreter this setup verified ({sys.executable}).
Typing `python3` instead may pick a different one that cannot reach the server.

Next: read QUICKSTART.md, part 2.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
