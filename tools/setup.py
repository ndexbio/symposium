#!/usr/bin/env python3
"""Join a Symposium community, or the server's administration, with an invite file:
`/symposium setup --invite-file <file>`.

    python3 setup.py --invite-file lyra.invite

The invite file comes out of band from whoever invited you. It names your handle, your
community (none, for a server-level user) and the data server's URL; the access roles you join
with are stored on the server with the invite. Setup:
  1. sets this directory's context from the invite file (`symposium-data context set`);
  2. makes your key on this machine and joins with the invite (`symposium-data owner
     register`): the server creates your user with the invite's roles. Your private key never
     leaves this machine, and the invite works once;
  3. reads your access back (`symposium-data access`), so the session knows what it may do;
  4. for a community: syncs. `./record`, beside the context, becomes your copy of the
     community's record. The Messages already in it addressed to you are in
     `messages_for_you`, one line each, as `sync` lists them. Access that reads only some
     collections (`community-observer` on named ones) works without a copy: `record` is
     null, and `record_access` says so.

It is idempotent: run again with the same invite, it reports that you are already registered
with this machine's key and changes nothing.

Everything goes through the `symposium-data` CLI; this script never contacts the data
server itself. It prints one JSON object.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_io import DataError, SymposiumData, rbac  # noqa: E402
from sync import Sync, message_line  # noqa: E402

RECORD = "record"


class Setup:
    def __init__(self, data: SymposiumData):
        self.data = data

    def run(self, invite_file: str) -> dict:
        context = self.data.run("context", "set", "--invite-file", invite_file)["context"]
        registered = self.data.run("owner", "register")
        access = self.data.run("access")
        out = {
            "community": context["community"],
            "handle": context["handle"],
            "data-server-url": context["data-server-url"],
            "registered": registered["registered"],
            "fingerprint": registered["fingerprint"],
            "roles": access["roles"],
        }
        if context["community"] is None:
            return out  # a server-level user: its communities have sessions of their own
        held = rbac.UserContext.from_view(access["context"])
        if not held.allowsRequest(rbac.READ, context["community"],
                                  rbac.CollectionRef(RECORD)):
            return {**out, "record": None,
                    "record_access": "your access reads named collections only, so this "
                                     "session works without a copy of the record"}
        sync = Sync(self.data, quiet=True, lists_messages=True)
        synced = sync.once()
        if synced is None:
            raise DataError({"error": "registered, but the record could not be synced: run "
                             "`/symposium sync` once the server answers"})
        return {
            **out,
            "record": {"artifacts": synced["artifacts"], "replies": synced["replies"]},
            "messages_for_you": [message_line(m) for m in synced["messages"]],
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup", description="Join with an invite file: a community, or the server."
    )
    parser.add_argument("--invite-file", required=True, help="the invite file you were sent")
    args = parser.parse_args(argv)
    try:
        result = Setup(SymposiumData()).run(args.invite_file)
    except DataError as e:
        print(json.dumps(e.report))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
