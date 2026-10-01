"""data-admin: host-operator commands, reachable only through docker exec or kubectl exec.

data-admin init --admin <handle> --pubkey -     (the admin's public JWK on stdin)
data-admin status
"""

from __future__ import annotations

import argparse
import json
import sys

from . import version
from .auth import PublicKeys
from .records import AlreadyInitialized, Records
from .runtime import Database, Settings


class Admin:
    def __init__(self):
        self.settings = Settings()
        self.db = Database(self.settings)
        self.db.migrate()
        self.db.open()
        self.records = Records()
        self.keys = PublicKeys()

    def emit(self, payload: dict):
        print(json.dumps(payload))

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
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    admin = Admin()
    return {"init": admin.init, "status": admin.status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
