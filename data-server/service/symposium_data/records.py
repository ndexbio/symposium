"""The server's records: configuration, communities, users and their role assignments, invites,
files and versions. Every community-dependent record is scoped by its community.

Used by the HTTP service, its jobs, export and import, and the port, so every invariant has one
implementation.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import psycopg

from .access import rbac

# The collections every community has: submissions, stored files and the
# accepted record.
COLLECTIONS = ("inbox", "files", "record")

# The two kinds of `inbox` item, by the mark in their metadata: a member's submission to the
# gate, and the gate's reply to it.
SUBMISSION_MARK = "symposium_submission"
REPLY_MARK = "symposium_reply"


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


class Invalid(Exception):
    """A request the server understands but cannot apply as asked (400)."""


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

    # ── communities ─────────────────────────────────────────────────────────────────────────
    def community_name(self, conn, name: str) -> str | None:
        """The community's name as it was created, matching `name` ignoring case."""
        row = conn.execute(
            "SELECT name FROM communities WHERE lower(name) = lower(%s)", (name,)
        ).fetchone()
        return row["name"] if row else None

    def create_community(self, conn, name: str, owner_id) -> bool:
        """Create a community and its default collections, owned by `owner_id` (the root user).
        -> True when created, False when exactly this name already exists. A name differing
        only in case from an existing one is a Conflict."""
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
        self.ensure_collections(conn, name, owner_id)
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

    # ── ports ────────────────────────────────────────────────────────────────────────
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

    # ── users ───────────────────────────────────────────────────────────────────────────────
    _USER = (
        "SELECT u.*, EXISTS (SELECT 1 FROM user_keys k WHERE k.user_id = u.id AND k.active) "
        "AS registered FROM users u "
    )

    def user(self, conn, user_id):
        return conn.execute(self._USER + "WHERE u.id = %s", (user_id,)).fetchone()

    def user_by_handle(self, conn, home: str | None, handle: str):
        """The user `handle` homed in `home` (None: server-level), removed ones included."""
        return conn.execute(
            self._USER + "WHERE u.home IS NOT DISTINCT FROM %s AND u.handle = %s",
            (home, handle),
        ).fetchone()

    def users(self, conn, home: str | None) -> list:
        """Every user of a community (or every server-level user), removed ones included, each
        with its live roles."""
        rows = conn.execute(
            self._USER + "WHERE u.home IS NOT DISTINCT FROM %s ORDER BY u.handle",
            (home,),
        ).fetchall()
        return [
            {**row, "roles": self.role_list(conn, user_id=row["id"])} for row in rows
        ]

    def root_user(self, conn):
        """The server-level user holding server-root, or None before the key file binds one."""
        return conn.execute(
            self._USER + "JOIN role_assignments a ON a.user_id = u.id "
            "WHERE a.role_id = %s AND a.revoked IS NULL",
            (rbac.SERVER_ROOT,),
        ).fetchone()

    def bind_root(self, conn, handle: str, kid: str, jwk: dict):
        """Initialize the server: the key file's handle becomes the server-level root user,
        holding `server-root`, with this key. Works exactly once."""
        conn.execute("LOCK TABLE users IN EXCLUSIVE MODE")
        current = self.root_user(conn)
        if current is not None:
            raise AlreadyInitialized(current["handle"])
        root = self.create_user(conn, handle, None)
        self.add_key(conn, root["id"], kid, jwk)
        conn.execute(
            "INSERT INTO role_assignments (user_id, role_id, created_by) VALUES (%s, %s, %s)",
            (root["id"], rbac.SERVER_ROOT, handle),
        )

    def create_user(self, conn, handle: str, home: str | None):
        """A new user (`check_new_handle` first). -> its row."""
        self.check_new_handle(conn, handle, home)
        conn.execute("INSERT INTO users (handle, home) VALUES (%s, %s)", (handle, home))
        return self.user_by_handle(conn, home, handle)

    def check_new_handle(self, conn, handle: str, home: str | None):
        """Conflict unless `handle` can become a new user in `home`: unused there (a tombstone
        included) and, across server-level and community users, never both."""
        taken = self.user_by_handle(conn, home, handle)
        if taken is not None:
            if taken["removed"] is not None:
                raise Conflict(f"handle '{handle}' belongs to a removed member")
            raise Conflict(f"'{handle}' already exists")
        if home is None:
            clash = conn.execute(
                "SELECT home FROM users WHERE handle = %s AND home IS NOT NULL LIMIT 1",
                (handle,),
            ).fetchone()
        else:
            clash = conn.execute(
                "SELECT home FROM users WHERE handle = %s AND home IS NULL", (handle,)
            ).fetchone()
        if clash is not None:
            raise Conflict(
                f"'{handle}' is a server-level handle"
                if home is not None
                else f"'{handle}' is a handle in {clash['home']}"
            )

    def set_suspect_after(self, conn, user_id, instant) -> bool:
        return (
            conn.execute(
                "UPDATE users SET suspect_after = %s WHERE id = %s AND removed IS NULL",
                (instant, user_id),
            ).rowcount
            == 1
        )

    def remove_user(self, conn, user_id, by: str) -> bool:
        """Make the user a tombstone: its assignments end, its sign-in keys retire, its
        sessions and every API key it issued go. -> False when it was already removed."""
        found = self.user(conn, user_id)
        if found is None or found["removed"] is not None:
            return False
        if found["home"] is not None:
            self.lock_community(conn, found["home"])
            if self.last_members_holder(conn, found["home"], user_id):
                raise Conflict(
                    "this is the community's last community admin; appoint another one first"
                )
        conn.execute(
            "UPDATE users SET removed = now(), removed_by = %s WHERE id = %s",
            (by, user_id),
        )
        conn.execute(
            "UPDATE role_assignments SET revoked = now(), revoked_by = %s "
            "WHERE user_id = %s AND revoked IS NULL",
            (by, user_id),
        )
        self.retire_keys(conn, user_id)
        # every key it issued: a homed user's in its community, a server-level user's in
        # any (a server-level handle is used in no community)
        conn.execute(
            "DELETE FROM api_keys WHERE user_id = %s OR (created_by = %s AND "
            "(%s::text IS NULL OR community = %s))",
            (user_id, found["handle"], found["home"], found["home"]),
        )
        conn.execute(
            "UPDATE invites SET revoked = now(), secret = NULL WHERE user_id = %s "
            "AND used IS NULL AND revoked IS NULL",
            (user_id,),
        )
        return True

    def known_handles(self, conn, community: str) -> set:
        """Every handle that resolves in the community: its users, removed ones included, and
        every server-level user."""
        return {
            r["handle"]
            for r in conn.execute(
                "SELECT handle FROM users WHERE home = %s OR home IS NULL", (community,)
            ).fetchall()
        }

    def active_submitters(self, conn, community: str) -> set:
        """The handles whose submissions the gate decides: the community's users, not removed,
        holding `publish` through a live `community-member` assignment."""
        return {
            r["handle"]
            for r in conn.execute(
                "SELECT u.handle FROM users u JOIN role_assignments a ON a.user_id = u.id "
                "WHERE u.home = %s AND u.removed IS NULL AND a.revoked IS NULL "
                "AND a.role_id = %s",
                (community, rbac.COMMUNITY_MEMBER),
            ).fetchall()
        }

    # ── a user's sign-in keys ───────────────────────────────────────────────────────────────
    def active_keys(self, conn, user_id) -> list:
        return conn.execute(
            "SELECT kid, jwk FROM user_keys WHERE user_id = %s AND active", (user_id,)
        ).fetchall()

    def key_is_active(self, conn, user_id, kid: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM user_keys WHERE user_id = %s AND kid = %s AND active",
            (user_id, kid),
        ).fetchone()
        return row is not None

    def add_key(self, conn, user_id, kid: str, jwk: dict):
        """The user's only active key: earlier ones retire, never deleted (versions name
        them). A key that was the user's before becomes active again."""
        self.retire_keys(conn, user_id, keep=kid)
        conn.execute(
            "INSERT INTO user_keys (user_id, kid, jwk) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, kid) DO UPDATE SET active = true, retired = NULL",
            (user_id, kid, json.dumps(jwk)),
        )

    def retire_keys(self, conn, user_id, keep: str | None = None) -> int:
        """Retire the user's active keys and end the sessions they obtained."""
        retired = conn.execute(
            "UPDATE user_keys SET active = false, retired = now() "
            "WHERE user_id = %s AND active AND kid IS DISTINCT FROM %s RETURNING kid",
            (user_id, keep),
        ).fetchall()
        kids = [r["kid"] for r in retired]
        if kids:
            conn.execute(
                "DELETE FROM api_keys WHERE kind = 'session' AND user_id = %s "
                "AND ed25519_kid = ANY(%s)",
                (user_id, kids),
            )
        return len(kids)

    def key_on_record(self, conn, kid: str) -> bool:
        """Whether `kid` is, or was, any user's key."""
        row = conn.execute("SELECT 1 FROM user_keys WHERE kid = %s", (kid,)).fetchone()
        return row is not None

    # ── role assignments ────────────────────────────────────────────────────────────────────
    @staticmethod
    def _principal(user_id, api_key_id) -> tuple:
        if (user_id is None) == (api_key_id is None):
            raise Invalid("name either a user or an API key")
        return (
            ("user_id", user_id) if user_id is not None else ("api_key_id", api_key_id)
        )

    def assignments_of(self, conn, *, user_id=None, api_key_id=None) -> list:
        column, value = self._principal(user_id, api_key_id)
        return [
            rbac.Assignment(
                r["role_id"],
                None if r["collections"] is None else tuple(r["collections"]),
            )
            for r in conn.execute(
                f"SELECT role_id, collections FROM role_assignments WHERE {column} = %s "
                "AND revoked IS NULL ORDER BY role_id",
                (value,),
            ).fetchall()
        ]

    def role_list(self, conn, *, user_id=None, api_key_id=None) -> list:
        """The live roles of a principal, as the API shows them."""
        return [
            {
                "role": a.role_id,
                "collections": None if a.collections is None else list(a.collections),
            }
            for a in self.assignments_of(conn, user_id=user_id, api_key_id=api_key_id)
        ]

    def assign(
        self, conn, role_id: str, collections, by: str, *, user_id=None, api_key_id=None
    ):
        """Add `collections` to the principal's live assignment of `role_id`, or create it.
        `*` absorbs names; names leave a `*` assignment as it is. -> the stored value."""
        column, value = self._principal(user_id, api_key_id)
        wanted = rbac.collection_value(role_id, collections)
        current = conn.execute(
            f"SELECT id, collections FROM role_assignments WHERE {column} = %s "
            "AND role_id = %s AND revoked IS NULL FOR UPDATE",
            (value, role_id),
        ).fetchone()
        if current is None:
            conn.execute(
                f"INSERT INTO role_assignments ({column}, role_id, collections, created_by) "
                "VALUES (%s, %s, %s, %s)",
                (value, role_id, None if wanted is None else list(wanted), by),
            )
            return wanted
        if wanted is None:
            return None
        merged = rbac.merge(tuple(current["collections"]), wanted)
        conn.execute(
            "UPDATE role_assignments SET collections = %s WHERE id = %s",
            (list(merged), current["id"]),
        )
        return merged

    def replace_value(
        self, conn, role_id: str, collections, by: str, *, user_id=None, api_key_id=None
    ):
        """Set the whole collection value of the principal's live assignment of `role_id`."""
        column, value = self._principal(user_id, api_key_id)
        wanted = rbac.collection_value(role_id, collections)
        conn.execute(
            f"UPDATE role_assignments SET collections = %s WHERE {column} = %s "
            "AND role_id = %s AND revoked IS NULL",
            (None if wanted is None else list(wanted), value, role_id),
        )

    def current_value(self, conn, role_id: str, *, user_id=None, api_key_id=None):
        """The principal's live assignment of `role_id`: its collection value (None for a role
        without one), or False when it holds no such assignment."""
        column, value = self._principal(user_id, api_key_id)
        row = conn.execute(
            f"SELECT collections FROM role_assignments WHERE {column} = %s AND role_id = %s "
            "AND revoked IS NULL",
            (value, role_id),
        ).fetchone()
        if row is None:
            return False
        return None if row["collections"] is None else tuple(row["collections"])

    def unassign(
        self, conn, role_id: str, names, by: str, *, user_id=None, api_key_id=None
    ) -> bool:
        """Remove `names` from the principal's live assignment of `role_id`, ending it when
        none remain; with `names` None, end it. A user's ended assignment stays, revoked, as
        its access history; a key's goes. -> False when there was nothing to remove."""
        column, value = self._principal(user_id, api_key_id)
        current = conn.execute(
            f"SELECT id, collections FROM role_assignments WHERE {column} = %s "
            "AND role_id = %s AND revoked IS NULL FOR UPDATE",
            (value, role_id),
        ).fetchone()
        if current is None:
            return False
        if names is not None and current["collections"] is not None:
            held = list(current["collections"])
            if not set(names) & set(held):
                return False
            left = [c for c in held if c not in set(names)]
            if left:
                conn.execute(
                    "UPDATE role_assignments SET collections = %s WHERE id = %s",
                    (left, current["id"]),
                )
                return True
        if user_id is not None:
            found = self.user(conn, user_id)
            if found is not None and found["home"] is not None:
                self.lock_community(conn, found["home"])
                if rbac.MEMBERS in rbac.role(
                    role_id
                ).grants and self.last_members_holder(conn, found["home"], user_id):
                    raise Conflict(
                        "this is the community's last community admin; appoint another one first"
                    )
            conn.execute(
                "UPDATE role_assignments SET revoked = now(), revoked_by = %s WHERE id = %s",
                (by, current["id"]),
            )
        else:
            conn.execute("DELETE FROM role_assignments WHERE id = %s", (current["id"],))
        return True

    def lock_community(self, conn, community: str):
        conn.execute(
            "SELECT 1 FROM communities WHERE name = %s FOR UPDATE", (community,)
        )

    def last_members_holder(self, conn, community: str, user_id) -> bool:
        """Whether `user_id` is the only registered, unremoved user of the community holding
        `members`. Called with the community row locked."""
        roles = [r.id for r in rbac.ROLES.values() if rbac.MEMBERS in r.grants]
        holders = [
            r["id"]
            for r in conn.execute(
                "SELECT DISTINCT u.id FROM users u JOIN role_assignments a ON a.user_id = u.id "
                "WHERE u.home = %s AND u.removed IS NULL AND a.revoked IS NULL "
                "AND a.role_id = ANY(%s) AND EXISTS (SELECT 1 FROM user_keys k "
                "WHERE k.user_id = u.id AND k.active)",
                (community, roles),
            ).fetchall()
        ]
        return holders == [user_id]

    def context_for(
        self,
        conn,
        *,
        principal_id,
        principal_name,
        community,
        via_session,
        user_id=None,
        api_key_id=None,
        issuer=None,
    ) -> rbac.UserContext:
        """The request's UserContext: the principal's live assignments, compiled. An issued
        key's (`api_key_id` with `issuer`, the user who issued it) are limited to what its
        issuer reaches now."""
        grants = rbac.compile_grants(
            self.assignments_of(conn, user_id=user_id, api_key_id=api_key_id),
            user=api_key_id is None,
        )
        if issuer is not None:
            held = self.context_for(
                conn,
                principal_id=issuer["id"],
                principal_name=issuer["handle"],
                community=issuer["home"],
                via_session=True,
                user_id=issuer["id"],
            )
            owned = self.owned_collections(conn, community, issuer["id"])
            grants = rbac.within(grants, held, community, owned)
        return rbac.UserContext(
            principal_id=principal_id,
            principal_name=principal_name,
            community=community,
            via_session=via_session,
            grants=grants,
        )

    def owned_collections(self, conn, community: str, user_id) -> set:
        return {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM collections WHERE community = %s AND owner = %s",
                (community, user_id),
            ).fetchall()
        }

    def issuer_of(self, conn, community: str, handle: str):
        """The live user who issued a key of `community`: homed there, or server-level; None
        once it is removed."""
        for home in (community, None):
            user = self.user_by_handle(conn, home, handle)
            if user is not None:
                return None if user["removed"] is not None else user
        return None

    # ── invites ─────────────────────────────────────────────────────────────────────────────
    def add_invite(
        self,
        conn,
        *,
        digest: str,
        secret: str,
        handle: str,
        home: str | None,
        roles: list,
        by: str,
        hours: int,
        user_id=None,
    ):
        """Issue an invite, revoking any earlier pending one for the same handle and home, so
        only the newest works. Its roles are stored here and applied when it is redeemed; its
        secret is kept, retrievable, only while pending. -> its expiry."""
        conn.execute(
            "UPDATE invites SET revoked = now(), secret = NULL WHERE handle = %s "
            "AND home IS NOT DISTINCT FROM %s AND used IS NULL AND revoked IS NULL",
            (handle, home),
        )
        return conn.execute(
            "INSERT INTO invites (hash, secret, handle, home, roles, user_id, created_by, "
            "expires) VALUES (%s, %s, %s, %s, %s, %s, %s, now() + %s * interval '1 hour') "
            "RETURNING expires",
            (digest, secret, handle, home, json.dumps(roles), user_id, by, hours),
        ).fetchone()["expires"]

    def pending_invites(self, conn, home: str | None) -> list:
        return conn.execute(
            "SELECT hash, handle, home, roles, secret, expires FROM invites "
            "WHERE home IS NOT DISTINCT FROM %s AND used IS NULL AND revoked IS NULL "
            "AND expires > now() AND secret IS NOT NULL ORDER BY handle",
            (home,),
        ).fetchall()

    def invite_by_id(self, conn, home: str | None, digest: str):
        """A pending invite of `home` by its id (its hash), or None."""
        return conn.execute(
            "SELECT hash, handle, home, roles, secret, expires FROM invites "
            "WHERE hash = %s AND home IS NOT DISTINCT FROM %s AND used IS NULL "
            "AND revoked IS NULL AND expires > now()",
            (digest, home),
        ).fetchone()

    def revoke_invite(self, conn, digest: str):
        conn.execute(
            "UPDATE invites SET revoked = now(), secret = NULL WHERE hash = %s",
            (digest,),
        )

    def pending_invite(self, conn, digest: str, handle: str):
        """The usable invite with this secret for this handle, without spending it."""
        return conn.execute(
            "SELECT * FROM invites WHERE hash = %s AND handle = %s AND used IS NULL "
            "AND revoked IS NULL AND expires > now()",
            (digest, handle),
        ).fetchone()

    def take_invite(self, conn, digest: str, handle: str):
        """Spend an invite: valid once, for its own handle, before expiry and unless revoked.
        Its secret is erased as it is used. -> its row, or None."""
        return conn.execute(
            "UPDATE invites SET used = now(), secret = NULL WHERE hash = %s AND handle = %s "
            "AND used IS NULL AND revoked IS NULL AND expires > now() RETURNING *",
            (digest, handle),
        ).fetchone()

    def forget_expired_invites(self, conn) -> int:
        """The janitor erases the secret of every invite that expired unused."""
        return conn.execute(
            "UPDATE invites SET secret = NULL WHERE secret IS NOT NULL AND expires <= now()"
        ).rowcount

    # ── sign-in challenges ──────────────────────────────────────────────────────────────────
    def add_challenge(
        self, conn, home: str | None, handle: str, nonce: str, ttl: int = 300
    ):
        conn.execute("DELETE FROM challenges WHERE expires < now()")
        conn.execute(
            "INSERT INTO challenges (nonce, home, handle, expires) "
            "VALUES (%s, %s, %s, now() + %s * interval '1 second')",
            (nonce, home, handle, ttl),
        )

    def take_challenge(self, conn, home: str | None, handle: str, nonce: str) -> bool:
        """Consume a challenge: true only once, for its own home and handle, before expiry."""
        row = conn.execute(
            "DELETE FROM challenges WHERE nonce = %s AND handle = %s "
            "AND home IS NOT DISTINCT FROM %s RETURNING expires > now() AS live",
            (nonce, handle, home),
        ).fetchone()
        return bool(row and row["live"])

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
        this: each instant must be strictly later than the collection's last one, so
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

    # ── access to collections ───────────────────────────────────────────────────────────────
    def collection_ref(
        self, conn, community: str, collection: str
    ) -> rbac.CollectionRef:
        """What an access check takes for one collection; NotFound when it does not exist."""
        row = self.collection_row(conn, community, collection)
        return rbac.CollectionRef(row["name"], row["owner"])

    def collection_row(self, conn, community: str, collection: str):
        row = conn.execute(
            "SELECT * FROM collections WHERE community = %s AND name = %s",
            (community, collection),
        ).fetchone()
        if row is None:
            raise NotFound(f"no collection {community}/{collection}")
        return row

    def is_public(self, conn, community: str, collection: str) -> bool:
        """`inbox` is never public, whatever its row says."""
        return (
            collection != "inbox"
            and self.collection_row(conn, community, collection)["public"]
        )

    def allows(self, conn, ctx, grant: str, community: str, collection: str) -> bool:
        """`ctx.allowsRequest` for a collection named by community and name."""
        if ctx is None:
            return False
        return ctx.allowsRequest(
            grant, community, self.collection_ref(conn, community, collection)
        )

    def can_create(self, conn, ctx, community: str, collection: str, metadata) -> bool:
        """A new file. In `inbox`: a submission takes `publish`, a reply takes `gate`, and
        nothing else goes in. Elsewhere: `write` on the collection."""
        if ctx is None:
            return False
        if collection == rbac.INBOX:
            metadata = metadata or {}
            if metadata.get(SUBMISSION_MARK) is True and not metadata.get(REPLY_MARK):
                return ctx.allowsRequest(rbac.PUBLISH, community)
            if metadata.get(REPLY_MARK) is True and not metadata.get(SUBMISSION_MARK):
                return ctx.allowsRequest(rbac.GATE, community)
            return False
        if collection == rbac.RECORD:
            return False
        return self.allows(conn, ctx, rbac.WRITE, community, collection)

    def can_modify(self, conn, ctx, file_row) -> bool:
        """New versions and tombstones: `manage` on the collection, or the file's first writer
        while it can still write there. Nothing in `inbox` or `record` changes."""
        community, collection = file_row["community"], file_row["collection"]
        if collection in (rbac.INBOX, rbac.RECORD):
            return False
        if self.allows(conn, ctx, rbac.MANAGE, community, collection):
            return True
        return (
            ctx is not None
            and self.first_writer(conn, file_row["id"]) == ctx.principal_name
            and self.allows(conn, ctx, rbac.WRITE, community, collection)
        )

    def can_read(self, conn, ctx, row) -> bool:
        """One version. In a public collection, anyone. In `inbox`, `gate` reads every item and
        `publish` the items its holder wrote and the replies naming it. Elsewhere, `read`."""
        community, collection = row["community"], row["collection"]
        if self.is_public(conn, community, collection):
            return True
        if ctx is None:
            return False
        if collection == rbac.INBOX:
            if ctx.allowsRequest(rbac.GATE, community):
                return True
            if not ctx.allowsRequest(rbac.PUBLISH, community):
                return False
            return ctx.principal_name == self.first_writer(conn, row["file_id"]) or (
                ctx.principal_name in (row["metadata"] or {}).get("recipients", [])
            )
        return self.allows(conn, ctx, rbac.READ, community, collection)

    def can_read_collection(self, conn, ctx, community, collection) -> bool:
        """Listing a collection (changes, find, query). Each listed row is still checked with
        can_read: a member listing `inbox` sees only its own items and replies."""
        if self.is_public(conn, community, collection):
            return True
        if ctx is None:
            return False
        if collection == rbac.INBOX:
            return ctx.allowsRequest(rbac.GATE, community) or ctx.allowsRequest(
                rbac.PUBLISH, community
            )
        return self.allows(conn, ctx, rbac.READ, community, collection)

    def readable_collections(self, conn, ctx, community: str) -> list:
        """The community's collections `ctx` may use, by name, each with what it may do there:
        `read`, `write` and `manage`, as they apply."""
        rows = conn.execute(
            "SELECT c.name, c.owner, c.public, u.handle AS owner_handle FROM collections c "
            "LEFT JOIN users u ON u.id = c.owner WHERE c.community = %s ORDER BY c.name",
            (community,),
        ).fetchall()
        out = []
        for row in rows:
            ref = rbac.CollectionRef(row["name"], row["owner"])
            public = row["public"] and row["name"] != rbac.INBOX
            if row["name"] == rbac.INBOX:
                access = (
                    ["read"]
                    if self.can_read_collection(conn, ctx, community, rbac.INBOX)
                    else []
                )
            else:
                access = [
                    perm
                    for perm, grant in (
                        ("read", rbac.READ),
                        ("write", rbac.WRITE),
                        ("manage", rbac.MANAGE),
                    )
                    if ctx is not None and ctx.allowsRequest(grant, community, ref)
                ]
                if public and "read" not in access:
                    access.insert(0, "read")
            if not access:
                continue
            out.append(
                {
                    "community": community,
                    "name": row["name"],
                    "owner": row["owner_handle"],
                    "public": public,
                    "access": access,
                }
            )
        return out

    def create_collection(self, conn, community: str, name: str, owner_id):
        try:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO collections (community, name, owner) VALUES (%s, %s, %s)",
                    (community, name, owner_id),
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
                turned = conn.execute(
                    "UPDATE payloads SET state = 'ready', sha256 = %s, size = %s, upload_id = NULL "
                    "WHERE id = %s AND state = 'pending'",
                    (sha, size, pid),
                ).rowcount
            if turned == 0:
                # the janitor expired this upload (its bytes are gone) before this commit
                # reached it: nothing may point at it
                raise Conflict(
                    "the upload expired before it was committed; send it again"
                )
            return pid, None
        except psycopg.errors.UniqueViolation:
            # an identical payload turned ready concurrently: use that one
            return self.commit_payload(conn, pid, community, sha, size, owner, quota)

    def lock_owner(self, conn, community: str, owner: str):
        """Writers take their user row before the collection's clock, always in that order,
        so concurrent writes never deadlock. A server-level user has no quota."""
        conn.execute(
            "SELECT 1 FROM users WHERE home = %s AND handle = %s FOR UPDATE",
            (community, owner),
        )

    def touch_pending(self, conn, pid, file_id=None) -> bool:
        """Heartbeat of an upload in progress: the janitor expires only work that has stopped,
        never a long upload that is still streaming. -> False when the janitor has already
        expired it."""
        touched = conn.execute(
            "UPDATE payloads SET created = now() WHERE id = %s AND state = 'pending'",
            (pid,),
        ).rowcount
        if file_id is not None:
            conn.execute(
                "UPDATE files SET reserved_at = now() WHERE id = %s AND state = 'reserved'",
                (file_id,),
            )
        return touched > 0

    def touch_pending_many(self, conn, pids: list):
        """Heartbeat of a batch still waiting for its commit (an import, a port)."""
        conn.execute(
            "UPDATE payloads SET created = now() WHERE id = ANY(%s) AND state = 'pending'",
            (list(pids),),
        )

    def claim_pending(self, conn, pid):
        """Inside the caller's transaction: lock a pending payload to remove it. -> its row, or
        None when it is gone or a commit holds it (that commit decides its fate, never both).
        A commit that comes after waits for this transaction, then finds the row gone."""
        return conn.execute(
            "SELECT id, s3_key, upload_id FROM payloads WHERE id = %s AND state = 'pending' "
            "FOR UPDATE SKIP LOCKED",
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

    def files_after(self, conn, community, collection, after: str, limit: int) -> list:
        """The collection's live files named after `after`, by name. -> [(id, name)]"""
        return [
            (r["id"], r["name"])
            for r in conn.execute(
                "SELECT id, name FROM files WHERE community = %s AND collection = %s "
                "AND state = 'live' AND name > %s ORDER BY name LIMIT %s",
                (community, collection, after, limit),
            ).fetchall()
        ]

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
        "LEFT JOIN users o ON o.home = f.community AND o.handle = v.created_by "
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
        """Versions written into a collection after `since`, in seq order. seq is
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
        like changes."""
        return conn.execute(
            self._ROWS + "WHERE f.community = %s AND f.collection = %s AND v.seq > %s "
            "AND v.metadata @> %s::jsonb ORDER BY v.seq LIMIT %s",
            (community, collection, since, json.dumps(contains), limit),
        ).fetchall()

    def by_hash(self, conn, community: str, sha: str) -> list:
        """Every version holding this content, in any collection of the community."""
        return conn.execute(
            self._ROWS
            + "WHERE f.community = %s AND p.sha256 = %s ORDER BY f.collection, v.seq",
            (community, sha),
        ).fetchall()

    def verify(self, row, before: datetime | None, sha: str | None) -> dict:
        """The gate's check of a cited version: its content is still there, its sha256
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
        """Mark a version purged. When no live version uses its payload any more, the
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
