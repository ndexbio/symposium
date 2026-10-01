"""The server's records: configuration and owner identities.

Shared by the HTTP service and data-admin, so every invariant has one implementation.
"""

from __future__ import annotations

import json


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
