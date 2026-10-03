"""data-admin: host-operator commands, reachable only through docker exec or kubectl exec.

    data-admin init --admin <handle> --pubkey -     (the admin's public JWK on stdin)
    data-admin status
    data-admin invite --community <c> --handle <h> [--hours N]
    data-admin rebind-key --community <c> --handle <h>
    data-admin suspect-after --community <c> --handle <h> --at <ISO-8601 instant>
    data-admin purge --cite symposium-data:<file-id>@v<n>
    data-admin export --community <c> > <c>.tar
    data-admin import < <c>.tar
    data-admin port-ndex      (one-time bootstrap; configured by PORT_* environment, see PORT_NDEX.md)

Invites are printed alone on stdout, for the operator to redirect into a file and hand over
out of band. They are single-use and stored only as hashes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from . import version
from .archive import Archive, Malformed, Refused
from .auth import PublicKeys, Secrets
from .cleanup import Cleanup
from .records import AlreadyInitialized, NotFound, Records
from .runtime import Database, PayloadStore, Settings
from .wire import parse_citation


class Admin:
    def __init__(self):
        self.settings = Settings()
        self.db = Database(self.settings)
        self.db.migrate()
        self.db.open()
        self.records = Records()
        self.keys = PublicKeys()
        self.secrets = Secrets()
        self.store = PayloadStore(self.settings)
        self.cleanup = Cleanup(self.db, self.store, self.records)
        self.archive = Archive(self.db, self.store, self.records, self.cleanup)

    def emit(self, payload: dict, stream=None):
        print(json.dumps(payload), file=stream or sys.stdout)

    def mint_invite(self, conn, community: str, handle: str, hours: int | None) -> str:
        invite = self.secrets.new("sdi_")
        hours = self.settings.invite_hours if hours is None else hours
        self.records.add_invite(
            conn, self.secrets.digest(invite), community, handle, hours
        )
        return invite

    def invite(self, args) -> int:
        with self.db.connection() as conn:
            if self.records.config(conn, "admin") is None:
                self.emit({"error": "the server is not initialized"})
                return 2
            if not self.records.on_roster(conn, args.community, args.handle):
                self.emit(
                    {"error": f"'{args.handle}' is not on the {args.community} roster"}
                )
                return 2
            invite = self.mint_invite(conn, args.community, args.handle, args.hours)
        print(invite)
        return 0

    def rebind_key(self, args) -> int:
        """Lost or compromised key: retire the handle's keys and print a fresh invite, so the
        member registers a new key under the same handle. Attribution is untouched."""
        with self.db.connection() as conn:
            if not self.records.on_roster(conn, args.community, args.handle):
                self.emit(
                    {"error": f"'{args.handle}' is not on the {args.community} roster"}
                )
                return 2
            retired = self.records.retire_keys(conn, args.community, args.handle)
            invite = self.mint_invite(conn, args.community, args.handle, args.hours)
        self.emit({"handle": args.handle, "retired_keys": retired}, stream=sys.stderr)
        print(invite)
        return 0

    def purge(self, args) -> int:
        """Free a version's content (R-B3). The version stays addressable and answers 410 with
        its metadata; the bytes go only when no other live version shares them."""
        cited = parse_citation(args.cite)
        if cited is None:
            self.emit({"error": "expected symposium-data:<file-id>@v<n>"})
            return 1
        try:
            with self.db.connection() as conn:
                pid = self.records.purge(conn, *cited)
        except NotFound:
            self.emit({"error": f"no version {args.cite}"})
            return 2
        freed = pid is not None and self.cleanup.finish_purge(pid)
        result = {"purged": args.cite, "bytes_freed": freed}
        if pid is not None and not freed:
            result["note"] = (
                "the bytes could not be removed yet; the janitor will retry"
            )
        self.emit(result)
        return 0

    def export(self, args) -> int:
        """Write one community to stdout as a tar stream (R-J6); the summary goes to stderr."""
        try:
            manifest = self.archive.export(args.community, sys.stdout.buffer)
        except Refused as e:
            self.emit({"error": str(e)}, stream=sys.stderr)
            return 2
        sys.stdout.buffer.flush()
        self.emit({"exported": args.community, **manifest["counts"]}, stream=sys.stderr)
        return 0

    def import_(self, _args) -> int:
        """Read an export from stdin and write it in one transaction (R-J6). Prints one line
        per handle (created, unchanged, keys merged), then the summary."""
        try:
            report = self.archive.import_(sys.stdin.buffer)
        except Refused as e:
            self.emit({"error": str(e)})
            return 2
        except Malformed as e:
            self.emit({"error": str(e)})
            return 1
        for handle in report.pop("handles"):
            self.emit(handle)
        self.emit(report)
        return 0

    def port(self, _args) -> int:
        from . import port_ndex  # the port feature, isolated: port_ndex only here

        return port_ndex.Port(
            self.db, self.store, self.records, self.cleanup, dict(os.environ)
        ).run()

    def suspect_after(self, args) -> int:
        """Flag everything the handle writes after an instant; nothing is deleted."""
        try:
            instant = datetime.fromisoformat(args.at)
        except ValueError:
            self.emit({"error": f"not an ISO-8601 instant: {args.at}"})
            return 1
        if instant.tzinfo is None:
            self.emit(
                {
                    "error": "the instant needs a timezone, e.g. 2026-10-01T12:00:00+00:00"
                }
            )
            return 1
        with self.db.connection() as conn:
            if not self.records.set_suspect_after(
                conn, args.community, args.handle, instant
            ):
                self.emit({"error": f"no owner '{args.handle}' in {args.community}"})
                return 2
        self.emit(
            {
                "community": args.community,
                "handle": args.handle,
                "suspect_after": instant.isoformat(),
            }
        )
        return 0

    def init(self, args) -> int:
        source = sys.stdin if args.pubkey == "-" else open(args.pubkey)
        with source:
            jwk = json.loads(source.read())
        try:
            self.keys.validate(jwk)
        except ValueError as e:
            self.emit({"error": str(e)})
            return 1
        kid = self.keys.thumbprint(jwk)
        try:
            with self.db.connection() as conn:
                ported = self.records.config(conn, "port_admin")
                if ported is not None and ported != args.admin:
                    self.emit(
                        {
                            "error": f"this server was ported for admin '{ported}'; "
                            "initialize with that handle"
                        }
                    )
                    return 2
                self.records.bind_admin(conn, args.admin, kid, jwk)
        except AlreadyInitialized as e:
            self.emit({"error": f"already initialized with admin '{e}'"})
            return 2
        self.emit(
            {
                "initialized": True,
                "admin": args.admin,
                "fingerprint": kid,
                "server_id": self.settings.server_id,
            }
        )
        return 0

    def status(self, _args) -> int:
        with self.db.connection() as conn:
            admin = self.records.config(conn, "admin")
        self.emit(
            {
                "version": version(),
                "server_id": self.settings.server_id,
                "initialized": admin is not None,
                "admin": admin,
                "registration": self.settings.registration,
            }
        )
        return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="data-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="bind the admin handle to its public key (once)")
    init.add_argument("--admin", required=True, metavar="HANDLE")
    init.add_argument(
        "--pubkey", required=True, help="path to the public JWK, or - for stdin"
    )
    sub.add_parser("status", help="show initialization state")
    for name, text in (
        ("invite", "print a single-use invite for a roster member"),
        ("rebind-key", "retire a member's keys and print a fresh invite"),
    ):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--community", required=True)
        cmd.add_argument("--handle", required=True)
        cmd.add_argument(
            "--hours",
            type=int,
            help="validity (default 72, or SYMPOSIUM_DATA_INVITE_HOURS)",
        )
    purge = sub.add_parser(
        "purge", help="free one version's content; it then answers 410"
    )
    purge.add_argument("--cite", required=True, metavar="symposium-data:<id>@v<n>")
    export = sub.add_parser(
        "export", help="write one community to stdout as a tar stream"
    )
    export.add_argument("--community", required=True)
    sub.add_parser("import", help="read an export from stdin into this server")
    sub.add_parser(
        "port-ndex", help="one-time bootstrap of a fresh server (PORT_* env)"
    )
    flag = sub.add_parser(
        "suspect-after", help="flag a handle's writes after an instant"
    )
    flag.add_argument("--community", required=True)
    flag.add_argument("--handle", required=True)
    flag.add_argument("--at", required=True, metavar="ISO-8601")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    admin = Admin()
    return {
        "init": admin.init,
        "status": admin.status,
        "invite": admin.invite,
        "rebind-key": admin.rebind_key,
        "suspect-after": admin.suspect_after,
        "purge": admin.purge,
        "export": admin.export,
        "import": admin.import_,
        "port-ndex": admin.port,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
