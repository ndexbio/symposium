"""symposium-data: the command-line client of a Symposium Data server, and its only client.
Every command prints one JSON object on stdout, errors included, and exits non-zero on
an error. Nothing secret is ever printed or taken from the command line: keys stay in
the keystore, and invites and API keys move only as files.

Every command but `status`, `admin-config` and `context set` works on the context set in this
directory: `./.symposium/context.json`, written by `context set --invite-file` (any user
joining with an invite), `context set --community-file` (a server-level user working in a
community) or `admin-config` (root's server-level context). The context names the user (its
handle and home, none for a server-level user) and caches the access the server resolved for
it, which `access` refreshes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import port_ndex  # the port-ndex command: all of the CLI's NDEx code is in port_ndex.py
import rbac
from keystore import ADMIN_SCOPE, Keystore, KeystoreError, thumbprint

API_VERSION = "1"
HERE = Path(__file__).resolve().parent
CHUNK = 1 << 20
CITATION = re.compile(r"^symposium-data:([0-9a-fA-F-]{36})@v(\d+)$")
FILE_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
NO_CONTEXT = (
    "no context in this directory: run `/symposium setup --invite-file <file>` (with an "
    "invite) or `/symposium bootstrap --community-file <file>` (server admins) first"
)
NO_COMMUNITY = (
    "this is a community command, and this context is server-level: run it in a community's "
    "session (`/symposium use-community <community>`)"
)


class CommandError(Exception):
    def __init__(self, message: str, status: int | None = None, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra

    def report(self) -> dict:
        out = {"error": str(self)}
        if self.status is not None:
            out["status"] = self.status
        out.update(self.extra)
        return out


class JsonArgumentParser(argparse.ArgumentParser):
    """Usage errors are reported as JSON too, like every other error. Help is formatted at a
    fixed width, so reference/COMMANDS.md is the same on every machine."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "formatter_class", lambda prog: argparse.HelpFormatter(prog, width=100)
        )
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise CommandError(message, usage=self.format_usage().strip())


def image_version() -> str:
    """The data-server image this bundle was built for, from the build's stamp."""
    try:
        return json.loads((HERE / "compat.json").read_text())["data_server_version"]
    except (OSError, ValueError, KeyError):
        return "development checkout"


def same_release(expected: str, running: str) -> bool | None:
    """Whether two data-server versions are the same release line (major.minor); None when
    either is not a version."""
    pattern = re.compile(r"^(\d+)\.(\d+)")
    ours, theirs = pattern.match(expected), pattern.match(running)
    if not ours or not theirs:
        return None
    return ours.groups() == theirs.groups()


def write_secret(path: Path, content: dict):
    """A file only its owner can read: an invite or an API key. Never printed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(content, fh)
    os.chmod(path, 0o600)


def read_json_file(path, what: str) -> dict:
    try:
        content = json.loads(Path(path).read_text())
    except OSError as e:
        raise CommandError(f"cannot read the {what} {path}: {e.strerror}") from None
    except ValueError:
        raise CommandError(f"the {what} {path} is not JSON") from None
    if not isinstance(content, dict):
        raise CommandError(f"the {what} {path} is not a JSON object")
    return content


def loopback_warning(url: str) -> dict:
    """A warning when an invite names a loopback address, which works on that machine only."""
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("localhost", "::1") or host.startswith("127."):
        return {
            "warning": f"the invite names {url}, which reaches the server only from this "
            "machine: set the server's public URL (SYMPOSIUM_SERVER_PUBLIC_URL) for invites "
            "used elsewhere"
        }
    return {}


def json_object(text: str) -> dict:
    """A JSON object given on the command line (metadata, a query)."""
    try:
        value = json.loads(text)
    except ValueError:
        raise argparse.ArgumentTypeError("not JSON") from None
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("not a JSON object")
    return value


def b64u_json(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


def parse_ref(ref: str, version: str | None) -> tuple[str, str]:
    """A citation (`symposium-data:<id>@v<n>`) or a file id -> (file id, version ref)."""
    cited = CITATION.match(ref)
    if cited:
        if version is not None:
            raise CommandError("a citation already names its version: drop --version")
        return cited.group(1), cited.group(2)
    if FILE_ID.match(ref):
        return ref, version or "latest"
    raise CommandError(f"'{ref}' is neither a citation nor a file id")


class DataServer:
    """The one client of a data server's REST API. Constructed for a community, so every
    community route is `/v1/communities/{community}/…` without naming it again; the server-wide calls
    (`status`, sign-in, users, roles, invites, communities) are here too."""

    def __init__(self, base_url: str, community: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.community = community
        self.key = None  # the session key a sign-in answers, or an API key
        self.checked = False

    # ── transport ──────────────────────────────────────────────────────────────────────────
    def request(
        self,
        method: str,
        path: str,
        body=None,
        data=None,
        headers: dict | None = None,
        auth: bool = True,
        stream: bool = False,
        answered: dict | None = None,
    ):
        """-> the parsed JSON body, or the open response when `stream`. `answered`, when
        given, receives the response's headers."""
        if not self.checked:
            self.check_api()
        headers = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth and self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request, timeout=600)
        except urllib.error.HTTPError as e:
            raise self.refusal(e) from None
        except urllib.error.URLError as e:
            raise CommandError(
                f"the data server at {self.base_url} does not answer: {e.reason}"
            ) from None
        if stream:
            return response
        if answered is not None:
            answered.update({k.lower(): v for k, v in response.headers.items()})
        with response:
            raw = response.read()
        return json.loads(raw) if raw else {}

    def refusal(self, error: urllib.error.HTTPError) -> CommandError:
        raw = error.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"detail": raw.decode(errors="replace")[:500]}
        detail = body.get("detail", body) if isinstance(body, dict) else body
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        if error.code == 501:
            return CommandError(
                f"{detail}. Run `/symposium admin-config` and place the root key file as it "
                "prints, then restart the server",
                501,
            )
        if error.code == 410 and isinstance(body, dict):
            metadata = {k: v for k, v in body.items() if k not in ("detail", "code")}
            return CommandError("the version's content was purged", 410, **metadata)
        return CommandError(detail, error.code)

    def status(self) -> dict:
        """`/v1/status`, answered in either mode; a 503 (a dependency down) still carries the
        status body, which says which."""
        try:
            with urllib.request.urlopen(self.base_url + "/v1/status", timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 503:
                return json.loads(e.read())
            raise self.refusal(e) from None
        except (urllib.error.URLError, ValueError) as e:
            reason = getattr(e, "reason", e)
            raise CommandError(
                f"the data server at {self.base_url} does not answer: {reason}"
            ) from None

    def check_api(self):
        self.checked = True
        status = self.status()
        if status.get("api") != API_VERSION:
            raise CommandError(
                f"this CLI speaks the data server's API version {API_VERSION}, but the server "
                f"at {self.base_url} speaks version {status.get('api')}; this bundle was built "
                f"for data-server image {image_version()}"
            )
        expected, running = image_version(), str(status.get("version") or "")
        if (
            re.match(r"^\d+\.\d+", expected)
            and same_release(expected, running) is False
        ):
            raise CommandError(
                f"the data server at {self.base_url} runs version {running}, and this skill "
                f"works with data server {expected}: install the skill released for data "
                f"server {running}"
            )

    def c(self, path: str) -> str:
        if not self.community:
            raise CommandError(NO_COMMUNITY)
        return f"/v1/communities/{urllib.parse.quote(self.community)}{path}"

    # ── sign-in ────────────────────────────────────────────────────────────────────────────
    def challenge(self, handle: str, home: str | None) -> str:
        return self.request(
            "POST",
            "/v1/challenges",
            body={"handle": handle, "community": home},
            auth=False,
        )["nonce"]

    def sign_in(self, keystore: Keystore, handle: str, home: str | None):
        """A session key for the user `handle` homed in `home` (None: a server-level user),
        signed with its key on this machine."""
        nonce = self.challenge(handle, home)
        signature = keystore.sign(home or ADMIN_SCOPE, handle, nonce.encode())
        self.key = self.request(
            "POST",
            "/v1/sessions",
            body={
                "handle": handle,
                "community": home,
                "nonce": nonce,
                "signature": signature,
            },
            auth=False,
        )["key"]

    def register(self, handle: str, jwk: dict, nonce: str, signature: str, invite: str):
        return self.request(
            "POST",
            "/v1/registrations",
            body={
                "handle": handle,
                "public_jwk": jwk,
                "nonce": nonce,
                "signature": signature,
                "invite": invite,
            },
            auth=False,
        )

    def rotate(self, jwk: dict, nonce: str, signature: str) -> dict:
        return self.request(
            "POST",
            "/v1/me/keys",
            body={"public_jwk": jwk, "nonce": nonce, "signature": signature},
        )

    def me(self) -> dict:
        return self.request("GET", "/v1/me")

    # ── server-wide ────────────────────────────────────────────────────────────────────────
    def communities(self) -> dict:
        return self.request("GET", "/v1/communities")

    def create_community(self, name: str, first_admin: str) -> dict:
        return self.request(
            "POST", "/v1/communities", body={"name": name, "admin": first_admin}
        )

    def import_community(self, path: Path) -> dict:
        with open(path, "rb") as source:
            return self.request(
                "POST",
                "/v1/communities",
                data=source,
                headers={
                    "Content-Type": "application/x-tar",
                    "Content-Length": str(path.stat().st_size),
                },
            )

    # ── users, roles and invites ───────────────────────────────────────────────────────────
    @staticmethod
    def scope(community: str | None) -> str:
        """Where a scope's users and invites live: a community's, or the server's."""
        if community is None:
            return "/v1"
        return f"/v1/communities/{urllib.parse.quote(community)}"

    def user_path(self, handle: str, community: str | None) -> str:
        return f"{self.scope(community)}/users/{urllib.parse.quote(handle, safe='')}"

    def key_path(self, key_id: str) -> str:
        return self.c(f"/api-keys/{urllib.parse.quote(key_id, safe='')}")

    def users(self, community: str | None) -> dict:
        return self.request("GET", f"{self.scope(community)}/users")

    def remove_user(self, handle: str, community: str | None) -> dict:
        return self.request("DELETE", self.user_path(handle, community))

    def rebind(self, handle: str, community: str | None, hours: int | None) -> dict:
        body = {} if hours is None else {"hours": hours}
        return self.request(
            "POST", self.user_path(handle, community) + "/invites", body=body
        )

    def suspect_after(self, handle: str, community: str | None, at: str) -> dict:
        return self.request(
            "PATCH", self.user_path(handle, community), body={"suspect_after": at}
        )

    def roles(self) -> dict:
        return self.request("GET", "/v1/roles")

    def set_role(self, principal: str, role: str, collections) -> dict:
        """Assign a role, or set its whole collection value under its ETag."""
        path = f"{principal}/roles/{role}"
        answered: dict = {}
        headers = {}
        try:
            self.request("GET", path, answered=answered)
        except CommandError as e:
            if e.status != 404:
                raise
        if answered.get("etag"):
            headers["If-Match"] = answered["etag"]
        body = None if collections is None else {"collections": collections}
        return self.request(
            "PUT", path, body=body if body is not None else {}, headers=headers
        )

    def unset_role(self, principal: str, role: str) -> dict:
        return self.request("DELETE", f"{principal}/roles/{role}")

    def add_role_collection(self, principal: str, role: str, collection: str) -> dict:
        name = urllib.parse.quote(collection, safe="")
        return self.request("PUT", f"{principal}/roles/{role}/collections/{name}")

    def remove_role_collection(self, principal: str, role: str, collection: str):
        name = urllib.parse.quote(collection, safe="")
        return self.request("DELETE", f"{principal}/roles/{role}/collections/{name}")

    def invite(self, community: str | None, body: dict) -> dict:
        return self.request("POST", f"{self.scope(community)}/invites", body=body)

    def pending_invites(self, community: str | None) -> dict:
        return self.request("GET", f"{self.scope(community)}/invites")

    # ── API keys: issued per community by a signed-in user ─────────────────────────────────
    @staticmethod
    def api_keys_path(community: str, path: str = "") -> str:
        return f"/v1/communities/{urllib.parse.quote(community)}/api-keys{path}"

    def create_api_key(self, community: str, body: dict) -> dict:
        return self.request("POST", self.api_keys_path(community), body=body)

    def api_keys(self, community: str) -> list:
        """The community's API keys the caller may see, page by page."""
        items, cursor = [], None
        while True:
            query = {"limit": "1000"}
            if cursor:
                query["cursor"] = cursor
            page = self.request(
                "GET",
                self.api_keys_path(community, "?" + urllib.parse.urlencode(query)),
            )
            items += page["items"]
            cursor = page.get("next")
            if not cursor:
                return items

    def revoke_api_key(self, community: str, key_id: str) -> dict:
        return self.request(
            "DELETE",
            self.api_keys_path(community, f"/{urllib.parse.quote(key_id)}"),
        )

    # ── files ──────────────────────────────────────────────────────────────────────────────
    def upload(
        self, method: str, path: str, source: Path | None, headers: dict
    ) -> dict:
        """Stream a file's bytes, declaring its sha-256 as Repr-Digest; the server hashes the
        body as it arrives and refuses a mismatch."""
        if source is None:
            return self.request(method, path, data=b"", headers=headers)
        digest = hashlib.sha256()
        with open(source, "rb") as fh:
            while chunk := fh.read(CHUNK):
                digest.update(chunk)
        headers = {
            **headers,
            "Repr-Digest": "sha-256=:"
            + base64.b64encode(digest.digest()).decode()
            + ":",
            "Content-Length": str(source.stat().st_size),
        }
        with open(source, "rb") as fh:
            return self.request(method, path, data=fh, headers=headers)

    def put(self, collection: str, name: str, source: Path, headers: dict) -> dict:
        path = self.c(
            f"/collections/{collection}/files/{urllib.parse.quote(name, safe='')}"
        )
        return self.upload("PUT", path, source, {**headers, "If-None-Match": "*"})

    def add_version(self, file_id: str, source: Path | None, headers: dict) -> dict:
        return self.upload(
            "POST", self.c(f"/files/{file_id}/versions"), source, headers
        )

    def delete(self, file_id: str, reason: str | None) -> dict:
        query = "?" + urllib.parse.urlencode({"reason": reason}) if reason else ""
        return self.request("DELETE", self.c(f"/files/{file_id}{query}"))

    def promote(self, collection: str, body: dict) -> dict:
        """Copy the version `body["from"]` cites into `collection` as a new file."""
        return self.request(
            "POST", self.c(f"/collections/{collection}/files"), body=body
        )

    def find(self, collection: str, name: str) -> dict:
        query = urllib.parse.urlencode({"name": name})
        found = self.request("GET", self.c(f"/collections/{collection}/files?{query}"))
        if not found["items"]:
            raise CommandError(f"no file named '{name}' in {collection}", 404)
        return found["items"][0]

    def by_hash(self, sha256: str) -> dict:
        query = urllib.parse.urlencode({"sha256": sha256})
        return self.request("GET", self.c(f"/versions?{query}"))

    def query(self, collection: str, contains: dict, since: int, limit: int) -> dict:
        return self.request(
            "POST",
            self.c(f"/collections/{collection}/files/search"),
            body={"contains": contains, "since": since, "limit": limit},
        )

    def verify(self, file_id: str, n: str, before: str | None, sha256: str | None):
        params = {k: v for k, v in (("before", before), ("sha256", sha256)) if v}
        query = "?" + urllib.parse.urlencode(params) if params else ""
        return self.request(
            "GET", self.c(f"/files/{file_id}/versions/{n}/verification{query}")
        )

    # ── collections ────────────────────────────────────────────────────────────────────────
    def list_collections(self) -> dict:
        return self.request("GET", self.c("/collections"))

    def create_collection(self, name: str) -> dict:
        return self.request("POST", self.c("/collections"), body={"name": name})

    def set_public(self, collection: str, public: bool) -> dict:
        return self.request(
            "PATCH", self.c(f"/collections/{collection}"), body={"public": public}
        )

    def purge(self, file_id: str, n: str) -> dict:
        return self.request("DELETE", self.c(f"/files/{file_id}/versions/{n}"))

    def stat(self, file_id: str, ref: str) -> dict:
        return self.request("GET", self.c(f"/files/{file_id}/versions/{ref}/metadata"))

    def versions(self, file_id: str) -> dict:
        return self.request("GET", self.c(f"/files/{file_id}/versions"))

    def content(self, file_id: str, ref: str):
        return self.request(
            "GET", self.c(f"/files/{file_id}/versions/{ref}"), stream=True
        )

    def changes(self, collection: str, since: int, limit: int) -> dict:
        query = urllib.parse.urlencode({"since": since, "limit": limit})
        return self.request("GET", self.c(f"/collections/{collection}/changes?{query}"))

    def export(self):
        return self.request("GET", self.c("/archive"), stream=True)

    # ── the port ────────────────────────────────────────────────────────────────────
    def start_port(self, body: dict) -> dict:  # port-ndex
        return self.request("POST", self.c("/ndex-imports"), body=body)

    def port(self, port_id: str) -> dict:  # port-ndex
        return self.request("GET", self.c(f"/ndex-imports/{port_id}"))


class Context:
    """`./.symposium/context.json`: the data-server URL, the user this directory works as (its
    handle, and its home: a community, or None for a server-level user), the community it
    works in (None for a server-level context), and the access the server resolved for it.
    It holds no secret: an invite stays in its file."""

    PATH = Path(".symposium") / "context.json"

    def load(self) -> dict:
        if not self.PATH.exists():
            raise CommandError(NO_CONTEXT)
        context = json.loads(self.PATH.read_text())
        if "home" not in context:
            context = self.upgraded(context)
            self.save(context)
        return context

    @staticmethod
    def upgraded(context: dict) -> dict:
        """A context the 0.1 skill wrote names its user's `role` instead of its home: a
        member's home is the community it works in, and the user bound from the key file is
        root, a server-level user. Written back once, so the session needs no step of its own."""
        out = {k: v for k, v in context.items() if k != "role"}
        out["home"] = (
            context.get("community") if context.get("role") == "member" else None
        )
        return out

    def save(self, context: dict):
        """Whole or not at all: a sibling file named for this process, then an atomic rename,
        so a command reading the context beside this one reads a whole one."""
        self.PATH.parent.mkdir(exist_ok=True)
        staged = self.PATH.with_name(f"{self.PATH.name}.{os.getpid()}.tmp")
        staged.write_text(json.dumps(context, indent=2) + "\n")
        os.replace(staged, self.PATH)


def scope_of(context: dict) -> str:
    """The keystore scope of the context's user: its home, or `admin` for a server-level
    user."""
    return context.get("home") or ADMIN_SCOPE


def access_list(values) -> list:
    """Every `--access` value of a command line, parsed."""
    try:
        return [rbac.parse_access(v) for v in values or []]
    except rbac.AccessError as e:
        raise CommandError(str(e)) from None


class Commands:
    def __init__(self):
        self.context = Context()

    # ── shared ─────────────────────────────────────────────────────────────────────────────
    def server_for(self, url: str, community: str | None = None) -> DataServer:
        return DataServer(url, community)

    def keystore(self, server_id: str) -> Keystore:
        return Keystore(server_id)

    def signed_in(self, context: dict | None = None) -> DataServer:
        """A client for the context's community, signed in as the context's user."""
        context = context or self.context.load()
        server = self.server_for(context["data-server-url"], context.get("community"))
        keystore = self.keystore(context["server_id"])
        try:
            server.sign_in(keystore, context["handle"], context.get("home"))
        except CommandError as e:
            if e.status == 401 and "removed" in str(e):
                where = context.get("home") or "this server"
                raise CommandError(
                    f"this account was removed from {where}", 401
                ) from None
            raise
        return server

    def server_handle(self, server_id: str, url: str, handle: str | None = None) -> str:
        """The server-level user whose key this machine holds for the server: `handle`, or
        the only one."""
        handles = self.keystore(server_id).handles(ADMIN_SCOPE)
        if not handles:
            raise CommandError(
                f"this machine holds no server-level key for the data server at {url}: join "
                "with a server-level invite (`/symposium setup --invite-file <file>`), or, as "
                "root, run `/symposium admin-config --handle <root> --data-server-url <url>`"
            )
        if handle is not None:
            if handle not in handles:
                raise CommandError(
                    f"this machine holds no server-level key for '{handle}' at {url}; it "
                    f"holds {', '.join(handles)}"
                )
            return handle
        if len(handles) > 1:
            raise CommandError(
                f"this machine holds the server-level keys of {', '.join(handles)} for {url}: "
                "name one with --handle"
            )
        return handles[0]

    def community_of(self, args, context: dict) -> str | None:
        """The community a command names (`--community`), else the context's."""
        return getattr(args, "community", None) or context.get("community")

    # ── status and context ─────────────────────────────────────────────────────────────────
    def status(self, args) -> dict:
        url = args.data_server_url or self.context.load()["data-server-url"]
        return self.server_for(url).status()

    def context_set(self, args) -> dict:
        if args.community_file or args.community:
            if args.community_file:
                spec = read_json_file(args.community_file, "community file")
                community, url = spec.get("community"), spec.get("data-server-url")
                if not community or not url:
                    raise CommandError(
                        f"{args.community_file} needs `community` and `data-server-url`"
                    )
            else:
                community, url = args.community, args.data_server_url
                if not url:
                    raise CommandError("--community takes --data-server-url too")
            status = self.server_for(url).status()
            handle = self.server_handle(status["server_id"], url, args.handle)
            home, extra = None, {}
        else:
            invite = read_json_file(args.invite_file, "invite file")
            missing = [
                k for k in ("invite", "handle", "data-server-url") if not invite.get(k)
            ]
            if missing or "community" not in invite:
                missing += [] if "community" in invite else ["community"]
                raise CommandError(f"{args.invite_file} lacks {', '.join(missing)}")
            community = home = invite["community"]
            url, handle = invite["data-server-url"], invite["handle"]
            status = self.server_for(url).status()
            extra = {"invite_file": str(Path(args.invite_file).resolve())}
        return {
            "context": self.save_context(url, community, handle, home, status, extra)
        }

    def save_context(self, url, community, handle, home, status, extra=None) -> dict:
        context = {
            "community": community,
            "data-server-url": url.rstrip("/"),
            "handle": handle,
            "home": home,
            "server_id": status["server_id"],
            **(extra or {}),
        }
        self.context.save(context)
        return context

    def context_show(self, _args) -> dict:
        return {"context": self.context.load()}

    # ── root ───────────────────────────────────────────────────────────────────────────────
    def admin_config(self, args) -> dict:
        """Make root's key and set root's server-level context here: idempotent; a key
        pair is generated only when this machine holds none for the server, or with
        --new-key."""
        url = args.data_server_url.rstrip("/")
        status = self.server_for(url).status()
        server_id = status["server_id"]
        keystore = self.keystore(server_id)
        held = keystore.handles(ADMIN_SCOPE)
        if held and args.handle not in held:
            raise CommandError(
                f"this machine holds the server-level keys of {', '.join(held)} for this "
                "server: run admin-config with root's handle"
            )
        created = args.new_key or not held
        jwk = (
            keystore.create(ADMIN_SCOPE, args.handle, replace=args.new_key)
            if created
            else keystore.public_jwk(ADMIN_SCOPE, args.handle)
        )
        key_file = Path(f"admin_pub_{args.handle}.key").resolve()
        key_file.write_text(json.dumps(jwk))
        os.chmod(key_file, 0o644)
        self.save_context(url, None, args.handle, None, status)
        out = {
            "handle": args.handle,
            "server_id": server_id,
            "fingerprint": thumbprint(jwk),
            "public_key_file": str(key_file),
            "created": created,
            "steps": [
                f"with Docker: place {key_file} on the server, by copying it into the "
                f"directory of your machine mounted on /apps (`cp {key_file} <that "
                f"directory>/`) or with `docker cp {key_file} <container>:/apps/`, then "
                "restart it (`docker restart <container>`)",
                "or on Kubernetes, with the Helm chart: add `adminKey: {handle: "
                f"{args.handle}}}` to the install's values file and run `helm upgrade "
                "<release> <chart> -n <namespace> --version <chart version> -f <values "
                f"file> --set-file adminKey.publicKey={key_file}`, which restarts the "
                "server (the data server's RUNBOOK.md, 5.3: the root key on Kubernetes)",
                f"check that GET {url}/v1/status reports root '{args.handle}' with this "
                "fingerprint",
            ],
        }
        if args.new_key and held:
            out["warning"] = (
                "a new key: placing this file rebinds root, and the old key is refused from "
                "then on"
            )
        return out

    # ── communities ────────────────────────────────────────────────────────────────────────
    def communities_create(self, args) -> dict:
        """Create a community with its first community admin, and write that community admin's
        invite file (0600) when the community is new."""
        server = self.signed_in()
        made = server.create_community(args.name, args.admin)
        issued = made.pop("admin_invite", None)
        if issued is not None:
            out = Path(args.out or f"{made.get('name', args.name)}-{args.admin}.invite")
            write_secret(out, self.invite_file(server, issued))
            made["admin_invite_file"] = str(out.resolve())
        return made

    def communities_list(self, _args) -> dict:
        return self.signed_in().communities()

    # ── invites ────────────────────────────────────────────────────────────────────────────
    def invite_file(self, server: DataServer, issued: dict) -> dict:
        """An invite as a file: its secret, the handle, its home and the server's URL. The
        roles stay on the server."""
        return {
            "invite": issued["invite"],
            "handle": issued["handle"],
            "community": issued["community"],
            "data-server-url": issued.get("data-server-url") or server.base_url,
        }

    def invite(self, args) -> dict:
        if args.action == "list":
            return self.invite_list(args)
        if not args.handle or not args.out or not args.access:
            raise CommandError(
                "invite needs --handle, --access and --out (or: invite list --out-dir)"
            )
        context = self.context.load()
        server = self.signed_in(context)
        body = {"handle": args.handle, "roles": access_list(args.access)}
        if args.hours is not None:
            body["hours"] = args.hours
        issued = server.invite(self.invitee_home(args, context), body)
        write_secret(Path(args.out), self.invite_file(server, issued))
        return {
            "community": issued["community"],
            "handle": issued["handle"],
            "roles": issued["roles"],
            "expires": issued["expires"],
            "invite_file": str(Path(args.out).resolve()),
            **loopback_warning(issued.get("data-server-url") or server.base_url),
        }

    def invitee_home(self, args, context: dict) -> str | None:
        """The invitee's home: --community, else the context's community. A server role
        makes a server-level user; a community role needs a community."""
        if any(
            a.split(":")[0] in (rbac.SERVER_ADMIN, rbac.SERVER_ROOT)
            for a in args.access
        ):
            return None
        community = self.community_of(args, context)
        if community is None:
            raise CommandError(
                "a community role invites into a community: name it with --community "
                "<community> (this session works server-wide)"
            )
        return community

    def invite_list(self, args) -> dict:
        """Every pending invite as `<community>-<handle>.invite` (0600) in --out-dir; only
        the paths are printed, because invites are secrets."""
        context = self.context.load()
        server = self.signed_in(context)
        community = None if args.server else self.community_of(args, context)
        pending = server.pending_invites(community)
        directory = Path(args.out_dir)
        written = []
        for item in pending["invites"]:
            prefix = item["community"] or "server"
            path = directory / f"{prefix}-{item['handle']}.invite"
            write_secret(path, self.invite_file(server, item))
            written.append(
                {
                    "handle": item["handle"],
                    "roles": item["roles"],
                    "expires": item["expires"],
                    "invite_file": str(path.resolve()),
                }
            )
        return {"community": pending["community"], "invites": written}

    # ── access roles ───────────────────────────────────────────────────────────────────────
    def access(self, _args) -> dict:
        """The six access roles, and this context's own: its roles and the grants the server
        resolved for it, which the context caches for the tools."""
        context = self.context.load()
        server = self.signed_in(context)
        roles = server.roles()["roles"]
        me = server.me()
        context["access"] = {"roles": me["roles"], "context": me["context"]}
        self.context.save(context)
        return {
            "handle": context["handle"],
            "community": context.get("community"),
            "roles": me["roles"],
            "context": me["context"],
            "access_roles": roles,
        }

    def principal(self, server: DataServer, args, context: dict) -> tuple[str, dict]:
        """The principal an assign or unassign names: a user, or an issued key. -> (its
        path, how it is printed)."""
        if args.api_key:
            return server.key_path(args.api_key), {"api_key_id": args.api_key}
        home = self.target_home(args, context)
        return server.user_path(args.handle, home), {
            "handle": args.handle,
            "community": home,
        }

    def target_home(self, args, context: dict) -> str | None:
        """--community, else the context's community; --server names a server-level user."""
        if getattr(args, "server", False):
            return None
        return self.community_of(args, context)

    def assign(self, args) -> dict:
        """`<role>:c1,c2` adds those collections, one at a time; `<role>:*`, `<role>:` and
        `<role>` set the role's whole value. -> each changed assignment, as the server answers
        it."""
        context = self.context.load()
        server = self.signed_in(context)
        path, target = self.principal(server, args, context)
        changed = []
        for assignment in access_list(args.access):
            names = assignment["collections"]
            if names and rbac.ALL not in names:
                for name in names:
                    held = server.add_role_collection(path, assignment["role"], name)
            else:
                held = server.set_role(path, assignment["role"], names)
            changed.append(held)
        return {**target, "roles": changed}

    def unassign(self, args) -> dict:
        """`<role>` ends the role; `<role>:c1,c2` withdraws those collections. -> the
        principal's roles as the last change left them."""
        context = self.context.load()
        server = self.signed_in(context)
        path, target = self.principal(server, args, context)
        left: dict = {"roles": []}
        for value in args.access:
            role, colon, _ = value.partition(":")
            if not colon:
                left = server.unset_role(path, role)
                continue
            for name in access_list([value])[0]["collections"] or []:
                left = server.remove_role_collection(path, role, name)
        return {**target, "roles": left["roles"]}

    # ── users ──────────────────────────────────────────────────────────────────────────────
    def users_list(self, args) -> dict:
        """A community's users, readable by any principal of it, or with --server the
        server-level users."""
        context = self.context.load()
        return self.signed_in(context).users(self.target_home(args, context))

    def users_remove(self, args) -> dict:
        context = self.context.load()
        return self.signed_in(context).remove_user(
            args.handle, self.target_home(args, context)
        )

    def rebind_key(self, args) -> dict:
        context = self.context.load()
        server = self.signed_in(context)
        issued = server.rebind(args.handle, self.target_home(args, context), args.hours)
        write_secret(Path(args.out), self.invite_file(server, issued))
        return {
            "community": issued["community"],
            "handle": issued["handle"],
            "retired_keys": issued["retired_keys"],
            "expires": issued["expires"],
            "invite_file": str(Path(args.out).resolve()),
        }

    def suspect_after(self, args) -> dict:
        context = self.context.load()
        return self.signed_in(context).suspect_after(
            args.handle, self.target_home(args, context), args.at
        )

    # ── API keys (api/DESIGN.md §4.6): values move as 0600 files, never on stdout ───────────
    @staticmethod
    def api_key_dir(context: dict) -> Path:
        """Where a session's key files go: a homed user's in its own session, a server-level
        user's beside its other server-level files."""
        if not context.get("home"):
            return (
                Path.home()
                / ".symposium"
                / "admin"
                / ADMIN_SCOPE
                / context["handle"]
                / "api-keys"
            )
        return (
            Path.home()
            / ".symposium"
            / "member"
            / context["home"]
            / context["handle"]
            / "api-keys"
        )

    @staticmethod
    def api_key_view(item: dict) -> dict:
        """A key as printed: everything but its value."""
        return {k: v for k, v in item.items() if k != "key"}

    def key_community(self, args, context: dict) -> str:
        community = self.community_of(args, context)
        if not community:
            raise CommandError(NO_COMMUNITY)
        return community

    def gen_api_key(self, args) -> dict:
        """Issue a key carrying --access roles: a member key acts as the signed-in user,
        within its grants; with --non-member, a key of its own for an application, carrying
        community-observer."""
        context = self.context.load()
        community = self.key_community(args, context)
        server = self.signed_in(context)
        if not args.access:
            raise CommandError(f"gen-api-key needs --access: {rbac.ACCESS_FORMS}")
        body = {
            "label": args.label,
            "non_member": args.non_member,
            "roles": access_list(args.access),
        }
        if args.expires_days:
            body["expires_days"] = args.expires_days
        issued = server.create_api_key(community, body)
        path = self.api_key_dir(context) / f"{issued['id']}.key"
        write_secret(
            path,
            {
                **issued,
                "data-server-url": server.base_url,
                "api": server.base_url + "/v1",
            },
        )
        return {**self.api_key_view(issued), "key_file": str(path.resolve())}

    def list_api_keys(self, args) -> dict:
        """The keys this user issued, or every key of the community for a `members`
        holder, with their roles."""
        context = self.context.load()
        community = self.key_community(args, context)
        server = self.signed_in(context)
        items = server.api_keys(community)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.api_key_dir(context) / f"list-{stamp}.json"
        write_secret(
            path,
            {"data-server-url": server.base_url, "community": community, "keys": items},
        )
        return {
            "community": community,
            "keys": [self.api_key_view(item) for item in items],
            "keys_file": str(path.resolve()),
        }

    def revoke_api_key(self, args) -> dict:
        """Delete a key this user issued, or any key of the community with `members`."""
        context = self.context.load()
        community = self.key_community(args, context)
        server = self.signed_in(context)
        return self.api_key_view(server.revoke_api_key(community, args.key_id))

    # ── curation, export and import ────────────────────────────────────────────────────────
    def purge(self, args) -> dict:
        cited = CITATION.match(args.cite)
        if not cited:
            raise CommandError("--cite takes a citation: symposium-data:<file-id>@v<n>")
        return self.signed_in().purge(cited.group(1), cited.group(2))

    def export(self, args) -> dict:
        server = self.signed_in()
        out = Path(args.out)
        size = 0
        partial = out.with_name(out.name + ".partial")
        with server.export() as response:
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                while chunk := response.read(CHUNK):
                    fh.write(chunk)
                    size += len(chunk)
        os.replace(partial, out)
        return {"exported": server.community, "file": str(out.resolve()), "bytes": size}

    def import_(self, args) -> dict:
        """Create the exported community on this server, then set the context: the
        server-level user's session for that community."""
        source = Path(args.from_)
        spec = read_json_file(args.community_file, "community file")
        exported = self.exported_community(source)
        if exported != spec.get("community"):
            raise CommandError(
                f"{source} holds the community '{exported}', but {args.community_file} names "
                f"'{spec.get('community')}': use the community file of the exported community"
            )
        url = spec.get("data-server-url")
        if not url:
            raise CommandError(f"{args.community_file} needs `data-server-url`")
        status = self.server_for(url).status()
        handle = self.server_handle(status["server_id"], url, args.handle)
        context = {
            "community": exported,
            "data-server-url": url.rstrip("/"),
            "handle": handle,
            "home": None,
            "server_id": status["server_id"],
        }
        report = self.signed_in(context).import_community(source)
        self.context.save(context)
        return report

    def exported_community(self, source: Path) -> str:
        try:
            with tarfile.open(source, mode="r|") as tar:
                for member in tar:
                    if member.name == "manifest.json":
                        return json.loads(tar.extractfile(member).read())["community"]
                    break
        except (OSError, tarfile.TarError, ValueError, KeyError) as e:
            raise CommandError(f"{source} is not a community export: {e}") from None
        raise CommandError(
            f"{source} is not a community export: no manifest.json first"
        )

    # ── this user's identity ───────────────────────────────────────────────────────────────
    def owner_register(self, _args) -> dict:
        """Join with the context's invite and a key made on this machine: the
        server creates the user with the invite's roles. Idempotent: a user already joined
        with this machine's key is reported, not joined again."""
        context = self.context.load()
        if not context.get("invite_file"):
            raise CommandError(
                "this context was set without an invite: join with "
                "`/symposium setup --invite-file <file>`"
            )
        handle, scope = context["handle"], scope_of(context)
        keystore = self.keystore(context["server_id"])
        server = self.server_for(context["data-server-url"], context.get("community"))
        out = {"community": context.get("home"), "handle": handle}
        if keystore.exists(scope, handle):
            try:
                server.sign_in(keystore, handle, context.get("home"))
                jwk = keystore.public_jwk(scope, handle)
                return {**out, "registered": False, "fingerprint": thumbprint(jwk)}
            except CommandError as e:
                if e.status != 401 or "removed" in str(e):
                    raise  # 401: this key is unregistered; join anew
        invite = read_json_file(context["invite_file"], "invite file").get("invite")
        jwk = keystore.stage(scope, handle)
        try:
            nonce = server.challenge(handle, context.get("home"))
            signature = keystore.sign_staged(scope, handle, nonce.encode())
            joined = server.register(handle, jwk, nonce, signature, invite)
        except CommandError:
            keystore.discard(scope, handle)
            raise
        keystore.commit(scope, handle)
        return {
            **out,
            "registered": True,
            "roles": joined.get("roles", []),
            "fingerprint": thumbprint(jwk),
        }

    def owner_whoami(self, _args) -> dict:
        return self.signed_in().me()

    def owner_pubkey(self, _args) -> dict:
        context = self.context.load()
        jwk = self.keystore(context["server_id"]).public_jwk(
            scope_of(context), context["handle"]
        )
        return {
            "handle": context["handle"],
            "public_jwk": jwk,
            "fingerprint": thumbprint(jwk),
        }

    def owner_rotate(self, _args) -> dict:
        """A new key for this user, proven by the new key and authorized by the current one;
        the current key is replaced only once the server has accepted the new one."""
        context = self.context.load()
        handle, scope = context["handle"], scope_of(context)
        keystore = self.keystore(context["server_id"])
        server = self.signed_in(context)
        jwk = keystore.stage(scope, handle)
        try:
            nonce = server.challenge(handle, context.get("home"))
            signature = keystore.sign_staged(scope, handle, nonce.encode())
            rotated = server.rotate(jwk, nonce, signature)
        except CommandError:
            keystore.discard(scope, handle)
            raise
        keystore.commit(scope, handle)
        return {**rotated, "fingerprint": thumbprint(jwk)}

    # ── writing ────────────────────────────────────────────────────────────────────────────
    def file_headers(self, metadata: dict | None, content_type: str | None) -> dict:
        headers = {"Content-Type": content_type or "application/octet-stream"}
        if metadata is not None:
            headers["X-Data-Metadata"] = b64u_json(metadata)
        return headers

    def put(self, args) -> dict:
        headers = self.file_headers(args.metadata, args.content_type)
        return self.signed_in().put(
            args.collection, args.name, Path(args.file), headers
        )

    def version(self, args) -> dict:
        file_id, _ = parse_ref(args.file_id, None)
        if args.file is None and args.metadata is None:
            raise CommandError(
                "a version needs new content (a file), new --metadata, or both"
            )
        headers = self.file_headers(args.metadata, args.content_type)
        if args.file is None:
            headers["X-Data-Metadata-Only"] = "1"
        if args.if_match is not None:
            headers["If-Match"] = f'"v{args.if_match}"'
        source = Path(args.file) if args.file else None
        return self.signed_in().add_version(file_id, source, headers)

    def delete(self, args) -> dict:
        file_id, _ = parse_ref(args.file_id, None)
        return self.signed_in().delete(file_id, args.reason)

    def promote(self, args) -> dict:
        file_id, n = parse_ref(args.ref, None)
        if n == "latest":
            raise CommandError(
                "promote takes a citation: symposium-data:<file-id>@v<n>"
            )
        body = {"from": f"symposium-data:{file_id}@v{n}"}
        for key, value in (
            ("name", args.name),
            ("metadata", args.metadata),
            ("stamp_json_pointer", args.stamp_json_pointer),
        ):
            if value is not None:
                body[key] = value
        return self.signed_in().promote(args.collection, body)

    # ── collections ────────────────────────────────────────────────────────────────────────
    def collection_list(self, _args) -> dict:
        return self.signed_in().list_collections()

    def collection_create(self, args) -> dict:
        return self.signed_in().create_collection(args.name)

    def collection_set_public(self, args) -> dict:
        return self.signed_in().set_public(args.collection, args.public)

    # ── reading ────────────────────────────────────────────────────────────────────────────
    def find_name(self, args) -> dict:
        return self.signed_in().find(args.collection, args.name)

    def find_hash(self, args) -> dict:
        return self.signed_in().by_hash(args.sha256)

    def find_meta(self, args) -> dict:
        return self.signed_in().query(
            args.collection, args.contains, args.since, args.limit
        )

    def verify(self, args) -> dict:
        """A citation names its version: the check is that version's verification."""
        cited = CITATION.match(args.cite)
        if not cited:
            return {
                "ok": False,
                "exists": False,
                "reason": "not a symposium-data citation",
            }
        return self.signed_in().verify(
            cited.group(1), cited.group(2), args.before, args.sha256
        )

    def changes(self, args) -> dict:
        server = self.signed_in()
        page = server.changes(args.collection, args.since, args.limit)
        if not args.all:
            return page
        # every page from --since on, as one object; never silently capped
        items = list(page["items"])
        while page["more"]:
            page = server.changes(args.collection, page["next_since"], args.limit)
            items.extend(page["items"])
        return {"items": items, "next_since": page["next_since"], "more": False}

    def stat(self, args) -> dict:
        return self.signed_in().stat(*parse_ref(args.ref, args.version))

    def versions(self, args) -> dict:
        file_id, _ = parse_ref(args.file_id, None)
        return self.signed_in().versions(file_id)

    def get(self, args) -> dict:
        file_id, ref = parse_ref(args.ref, args.version)
        if args.api_key_file:
            server = self.with_api_key(args.api_key_file)
        else:
            server = self.signed_in()
        return self.download(server.content(file_id, ref), Path(args.out))

    def with_api_key(self, path) -> DataServer:
        """A client that reads with an API key file, as `gen-api-key` writes one, with no
        context: what an application holding an issued key does."""
        key = read_json_file(path, "API key file")
        missing = [k for k in ("key", "community", "data-server-url") if not key.get(k)]
        if missing:
            raise CommandError(f"{path} lacks {', '.join(missing)}")
        server = self.server_for(key["data-server-url"], key["community"])
        server.key = key["key"]
        return server

    def download(self, response, out: Path) -> dict:
        """Stream the content to `out`, checking it against the server's Repr-Digest."""
        digest = hashlib.sha256()
        size = 0
        partial = out.with_name(out.name + ".partial")
        with response, open(partial, "wb") as fh:
            headers = response.headers
            while chunk := response.read(CHUNK):
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        expected = re.search(r"sha-256=:([^:]+):", headers.get("Repr-Digest", ""))
        if expected and base64.b64decode(expected.group(1)) != digest.digest():
            partial.unlink()
            raise CommandError(
                "the content does not match its Repr-Digest; nothing kept"
            )
        os.replace(partial, out)
        return {
            "citation": headers.get("X-Data-Citation"),
            "version": headers.get("X-Data-Version"),
            "sha256": digest.hexdigest(),
            "size": size,
            "file": str(out.resolve()),
            "deleted": headers.get("X-Data-Deleted") == "true",
        }


def build_parser(commands: Commands) -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="symposium-data",
        description="The command-line client of a Symposium Data server. Every command "
        "prints one JSON object.",
    )
    parser.add_argument(
        "--reference",
        action="store_true",
        help="write reference/COMMANDS.md from this parser, and exit",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def command(group, name, func, help_text):
        p = group.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    p = command(
        sub, "status", commands.status, "the data server's status, in either mode"
    )
    p.add_argument("--data-server-url", help="default: the context's server")

    context = sub.add_parser("context", help="this directory's context")
    actions = context.add_subparsers(dest="action", metavar="<action>", required=True)
    p = command(actions, "set", commands.context_set, "set the context from a file")
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument(
        "--community-file",
        help="community.json: a server-level user's community session",
    )
    which.add_argument("--invite-file", help="an invite file: the user it invites")
    which.add_argument(
        "--community",
        help="a server-level user's session for an existing community (with "
        "--data-server-url)",
    )
    p.add_argument("--data-server-url", help="with --community: the data server")
    p.add_argument(
        "--handle",
        help="with --community-file or --community: the server-level user, when this "
        "machine holds several",
    )
    command(actions, "show", commands.context_show, "print the context")

    p = command(
        sub,
        "admin-config",
        commands.admin_config,
        "make root's key and its public key file, and set root's server-level context",
    )
    p.add_argument("--handle", required=True)
    p.add_argument("--data-server-url", required=True)
    p.add_argument(
        "--new-key",
        action="store_true",
        help="replace the key: placing the new file rebinds root",
    )

    access_help = (
        "an access role, repeatable: <role>, or for community-member and community-observer "
        "<role>:* (every collection), <role>: (only its own) or <role>:c1,c2"
    )

    communities = sub.add_parser(
        "communities", help="the server's communities (`communities` grant)"
    )
    actions = communities.add_subparsers(
        dest="action", metavar="<action>", required=True
    )
    p = command(
        actions,
        "create",
        commands.communities_create,
        "create a community with its first community admin, and write its invite file (0600)",
    )
    p.add_argument("--name", required=True)
    p.add_argument(
        "--admin",
        required=True,
        metavar="HANDLE",
        help="the first community admin's handle",
    )
    p.add_argument(
        "--out",
        help="the community admin's invite file; default <community>-<handle>.invite",
    )
    command(actions, "list", commands.communities_list, "list the communities")

    p = command(
        sub,
        "invite",
        commands.invite,
        "write a single-use invite file carrying access roles, which the server applies when "
        "the invitee joins; `invite list --out-dir <dir>` writes every pending invite",
    )
    p.add_argument("--handle")
    p.add_argument("--access", action="append", help=access_help)
    p.add_argument("--community", help="the invitee's community; default the context's")
    p.add_argument("--out", help="the invite file to write (0600)")
    p.add_argument("--hours", type=int)
    actions = p.add_subparsers(dest="action", metavar="list")
    q = actions.add_parser("list", help="write every pending invite as a file")
    q.add_argument("--out-dir", required=True)
    q.add_argument("--community", help="default: the context's community")
    q.add_argument(
        "--server", action="store_true", help="the server-level users' pending invites"
    )

    command(
        sub,
        "access",
        commands.access,
        "the six access roles, and this context's roles and resolved grants (cached in the "
        "context for the tools)",
    )

    for name, func, text in (
        ("assign", commands.assign, "assign access roles to a user or an issued key"),
        (
            "unassign",
            commands.unassign,
            "unassign access roles, or some collections of one: `<role>` ends the "
            "assignment, `<role>:c1` removes c1",
        ),
    ):
        p = command(sub, name, func, text)
        who = p.add_mutually_exclusive_group(required=True)
        who.add_argument("--handle", help="a user")
        who.add_argument("--api-key", help="an issued key's id")
        p.add_argument(
            "--community", help="the user's community; default the context's"
        )
        p.add_argument("--server", action="store_true", help="a server-level user")
        p.add_argument("--access", action="append", required=True, help=access_help)

    users = sub.add_parser("users", help="users: list and remove")
    actions = users.add_subparsers(dest="action", metavar="<action>", required=True)
    p = command(
        actions,
        "list",
        commands.users_list,
        "a community's users, removed ones marked, each with its roles, and the server-level "
        "users (anyone in the community reads them); with --server, the server-level users",
    )
    p.add_argument("--community", help="default: the context's community")
    p.add_argument("--server", action="store_true")
    p = command(
        actions,
        "remove",
        commands.users_remove,
        "remove a user: it stays as a tombstone, its handle retired and its work kept",
    )
    p.add_argument("--handle", required=True)
    p.add_argument("--community", help="default: the context's community")
    p.add_argument("--server", action="store_true", help="a server-level user")

    p = command(
        sub,
        "rebind-key",
        commands.rebind_key,
        "retire a user's keys and write a fresh invite file",
    )
    p.add_argument("--handle", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--hours", type=int)
    p.add_argument("--community", help="default: the context's community")
    p.add_argument("--server", action="store_true", help="a server-level user")

    p = command(
        sub,
        "suspect-after",
        commands.suspect_after,
        "flag a user's writes after an instant",
    )
    p.add_argument("--handle", required=True)
    p.add_argument("--at", required=True, help="ISO 8601, with a timezone")
    p.add_argument("--community", help="default: the context's community")
    p.add_argument("--server", action="store_true", help="a server-level user")

    p = command(
        sub,
        "gen-api-key",
        commands.gen_api_key,
        "issue a key carrying --access roles and write it to a 0600 file in this session's "
        "api-keys/: a member key acts as you, within your grants; with --non-member, a key "
        "of its own for an application, carrying community-observer",
    )
    p.add_argument("label", help="the key's name, unique among your keys")
    p.add_argument("--access", action="append", help=access_help)
    p.add_argument(
        "--non-member",
        action="store_true",
        help="a key for an application: its own identity, reading only",
    )
    p.add_argument("--community", help="default: the context's community")
    p.add_argument("--expires-days", type=int)

    p = command(
        sub,
        "list-api-keys",
        commands.list_api_keys,
        "write the keys you issued, with their roles and values, to a 0600 file in this "
        "session's api-keys/, and print them without values; a `members` holder sees every "
        "key of the community",
    )
    p.add_argument("--community", help="default: the context's community")

    p = command(
        sub,
        "revoke-api-key",
        commands.revoke_api_key,
        "delete a key you issued, or with `members` any key of the community; its next "
        "request answers 401",
    )
    p.add_argument("key_id")
    p.add_argument("--community", help="default: the context's community")

    p = command(sub, "purge", commands.purge, "free one version's content (`manage`)")
    p.add_argument("--cite", required=True, help="symposium-data:<file-id>@v<n>")

    p = command(
        sub, "export", commands.export, "export the community as a tar (`export`)"
    )
    p.add_argument("--out", required=True)

    p = command(
        sub,
        "import",
        commands.import_,
        "create a community from an export, then set the context (`communities`)",
    )
    p.add_argument("--from", dest="from_", required=True)
    p.add_argument("--community-file", required=True)
    p.add_argument(
        "--handle", help="the server-level user, when this machine holds several"
    )

    p = command(
        sub,
        "changes",
        commands.changes,
        "a collection's changes since a cursor: one page, or with --all every page",
    )
    p.add_argument("--collection", required=True)
    p.add_argument("--since", type=int, default=0)
    p.add_argument("--limit", type=int, default=100, help="per page (at most 1000)")
    p.add_argument("--all", action="store_true", help="every page from --since on")

    for name, func, text in (
        ("stat", commands.stat, "a version's metadata"),
        (
            "get",
            commands.get,
            "download a version to a file, checked against its digest",
        ),
    ):
        p = command(sub, name, func, text)
        p.add_argument("ref", help="a citation, or a file id")
        p.add_argument("--version", help="with a file id: n or latest (default)")
        if name == "get":
            p.add_argument("--out", required=True)
            p.add_argument(
                "--api-key-file",
                help="read with an API key file from gen-api-key instead of the context "
                "(needs no context)",
            )
    p = command(sub, "versions", commands.versions, "every version of a file")
    p.add_argument("file_id")

    owner = sub.add_parser("owner", help="this user's identity")
    actions = owner.add_subparsers(dest="action", metavar="<action>", required=True)
    command(
        actions,
        "register",
        commands.owner_register,
        "join with the context's invite and a key made here (idempotent)",
    )
    command(actions, "whoami", commands.owner_whoami, "who the server says this is")
    command(
        actions,
        "pubkey",
        commands.owner_pubkey,
        "this handle's public key and fingerprint",
    )
    command(
        actions,
        "rotate",
        commands.owner_rotate,
        "replace this handle's key; the old one is retired, never deleted",
    )

    p = command(
        sub, "put", commands.put, "create a file from a local file; it becomes v1"
    )
    p.add_argument("file")
    p.add_argument("--collection", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--metadata", type=json_object, help="a JSON object")
    p.add_argument("--content-type")

    p = command(
        sub,
        "version",
        commands.version,
        "add a version: new content, new metadata (alone it reuses the content), or both",
    )
    p.add_argument("file_id")
    p.add_argument(
        "file", nargs="?", help="the new content (omit for a metadata-only version)"
    )
    p.add_argument("--metadata", type=json_object, help="a JSON object")
    p.add_argument("--content-type")
    p.add_argument(
        "--if-match", type=int, metavar="N", help="refuse unless the head is vN"
    )

    p = command(sub, "delete", commands.delete, "delete a file (a tombstone version)")
    p.add_argument("file_id")
    p.add_argument("--reason")

    p = command(
        sub,
        "promote",
        commands.promote,
        "copy a version into a collection as a new file (`gate` into record)",
    )
    p.add_argument("ref", help="symposium-data:<file-id>@v<n>")
    p.add_argument("--collection", required=True)
    p.add_argument("--name")
    p.add_argument("--metadata", type=json_object, help="a JSON object")
    p.add_argument(
        "--stamp-json-pointer", help="where to write the server's clock in the JSON"
    )

    collection = sub.add_parser(
        "collection",
        help="collections; share one read-only with `assign --access community-observer:<c>`",
    )
    actions = collection.add_subparsers(
        dest="action", metavar="<action>", required=True
    )
    command(
        actions,
        "list",
        commands.collection_list,
        "the collections the caller may use, with its read, write and manage access on each",
    )
    p = command(
        actions, "create", commands.collection_create, "create a collection you own"
    )
    p.add_argument("--name", required=True)
    p = command(
        actions,
        "set-public",
        commands.collection_set_public,
        "make a collection you manage readable by anyone, or not",
    )
    p.add_argument("--collection", required=True)
    visibility = p.add_mutually_exclusive_group(required=True)
    visibility.add_argument("--public", dest="public", action="store_true")
    visibility.add_argument("--private", dest="public", action="store_false")

    find = sub.add_parser("find", help="find files and versions")
    actions = find.add_subparsers(dest="action", metavar="<action>", required=True)
    p = command(actions, "name", commands.find_name, "the file holding a name")
    p.add_argument("--collection", required=True)
    p.add_argument("--name", required=True)
    p = command(
        actions,
        "hash",
        commands.find_hash,
        "every version you may read with this content",
    )
    p.add_argument("--sha256", required=True)
    p = command(
        actions,
        "meta",
        commands.find_meta,
        "versions whose metadata contains a JSON object",
    )
    p.add_argument("--collection", required=True)
    p.add_argument("--contains", type=json_object, required=True)
    p.add_argument("--since", type=int, default=0)
    p.add_argument("--limit", type=int, default=100)

    p = command(sub, "verify", commands.verify, "check a citation")
    p.add_argument("--cite", required=True)
    p.add_argument("--before", help="it must be strictly earlier than this instant")
    p.add_argument("--sha256")

    port_ndex.add_command(sub, command, commands, CommandError)  # port-ndex
    return parser


def reference(parser: argparse.ArgumentParser) -> str:
    """reference/COMMANDS.md: every command's usage and help, from the parser itself."""
    lines = [
        "# symposium-data commands",
        "",
        "Generated by `cli.py --reference`. Every command prints one JSON object.",
        "",
    ]

    def walk(p, prefix):
        actions = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        if p is not parser and p.description:
            lines.extend([f"## `{prefix}`", "", p.description, "", "```"])
            lines.append(p.format_usage().strip().replace("usage: ", ""))
            lines.extend(["```", ""])
        for action in actions:
            for name, child in action.choices.items():
                walk(child, f"{prefix} {name}".strip())

    walk(parser, "")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    commands = Commands()
    parser = build_parser(commands)
    try:
        args = parser.parse_args(argv)
        if args.reference:
            path = HERE / "reference" / "COMMANDS.md"
            path.parent.mkdir(exist_ok=True)
            path.write_text(reference(parser))
            result = {"written": str(path)}
        elif not getattr(args, "func", None):
            raise CommandError("name a command", usage=parser.format_usage().strip())
        else:
            result = args.func(args)
    except CommandError as e:
        print(json.dumps(e.report()))
        return 1
    except KeystoreError as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
