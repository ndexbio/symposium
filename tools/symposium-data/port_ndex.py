"""The `port-ndex` command (R-M1): all of the CLI's NDEx code, argument parsing included (R-S1).

It copies a Symposium community's record from an NDEx server into the context's community,
which must exist and hold no files. The data server does the work in the background; this
command starts it, polls it until it finishes, and prints the result. The NDEx credentials are
read from a file (JSON {"username": ..., "password": ...}, mode 0600), never from the command
line, and are sent only to the data server, which holds the password in memory for the length
of the port.
"""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path

POLL_FIRST, POLL_MAX = 0.2, 2.0


def add_command(sub, command, commands, error):
    """Register `port-ndex` on the CLI's parser; `error` is the CLI's CommandError."""
    p = command(
        sub,
        "port-ndex",
        lambda args: port(commands, args, error),
        "port-ndex: copy a community's record from NDEx into the context's empty "
        "community (admin)",
    )
    p.add_argument(
        "credentials_file",
        help='the NDEx admin account: JSON {"username": ..., "password": ...}, mode 0600',
    )
    p.add_argument("--ndex-url", required=True, help="the NDEx server's base URL")
    p.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="NDEx listing page size (default 100)",
    )


def credentials(path: str, error) -> dict:
    """The NDEx account, a bound pair, from a file only its owner can read."""
    file = Path(path)
    try:
        mode = file.stat().st_mode
        content = json.loads(file.read_text())
    except OSError as e:
        raise error(
            f"cannot read the NDEx credentials file {path}: {e.strerror}"
        ) from None
    except ValueError:
        raise error(f"the NDEx credentials file {path} is not JSON") from None
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise error(
            f"the NDEx credentials file {path} is readable by others: chmod 600 {path}"
        )
    if (
        not isinstance(content, dict)
        or not content.get("username")
        or not content.get("password")
    ):
        raise error(f"the NDEx credentials file {path} needs `username` and `password`")
    return {"username": content["username"], "password": content["password"]}


def port(commands, args, error) -> dict:
    account = credentials(args.credentials_file, error)
    server = commands.admin()
    started = server.start_port(
        {
            "ndex_url": args.ndex_url,
            "credentials": account,
            "page_size": args.page_size,
        }
    )
    view, delay = started, POLL_FIRST
    while view["state"] == "running":
        time.sleep(delay)
        delay = min(delay * 2, POLL_MAX)
        view = server.port(started["id"])
    if view["state"] != "ok":
        raise error(
            f"the port-ndex failed: {view['result'].get('reason')}",
            port=view,
        )
    return view
