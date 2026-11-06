#!/usr/bin/env python3
"""Bring a community up on a data server, as a server admin:
`/symposium bootstrap --community-file <file>`.

    python3 bootstrap.py --community-file community.json

`community.json` (see community.example.json) holds `community`, the community's name (1-20
letters, digits or underscores); `admin`, the handle of its first community admin; optionally
`handles`, members to invite with `community-member` on every collection; and
`data-server-url`.

Bootstrap:
  1. validates the file, reporting every missing or invalid field at once;
  2. checks that the data server answers and is operational, then sets this directory's
     context: the session of this machine's server-level user for the community;
  3. creates the community with its first community admin, if it does not exist yet. The
     community admin joins with its invite and from then on runs the community: invites,
     roles, the gate;
  4. invites every handle in `handles`, and every user of the community holding no key yet
     (the authors a port brought in), that has not joined and is not invited yet, then writes
     every pending invite, the community admin's included, into the directory it runs in (the
     server admin's session, `~/.symposium/admin/<community>/`, when the skill runs it) as
     `<community>-<handle>.invite` (0600), and prints each full path. Hand each one over out of
     band. A lost file is recovered by running it again.

It is idempotent. Every step runs the `symposium-data` CLI, signed in as this machine's
server-level user, which needs the `communities` grant (root or a server admin); this script
never contacts the data server itself. It prints one JSON object.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from data_io import DataError, SymposiumData  # noqa: E402

# The data server's rules: a community name is a slug, and `admin` is a privileged name; a
# handle is a plain name.
COMMUNITY = re.compile(r"^[A-Za-z0-9_]{1,20}$")
PRIVILEGED = "admin"
HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class Bootstrap:
    def __init__(self, data: SymposiumData):
        self.data = data

    def run(self, community_file: str) -> dict:
        spec = self.read(community_file)
        problems = self.check_fields(spec)
        url = spec.get("data-server-url")
        status = None
        if not any(p.startswith("data-server-url") for p in problems):
            try:
                status = self.data.run("status", "--data-server-url", url)
            except DataError as e:
                if not problems:
                    raise
                problems.append(f"data-server-url: {e}")
        if problems:
            raise DataError({"error": f"{community_file} is not valid", "problems": problems})
        if status.get("mode") != "operational":
            raise DataError(
                {
                    "error": "the data server is not operational: "
                    f"{status.get('reason')}. As root, run `/symposium admin-config` and place "
                    "the root key file as it prints, then restart the server",
                }
            )

        context = self.data.run("context", "set", "--community-file", community_file)["context"]
        community, first_admin = context["community"], spec["admin"]
        made = self.data.run("communities", "create", "--name", community,
                             "--admin", first_admin,
                             "--out", Path(f"{community}-{first_admin}.invite"))
        community = made.get("name", community)
        self.data.run("access")  # the session knows what it may do
        users = self.data.run("users", "list")["users"]
        joined = {u["handle"] for u in users if u["registered"] or u["removed"]}
        # users who hold no key yet: the authors a port brought in
        keyless = [u["handle"] for u in users if not u["registered"] and not u["removed"]]
        pending = {i["handle"]
                   for i in self.data.run("invite", "list", "--out-dir", Path.cwd())["invites"]}
        invited = []
        for handle in [*(spec.get("handles") or []), *keyless]:
            if handle in joined or handle in pending or handle == first_admin:
                continue
            pending.add(handle)
            self.data.run("invite", "--handle", handle, "--access", "community-member:*",
                          "--out", Path(f"{community}-{handle}.invite"))
            invited.append(handle)
        # full paths: the invite files are in the session's directory, not the caller's
        written = self.data.run("invite", "list", "--out-dir", Path.cwd())["invites"]
        return {
            "community": community,
            "data-server-url": context["data-server-url"],
            "admin": first_admin,
            "created": made.get("created", False),
            "invited": invited,
            "invite_files": [invite["invite_file"] for invite in written],
        }

    def read(self, community_file: str) -> dict:
        try:
            spec = json.loads(Path(community_file).read_text())
        except OSError as e:
            raise DataError({"error": f"cannot read {community_file}: {e.strerror}"}) from None
        except ValueError:
            raise DataError({"error": f"{community_file} is not JSON"}) from None
        if not isinstance(spec, dict):
            raise DataError({"error": f"{community_file} is not a JSON object"})
        return spec

    def check_fields(self, spec: dict) -> list:
        problems = []
        community = spec.get("community")
        if community is None:
            problems.append("community: missing (the community's name)")
        elif not isinstance(community, str) or not COMMUNITY.match(community):
            problems.append(
                f"community: '{community}' is not a community name: 1-20 letters, digits or "
                "underscores"
            )
        elif community.lower() == PRIVILEGED:
            problems.append("community: 'admin' is a privileged name and not allowed")
        first_admin = spec.get("admin")
        if first_admin is None:
            problems.append("admin: missing (the handle of the community's first community admin)")
        elif not isinstance(first_admin, str) or not HANDLE.match(first_admin):
            problems.append(f"admin: '{first_admin}' is not a valid handle")
        handles = spec.get("handles")
        if handles is not None and not isinstance(handles, list):
            problems.append("handles: not a list")
        elif handles:
            for handle in handles:
                if not isinstance(handle, str) or not HANDLE.match(handle):
                    problems.append(f"handles: '{handle}' is not a valid handle")
        url = spec.get("data-server-url")
        if url is None:
            problems.append("data-server-url: missing (the data server's URL)")
        elif not isinstance(url, str) or not re.match(r"^https?://", url):
            problems.append(f"data-server-url: '{url}' is not an http(s) URL")
        return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="bootstrap", description="Bring a community up on a data server, as a server admin."
    )
    parser.add_argument(
        "--community-file", required=True, help="community.json: it names the community"
    )
    args = parser.parse_args(argv)
    try:
        result = Bootstrap(SymposiumData()).run(args.community_file)
    except DataError as e:
        print(json.dumps(e.report))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
