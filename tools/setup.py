#!/usr/bin/env python3
"""Join a Symposium community as a member: `/symposium setup --invite-file <file>`.

    python3 setup.py --invite-file lyra.invite

The invite file comes from the community's admin, out of band. It names the community, your
handle and the data server's URL, so nothing else is needed, on a local server or a remote
one. Setup:
  1. sets this directory's context from the invite file (`symposium-data context set`);
  2. makes your key on this machine and registers it with the invite (`symposium-data owner
     register`). Your private key never leaves this machine, and the invite works once.

It is idempotent: run again with the same invite, it reports that you are already registered
with this machine's key and changes nothing. Run it in another directory with another invite
to join another community; every agent session works in its own directory.

Everything goes through the `symposium-data` CLI (R-I1); this script never contacts the data
server itself. It prints one JSON object. (Syncing the record after joining arrives with #21.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_io import DataError, SymposiumData  # noqa: E402


class Setup:
    def __init__(self, data: SymposiumData):
        self.data = data

    def run(self, invite_file: str) -> dict:
        context = self.data.run("context", "set", "--invite-file", invite_file)["context"]
        registered = self.data.run("owner", "register")
        return {
            "community": context["community"],
            "handle": context["handle"],
            "data-server-url": context["data-server-url"],
            "registered": registered["registered"],
            "fingerprint": registered["fingerprint"],
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup", description="Join a community as a member, with an invite file."
    )
    parser.add_argument("--invite-file", required=True, help="the invite file from the admin")
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
