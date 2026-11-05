#!/usr/bin/env python3
"""Serve the record browser and rebuild it as the record grows.

    python serve.py                  # ./record, this session's copy: http://localhost:8760
    python serve.py <record dir>

Run it as `/symposium serve`. The record defaults to `./record`, the copy beside the session's
context that sync (and the gate, on the admin's machine) keeps; it stops with an error when
that is missing. The pages are titled with that session's community, unless `--title` says
otherwise.

It runs until stopped, with no time limit of its own: run it in the background. ctrl-c,
SIGTERM or (Windows) CTRL_BREAK stops it within a second, with exit code 0. A restart on the same port
takes over from a `serve` still running there for this session, which it stops.

Deliberately a full recompile on every change, with no incremental patching. Rebuilding
everything cannot drift from the record the way a partial update can. Each build line says
how long it took. A twenty-artifact record once compiled in about 70 ms; c037_2's 74
artifacts take 3 to 5 s (2026-11-02, Apple M3, by machine load), nearly all of it in the
overview's crossing-minimising layout (`browse._layout_overview`), whose score is quadratic
in edges and is recomputed for every swap it tries. `sync.py` writes a build counter and a dirty set
into `manifest.json`; those are useful as a signal that something changed, and are not used
to decide what to recompile.

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
import browse  # noqa: E402
from data_io import stop_on_signals, take_over  # noqa: E402

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
        started = time.perf_counter()
        manifest = browse.compile_record(record_dir, out_dir, title=title, quiet=True)
        took = time.perf_counter() - started
        with _LOCK:
            STATE["build"] += 1
            STATE["error"] = None
            STATE["artifacts"] = manifest["artifacts"]
            STATE["at"] = time.strftime("%H:%M:%S")
        print(f"[{STATE['at']}] build {STATE['build']}: {manifest['artifacts']} artifacts, "
              f"{manifest['arguments']} argument(s), {manifest['findings']} finding(s), "
              f"in {took:.2f}s")
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
    # on macOS and Linux a restarted serve rebinds its port at once, past TIME_WAIT; on Windows
    # SO_REUSEADDR would let two processes bind one port, and take_over has ended the old one
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("record_dir", nargs="?", default="record",
                    help="directory of canonical JSON (default: ./record)")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--port", type=int, default=8760,
                    help="the port to serve on; 0 takes any free one, and says which")
    ap.add_argument("--title", default=None,
                    help="the pages' title (default: the community of the session whose "
                         "record copy this is)")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="seconds between checks of the record directory")
    args = ap.parse_args(argv)

    record = pathlib.Path(args.record_dir).resolve()
    out = pathlib.Path(args.out).resolve()
    if not record.is_dir():
        raise SystemExit(f"ERROR: no record copy at {record}: run `/symposium sync` here first\n"
                         f"  (on the admin's machine, `/symposium gate` writes the gate's copy)")
    # a session's copy is titled with its community, so two communities open side by side
    # can be told apart; any other record directory keeps the generic title
    args.title = args.title or browse.community_name(record)

    stop_on_signals()
    if args.port == 0:
        # a port of its own, bound first: no other serve can hold it, so none is taken over
        httpd = Server(("", 0), make_handler(out))
        port = httpd.server_address[1]
        lock = take_over(f"serve-{port}")  # noqa: F841 — held for as long as this serve runs
    else:
        # a serve still on this port is ended first, so the port is free to bind
        port = args.port
        lock = take_over(f"serve-{port}")  # noqa: F841 — held for as long as this serve runs
        httpd = Server(("", port), make_handler(out))
    try:
        rebuild(str(record), str(out), args.title)
        threading.Thread(target=watch, args=(str(record), str(out), args.title,
                                             args.interval), daemon=True).start()
        with httpd:
            print(f"watching {record}", flush=True)
            print(f"serving  http://localhost:{port}/   (ctrl-c to stop)", flush=True)
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
