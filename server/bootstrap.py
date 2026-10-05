#!/usr/bin/env python3
"""Bring a community up on a data server, as its admin: `/symposium bootstrap --community <file>`.

    python3 bootstrap.py --community community.json

`community.json` holds three fields (see community.example.json): `community`, the community's
name (1-20 letters, digits or underscores); `handles`, its members' handles; and
`data-server-url`. A community inherits its server's admin, so there is no admin field.

Bootstrap:
  1. validates the file, reporting every missing or invalid field at once: a handle that is
     not a valid handle name, or that is the server admin's own handle, is invalid;
  2. checks that the data server answers and is operational, that this machine holds the
     admin key for that server (otherwise run `/symposium admin-config`), and that the server
     is bound to that very key (its `/v1/status` reports the key's handle and fingerprint;
     otherwise the key file was not placed, or the server not restarted);
  3. creates the community if it does not exist, sets this directory's context, and adds every
     handle to the roster (only adding: nobody is ever removed);
  4. writes the invite files: it mints an invite for every roster handle that is neither
     registered nor already invited, then writes every pending invite into the directory it
     runs in (the admin's session, `~/.symposium/admin/<community>/`, when the skill runs it) as
     `<community>-<handle>.invite` (0600), and prints each full path. Hand each one to its member
     out of band. It keeps no state about invites: a lost file is recovered by running it
     again.

It is idempotent. Every step runs the `symposium-data` CLI (R-I1), signed in as the server
admin; this script never contacts the data server itself. It prints one JSON object.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from data_io import DataError, SymposiumData  # noqa: E402

# The data server's rules (R-G8, R-D): a community name is a slug, not a route segment; a handle
# is a plain name.
COMMUNITY = re.compile(r"^[A-Za-z0-9_]{1,20}$")
RESERVED = {"status", "communities", "admin"}
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
        if status is not None:
            if status.get("mode") != "operational":
                raise DataError(
                    {
                        "error": "the data server is not operational: "
                        f"{status.get('reason')}. Run `/symposium admin-config` and place the "
                        "admin key file as it prints, then restart the server",
                    }
                )
            admin = status["admin"]
            for handle in spec.get("handles") or []:
                if handle == admin:
                    problems.append(
                        f"handles: '{handle}' is the server admin's handle, which can never be "
                        "a member"
                    )
        if problems:
            raise DataError({"error": f"{community_file} is not valid", "problems": problems})

        context = self.data.run("context", "set", "--community-file", community_file)["context"]
        key = self.data.run("owner", "pubkey")
        if (status["admin"], status["fingerprint"]) != (key["handle"], key["fingerprint"]):
            raise DataError(
                {
                    "error": f"the data server is bound to '{status['admin']}' with key "
                    f"{status['fingerprint']}, but this machine holds '{key['handle']}' with "
                    f"key {key['fingerprint']}: place the admin_pub_{key['handle']}.key "
                    "file `/symposium admin-config` wrote, and restart the server",
                }
            )

        community = context["community"]
        created = self.data.run("communities", "create", "--name", community)["created"]
        added = [
            handle
            for handle in spec["handles"]
            if self.data.run("roster", "add", "--handle", handle)["added"]
        ]
        for member in self.data.run("roster", "list")["roster"]:
            if not member["registered"] and member["invite_expires"] is None:
                path = Path(f"{community}-{member['handle']}.invite")
                self.data.run("invite", "--handle", member["handle"], "--out", path)
        # full paths: the invite files are in the session's directory, not the caller's
        written = self.data.run("invite", "list", "--out-dir", Path.cwd())["invites"]
        return {
            "community": community,
            "data-server-url": context["data-server-url"],
            "admin": status["admin"],
            "created": created,
            "added_to_roster": added,
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
        elif (
            not isinstance(community, str)
            or not COMMUNITY.match(community)
            or community.lower() in RESERVED
        ):
            problems.append(
                f"community: '{community}' is not a community name: 1-20 letters, digits or "
                "underscores, and not 'status', 'communities' or 'admin'"
            )
        handles = spec.get("handles")
        if handles is None:
            problems.append("handles: missing (the members' handles, a list)")
        elif not isinstance(handles, list):
            problems.append("handles: not a list")
        else:
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
        prog="bootstrap", description="Bring a community up on a data server, as its admin."
    )
    parser.add_argument("--community", required=True, help="community.json")
    args = parser.parse_args(argv)
    try:
        result = Bootstrap(SymposiumData()).run(args.community)
    except DataError as e:
        print(json.dumps(e.report))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
