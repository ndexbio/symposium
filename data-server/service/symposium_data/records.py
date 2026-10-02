"""The server's records: configuration, identities, rosters, grants, invites, files and versions.

Shared by the HTTP service and data-admin, so every invariant has one implementation.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import psycopg

# Every roster member gets these grants in their community (R-D6).
DEFAULT_GRANTS = (
    ("inbox", "write"),
    ("files", "write"),
    ("files", "read"),
    ("record", "read"),
)


# The collections every community has (Part 4 of the spike): submissions, stored files and the
# accepted record.
COLLECTIONS = ("inbox", "files", "record")


class AlreadyInitialized(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class PreconditionFailed(Exception):
    pass


class QuotaExceeded(Exception):
    pass


def iso(instant: datetime | None) -> str | None:
    return instant.astimezone(UTC).isoformat() if instant else None


class Records:
    def config(self, conn, key):
        row = conn.execute(
            "SELECT v FROM server_config WHERE k = %s", (key,)
        ).fetchone()
        return row["v"] if row else None

    def set_config(self, conn, key, value):
        conn.execute(
            "INSERT INTO server_config (k, v) VALUES (%s, %s) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v",
            (key, value),
        )

    def bind_admin(self, conn, handle: str, kid: str, jwk: dict):
        """Initialize the server: bind the admin handle to its public key. Works exactly once."""
        conn.execute("LOCK TABLE server_config IN EXCLUSIVE MODE")
        current = self.config(conn, "admin")
        if current is not None:
            raise AlreadyInitialized(current)
        conn.execute(
            "INSERT INTO owners (handle) VALUES (%s) ON CONFLICT (handle) DO UPDATE SET reserved = false",
            (handle,),
        )
        conn.execute(
            "INSERT INTO owner_keys (kid, handle, jwk) VALUES (%s, %s, %s)",
            (kid, handle, json.dumps(jwk)),
        )
        self.set_config(conn, "admin", handle)

    # ── identity ────────────────────────────────────────────────────────────────────────────
    def add_challenge(self, conn, handle: str, nonce: str, ttl_seconds: int = 300):
        conn.execute("DELETE FROM challenges WHERE expires < now()")
        conn.execute(
            "INSERT INTO challenges (nonce, handle, expires) VALUES (%s, %s, now() + %s * interval '1 second')",
            (nonce, handle, ttl_seconds),
        )

    def take_challenge(self, conn, handle: str, nonce: str) -> bool:
        """Consume a challenge: true only once, for its own handle, before it expires."""
        row = conn.execute(
            "DELETE FROM challenges WHERE nonce = %s AND handle = %s RETURNING expires > now() AS live",
            (nonce, handle),
        ).fetchone()
        return bool(row and row["live"])

    def active_keys(self, conn, handle: str) -> list:
        return conn.execute(
            "SELECT kid, jwk FROM owner_keys WHERE handle = %s AND active",
            (handle,),
        ).fetchall()

    def key_is_active(self, conn, handle: str, kid: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM owner_keys WHERE handle = %s AND kid = %s AND active",
            (handle, kid),
        ).fetchone()
        return row is not None

    def on_roster(self, conn, community: str, handle: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM roster WHERE community = %s AND handle = %s",
            (community, handle),
        ).fetchone()
        return row is not None

    def set_roster(self, conn, community: str, handles: list) -> tuple[list, list]:
        """Replace a community's roster. New members get the default grants; removed members
        lose every grant in the community but keep their identity and attribution."""
        current = {
            r["handle"]
            for r in conn.execute(
                "SELECT handle FROM roster WHERE community = %s", (community,)
            ).fetchall()
        }
        wanted = set(handles)
        added, removed = sorted(wanted - current), sorted(current - wanted)
        for handle in added:
            conn.execute(
                "INSERT INTO roster (community, handle) VALUES (%s, %s)",
                (community, handle),
            )
            for collection, perm in DEFAULT_GRANTS:
                conn.execute(
                    "INSERT INTO grants (community, collection, handle, perm) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (community, collection, handle, perm),
                )
        for handle in removed:
            conn.execute(
                "DELETE FROM roster WHERE community = %s AND handle = %s",
                (community, handle),
            )
            conn.execute(
                "DELETE FROM grants WHERE community = %s AND handle = %s",
                (community, handle),
            )
        return added, removed

    def grants(self, conn, community: str, handle: str) -> list:
        return [
            (r["collection"], r["perm"])
            for r in conn.execute(
                "SELECT collection, perm FROM grants WHERE community = %s AND handle = %s "
                "ORDER BY collection, perm",
                (community, handle),
            ).fetchall()
        ]

    def add_invite(self, conn, digest: str, community: str, handle: str, hours: int):
        conn.execute(
            "INSERT INTO invites (hash, community, handle, expires) "
            "VALUES (%s, %s, %s, now() + %s * interval '1 hour')",
            (digest, community, handle, hours),
        )

    def consume_invite(self, conn, digest: str, community: str, handle: str) -> bool:
        """Spend an invite: valid only once, for its own handle and community, before expiry."""
        row = conn.execute(
            "UPDATE invites SET used = now() WHERE hash = %s AND community = %s AND handle = %s "
            "AND used IS NULL AND expires > now() RETURNING hash",
            (digest, community, handle),
        ).fetchone()
        return row is not None

    def register(self, conn, handle: str, kid: str, jwk: dict):
        conn.execute(
            "INSERT INTO owners (handle) VALUES (%s) ON CONFLICT (handle) DO UPDATE SET reserved = false",
            (handle,),
        )
        conn.execute(
            "INSERT INTO owner_keys (kid, handle, jwk) VALUES (%s, %s, %s)",
            (kid, handle, json.dumps(jwk)),
        )

    def retire_keys(self, conn, handle: str) -> int:
        """Retire every active key of a handle; retired keys stay on record for attribution."""
        return conn.execute(
            "UPDATE owner_keys SET active = false, retired = now() WHERE handle = %s AND active",
            (handle,),
        ).rowcount

    def rotate(self, conn, handle: str, kid: str, jwk: dict):
        self.retire_keys(conn, handle)
        conn.execute(
            "INSERT INTO owner_keys (kid, handle, jwk) VALUES (%s, %s, %s)",
            (kid, handle, json.dumps(jwk)),
        )

    def owner(self, conn, handle: str):
        return conn.execute(
            "SELECT handle, reserved, suspect_after FROM owners WHERE handle = %s",
            (handle,),
        ).fetchone()

    def set_suspect_after(self, conn, handle: str, instant) -> bool:
        return (
            conn.execute(
                "UPDATE owners SET suspect_after = %s WHERE handle = %s",
                (instant, handle),
            ).rowcount
            == 1
        )

    def communities_of(self, conn, handle: str) -> list:
        return [
            r["community"]
            for r in conn.execute(
                "SELECT community FROM roster WHERE handle = %s ORDER BY community",
                (handle,),
            ).fetchall()
        ]

    # ── collections and the per-collection clock ────────────────────────────────────────────
    def ensure_collections(self, conn, community: str, owner: str):
        for name in COLLECTIONS:
            conn.execute(
                "INSERT INTO collections (community, name, owner) VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (community, name, owner),
            )

    def collection_exists(self, conn, community: str, collection: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM collections WHERE community = %s AND name = %s",
            (community, collection),
        ).fetchone()
        return row is not None

    def allocate(self, conn, community: str, collection: str):
        """-> (seq, created). The collection row's lock serialises writers until commit, so seq
        is gap-free (a rolled-back write takes its increment with it) and created is strictly
        increasing even when the wall clock is not."""
        row = conn.execute(
            "UPDATE collections SET seq = seq + 1, last_created = GREATEST(clock_timestamp(), "
            "COALESCE(last_created, '-infinity'::timestamptz) + interval '1 microsecond') "
            "WHERE community = %s AND name = %s RETURNING seq, last_created",
            (community, collection),
        ).fetchone()
        if row is None:
            raise NotFound(f"no collection {community}/{collection}")
        return row["seq"], row["last_created"]

    # ── authorization over files ────────────────────────────────────────────────────────────
    def is_admin(self, conn, handle: str | None) -> bool:
        return handle is not None and handle == self.config(conn, "admin")

    def has_grant(self, conn, community, collection, handle, perm) -> bool:
        row = conn.execute(
            "SELECT 1 FROM grants WHERE community = %s AND collection = %s AND handle = %s "
            "AND perm = %s",
            (community, collection, handle, perm),
        ).fetchone()
        return row is not None

    def can_create(self, conn, handle, community, collection) -> bool:
        return self.is_admin(conn, handle) or self.has_grant(
            conn, community, collection, handle, "write"
        )

    def can_modify(self, conn, handle, file_row) -> bool:
        """New versions and tombstones: the file's creator (while they still have write on the
        collection) or the admin. Members cannot change each other's files."""
        if self.is_admin(conn, handle):
            return True
        creator = self.first_writer(conn, file_row["id"])
        return creator == handle and self.has_grant(
            conn, file_row["community"], file_row["collection"], handle, "write"
        )

    def can_read(self, conn, handle, row) -> bool:
        if self.is_admin(conn, handle):
            return True
        if self.has_grant(conn, row["community"], row["collection"], handle, "read"):
            return True
        if row["collection"] == "inbox":
            # a submission is readable by its submitter and by the recipients named on it
            return handle == self.first_writer(conn, row["file_id"]) or handle in (
                row["metadata"] or {}
            ).get("recipients", [])
        return False

    # ── payloads ────────────────────────────────────────────────────────────────────────────
    def begin_payload(self, conn, owner: str):
        pid = uuid.uuid4()
        key = f"payloads/{pid}"
        conn.execute(
            "INSERT INTO payloads (id, state, s3_key, first_owner) VALUES (%s, 'pending', %s, %s)",
            (pid, key, owner),
        )
        return pid, key

    def note_upload(self, conn, pid, upload_id: str):
        conn.execute(
            "UPDATE payloads SET upload_id = %s WHERE id = %s", (upload_id, pid)
        )

    def commit_payload(self, conn, pid, sha: str, size: int, owner: str, quota: int):
        """Inside the caller's commit transaction: make a verified pending payload ready, or
        reuse an identical ready one. -> (payload_id, duplicate_pending_id_or_None).

        A duplicate's own row is deliberately left pending: its bytes still exist, and only
        the cleanup after commit removes them, bytes first and row second.

        The owner's row is locked first, so the quota check and the payload it admits are one
        atomic step: concurrent uploads by the same owner cannot jointly exceed the quota."""
        conn.execute("SELECT 1 FROM owners WHERE handle = %s FOR UPDATE", (owner,))
        existing = conn.execute(
            "SELECT id FROM payloads WHERE sha256 = %s AND state = 'ready'", (sha,)
        ).fetchone()
        if existing:
            return existing["id"], pid
        if quota and self.usage(conn, owner) + size > quota:
            raise QuotaExceeded("this upload would exceed the owner's quota")
        try:
            with conn.transaction():
                conn.execute(
                    "UPDATE payloads SET state = 'ready', sha256 = %s, size = %s, upload_id = NULL "
                    "WHERE id = %s AND state = 'pending'",
                    (sha, size, pid),
                )
            return pid, None
        except psycopg.errors.UniqueViolation:
            # an identical payload turned ready concurrently: use that one
            return self.commit_payload(conn, pid, sha, size, owner, quota)

    def touch_pending(self, conn, pid, file_id=None):
        """Heartbeat of an upload in progress: the janitor expires only work that has stopped,
        never a long upload that is still streaming."""
        conn.execute(
            "UPDATE payloads SET created = now() WHERE id = %s AND state = 'pending'",
            (pid,),
        )
        if file_id is not None:
            conn.execute(
                "UPDATE files SET reserved_at = now() WHERE id = %s AND state = 'reserved'",
                (file_id,),
            )

    def pending_payload(self, conn, pid):
        return conn.execute(
            "SELECT id, s3_key, upload_id FROM payloads WHERE id = %s AND state = 'pending'",
            (pid,),
        ).fetchone()

    def expire_pending(self, conn, pid):
        """Its bytes could not be removed now: make the janitor retry on its next pass rather
        than after the full pending TTL."""
        conn.execute(
            "UPDATE payloads SET created = now() - interval '100 years' "
            "WHERE id = %s AND state = 'pending'",
            (pid,),
        )

    def usage(self, conn, owner: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(SUM(size), 0) AS total FROM payloads "
            "WHERE first_owner = %s AND state = 'ready'",
            (owner,),
        ).fetchone()
        return int(row["total"])

    # ── files and versions ──────────────────────────────────────────────────────────────────
    def find_name(self, conn, community, collection, name):
        row = conn.execute(
            "SELECT id FROM files WHERE community = %s AND collection = %s AND name = %s "
            "AND state = 'live'",
            (community, collection, name),
        ).fetchone()
        return row["id"] if row else None

    def reserve_file(self, conn, community, collection, name, by):
        """Reserve a name before any bytes are streamed (committed by the caller at once), so
        a concurrent writer of the same name gets 409 before it uploads anything."""
        fid = uuid.uuid4()
        try:
            conn.execute(
                "INSERT INTO files (id, community, collection, name, state, reserved_by, reserved_at) "
                "VALUES (%s, %s, %s, %s, 'reserved', %s, now())",
                (fid, community, collection, name, by),
            )
        except psycopg.errors.UniqueViolation:
            raise Conflict(
                f"'{name}' already exists in {community}/{collection}"
            ) from None
        return fid

    def claim_reservation(self, conn, fid, by):
        """Inside the commit transaction: lock the reservation and turn the file live."""
        row = conn.execute(
            "UPDATE files SET state = 'live', reserved_by = NULL, reserved_at = NULL "
            "WHERE id = %s AND state = 'reserved' AND reserved_by = %s RETURNING id",
            (fid, by),
        ).fetchone()
        if row is None:
            raise Conflict("the name reservation was lost; try again")

    def release_reservation(self, conn, fid):
        conn.execute("DELETE FROM files WHERE id = %s AND state = 'reserved'", (fid,))

    def stale_reservations(self, conn, older_than_seconds: int) -> list:
        return conn.execute(
            "DELETE FROM files WHERE state = 'reserved' "
            "AND reserved_at < now() - %s * interval '1 second' RETURNING id",
            (older_than_seconds,),
        ).fetchall()

    def file_row(self, conn, file_id):
        row = conn.execute(
            "SELECT * FROM files WHERE id = %s AND state = 'live'", (file_id,)
        ).fetchone()
        if row is None:
            raise NotFound("no such file")
        return row

    def lock_head(self, conn, file_id, expected: int | None) -> dict:
        """Inside a write transaction: lock the file and return its head version. With
        `expected` (from If-Match), refuse if the head has moved: optimistic concurrency."""
        conn.execute(
            "SELECT 1 FROM files WHERE id = %s AND state = 'live' FOR UPDATE",
            (file_id,),
        )
        head = self.latest_version(conn, file_id)
        if head is None:
            raise NotFound("no such file")
        if expected is not None and head["n"] != expected:
            raise PreconditionFailed(
                f"the file is at v{head['n']}, not v{expected}; re-read it and try again"
            )
        return head

    def add_version(
        self,
        conn,
        file_id,
        payload_id,
        metadata,
        content_type,
        by,
        key_id,
        deleted=False,
        reason=None,
    ) -> int:
        f = conn.execute(
            "SELECT community, collection FROM files WHERE id = %s FOR UPDATE",
            (file_id,),
        ).fetchone()
        if f is None:
            raise NotFound("no such file")
        n = conn.execute(
            "SELECT COALESCE(MAX(n), 0) + 1 AS n FROM versions WHERE file_id = %s",
            (file_id,),
        ).fetchone()["n"]
        seq, created = self.allocate(conn, f["community"], f["collection"])
        conn.execute(
            "INSERT INTO versions (file_id, n, payload_id, metadata, content_type, created, seq, "
            "created_by, key_id, deleted, reason) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                file_id,
                n,
                payload_id,
                json.dumps(metadata),
                content_type,
                created,
                seq,
                by,
                key_id,
                deleted,
                reason,
            ),
        )
        return n

    def latest_version(self, conn, file_id):
        """The newest version, tombstone or not (the next version's base)."""
        return conn.execute(
            "SELECT * FROM versions WHERE file_id = %s ORDER BY n DESC LIMIT 1",
            (file_id,),
        ).fetchone()

    def tombstone(self, conn, file_id, by, key_id, reason, expected=None) -> int:
        head = self.lock_head(conn, file_id, expected)
        if head["deleted"]:
            raise Conflict("the file is already deleted")
        return self.add_version(
            conn,
            file_id,
            head["payload_id"],
            head["metadata"],
            head["content_type"],
            by,
            key_id,
            deleted=True,
            reason=reason,
        )

    _VERSION = (
        "SELECT v.*, p.sha256, p.size, p.s3_key, p.state AS payload_state, p.scrub_ok, "
        "f.name, f.community, f.collection, o.suspect_after "
        "FROM versions v JOIN payloads p ON p.id = v.payload_id JOIN files f ON f.id = v.file_id "
        "LEFT JOIN owners o ON o.handle = v.created_by WHERE v.file_id = %s "
    )

    def version(self, conn, file_id, ref):
        """ref: a version number, or 'latest' (the newest version that is not a tombstone)."""
        if ref == "latest":
            row = conn.execute(
                self._VERSION + "AND NOT v.deleted ORDER BY v.n DESC LIMIT 1",
                (file_id,),
            ).fetchone()
        else:
            try:
                n = int(ref)
            except (TypeError, ValueError):
                raise NotFound("a version is a number or 'latest'") from None
            row = conn.execute(self._VERSION + "AND v.n = %s", (file_id, n)).fetchone()
        if row is None:
            raise NotFound("no such version")
        return row

    def first_writer(self, conn, file_id):
        row = conn.execute(
            "SELECT created_by FROM versions WHERE file_id = %s AND n = 1", (file_id,)
        ).fetchone()
        return row["created_by"] if row else None

    def stat(self, conn, row) -> dict:
        head = self.latest_version(conn, row["file_id"])
        live = conn.execute(
            "SELECT MAX(n) AS n FROM versions WHERE file_id = %s AND NOT deleted",
            (row["file_id"],),
        ).fetchone()["n"]
        n = row["n"]
        suspect_after = row["suspect_after"]
        return {
            "citation": f"symposium-data:{row['file_id']}@v{n}",
            "file_id": str(row["file_id"]),
            "name": row["name"],
            "community": row["community"],
            "collection": row["collection"],
            "version": n,
            "prev": n - 1 if n > 1 else None,
            "next": n + 1 if n < head["n"] else None,
            "latest": live,
            "sha256": row["sha256"],
            "size": row["size"],
            "content_type": row["content_type"],
            "created": iso(row["created"]),
            "seq": row["seq"],
            "created_by": row["created_by"],
            "key_id": row["key_id"],
            "deleted": row["deleted"],
            "file_deleted": head["deleted"],
            "reason": row["reason"],
            "purged": row["purged"],
            "suspect": bool(suspect_after and row["created"] > suspect_after),
            "integrity": "ok" if row["scrub_ok"] else "mismatch",
            "metadata": row["metadata"],
        }

    def versions(self, conn, file_id) -> list:
        rows = conn.execute(
            "SELECT n FROM versions WHERE file_id = %s ORDER BY n", (file_id,)
        ).fetchall()
        return [self.stat(conn, self.version(conn, file_id, r["n"])) for r in rows]

    # ── purge, janitor and scrub ────────────────────────────────────────────────────────────
    def purge(self, conn, file_id, n: int):
        """Mark a version purged (R-B3). When no live version uses its payload any more, the
        payload moves to 'purging': the intent to free its bytes is recorded before they are
        touched. -> that payload's id, or None while it is still shared. The rows stay."""
        row = conn.execute(
            "UPDATE versions SET purged = true WHERE file_id = %s AND n = %s RETURNING payload_id",
            (file_id, n),
        ).fetchone()
        if row is None:
            raise NotFound("no such version")
        in_use = conn.execute(
            "SELECT 1 FROM versions WHERE payload_id = %s AND NOT purged",
            (row["payload_id"],),
        ).fetchone()
        if in_use:
            return None
        freed = conn.execute(
            "UPDATE payloads SET state = 'purging' WHERE id = %s AND state = 'ready' RETURNING id",
            (row["payload_id"],),
        ).fetchone()
        return freed["id"] if freed else None

    def purging_payloads(self, conn) -> list:
        return conn.execute(
            "SELECT id FROM payloads WHERE state = 'purging'"
        ).fetchall()

    def purging_payload(self, conn, pid):
        return conn.execute(
            "SELECT id, s3_key FROM payloads WHERE id = %s AND state = 'purging'",
            (pid,),
        ).fetchone()

    def mark_purged(self, conn, pid):
        conn.execute(
            "UPDATE payloads SET state = 'purged' WHERE id = %s AND state = 'purging'",
            (pid,),
        )

    def stale_pending(self, conn, older_than_seconds: int) -> list:
        return conn.execute(
            "SELECT id FROM payloads WHERE state = 'pending' "
            "AND created < now() - %s * interval '1 second'",
            (older_than_seconds,),
        ).fetchall()

    def drop_pending(self, conn, pid):
        conn.execute("DELETE FROM payloads WHERE id = %s AND state = 'pending'", (pid,))

    def scrub_candidates(self, conn, batch: int) -> list:
        return conn.execute(
            "SELECT id, s3_key, sha256 FROM payloads WHERE state = 'ready' "
            "ORDER BY scrubbed_at NULLS FIRST, created LIMIT %s",
            (batch,),
        ).fetchall()

    def record_scrub(self, conn, pid, ok: bool):
        conn.execute(
            "UPDATE payloads SET scrubbed_at = now(), scrub_ok = %s WHERE id = %s",
            (ok, pid),
        )
