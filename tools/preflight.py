#!/usr/bin/env python3
"""Check that THIS machine can talk to the Symposium server. No account needed.

    python3 tools/preflight.py

Run this before anything else, and before you have credentials. It needs no password and
sends none. It answers one question: can the Python you just typed reach the server?

WHY IT EXISTS
-------------
macOS ships a `python3` linked against LibreSSL 2.8.3. It cannot complete a TLS handshake with
an HTTPS server — it replies `sslv3 alert handshake failure` and the connection
dies before anything is sent. On a Mac with nothing else installed, that interpreter IS
`python3`, so the very first command fails for a reason unrelated to the toolchain, and every
downstream error message blames your password instead.

Nothing else in the toolchain needs the network until you publish, so without this check the
problem surfaces an hour later, in the middle of real work.

This script is deliberately dependency-free and syntax-conservative so that it runs on the
BROKEN interpreter and can tell you it is broken.
"""
import json
import os
import subprocess
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SYMPOSIUM_BASE", "http://localhost:8080")
PROBE_PATH = "/v2/user"          # answers 401 unauthenticated: proof of reach without a login

def candidates():
    """Every Python interpreter this machine plausibly has, most likely to work first.

    A hardcoded list of Homebrew paths was wrong for the first participant who tried it: they
    install with Anaconda, which lives somewhere else entirely. So look in four ways —
    everything on PATH, the active conda environment, the usual install roots for Homebrew /
    python.org / Anaconda / Miniconda / MacPorts, and pyenv's versions — and de-duplicate by
    the path each one really resolves to.
    """
    import glob
    found = []

    def add(p):
        if p and os.path.exists(p) and os.access(p, os.X_OK) and not os.path.isdir(p):
            found.append(p)

    # 1. anything named pythonN on PATH
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        for name in ("python3", "python3.13", "python3.12", "python3.11", "python3.10",
                     "python3.9", "python"):
            add(os.path.join(d, name))

    # 2. the conda environment that is active right now, if any
    if os.environ.get("CONDA_PREFIX"):
        add(os.path.join(os.environ["CONDA_PREFIX"], "bin", "python3"))

    # 3. the usual roots, including the ones Anaconda uses
    home = os.path.expanduser("~")
    roots = ["/opt/homebrew", "/usr/local", "/opt/local",
             "/opt/anaconda3", "/opt/miniconda3", "/opt/miniforge3",
             home + "/anaconda3", home + "/miniconda3", home + "/miniforge3",
             home + "/opt/anaconda3", home + "/opt/miniconda3",
             "/Library/Frameworks/Python.framework/Versions/Current"]
    for r in roots:
        for name in ("python3", "python3.13", "python3.12", "python3.11"):
            add(os.path.join(r, "bin", name))
    for pat in ("/Library/Frameworks/Python.framework/Versions/3.*/bin/python3",
                home + "/.pyenv/versions/*/bin/python3",
                home + "/.conda/envs/*/bin/python3",
                "/opt/anaconda3/envs/*/bin/python3",
                home + "/anaconda3/envs/*/bin/python3"):
        for p in sorted(glob.glob(pat), reverse=True):
            add(p)

    # de-duplicate by what each path actually resolves to, keeping the friendliest name
    seen, out = set(), []
    for p in found:
        try:
            real = os.path.realpath(p)
        except Exception:                                      # noqa: BLE001
            continue
        if real in seen:
            continue
        seen.add(real)
        out.append(p)
    return out


def reach():
    """-> (ok, kind, detail). Unauthenticated. Sends no credentials."""
    req = urllib.request.Request(BASE + PROBE_PATH, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, "http", "HTTP %d" % r.status
    except urllib.error.HTTPError as e:
        # 401 is SUCCESS here: we reached the server and it asked who we are.
        return True, "http", "HTTP %d" % e.code
    except urllib.error.URLError as e:
        text = str(e.reason)
        if "HANDSHAKE" in text.upper() or "SSL" in text.upper():
            return False, "tls", text
        if "not known" in text or "nodename" in text or "Name or service" in text:
            return False, "dns", text
        return False, "net", text
    except Exception as e:                                     # noqa: BLE001
        return False, "net", str(e)


def line():
    return "%s | %s" % (sys.version.split()[0], ssl.OPENSSL_VERSION)


def probe_others():
    """Test every other interpreter we can find, by running this script's --probe in it."""
    here = os.path.realpath(sys.executable)
    out = []
    for cand in candidates():
        if os.path.realpath(cand) == here:
            continue
        if len(out) >= 8:            # enough to answer the question; each costs a request
            break
        try:
            r = subprocess.run([cand, os.path.abspath(__file__), "--probe"],
                               capture_output=True, text=True, timeout=45)
            d = json.loads(r.stdout.strip().splitlines()[-1])
            out.append((cand, d))
        except Exception:                                      # noqa: BLE001
            continue
    return out


def main():
    if "--probe" in sys.argv:                    # machine-readable, used by probe_others()
        ok, kind, detail = reach()
        print(json.dumps({"python": line(), "ok": ok, "kind": kind, "detail": detail[:120]}))
        return 0

    print("Symposium preflight — no account needed, no password sent\n")
    print("  interpreter  %s" % sys.executable)
    print("  version      %s" % line())
    print("  server       %s" % BASE)

    ok, kind, detail = reach()
    if ok:
        print("  connection   OK — server answered %s\n" % detail)
        if "401" in detail:
            print("A 401 HERE IS THE RESULT WE WANT, and it is not an error.")
            print("This check deliberately sends NO credentials — it asks an authenticated")
            print("endpoint who it is without logging in, so the server replies 'unauthorized'.")
            print("That reply is the proof: the request crossed the network, completed the TLS")
            print("handshake, reached NDEx, and got an answer from it. A broken setup never gets")
            print("far enough to be refused. You will authenticate for real in setup.py.\n")
        print("This Python can reach the server. Use THIS interpreter for everything:")
        print("    %s tools/setup.py --as <YOUR_PREFIX>" % sys.executable)
        return 0

    print("  connection   FAILED (%s)" % kind)
    print("               %s\n" % detail)

    if kind == "tls":
        print("This is the known macOS problem, and it is not your network or your password.")
        print("%s cannot negotiate TLS with this server." % ssl.OPENSSL_VERSION)
        print("No credential was sent — the connection failed before that point.\n")
    elif kind == "dns":
        print("The server name did not resolve. Check the spelling and that you are online.\n")
    else:
        print("The server could not be reached. A VPN, proxy or firewall will do this.\n")

    others = probe_others()
    working = [(c, d) for c, d in others if d.get("ok")]
    if working:
        # Three, not all of them. A machine with Anaconda has a working interpreter in every
        # environment, and a list of nine is a wall of text for someone who only needs one.
        print("Another Python on this machine WORKS. Use it for every command:\n")
        for c, d in working[:3]:
            print("    %s\n        (%s)" % (c, d["python"]))
        if len(working) > 3:
            print("\n    (%d more also work; any one of them is fine)" % (len(working) - 3))
        print("\nCopy this, replacing the prefix with yours:\n")
        print("    %s tools/setup.py --as <YOUR_PREFIX>\n" % working[0][0])
        print("Use that same full path everywhere the instructions say `python3`.")
    elif others:
        print("Other interpreters found, none of which could connect either:")
        for c, d in others:
            print("    %s  (%s) — %s" % (c, d["python"], d["kind"]))
        print("\nThat points at the network rather than at Python: a VPN, proxy or firewall.")
    else:
        print("No other working Python found on this machine. Install one:")
        print("    brew install python@3.12          # Homebrew")
        print("    conda create -n symposium python=3.12   # if you use Anaconda")
        print("then re-run this preflight with that interpreter's full path.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
