"""The server's records: configuration, communities, identities, rosters, grants, invites, files
and versions. Every community-dependent record is scoped by its community (R-G8).

Used by the HTTP service, its jobs, export and import, and the port, so every invariant has one
implementation.
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


# The collections every community has: submissions, stored files and the
# accepted record.
COLLECTIONS = ("inbox", "files", "record")


class AlreadyInitialized(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Forbidden(Exception):
    pass


class PreconditionFailed(Exception):
    pass


class QuotaExceeded(Exception):
    pass


def unpurged(file_id_sql: str) -> str:
    """A SQL condition, true while every version of the file `file_id_sql` names keeps its
    content: the purge model is this module's, so other packages filter through it."""
    return f"NOT EXISTS (SELECT 1 FROM versions v WHERE v.file_id = {file_id_sql} AND v.purged)"


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
        """Initialize the server: bind the admin handle to its public key. Works exactly once.
        The admin is server-wide, so its keys live in admin_keys, not in any community."""
        conn.execute("LOCK TABLE server_config IN EXCLUSIVE MODE")
        current = self.config(conn, "admin")
        if current is not None:
            raise AlreadyInitialized(current)
        conn.execute(
            "INSERT INTO admin_keys (kid, handle, jwk) VALUES (%s, %s, %s)",
            (kid, handle, json.dumps(jwk)),
        )
        self.set_config(conn, "admin", handle)

    def rebind_admin(self, conn, handle: str, kid: str, jwk: dict):
        """Make `kid` the admin's only active key; the old keys are retired, never deleted. A
        key that was the admin's before becomes active again."""
        conn.execute(
            "UPDATE admin_keys SET active = false, retired = now() "
            "WHERE active AND kid <> %s",
            (kid,),
        )
        conn.execute(
            "INSERT INTO admin_keys (kid, handle, jwk) VALUES (%s, %s, %s) "
            "ON CONFLICT (kid) DO UPDATE SET active = true, retired = NULL",
            (kid, handle, json.dumps(jwk)),
        )

    def admin_keys(self, conn) -> list:
        return conn.execute("SELECT kid, jwk FROM admin_keys WHERE active").fetchall()

    def admin_key_is_active(self, conn, kid: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM admin_keys WHERE kid = %s AND active", (kid,)
        ).fetchone()
        return row is not None

    # ── communities ─────────────────────────────────────────────────────────────────────────
    def community_name(self, conn, name: str) -> str | None:
        """The community's name as it was created, matching `name` ignoring case."""
        row = conn.execute(
            "SELECT name FROM communities WHERE lower(name) = lower(%s)", (name,)
        ).fetchone()
        return row["name"] if row else None

    def create_community(self, conn, name: str, admin: str) -> bool:
        """Create a community and its default collections, owned by the admin. -> True when
        created, False when exactly this name already exists. A name differing only in case
        from an existing one is a Conflict."""
        existing = self.community_name(conn, name)
        if existing == name:
            return False
        if existing is not None:
            raise Conflict(f"community '{existing}' already exists")
        try:
            with conn.transaction():
                conn.execute("INSERT INTO communities (name) VALUES (%s)", (name,))
        except psycopg.errors.UniqueViolation:
            raise Conflict(f"community '{name}' already exists") from None
        self.ensure_collections(conn, name, admin)
        return True

    def communities(self, conn) -> list:
        return conn.execute(
            "SELECT name, created FROM communities ORDER BY lower(name)"
        ).fetchall()

    def holds_files(self, conn, community: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM files WHERE community = %s LIMIT 1", (community,)
        ).fetchone()
        return row is not None

    # ── ports (R-M1) ────────────────────────────────────────────────────────────────────────
    def start_port(
        self, conn, community: str, requested_by: str, source: str
    ) -> uuid.UUID:
        """Record a running port. -> its id. A Conflict while another port runs anywhere."""
        try:
            with conn.transaction():
                row = conn.execute(
                    "INSERT INTO ports (community, requested_by, source) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (community, requested_by, source),
                ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise Conflict("another port is running") from None
        return row["id"]

    def finish_port(self, conn, port_id, state: str, result: dict):
        conn.execute(
            "UPDATE ports SET state = %s, result = %s, finished = now() WHERE id = %s",
            (state, json.dumps(result), port_id),
        )

    def port(self, conn, community: str, port_id) -> dict | None:
        return conn.execute(
            "SELECT id, community, requested_by, source, state, result, started, finished "
            "FROM ports "
            "WHERE community = %s AND id = %s",
            (community, port_id),
        ).fetchone()

    def fail_running_ports(self, conn) -> int:
        """At start-up, a port still marked running was cut off by the restart."""
        return conn.execute(
            "UPDATE ports SET state = 'failed', finished = now(), "
            'result = \'{"reason": "the service restarted while the port ran"}\' '
            "WHERE state = 'running'"
        ).rowcount

    # ── identity, per community ─────────────────────────────────────────────────────────────
    def add_challenge(
        self, conn, community: str | None, handle: str, nonce: str, ttl: int = 300
    ):
        """`community` None is the server admin's challenge."""
        conn.execute("DELETE FROM challenges WHERE expires < now()")
        conn.execute(
            "INSERT INTO challenges (nonce, community, handle, expires) "
            "VALUES (%s, %s, %s, now() + %s * interval '1 second')",
            (nonce, community, handle, ttl),
        )

    def take_challenge(
        self, conn, community: str | None, handle: str, nonce: str
    ) -> bool:
        """Consume a challenge: true only once, for its own community and handle, before it
        expires."""
        row = conn.execute(
            "DELETE FROM challenges WHERE nonce = %s AND handle = %s "
            "AND community IS NOT DISTINCT FROM %s RETURNING expires > now() AS live",
            (nonce, handle, community),
        ).fetchone()
        return bool(row and row["live"])

    def active_keys(self, conn, community: str, handle: str) -> list:
        return conn.execute(
            "SELECT kid, jwk FROM owner_keys WHERE community = %s AND handle = %s AND active",
            (community, handle),
        ).fetchall()

    def key_is_active(self, conn, community: str, handle: str, kid: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM owner_keys WHERE community = %s AND handle = %s AND kid = %s "
            "AND active",
            (community, handle, kid),
        ).fetchone()
        return row is not None

    def on_roster(self, conn, community: str, handle: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM roster WHERE community = %s AND handle = %s",
            (community, handle),
        ).fetchone()
        return row is not None

    def add_to_roster(self, conn, community: str, handle: str) -> bool:
        """Add one handle with the default grants (R-D6). Idempotent: -> False when the handle
        was already on the roster. The admin's handle is reserved: it can never be a member."""
        if handle == self.config(conn, "admin"):
            raise Forbidden("the admin's handle cannot be on a roster")
        added = conn.execute(
            "INSERT INTO roster (community, handle) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING RETURNING handle",
            (community, handle),
        ).fetchone()
        for collection, perm in DEFAULT_GRANTS:
            conn.execute(
                "INSERT INTO grants (community, collection, handle, perm) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (community, collection, handle, perm),
            )
        return added is not None

    def remove_from_roster(self, conn, community: str, handle: str) -> bool:
        """Remove one handle: it loses every grant and pending invite in the community but keeps
        its identity and attribution. -> False when it was not on the roster."""
        removed = conn.execute(
            "DELETE FROM roster WHERE community = %s AND handle = %s RETURNING handle",
            (community, handle),
        ).fetchone()
        conn.execute(
            "DELETE FROM grants WHERE community = %s AND handle = %s",
            (community, handle),
        )
        self.revoke_invites(conn, community, handle)
        return removed is not None

    def roster(self, conn, community: str) -> list:
        """Each handle with whether it has registered and when its pending invite expires."""
        return conn.execute(
            "SELECT r.handle, "
            "EXISTS (SELECT 1 FROM owner_keys k WHERE k.community = r.community "
            "AND k.handle = r.handle AND k.active) AS registered, "
            "(SELECT max(i.expires) FROM invites i WHERE i.community = r.community "
            "AND i.handle = r.handle AND i.used IS NULL AND i.revoked IS NULL "
            "AND i.expires > now()) AS invite_expires "
            "FROM roster r WHERE r.community = %s ORDER BY r.handle",
            (community,),
        ).fetchall()

    def grants(self, conn, community: str, handle: str) -> list:
        return [
            (r["collection"], r["perm"])
            for r in conn.execute(
                "SELECT collection, perm FROM grants WHERE community = %s AND handle = %s "
                "ORDER BY collection, perm",
                (community, handle),
            ).fetchall()
        ]

    def add_invite(
        self, conn, digest: str, secret: str, community: str, handle: str, hours: int
    ):
        """Issue an invite, revoking any earlier unused one for the handle, so only the newest
        works (R-D6). The secret is kept, retrievable by the admin, only while pending."""
        self.revoke_invites(conn, community, handle)
        return conn.execute(
            "INSERT INTO invites (hash, secret, community, handle, expires) "
            "VALUES (%s, %s, %s, %s, now() + %s * interval '1 hour') RETURNING expires",
            (digest, secret, community, handle, hours),
        ).fetchone()["expires"]

    def revoke_invites(self, conn, community: str, handle: str):
        conn.execute(
            "UPDATE invites SET revoked = now(), secret = NULL WHERE community = %s "
            "AND handle = %s AND used IS NULL AND revoked IS NULL",
            (community, handle),
        )

    def pending_invites(self, conn, community: str) -> list:
        return conn.execute(
            "SELECT handle, secret, expires FROM invites WHERE community = %s "
            "AND used IS NULL AND revoked IS NULL AND expires > now() AND secret IS NOT NULL "
            "ORDER BY handle",
            (community,),
        ).fetchall()

    def consume_invite(self, conn, digest: str, community: str, handle: str) -> bool:
        """Spend an invite: valid only once, for its own handle and community, before expiry
        and unless revoked. Its secret is erased as it is used."""
        row = conn.execute(
            "UPDATE invites SET used = now(), secret = NULL WHERE hash = %s AND community = %s "
            "AND handle = %s AND used IS NULL AND revoked IS NULL AND expires > now() "
            "RETURNING hash",
            (digest, community, handle),
        ).fetchone()
        return row is not None

    def forget_expired_invites(self, conn) -> int:
        """The janitor erases the secret of every invite that expired unused."""
        return conn.execute(
            "UPDATE invites SET secret = NULL WHERE secret IS NOT NULL AND expires <= now()"
        ).rowcount

    def register(self, conn, community: str, handle: str, kid: str, jwk: dict):
        conn.execute(
            "INSERT INTO owners (community, handle) VALUES (%s, %s) "
            "ON CONFLICT (community, handle) DO UPDATE SET reserved = false",
            (community, handle),
        )
        conn.execute(
            "INSERT INTO owner_keys (community, kid, handle, jwk) VALUES (%s, %s, %s, %s)",
            (community, kid, handle, json.dumps(jwk)),
        )

    def retire_keys(self, conn, community: str, handle: str) -> int:
        """Retire every active key of a handle; retired keys stay on record for attribution."""
        return conn.execute(
            "UPDATE owner_keys SET active = false, retired = now() "
            "WHERE community = %s AND handle = %s AND active",
            (community, handle),
        ).rowcount

    def rotate(self, conn, community: str, handle: str, kid: str, jwk: dict):
        self.retire_keys(conn, community, handle)
        conn.execute(
            "INSERT INTO owner_keys (community, kid, handle, jwk) VALUES (%s, %s, %s, %s)",
            (community, kid, handle, json.dumps(jwk)),
        )

    def key_on_record(self, conn, community: str, kid: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM owner_keys WHERE community = %s AND kid = %s",
            (community, kid),
        ).fetchone()
        return row is not None

    def owner(self, conn, community: str, handle: str):
        return conn.execute(
            "SELECT handle, reserved, suspect_after FROM owners "
            "WHERE community = %s AND handle = %s",
            (community, handle),
        ).fetchone()

    def set_suspect_after(self, conn, community: str, handle: str, instant) -> bool:
        return (
            conn.execute(
                "UPDATE owners SET suspect_after = %s WHERE community = %s AND handle = %s",
                (instant, community, handle),
            ).rowcount
            == 1
        )

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

    def allocate_at(self, conn, community: str, collection: str, created: datetime):
        """-> (seq, created) for an instant the caller supplies. Only the port does
        this (R-M2): each instant must be strictly later than the collection's last one, so
        the clock still never runs backwards, and later writes continue after it."""
        row = conn.execute(
            "UPDATE collections SET seq = seq + 1, last_created = %s "
            "WHERE community = %s AND name = %s "
            "AND (last_created IS NULL OR last_created < %s) RETURNING seq, last_created",
            (created, community, collection, created),
        ).fetchone()
        if row is None:
            raise Conflict(
                f"{community}/{collection}: {created.isoformat()} is not later than the "
                "collection's clock"
            )
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

    def collection_row(self, conn, community: str, collection: str):
        row = conn.execute(
            "SELECT * FROM collections WHERE community = %s AND name = %s",
            (community, collection),
        ).fetchone()
        if row is None:
            raise NotFound(f"no collection {community}/{collection}")
        return row

    def owns(self, conn, handle, community, collection) -> bool:
        """The collection's owner, while they are still on the community's roster."""
        row = conn.execute(
            "SELECT owner FROM collections WHERE community = %s AND name = %s",
            (community, collection),
        ).fetchone()
        return (
            row is not None
            and handle is not None
            and row["owner"] == handle
            and self.on_roster(conn, community, handle)
        )

    def can_create(self, conn, handle, community, collection) -> bool:
        """New files in a collection: the admin, its owner, or a member granted write."""
        return (
            self.is_admin(conn, handle)
            or self.owns(conn, handle, community, collection)
            or self.has_grant(conn, community, collection, handle, "write")
        )

    def can_manage(self, conn, handle, community, collection) -> bool:
        """Grants, public visibility and collection read keys: the owner or the admin."""
        return self.is_admin(conn, handle) or self.owns(
            conn, handle, community, collection
        )

    def can_modify(self, conn, handle, file_row) -> bool:
        """New versions and tombstones: the file's creator (while they can still write to the
        collection) or the admin. Members cannot change each other's files."""
        if self.is_admin(conn, handle):
            return True
        creator = self.first_writer(conn, file_row["id"])
        return creator == handle and self.can_create(
            conn, handle, file_row["community"], file_row["collection"]
        )

    def can_read(self, conn, handle, row, key=None) -> bool:
        """`handle` is a signed-in owner, `key` a read-key row, both None for anonymous."""
        community, collection = row["community"], row["collection"]
        if (
            collection != "inbox"
            and self.collection_row(conn, community, collection)["public"]
        ):
            return True
        if key is not None:
            return (
                collection != "inbox"
                and key["community"] == community
                and key["collection"] == collection
                and (key["file_id"] is None or key["file_id"] == row["file_id"])
            )
        if handle is None:
            return False
        if self.is_admin(conn, handle) or self.owns(
            conn, handle, community, collection
        ):
            return True
        if self.has_grant(conn, community, collection, handle, "read"):
            return True
        if collection == "inbox":
            # a submission is readable by its submitter and by the recipients named on it
            return handle == self.first_writer(conn, row["file_id"]) or handle in (
                row["metadata"] or {}
            ).get("recipients", [])
        return False

    def can_read_collection(
        self, conn, handle, community, collection, key=None
    ) -> bool:
        """Listing a collection (changes, find, query). Each listed row is still checked with
        can_read: a file-scoped key, or a member reading inbox, sees only some of its rows."""
        if (
            collection != "inbox"
            and self.collection_row(conn, community, collection)["public"]
        ):
            return True
        if key is not None:
            return (
                collection != "inbox"
                and key["community"] == community
                and key["collection"] == collection
            )
        if handle is None:
            return False
        if collection == "inbox" and self.on_roster(conn, community, handle):
            return True
        return (
            self.is_admin(conn, handle)
            or self.owns(conn, handle, community, collection)
            or self.has_grant(conn, community, collection, handle, "read")
        )

    # ── collections and sharing ─────────────────────────────────────────────────────────────
    def create_collection(self, conn, community: str, name: str, owner: str):
        try:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO collections (community, name, owner) VALUES (%s, %s, %s)",
                    (community, name, owner),
                )
        except psycopg.errors.UniqueViolation:
            raise Conflict(f"collection {community}/{name} already exists") from None

    def set_public(self, conn, community: str, collection: str, public: bool):
        if collection == "inbox" and public:
            raise Forbidden("inbox is never public")
        conn.execute(
            "UPDATE collections SET public = %s WHERE community = %s AND name = %s",
            (public, community, collection),
        )

    def set_grant(self, conn, community, collection, handle, perm: str, granted: bool):
        if granted:
            if not self.on_roster(conn, community, handle):
                raise Forbidden(f"'{handle}' is not on the {community} roster")
            conn.execute(
                "INSERT INTO grants (community, collection, handle, perm) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (community, collection, handle, perm),
            )
        else:
            conn.execute(
                "DELETE FROM grants WHERE community = %s AND collection = %s AND handle = %s "
                "AND perm = %s",
                (community, collection, handle, perm),
            )

    def mint_key(self, conn, community, collection, file_id, label, by, hours, digest):
        if collection == "inbox":
            raise Forbidden("inbox accepts no read keys")
        key_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO read_keys (id, hash, community, collection, file_id, label, created_by, "
            "expires) VALUES (%s, %s, %s, %s, %s, %s, %s, "
            "CASE WHEN %s::int IS NULL THEN NULL ELSE now() + %s * interval '1 hour' END)",
            (key_id, digest, community, collection, file_id, label, by, hours, hours),
        )
        return self.key_row(conn, community, key_id)

    def key_row(self, conn, community: str, key_id):
        row = conn.execute(
            "SELECT * FROM read_keys WHERE id = %s AND community = %s",
            (key_id, community),
        ).fetchone()
        if row is None:
            raise NotFound("no such read key")
        return row

    def use_key(self, conn, community: str, digest: str):
        """A usable read key of this community for this secret, its use audited; None if
        unknown here, revoked or expired."""
        return conn.execute(
            "UPDATE read_keys SET uses = uses + 1, last_used = now() WHERE hash = %s "
            "AND community = %s AND revoked IS NULL AND (expires IS NULL OR expires > now()) "
            "RETURNING *",
            (digest, community),
        ).fetchone()

    def list_keys(self, conn, community, collection, created_by=None) -> list:
        query = "SELECT * FROM read_keys WHERE community = %s AND collection = %s"
        params = [community, collection]
        if created_by is not None:
            query += " AND created_by = %s"
            params.append(created_by)
        return conn.execute(query + " ORDER BY created", params).fetchall()

    def revoke_key(self, conn, key_id):
        conn.execute(
            "UPDATE read_keys SET revoked = now() WHERE id = %s AND revoked IS NULL",
            (key_id,),
        )

    # ── payloads ────────────────────────────────────────────────────────────────────────────
    def begin_payload(self, conn, community: str, owner: str):
        pid = uuid.uuid4()
        key = f"payloads/{pid}"
        conn.execute(
            "INSERT INTO payloads (id, state, s3_key, community, first_owner) "
            "VALUES (%s, 'pending', %s, %s, %s)",
            (pid, key, community, owner),
        )
        return pid, key

    def note_upload(self, conn, pid, upload_id: str):
        conn.execute(
            "UPDATE payloads SET upload_id = %s WHERE id = %s", (upload_id, pid)
        )

    def commit_payload(
        self, conn, pid, community: str, sha: str, size: int, owner: str, quota: int
    ):
        """Inside the caller's commit transaction: make a verified pending payload ready, or
        reuse an identical ready one in the same community (content is deduplicated within a
        community, never across). -> (payload_id, duplicate_pending_id_or_None).

        A duplicate's own row is deliberately left pending: its bytes still exist, and only
        the cleanup after commit removes them, bytes first and row second.

        The owner's row is locked first, so the quota check and the payload it admits are one
        atomic step: concurrent uploads by the same owner cannot jointly exceed the quota."""
        self.lock_owner(conn, community, owner)
        existing = conn.execute(
            "SELECT id FROM payloads WHERE community = %s AND sha256 = %s AND state = 'ready'",
            (community, sha),
        ).fetchone()
        if existing:
            return existing["id"], pid
        if quota and self.usage(conn, community, owner) + size > quota:
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
            return self.commit_payload(conn, pid, community, sha, size, owner, quota)

    def lock_owner(self, conn, community: str, owner: str):
        """Writers take the owner's row before the collection's clock, always in that order,
        so concurrent writes never deadlock. The server admin has no owner row and no quota."""
        conn.execute(
            "SELECT 1 FROM owners WHERE community = %s AND handle = %s FOR UPDATE",
            (community, owner),
        )

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

    def touch_pending_many(self, conn, pids: list):
        """Heartbeat of a batch still waiting for its commit (an import, a port)."""
        conn.execute(
            "UPDATE payloads SET created = now() WHERE id = ANY(%s) AND state = 'pending'",
            (list(pids),),
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

    def usage(self, conn, community: str, owner: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(SUM(size), 0) AS total FROM payloads "
            "WHERE community = %s AND first_owner = %s AND state = 'ready'",
            (community, owner),
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

    def create_live_file(self, conn, community, collection, name):
        """Inside a commit transaction: a new file, live at once (promote writes its v1 in the
        same transaction, so no reservation is needed)."""
        fid = uuid.uuid4()
        try:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO files (id, community, collection, name) VALUES (%s, %s, %s, %s)",
                    (fid, community, collection, name),
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

    def stale_reservations(self, conn, older_than_seconds: float) -> list:
        return conn.execute(
            "DELETE FROM files WHERE state = 'reserved' "
            "AND reserved_at < now() - %s * interval '1 second' RETURNING id",
            (older_than_seconds,),
        ).fetchall()

    def file_row(self, conn, community: str, file_id):
        """A live file of this community; a file of another community is not found."""
        row = conn.execute(
            "SELECT * FROM files WHERE id = %s AND community = %s AND state = 'live'",
            (file_id, community),
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
        clock=None,
    ) -> int:
        """Append version n+1. `clock` is a (seq, created) the caller already allocated in
        this transaction (promote stamps `created` into the bytes before inserting)."""
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
        seq, created = clock or self.allocate(conn, f["community"], f["collection"])
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

    _ROWS = (
        "SELECT v.*, p.sha256, p.size, p.s3_key, p.state AS payload_state, p.scrub_ok, "
        "f.name, f.community, f.collection, o.suspect_after "
        "FROM versions v JOIN payloads p ON p.id = v.payload_id JOIN files f ON f.id = v.file_id "
        "LEFT JOIN owners o ON o.community = f.community AND o.handle = v.created_by "
    )
    _VERSION = _ROWS + "WHERE v.file_id = %s AND f.community = %s "

    def version(self, conn, community: str, file_id, ref):
        """ref: a version number, or 'latest' (the newest version that is not a tombstone).
        A version of another community's file is not found."""
        if ref == "latest":
            row = conn.execute(
                self._VERSION + "AND NOT v.deleted ORDER BY v.n DESC LIMIT 1",
                (file_id, community),
            ).fetchone()
        else:
            try:
                n = int(ref)
            except (TypeError, ValueError):
                raise NotFound("a version is a number or 'latest'") from None
            row = conn.execute(
                self._VERSION + "AND v.n = %s", (file_id, community, n)
            ).fetchone()
        if row is None:
            raise NotFound("no such version")
        return row

    def changes(self, conn, community, collection, since: int, limit: int) -> list:
        """Versions written into a collection after `since`, in seq order (R-G3). seq is
        allocated under the collection's lock and committed in order, so a reader paging by
        seq never skips a version."""
        return conn.execute(
            self._ROWS + "WHERE f.community = %s AND f.collection = %s AND v.seq > %s "
            "ORDER BY v.seq LIMIT %s",
            (community, collection, since, limit),
        ).fetchall()

    def query(
        self, conn, community, collection, contains: dict, since: int, limit: int
    ):
        """Versions whose metadata contains `contains` (JSONB @>, GIN-indexed), paged by seq
        like changes (R-G6)."""
        return conn.execute(
            self._ROWS + "WHERE f.community = %s AND f.collection = %s AND v.seq > %s "
            "AND v.metadata @> %s::jsonb ORDER BY v.seq LIMIT %s",
            (community, collection, since, json.dumps(contains), limit),
        ).fetchall()

    def by_hash(self, conn, community: str, sha: str) -> list:
        """Every version holding this content, in any collection of the community (R-F2)."""
        return conn.execute(
            self._ROWS
            + "WHERE f.community = %s AND p.sha256 = %s ORDER BY f.collection, v.seq",
            (community, sha),
        ).fetchall()

    def verify(self, row, before: datetime | None, sha: str | None) -> dict:
        """The gate's check of a cited version (R-G9): its content is still there, its sha256
        is the one cited, and it was created strictly before `before`."""
        out = {
            "ok": True,
            "exists": True,
            "reason": None,
            "citation": f"symposium-data:{row['file_id']}@v{row['n']}",
            "sha256": row["sha256"],
            "created": iso(row["created"]),
            "deleted": row["deleted"],
            "purged": row["purged"],
        }
        if row["purged"]:
            out.update(ok=False, reason="content purged")
        elif sha and sha.lower() != row["sha256"]:
            out.update(ok=False, reason="sha256 does not match")
        elif before and not row["created"] < before:
            out.update(
                ok=False,
                reason=f"file version created {iso(row['created'])} is not strictly "
                f"earlier than {iso(before)}",
            )
        return out

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

    def versions(self, conn, community: str, file_id) -> list:
        rows = conn.execute(
            "SELECT n FROM versions WHERE file_id = %s ORDER BY n", (file_id,)
        ).fetchall()
        return [
            self.stat(conn, self.version(conn, community, file_id, r["n"]))
            for r in rows
        ]

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

    def stale_pending(self, conn, older_than_seconds: float) -> list:
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
