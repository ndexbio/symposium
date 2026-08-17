#!/usr/bin/env python3
"""Serve the record browser and rebuild it as the record grows.

    python serve.py ../examples/record               # http://localhost:8760
    SYMPOSIUM_MIRROR=./record python serve.py    # against a live mirror

Deliberately a full recompile on every change, with no incremental patching. A
twenty-artifact record compiles in about 70 ms and the whole thing is linear, so at any
size this event will reach, rebuilding everything is faster than deciding what not to
rebuild — and it cannot drift from the record the way a partial update can. `sync.py`
writes a build counter and a dirty set into `manifest.json`; those are useful as a
signal that something changed, and are not used to decide what to recompile.

Pages poll `/__build` and reload themselves when the number moves, so a browser left
open on the overview keeps up with the day without anyone touching it.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import socketserver
import sys
import threading
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import browse                                                      # noqa: E402

STATE = {"build": 0, "error": None, "artifacts": 0, "at": ""}
_LOCK = threading.Lock()


def record_signature(record_dir):
    """Cheap fingerprint of the record: which files exist and when they changed."""
    sig = []
    try:
        for p in sorted(pathlib.Path(record_dir).glob("*.json")):
            st = p.stat()
            sig.append((p.name, st.st_mtime_ns, st.st_size))
    except FileNotFoundError:
        pass
    return tuple(sig)


def rebuild(record_dir, out_dir, title):
    """Compile, and never let a bad record take the server down — during an event the
    browser is how people find out something is wrong, so it has to survive it."""
    try:
        manifest = browse.compile_record(record_dir, out_dir, title=title, quiet=True)
        with _LOCK:
            STATE["build"] += 1
            STATE["error"] = None
            STATE["artifacts"] = manifest["artifacts"]
            STATE["at"] = time.strftime("%H:%M:%S")
        print(f"[{STATE['at']}] build {STATE['build']}: {manifest['artifacts']} artifacts, "
              f"{manifest['arguments']} argument(s), {manifest['findings']} finding(s)")
    except Exception:
        with _LOCK:
            STATE["build"] += 1
            STATE["error"] = traceback.format_exc(limit=3)
        print(f"[{time.strftime('%H:%M:%S')}] BUILD FAILED — serving the previous build",
              file=sys.stderr)
        traceback.print_exc(limit=3)


def watch(record_dir, out_dir, title, interval):
    last = None
    while True:
        sig = record_signature(record_dir)
        if sig != last:
            last = sig
            rebuild(record_dir, out_dir, title)
        time.sleep(interval)


def make_handler(out_dir):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(out_dir), **kw)

        def do_GET(self):
            if self.path.split("?")[0].endswith("__build"):
                with _LOCK:
                    body = json.dumps(dict(STATE)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def end_headers(self):
            # A record that is being appended to all day must never be read from cache.
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, fmt, *args):
            pass                                    # the build log is the useful one

    return Handler


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("record_dir", nargs="?",
                    default=os.environ.get("SYMPOSIUM_MIRROR", "../examples/record"),
                    help="directory of canonical JSON (default: $SYMPOSIUM_MIRROR)")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--port", type=int, default=8760)
    ap.add_argument("--title", default=None)
    ap.add_argument("--interval", type=float, default=2.0,
                    help="seconds between checks of the record directory")
    args = ap.parse_args(argv)

    record = pathlib.Path(args.record_dir).resolve()
    out = pathlib.Path(args.out).resolve()
    if not record.is_dir():
        raise SystemExit(f"ERROR: no such record directory: {record}")

    rebuild(str(record), str(out), args.title)
    threading.Thread(target=watch, args=(str(record), str(out), args.title, args.interval),
                     daemon=True).start()

    with Server(("", args.port), make_handler(out)) as httpd:
        print(f"watching {record}")
        print(f"serving  http://localhost:{args.port}/   (ctrl-c to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
