#!/usr/bin/env python3
"""`/symposium port <ndex_credentials_file> <ndex_url>`: port a community's record from NDEx
into the community of the admin's context (R-M1), through `symposium-data port-ndex`.

Run it after `/symposium bootstrap` has created the community (empty) and set the context, and
run `bootstrap` again afterwards: it writes the invites for the authors and reply recipients the
port added to the roster. The NDEx credentials file is JSON {"username": ..., "password": ...},
mode 0600; it is read by the CLI and sent only to the data server. reference/PORT_NDEX.md is the
guide. This prints the CLI's one JSON object.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="port", description="Port a community's record from NDEx (port-ndex)."
    )
    parser.add_argument(
        "credentials_file", help="the NDEx admin account's credentials file"
    )
    parser.add_argument("ndex_url", help="the NDEx server's base URL")
    args = parser.parse_args(argv)
    return subprocess.run(
        [
            "symposium-data",
            "port-ndex",
            args.credentials_file,
            "--ndex-url",
            args.ndex_url,
        ]
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
