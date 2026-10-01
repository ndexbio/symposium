"""The server's records: configuration, owner identities, rosters, grants and invites.

Shared by the HTTP service and data-admin, so every invariant has one implementation.
"""

from __future__ import annotations

import json

# Every roster member gets these grants in their community (R-D6).
DEFAULT_GRANTS = (
    ("inbox", "write"),
    ("files", "write"),
    ("files", "read"),
    ("record", "read"),
)


class AlreadyInitialized(Exception):
    pass


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
