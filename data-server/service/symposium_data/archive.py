"""Export and import of one community (R-J6): a tar stream of its rows, as JSON lines, and the
bytes of every payload it stores. For backups and for moving a community to another server.

    manifest.json       format, community, admin handle, counts
    owners.jsonl        every handle the community uses, with its public keys
    roster.jsonl  collections.jsonl  grants.jsonl  files.jsonl  versions.jsonl  read_keys.jsonl
    payloads/<sha256>   each stored payload's bytes, once per sha256

The rows come first, so an import can refuse before any bytes move. Bytes are hashed as they
stream in and stay pending until one transaction writes every row (R-A6); if anything fails,
they are removed again, bytes first and row second.
"""

from __future__ import annotations

import io
import json
import tarfile
import uuid
from datetime import UTC, datetime

import psycopg

from .cleanup import Cleanup
from .records import Records
from .runtime import Database, MultipartWriter, PayloadStore
from .wire import valid_sha256

FORMAT = "symposium-data-export"
FORMAT_VERSION = 1
TABLES = ("owners", "roster", "collections", "grants", "files", "versions", "read_keys")
CHUNK = 1024 * 1024


class Refused(Exception):
    """The import does not fit this server; nothing was written."""


class Malformed(Exception):
    """The stream is not a complete export; nothing was written."""


def encode(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"cannot export {type(value).__name__}")


class Archive:
    def __init__(
        self, db: Database, store: PayloadStore, records: Records, cleanup: Cleanup
    ):
        self.db, self.store, self.records, self.cleanup = db, store, records, cleanup

    def community_exists(self, conn, community: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM collections WHERE community = %s "
            "UNION ALL SELECT 1 FROM roster WHERE community = %s LIMIT 1",
            (community, community),
        ).fetchone()
        return row is not None

    # ── export ──────────────────────────────────────────────────────────────────────────────
    def export(self, community: str, out) -> dict:
        """Write the community to `out` as a tar stream. -> the manifest."""
        with self.db.connection() as conn:
            # one consistent snapshot of every row, however long the bytes take to stream
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            if not self.community_exists(conn, community):
                raise Refused(f"no community '{community}' on this server")
            tables, payloads = self.snapshot(conn, community)
            manifest = {
                "format": FORMAT,
                "format_version": FORMAT_VERSION,
                "community": community,
                "admin": self.records.config(conn, "admin"),
                "counts": {name: len(rows) for name, rows in tables.items()},
                "payloads": len(payloads),
            }
        with tarfile.open(fileobj=out, mode="w|") as tar:
            self.add(tar, "manifest.json", json.dumps(manifest).encode())
            for name in TABLES:
                lines = "".join(
                    json.dumps(row, default=encode) + "\n" for row in tables[name]
                )
                self.add(tar, f"{name}.jsonl", lines.encode())
            for payload in payloads:
                info = tarfile.TarInfo(f"payloads/{payload['sha256']}")
                info.size = payload["size"]
                body = self.store.open_read(payload["s3_key"])["Body"]
                tar.addfile(info, body)
        return manifest

    def add(self, tar, name: str, data: bytes):
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    def snapshot(self, conn, community: str) -> tuple[dict, list]:
        q = conn.execute
        tables = {
            "roster": q(
                "SELECT handle FROM roster WHERE community = %s ORDER BY handle",
                (community,),
            ).fetchall(),
            "collections": q(
                "SELECT name, owner, seq, last_created, public FROM collections "
                "WHERE community = %s ORDER BY name",
                (community,),
            ).fetchall(),
            "grants": q(
                "SELECT collection, handle, perm FROM grants WHERE community = %s "
                "ORDER BY collection, handle, perm",
                (community,),
            ).fetchall(),
            "files": q(
                "SELECT id, collection, name FROM files WHERE community = %s "
                "AND state = 'live' ORDER BY collection, name",
                (community,),
            ).fetchall(),
            # `stored` says whether the bytes travel: a purged payload has none left
            "versions": q(
                "SELECT v.file_id, v.n, v.metadata, v.content_type, v.created, v.seq, "
                "v.created_by, v.key_id, v.deleted, v.reason, v.purged, p.sha256, p.size, "
                "p.first_owner, p.state = 'ready' AS stored "
                "FROM versions v JOIN files f ON f.id = v.file_id "
                "JOIN payloads p ON p.id = v.payload_id "
                "WHERE f.community = %s ORDER BY f.collection, v.seq",
                (community,),
            ).fetchall(),
            "read_keys": q(
                "SELECT id, hash, collection, file_id, label, created_by, created, expires, "
                "revoked, uses, last_used FROM read_keys WHERE community = %s ORDER BY created",
                (community,),
            ).fetchall(),
        }
        handles = sorted(
            {r["handle"] for r in tables["roster"]}
            | {r["owner"] for r in tables["collections"]}
            | {r["handle"] for r in tables["grants"]}
            | {r["created_by"] for r in tables["versions"]}
            | {r["created_by"] for r in tables["read_keys"]}
        )
        owners = q(
            "SELECT handle, reserved, created, suspect_after FROM owners "
            "WHERE handle = ANY(%s) ORDER BY handle",
            (handles,),
        ).fetchall()
        for owner in owners:
            owner["keys"] = q(
                "SELECT kid, jwk, active, created, retired FROM owner_keys "
                "WHERE handle = %s ORDER BY created",
                (owner["handle"],),
            ).fetchall()
        tables["owners"] = owners
        payloads = q(
            "SELECT DISTINCT p.sha256, p.size, p.s3_key FROM versions v "
            "JOIN files f ON f.id = v.file_id JOIN payloads p ON p.id = v.payload_id "
            "WHERE f.community = %s AND p.state = 'ready' ORDER BY p.sha256",
            (community,),
        ).fetchall()
        return tables, payloads

    # ── import ──────────────────────────────────────────────────────────────────────────────
    def import_(self, source) -> dict:
        """Read an export from `source` and write it as one transaction. -> a report with one
        entry per handle. Raises Refused or Malformed, having written nothing."""
        tables, pending = {}, {}
        try:
            try:
                manifest = self.read_stream(source, tables, pending)
            except (tarfile.TarError, EOFError) as e:
                raise Malformed(f"the stream is not a complete tar: {e}") from None
            report, duplicates = self.commit(manifest, tables, pending)
        except BaseException:
            for pid in pending.values():
                self.cleanup.discard_pending(pid)
            raise
        for pid in duplicates:
            self.cleanup.discard_pending(pid)
        return report

    def read_stream(self, source, tables: dict, pending: dict) -> dict:
        """Read every entry: the rows into `tables`, each payload into S3 as a pending
        payload recorded in `pending`. -> the manifest."""
        manifest = None
        with tarfile.open(fileobj=source, mode="r|") as tar:
            for member in tar:
                data = tar.extractfile(member) if member.isfile() else None
                if data is None:
                    raise Malformed(f"unexpected entry {member.name}")
                if member.name == "manifest.json":
                    manifest = self.read_manifest(data.read())
                    with self.db.connection() as conn:
                        self.check_target(conn, manifest)
                elif manifest is None:
                    raise Malformed("the stream does not start with manifest.json")
                elif member.name.endswith(".jsonl") and member.name[:-6] in TABLES:
                    tables[member.name[:-6]] = [
                        json.loads(line) for line in data.read().splitlines()
                    ]
                elif member.name.startswith("payloads/"):
                    self.receive(tables, pending, member, data)
                else:
                    raise Malformed(f"unexpected entry {member.name}")
        if manifest is None or set(tables) != set(TABLES):
            raise Malformed("the stream ends before every table is read")
        missing = self.stored(tables).keys() - pending.keys()
        if missing:
            raise Malformed(f"{len(missing)} payloads are missing from the stream")
        return manifest

    def read_manifest(self, raw: bytes) -> dict:
        try:
            manifest = json.loads(raw)
        except ValueError:
            raise Malformed("manifest.json is not JSON") from None
        if (
            manifest.get("format") != FORMAT
            or manifest.get("format_version") != FORMAT_VERSION
        ):
            raise Malformed(f"not a {FORMAT} v{FORMAT_VERSION} stream")
        return manifest

    def check_target(self, conn, manifest: dict):
        admin = self.records.config(conn, "admin")
        if admin is None:
            raise Refused("the server is not initialized")
        if admin != manifest["admin"]:
            raise Refused(
                f"the export's admin is '{manifest['admin']}' but this server's is "
                f"'{admin}'; initialize with the same admin handle"
            )
        if self.community_exists(conn, manifest["community"]):
            raise Refused(f"community '{manifest['community']}' already exists here")

    def stored(self, tables: dict) -> dict:
        """sha256 -> the version row describing its bytes, for every payload that travels."""
        if "versions" not in tables:
            raise Malformed("payloads arrive before versions.jsonl")
        return {v["sha256"]: v for v in tables["versions"] if v["stored"]}

    def receive(self, tables: dict, pending: dict, member, data):
        """Stream one payload into S3 as a pending payload, checking its sha256 and size."""
        sha = member.name[len("payloads/") :]
        expected = self.stored(tables).get(sha)
        if not valid_sha256(sha) or expected is None or sha in pending:
            raise Malformed(f"unexpected payload {member.name}")
        with self.db.connection() as conn:
            pid, key = self.records.begin_payload(conn, expected["first_owner"])
        pending[sha] = pid

        def started(upload_id):
            with self.db.connection() as conn:
                self.records.note_upload(conn, pid, upload_id)

        writer = MultipartWriter(self.store, key, on_upload_started=started)
        try:
            while chunk := data.read(CHUNK):
                writer.write(chunk)
            if writer.hexdigest() != sha or writer.size != expected["size"]:
                raise Malformed(f"payload {sha} does not match its sha256 or size")
            writer.finish()
        except BaseException:
            writer.abort()
            raise

    def commit(self, manifest: dict, tables: dict, pending: dict) -> tuple[dict, list]:
        community, admin = manifest["community"], manifest["admin"]
        duplicates = []
        try:
            with self.db.connection() as conn:
                self.check_target(conn, manifest)
                handles = [self.reconcile(conn, o, admin) for o in tables["owners"]]
                self.write_rows(conn, community, tables, pending, duplicates)
        except psycopg.errors.UniqueViolation as e:
            raise Refused(
                f"part of the export already exists here: {e.diag.message_detail}"
            ) from None
        counts = {name: len(tables[name]) for name in TABLES if name != "owners"}
        return {"imported": community, **counts, "handles": handles}, duplicates

    def reconcile(self, conn, owner: dict, admin: str) -> dict:
        """Bring one exported handle onto this server (R-J6). This server's identities win:
        a key it already holds stays as it is, and the export adds only history."""
        handle = owner["handle"]
        if handle == admin:
            return {"handle": handle, "result": "admin: this server's keys kept"}
        for key in owner["keys"]:
            row = conn.execute(
                "SELECT handle FROM owner_keys WHERE kid = %s", (key["kid"],)
            ).fetchone()
            if row is not None and row["handle"] != handle:
                raise Refused(
                    f"key {key['kid']} of '{handle}' belongs to '{row['handle']}' here"
                )
        exists = conn.execute(
            "SELECT 1 FROM owners WHERE handle = %s FOR UPDATE", (handle,)
        ).fetchone()
        if exists is None:
            conn.execute(
                "INSERT INTO owners (handle, reserved, created, suspect_after) "
                "VALUES (%s, %s, %s, %s)",
                (handle, owner["reserved"], owner["created"], owner["suspect_after"]),
            )
            for key in owner["keys"]:
                self.add_key(conn, handle, key, key["active"], key["retired"])
            return {"handle": handle, "result": "created"}
        conn.execute(
            "UPDATE owners SET suspect_after = LEAST(suspect_after, %s::timestamptz) "
            "WHERE handle = %s",
            (owner["suspect_after"], handle),
        )
        known = {
            r["kid"]
            for r in conn.execute(
                "SELECT kid FROM owner_keys WHERE handle = %s", (handle,)
            ).fetchall()
        }
        added = [key for key in owner["keys"] if key["kid"] not in known]
        for key in added:
            # retired, so every imported key_id resolves but none can sign in
            self.add_key(conn, handle, key, False, key["retired"] or datetime.now(UTC))
        return {"handle": handle, "result": "keys merged" if added else "unchanged"}

    def add_key(self, conn, handle: str, key: dict, active: bool, retired):
        conn.execute(
            "INSERT INTO owner_keys (kid, handle, jwk, active, created, retired) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                key["kid"],
                handle,
                json.dumps(key["jwk"]),
                active,
                key["created"],
                retired,
            ),
        )

    def write_rows(self, conn, community, tables, pending, duplicates):
        q = conn.execute
        for row in tables["roster"]:
            q(
                "INSERT INTO roster (community, handle) VALUES (%s, %s)",
                (community, row["handle"]),
            )
        for row in tables["collections"]:
            q(
                "INSERT INTO collections (community, name, owner, seq, last_created, public) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    community,
                    row["name"],
                    row["owner"],
                    row["seq"],
                    row["last_created"],
                    row["public"],
                ),
            )
        for row in tables["grants"]:
            q(
                "INSERT INTO grants (community, collection, handle, perm) "
                "VALUES (%s, %s, %s, %s)",
                (community, row["collection"], row["handle"], row["perm"]),
            )
        for row in tables["files"]:
            q(
                "INSERT INTO files (id, community, collection, name) VALUES (%s, %s, %s, %s)",
                (row["id"], community, row["collection"], row["name"]),
            )
        ready, purged = {}, {}
        for sha, version in self.stored(tables).items():
            # the restore is the operator's act: quota (0) does not apply
            ready[sha], duplicate = self.records.commit_payload(
                conn, pending[sha], sha, version["size"], version["first_owner"], 0
            )
            if duplicate:
                duplicates.append(duplicate)
        for v in tables["versions"]:
            if v["stored"]:
                payload = ready[v["sha256"]]
            else:
                payload = purged.get(v["sha256"]) or self.purged_payload(conn, v)
                purged[v["sha256"]] = payload
            q(
                "INSERT INTO versions (file_id, n, payload_id, metadata, content_type, created, "
                "seq, created_by, key_id, deleted, reason, purged) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    v["file_id"],
                    v["n"],
                    payload,
                    json.dumps(v["metadata"]),
                    v["content_type"],
                    v["created"],
                    v["seq"],
                    v["created_by"],
                    v["key_id"],
                    v["deleted"],
                    v["reason"],
                    v["purged"],
                ),
            )
        for row in tables["read_keys"]:
            q(
                "INSERT INTO read_keys (id, hash, community, collection, file_id, label, "
                "created_by, created, expires, revoked, uses, last_used) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    row["id"],
                    row["hash"],
                    community,
                    row["collection"],
                    row["file_id"],
                    row["label"],
                    row["created_by"],
                    row["created"],
                    row["expires"],
                    row["revoked"],
                    row["uses"],
                    row["last_used"],
                ),
            )

    def purged_payload(self, conn, version: dict):
        """A row for content that was purged at the source: its hash and size, no bytes."""
        pid = uuid.uuid4()
        conn.execute(
            "INSERT INTO payloads (id, sha256, size, state, s3_key, first_owner) "
            "VALUES (%s, %s, %s, 'purged', %s, %s)",
            (
                pid,
                version["sha256"],
                version["size"],
                f"payloads/{pid}",
                version["first_owner"],
            ),
        )
        return pid
