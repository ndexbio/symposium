"""symposium-data: the command-line client of a Symposium Data server, and its only client
(R-I1). Every command prints one JSON object on stdout, errors included, and exits non-zero on
an error. Nothing secret is ever printed or taken from the command line (R-I4): keys stay in
the keystore, and invites and read keys move only as files.

Every command but `status`, `admin-config` and `context set` works on the context set in this
directory (R-I3): `./.symposium/context.json`, written by `context set --community-file`
(admins) or `context set --invite-file` (members).
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
from keystore import ADMIN_SCOPE, Keystore, KeystoreError, thumbprint

API_VERSION = "1"
HERE = Path(__file__).resolve().parent
CHUNK = 1 << 20
CITATION = re.compile(r"^symposium-data:([0-9a-fA-F-]{36})@v(\d+)$")
FILE_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
NO_CONTEXT = (
    "no context in this directory: run `/symposium setup --invite-file <file>` (members) or "
    "`/symposium bootstrap --community-file <file>` (admins) first"
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
    """The data-server image this bundle was built for (R-I5), from the build's stamp."""
    try:
        return json.loads((HERE / "compat.json").read_text())["data_server_version"]
    except (OSError, ValueError, KeyError):
        return "development checkout"


def write_secret(path: Path, content: dict):
    """A file only its owner can read (R-E3): an invite or a read key. Never printed."""
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
    community route is `/v1/{community}/…` without naming it again; the server-wide calls
    (`status`, `communities`, the admin's sign-in, import) are here too."""

    def __init__(self, base_url: str, community: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.community = community
        self.token = None
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
    ):
        """-> the parsed JSON body, or the open response when `stream`."""
        if not self.checked:
            self.check_api()
        headers = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
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
                f"{detail}. Run `/symposium admin-config` and place the admin key file as it "
                "prints, then restart the server",
                501,
            )
        if error.code == 410 and isinstance(body, dict):
            metadata = {k: v for k, v in body.items() if k != "detail"}
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

    def c(self, path: str) -> str:
        if not self.community:
            raise CommandError(NO_CONTEXT)
        return f"/v1/{urllib.parse.quote(self.community)}{path}"

    # ── sign-in ────────────────────────────────────────────────────────────────────────────
    def sign_in_admin(self, keystore: Keystore, handle: str):
        nonce = self.request("POST", "/v1/admin/challenge", auth=False)["nonce"]
        signature = keystore.sign(ADMIN_SCOPE, handle, nonce.encode())
        self.token = self.request(
            "POST",
            "/v1/admin/token",
            body={"nonce": nonce, "signature": signature},
            auth=False,
        )["token"]

    def sign_in_member(self, keystore: Keystore, handle: str):
        nonce = self.request(
            "POST", self.c("/auth/challenge"), body={"handle": handle}, auth=False
        )["nonce"]
        signature = keystore.sign(self.community, handle, nonce.encode())
        self.token = self.request(
            "POST",
            self.c("/auth/token"),
            body={"handle": handle, "nonce": nonce, "signature": signature},
            auth=False,
        )["token"]

    # ── server-wide ────────────────────────────────────────────────────────────────────────
    def communities(self) -> dict:
        return self.request("GET", "/v1/communities")

    def create_community(self, name: str) -> dict:
        return self.request("POST", "/v1/communities", body={"name": name})

    def import_community(self, path: Path) -> dict:
        with open(path, "rb") as source:
            return self.request(
                "POST",
                "/v1/communities/import",
                data=source,
                headers={
                    "Content-Type": "application/x-tar",
                    "Content-Length": str(path.stat().st_size),
                },
            )

    # ── the community's roster, invites and members ────────────────────────────────────────
    def roster(self) -> dict:
        return self.request("GET", self.c("/roster"))

    def add_to_roster(self, handle: str) -> dict:
        return self.request("POST", self.c(f"/roster/{handle}"))

    def remove_from_roster(self, handle: str) -> dict:
        return self.request("DELETE", self.c(f"/roster/{handle}"))

    def invite(self, handle: str, hours: int | None) -> dict:
        body = (
            {"handle": handle} if hours is None else {"handle": handle, "hours": hours}
        )
        return self.request("POST", self.c("/invites"), body=body)

    def pending_invites(self) -> dict:
        return self.request("GET", self.c("/invites"))

    def rebind(self, handle: str, hours: int | None) -> dict:
        body = {} if hours is None else {"hours": hours}
        return self.request("POST", self.c(f"/owners/{handle}/rebind"), body=body)

    def suspect_after(self, handle: str, at: str) -> dict:
        return self.request(
            "PUT", self.c(f"/owners/{handle}/suspect-after"), body={"at": at}
        )

    # ── the Symposium API's keys: server-wide, the admin's Ed25519 token alone ──────────────
    def create_api_key(self, body: dict) -> dict:
        return self.request("POST", "/api/v1/admin/api-keys", body=body)

    def api_keys(self, community: str | None) -> list:
        """Every API key, page by page, each with its value."""
        items, cursor = [], None
        while True:
            query = {"limit": "1000"}
            if community:
                query["community"] = community
            if cursor:
                query["cursor"] = cursor
            page = self.request(
                "GET", "/api/v1/admin/api-keys?" + urllib.parse.urlencode(query)
            )
            items += page["items"]
            cursor = page.get("next")
            if not cursor:
                return items

    def revoke_api_key(self, key_id: str) -> dict:
        return self.request(
            "DELETE", f"/api/v1/admin/api-keys/{urllib.parse.quote(key_id)}"
        )

    def challenge(self, handle: str) -> str:
        return self.request(
            "POST", self.c("/auth/challenge"), body={"handle": handle}, auth=False
        )["nonce"]

    def register(self, handle: str, jwk: dict, nonce: str, signature: str, invite: str):
        return self.request(
            "POST",
            self.c("/owners"),
            body={
                "handle": handle,
                "public_jwk": jwk,
                "nonce": nonce,
                "signature": signature,
                "invite": invite,
            },
            auth=False,
        )

    def rotate(self, handle: str, jwk: dict, nonce: str, signature: str) -> dict:
        return self.request(
            "POST",
            self.c(f"/owners/{handle}/keys"),
            body={"public_jwk": jwk, "nonce": nonce, "signature": signature},
        )

    def whoami(self) -> dict:
        return self.request("GET", self.c("/whoami"))

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
        return self.upload("PUT", path, source, headers)

    def add_version(self, file_id: str, source: Path | None, headers: dict) -> dict:
        return self.upload(
            "POST", self.c(f"/files/{file_id}/versions"), source, headers
        )

    def delete(self, file_id: str, reason: str | None) -> dict:
        query = "?" + urllib.parse.urlencode({"reason": reason}) if reason else ""
        return self.request("DELETE", self.c(f"/files/{file_id}{query}"))

    def promote(self, file_id: str, n: str, body: dict) -> dict:
        return self.request(
            "POST", self.c(f"/files/{file_id}/v/{n}/promote"), body=body
        )

    def find(self, collection: str, name: str) -> dict:
        query = urllib.parse.urlencode({"name": name})
        return self.request("GET", self.c(f"/collections/{collection}/find?{query}"))

    def by_hash(self, sha256: str) -> dict:
        return self.request("GET", self.c(f"/sha256/{sha256}"))

    def query(self, collection: str, contains: dict, since: int, limit: int) -> dict:
        return self.request(
            "POST",
            self.c(f"/collections/{collection}/query"),
            body={"contains": contains, "since": since, "limit": limit},
        )

    def verify(self, cite: str, before: str | None, sha256: str | None) -> dict:
        params = {"cite": cite}
        params.update({k: v for k, v in (("before", before), ("sha256", sha256)) if v})
        return self.request("GET", self.c("/verify?" + urllib.parse.urlencode(params)))

    # ── collections and read keys ──────────────────────────────────────────────────────────
    def create_collection(self, name: str) -> dict:
        return self.request("POST", self.c("/collections"), body={"name": name})

    def grant_write(self, collection: str, handle: str) -> dict:
        return self.request(
            "PUT",
            self.c(f"/collections/{collection}/grants"),
            body={"handle": handle, "perm": "write"},
        )

    def set_public(self, collection: str, public: bool) -> dict:
        return self.request(
            "PUT", self.c(f"/collections/{collection}/public"), body={"public": public}
        )

    def mint_key(self, collection: str, body: dict) -> dict:
        return self.request(
            "POST", self.c(f"/collections/{collection}/keys"), body=body
        )

    def keys(self, collection: str) -> dict:
        return self.request("GET", self.c(f"/collections/{collection}/keys"))

    def revoke_key(self, key_id: str) -> dict:
        return self.request("DELETE", self.c(f"/keys/{key_id}"))

    def purge(self, file_id: str, n: str) -> dict:
        return self.request("POST", self.c(f"/files/{file_id}/v/{n}/purge"))

    def stat(self, file_id: str, ref: str) -> dict:
        return self.request("GET", self.c(f"/files/{file_id}/v/{ref}/stat"))

    def versions(self, file_id: str) -> dict:
        return self.request("GET", self.c(f"/files/{file_id}/versions"))

    def content(self, file_id: str, ref: str):
        return self.request("GET", self.c(f"/files/{file_id}/v/{ref}"), stream=True)

    def changes(self, collection: str, since: int, limit: int) -> dict:
        query = urllib.parse.urlencode({"since": since, "limit": limit})
        return self.request("GET", self.c(f"/collections/{collection}/changes?{query}"))

    def export(self):
        return self.request("GET", self.c("/export"), stream=True)

    # ── the port (R-M1) ────────────────────────────────────────────────────────────────────
    def start_port(self, body: dict) -> dict:  # port-ndex
        return self.request("POST", self.c("/port-ndex"), body=body)

    def port(self, port_id: str) -> dict:  # port-ndex
        return self.request("GET", self.c(f"/port-ndex/{port_id}"))


class Context:
    """`./.symposium/context.json`: the community, the data-server URL and the handle this
    directory works as (R-I3). It holds no secret: a member's invite stays in its file."""

    PATH = Path(".symposium") / "context.json"

    def load(self) -> dict:
        if not self.PATH.exists():
            raise CommandError(NO_CONTEXT)
        return json.loads(self.PATH.read_text())

    def save(self, context: dict):
        self.PATH.parent.mkdir(exist_ok=True)
        self.PATH.write_text(json.dumps(context, indent=2) + "\n")


class Commands:
    def __init__(self):
        self.context = Context()

    # ── shared ─────────────────────────────────────────────────────────────────────────────
    def server_for(self, url: str, community: str | None = None) -> DataServer:
        return DataServer(url, community)

    def keystore(self, server_id: str) -> Keystore:
        return Keystore(server_id)

    def signed_in(self, context: dict | None = None) -> DataServer:
        """A client for the context's community, signed in as the context's handle."""
        context = context or self.context.load()
        server = self.server_for(context["data-server-url"], context["community"])
        keystore = self.keystore(context["server_id"])
        if context["role"] == "admin":
            server.sign_in_admin(keystore, context["handle"])
        else:
            server.sign_in_member(keystore, context["handle"])
        return server

    def admin(self) -> DataServer:
        context = self.context.load()
        if context["role"] != "admin":
            raise CommandError(
                f"this is an admin command, but this directory's context is the member "
                f"'{context['handle']}': run it where `/symposium bootstrap` set the context"
            )
        return self.signed_in(context)

    def admin_handle(self, server_id: str, url: str) -> str:
        handles = self.keystore(server_id).handles(ADMIN_SCOPE)
        if not handles:
            raise CommandError(
                f"this machine holds no admin key for the data server at {url}: run "
                "`/symposium admin-config --handle <admin> --data-server-url <url>` first"
            )
        return handles[0]

    # ── status and context ─────────────────────────────────────────────────────────────────
    def status(self, args) -> dict:
        url = args.data_server_url or self.context.load()["data-server-url"]
        return self.server_for(url).status()

    def context_set(self, args) -> dict:
        if args.community_file:
            spec = read_json_file(args.community_file, "community file")
            community, url = spec.get("community"), spec.get("data-server-url")
            if not community or not url:
                raise CommandError(
                    f"{args.community_file} needs `community` and `data-server-url`"
                )
            status = self.server_for(url).status()
            handle = self.admin_handle(status["server_id"], url)
            role = "admin"
            extra = {}
        else:
            invite = read_json_file(args.invite_file, "invite file")
            missing = [
                k
                for k in ("invite", "handle", "community", "data-server-url")
                if not invite.get(k)
            ]
            if missing:
                raise CommandError(f"{args.invite_file} lacks {', '.join(missing)}")
            community, url, handle = (
                invite["community"],
                invite["data-server-url"],
                invite["handle"],
            )
            status = self.server_for(url).status()
            role = "member"
            extra = {"invite_file": str(Path(args.invite_file).resolve())}
        context = {
            "community": community,
            "data-server-url": url.rstrip("/"),
            "handle": handle,
            "role": role,
            "server_id": status["server_id"],
            **extra,
        }
        self.context.save(context)
        return {"context": context}

    def context_show(self, _args) -> dict:
        return {"context": self.context.load()}

    # ── the server admin ───────────────────────────────────────────────────────────────────
    def admin_config(self, args) -> dict:
        """Manage the server-wide admin key (R-D4): idempotent; a key pair is generated only
        when this machine holds none for the server, or with --new-key."""
        url = args.data_server_url.rstrip("/")
        server_id = self.server_for(url).status()["server_id"]
        keystore = self.keystore(server_id)
        held = keystore.handles(ADMIN_SCOPE)
        if held and held[0] != args.handle:
            raise CommandError(
                f"this machine holds the admin key of '{held[0]}' for this server, and the "
                "admin's handle never changes: run admin-config with that handle"
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
        out = {
            "handle": args.handle,
            "server_id": server_id,
            "fingerprint": thumbprint(jwk),
            "public_key_file": str(key_file),
            "created": created,
            "steps": [
                f"place {key_file} on the server: for a local container, copy it into "
                "the directory of your machine mounted on /apps (`cp "
                f"{key_file} <that directory>/`), or `docker cp {key_file} "
                "<container>:/apps/`; on Kubernetes, `kubectl create secret generic "
                f"symposium-data-admin-key --from-file={key_file}` "
                "(k8s-data-deployment.yml mounts it in /apps/admin-key/)",
                "restart the server (`docker restart <container>`, or `kubectl rollout "
                "restart deploy/symposium-data`)",
                f"check that GET {url}/v1/status reports this fingerprint, then run "
                "`/symposium bootstrap`",
            ],
        }
        if args.new_key and held:
            out["warning"] = (
                "a new key: placing this file rebinds the server's admin, and the old key is "
                "refused from then on"
            )
        return out

    def communities_create(self, args) -> dict:
        return self.admin().create_community(args.name)

    def communities_list(self, _args) -> dict:
        return self.admin().communities()

    def roster_list(self, _args) -> dict:
        """Every handle on the roster, registered or not yet: any member may read it."""
        return self.signed_in().roster()

    def roster_add(self, args) -> dict:
        return self.admin().add_to_roster(args.handle)

    def roster_remove(self, args) -> dict:
        return self.admin().remove_from_roster(args.handle)

    def invite_file(self, server: DataServer, issued: dict) -> dict:
        return {
            "invite": issued["invite"],
            "handle": issued["handle"],
            "community": issued["community"],
            "data-server-url": server.base_url,
        }

    def invite(self, args) -> dict:
        if args.action == "list":
            return self.invite_list(args)
        if not args.handle or not args.out:
            raise CommandError(
                "invite needs --handle and --out (or: invite list --out-dir)"
            )
        server = self.admin()
        issued = server.invite(args.handle, args.hours)
        write_secret(Path(args.out), self.invite_file(server, issued))
        return {
            "community": issued["community"],
            "handle": issued["handle"],
            "expires": issued["expires"],
            "invite_file": str(Path(args.out).resolve()),
        }

    def invite_list(self, args) -> dict:
        """Every pending invite as `<community>-<handle>.invite` (0600) in --out-dir; only
        the paths are printed, because invites are secrets."""
        server = self.admin()
        pending = server.pending_invites()
        directory = Path(args.out_dir)
        written = []
        for item in pending["invites"]:
            path = directory / f"{pending['community']}-{item['handle']}.invite"
            write_secret(
                path,
                self.invite_file(server, {**item, "community": pending["community"]}),
            )
            written.append(
                {
                    "handle": item["handle"],
                    "expires": item["expires"],
                    "invite_file": str(path.resolve()),
                }
            )
        return {"community": pending["community"], "invites": written}

    def rebind_key(self, args) -> dict:
        server = self.admin()
        issued = server.rebind(args.handle, args.hours)
        write_secret(Path(args.out), self.invite_file(server, issued))
        return {
            "community": issued["community"],
            "handle": issued["handle"],
            "retired_keys": issued["retired_keys"],
            "expires": issued["expires"],
            "invite_file": str(Path(args.out).resolve()),
        }

    def suspect_after(self, args) -> dict:
        return self.admin().suspect_after(args.handle, args.at)

    # ── API keys (api/DESIGN.md §4.5): values move as 0600 files, never on stdout ───────────
    @staticmethod
    def api_key_dir() -> Path:
        return Path.home() / ".symposium" / "admin" / "api-keys"

    @staticmethod
    def api_key_view(item: dict) -> dict:
        """A key as printed: everything but its value."""
        return {k: v for k, v in item.items() if k != "key"}

    def gen_api_key(self, args) -> dict:
        context = self.context.load()
        server = self.admin()
        scope = (
            {"kind": "server"}
            if args.server
            else {
                "kind": "community",
                "community": args.community or context["community"],
            }
        )
        body = {"username": args.username, "role": args.role, "scope": scope}
        if args.expires_days:
            body["expires_days"] = args.expires_days
        if args.label:
            body["label"] = args.label
        issued = server.create_api_key(body)
        path = self.api_key_dir() / f"{issued['id']}.key"
        write_secret(
            path,
            {
                **issued,
                "data-server-url": server.base_url,
                "api": server.base_url + "/api/v1",
            },
        )
        return {**self.api_key_view(issued), "key_file": str(path.resolve())}

    def list_api_keys(self, args) -> dict:
        server = self.admin()
        items = server.api_keys(args.community)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.api_key_dir() / f"list-{stamp}.json"
        write_secret(path, {"data-server-url": server.base_url, "keys": items})
        return {
            "keys": [self.api_key_view(item) for item in items],
            "keys_file": str(path.resolve()),
        }

    def revoke_api_key(self, args) -> dict:
        return self.api_key_view(self.admin().revoke_api_key(args.key_id))

    def purge(self, args) -> dict:
        cited = CITATION.match(args.cite)
        if not cited:
            raise CommandError("--cite takes a citation: symposium-data:<file-id>@v<n>")
        return self.admin().purge(cited.group(1), cited.group(2))

    def export(self, args) -> dict:
        server = self.admin()
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
        """Create the exported community on this server (R-J6), then set the context."""
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
        context = {
            "community": exported,
            "data-server-url": url.rstrip("/"),
            "handle": self.admin_handle(status["server_id"], url),
            "role": "admin",
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

    # ── a member's identity ────────────────────────────────────────────────────────────────
    def member_context(self) -> dict:
        context = self.context.load()
        if context["role"] != "member":
            raise CommandError(
                "this is a member's command: set the context from an invite file "
                "(`/symposium setup --invite-file <file>`)"
            )
        return context

    def owner_register(self, _args) -> dict:
        """Register this handle with a key made on this machine (R-D1, R-D5). Idempotent: a
        handle already registered with this machine's key is reported, not registered again."""
        context = self.member_context()
        community, handle = context["community"], context["handle"]
        keystore = self.keystore(context["server_id"])
        server = self.server_for(context["data-server-url"], community)
        out = {"community": community, "handle": handle}
        if keystore.exists(community, handle):
            try:
                server.sign_in_member(keystore, handle)
                jwk = keystore.public_jwk(community, handle)
                return {**out, "registered": False, "fingerprint": thumbprint(jwk)}
            except CommandError as e:
                if e.status != 401:
                    raise  # 401: this key is not (or no longer) registered; register anew
        invite = read_json_file(context["invite_file"], "invite file").get("invite")
        jwk = keystore.stage(community, handle)
        try:
            nonce = server.challenge(handle)
            signature = keystore.sign_staged(community, handle, nonce.encode())
            server.register(handle, jwk, nonce, signature, invite)
        except CommandError as e:
            keystore.discard(community, handle)
            if e.status == 409:
                raise CommandError(
                    f"'{handle}' is already registered in {community} with another key: ask "
                    "the admin for `/symposium rebind-key`, then set up with its invite",
                    409,
                ) from None
            raise
        keystore.commit(community, handle)
        return {**out, "registered": True, "fingerprint": thumbprint(jwk)}

    def owner_whoami(self, _args) -> dict:
        return self.signed_in().whoami()

    def owner_pubkey(self, _args) -> dict:
        context = self.context.load()
        scope = ADMIN_SCOPE if context["role"] == "admin" else context["community"]
        jwk = self.keystore(context["server_id"]).public_jwk(scope, context["handle"])
        return {
            "handle": context["handle"],
            "public_jwk": jwk,
            "fingerprint": thumbprint(jwk),
        }

    def owner_rotate(self, _args) -> dict:
        """A new key for this handle, proven by the new key and authorized by the current one;
        the current key is replaced only once the server has accepted the new one."""
        context = self.member_context()
        community, handle = context["community"], context["handle"]
        keystore = self.keystore(context["server_id"])
        server = self.signed_in(context)
        jwk = keystore.stage(community, handle)
        try:
            nonce = server.challenge(handle)
            signature = keystore.sign_staged(community, handle, nonce.encode())
            rotated = server.rotate(handle, jwk, nonce, signature)
        except CommandError:
            keystore.discard(community, handle)
            raise
        keystore.commit(community, handle)
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
        body = {"collection": args.collection}
        for key, value in (
            ("name", args.name),
            ("metadata", args.metadata),
            ("stamp_json_pointer", args.stamp_json_pointer),
        ):
            if value is not None:
                body[key] = value
        return self.admin().promote(file_id, n, body)

    # ── collections and read keys ──────────────────────────────────────────────────────────
    def collection_create(self, args) -> dict:
        return self.signed_in().create_collection(args.name)

    def collection_grant_write(self, args) -> dict:
        return self.signed_in().grant_write(args.collection, args.handle)

    def collection_set_public(self, args) -> dict:
        return self.signed_in().set_public(args.collection, args.public)

    def keys_mint(self, args) -> dict:
        """A read key for a non-member (R-E2), written to a file (0600) with its scope, the
        community and the server's URL, so it reads with no context. Never printed."""
        context = self.context.load()
        body = {"label": args.label}
        if args.file_id:
            body["file_id"] = parse_ref(args.file_id, None)[0]
        if args.hours:
            body["expires_hours"] = args.hours
        minted = self.signed_in(context).mint_key(args.collection, body)
        secret = minted.pop("key")
        write_secret(
            Path(args.out),
            {
                "key": secret,
                "scope": {
                    "collection": minted["collection"],
                    "file_id": minted["file_id"],
                },
                "community": context["community"],
                "data-server-url": context["data-server-url"],
            },
        )
        return {**minted, "read_key_file": str(Path(args.out).resolve())}

    def keys_list(self, args) -> dict:
        return self.signed_in().keys(args.collection)

    def keys_revoke(self, args) -> dict:
        return self.signed_in().revoke_key(args.key_id)

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
        return self.signed_in().verify(args.cite, args.before, args.sha256)

    def changes(self, args) -> dict:
        server = self.signed_in()
        page = server.changes(args.collection, args.since, args.limit)
        if not args.all:
            return page
        # every page from --since on, as one object; never silently capped (R-G3)
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
        if args.read_key_file:
            server = self.with_read_key(args.read_key_file)
        else:
            server = self.signed_in()
        return self.download(server.content(file_id, ref), Path(args.out))

    def with_read_key(self, path) -> DataServer:
        """A client that reads with a read key file, with no context (R-E3)."""
        key = read_json_file(path, "read key file")
        missing = [k for k in ("key", "community", "data-server-url") if not key.get(k)]
        if missing:
            raise CommandError(f"{path} lacks {', '.join(missing)}")
        server = self.server_for(key["data-server-url"], key["community"])
        server.token = key["key"]
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

    context = sub.add_parser("context", help="this directory's context (R-I3)")
    actions = context.add_subparsers(dest="action", metavar="<action>", required=True)
    p = command(actions, "set", commands.context_set, "set the context from a file")
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--community-file", help="community.json (admins)")
    which.add_argument("--invite-file", help="an invite file (members)")
    command(actions, "show", commands.context_show, "print the context")

    p = command(
        sub,
        "admin-config",
        commands.admin_config,
        "manage this server's admin key (R-D4)",
    )
    p.add_argument("--handle", required=True)
    p.add_argument("--data-server-url", required=True)
    p.add_argument(
        "--new-key",
        action="store_true",
        help="replace the key: placing the new file rebinds the server's admin",
    )

    communities = sub.add_parser("communities", help="the server's communities (admin)")
    actions = communities.add_subparsers(
        dest="action", metavar="<action>", required=True
    )
    p = command(actions, "create", commands.communities_create, "create a community")
    p.add_argument("--name", required=True)
    command(actions, "list", commands.communities_list, "list the communities")

    roster = sub.add_parser(
        "roster",
        help="the community's roster: any member lists it, the admin changes it",
    )
    actions = roster.add_subparsers(dest="action", metavar="<action>", required=True)
    command(
        actions,
        "list",
        commands.roster_list,
        "every handle on the roster, registered or not yet (any member)",
    )
    for name, func, text in (
        ("add", commands.roster_add, "add a handle (admin)"),
        ("remove", commands.roster_remove, "remove a handle (admin)"),
    ):
        command(actions, name, func, text).add_argument("--handle", required=True)

    p = command(
        sub,
        "invite",
        commands.invite,
        "write a single-use invite file for a roster handle (admin); "
        "`invite list --out-dir <dir>` writes every pending invite",
    )
    p.add_argument("--handle")
    p.add_argument("--out", help="the invite file to write (0600)")
    p.add_argument("--hours", type=int)
    actions = p.add_subparsers(dest="action", metavar="list")
    q = actions.add_parser("list", help="write every pending invite as a file (admin)")
    q.add_argument("--out-dir", required=True)

    p = command(
        sub,
        "rebind-key",
        commands.rebind_key,
        "retire a member's keys and write a fresh invite file (admin)",
    )
    p.add_argument("--handle", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--hours", type=int)

    p = command(
        sub,
        "suspect-after",
        commands.suspect_after,
        "flag a member's writes after an instant (admin)",
    )
    p.add_argument("--handle", required=True)
    p.add_argument("--at", required=True, help="ISO 8601, with a timezone")

    p = command(
        sub,
        "gen-api-key",
        commands.gen_api_key,
        "create a Symposium API key and write it to a 0600 file under "
        "~/.symposium/admin/api-keys/ (admin)",
    )
    p.add_argument("username", help="a registered handle, the admin, or an app label")
    p.add_argument("role", choices=("non-member", "member", "admin"))
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--community", help="default: the context's community")
    scope.add_argument(
        "--server", action="store_true", help="scope the key to the server (admin role)"
    )
    p.add_argument("--expires-days", type=int)
    p.add_argument("--label")

    p = command(
        sub,
        "list-api-keys",
        commands.list_api_keys,
        "write every API key, with its value, to a 0600 file under "
        "~/.symposium/admin/api-keys/; print the keys without values (admin)",
    )
    p.add_argument("--community", help="only keys scoped to this community")

    p = command(
        sub, "revoke-api-key", commands.revoke_api_key, "revoke an API key (admin)"
    )
    p.add_argument("key_id")

    p = command(sub, "purge", commands.purge, "free one version's content (admin)")
    p.add_argument("--cite", required=True, help="symposium-data:<file-id>@v<n>")

    p = command(sub, "export", commands.export, "export the community as a tar (admin)")
    p.add_argument("--out", required=True)

    p = command(
        sub,
        "import",
        commands.import_,
        "create a community from an export, then set the context (admin)",
    )
    p.add_argument("--from", dest="from_", required=True)
    p.add_argument("--community-file", required=True)

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
                "--read-key-file",
                help="read with a read key file instead of the context (needs no context)",
            )
    p = command(sub, "versions", commands.versions, "every version of a file")
    p.add_argument("file_id")

    owner = sub.add_parser("owner", help="this member's identity")
    actions = owner.add_subparsers(dest="action", metavar="<action>", required=True)
    command(
        actions,
        "register",
        commands.owner_register,
        "register with the context's invite and a key made here (idempotent)",
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
        "copy a version into a collection as a new file (admin)",
    )
    p.add_argument("ref", help="symposium-data:<file-id>@v<n>")
    p.add_argument("--collection", required=True)
    p.add_argument("--name")
    p.add_argument("--metadata", type=json_object, help="a JSON object")
    p.add_argument(
        "--stamp-json-pointer", help="where to write the server's clock in the JSON"
    )

    collection = sub.add_parser("collection", help="collections and their sharing")
    actions = collection.add_subparsers(
        dest="action", metavar="<action>", required=True
    )
    p = command(
        actions, "create", commands.collection_create, "create a collection you own"
    )
    p.add_argument("--name", required=True)
    p = command(
        actions,
        "grant-write",
        commands.collection_grant_write,
        "let a roster member write to your collection",
    )
    p.add_argument("--collection", required=True)
    p.add_argument("--handle", required=True)
    p = command(
        actions,
        "set-public",
        commands.collection_set_public,
        "make your collection readable by anyone, or not",
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

    p = command(sub, "verify", commands.verify, "check a citation (R-G9)")
    p.add_argument("--cite", required=True)
    p.add_argument("--before", help="it must be strictly earlier than this instant")
    p.add_argument("--sha256")

    keys = sub.add_parser("keys", help="read keys for non-members (R-E2)")
    actions = keys.add_subparsers(dest="action", metavar="<action>", required=True)
    p = command(
        actions,
        "mint",
        commands.keys_mint,
        "mint a read key into a file (0600); it is never printed",
    )
    p.add_argument("--collection", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--file-id", help="scope it to one file")
    p.add_argument("--hours", type=int, help="expire after this many hours")
    p.add_argument("--out", required=True)
    p = command(
        actions,
        "list",
        commands.keys_list,
        "a collection's read keys, never their secret",
    )
    p.add_argument("--collection", required=True)
    p = command(actions, "revoke", commands.keys_revoke, "revoke a read key at once")
    p.add_argument("key_id")

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
