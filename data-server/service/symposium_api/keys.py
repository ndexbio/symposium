"""API keys (api/DESIGN.md §4): `sak_` bearer keys, found by their SHA-256 and sealed with
AES-256-GCM so the admin can read one back while no key is ever stored in plain text.

Authentication hashes the presented key and looks the hash up; it decrypts nothing. Only the
admin's listing decrypts, with the 32-byte key in API_KEY_ENC_KEY_FILE, which start.sh writes
beside the server's other secrets. The associated data binds each ciphertext to its own row.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "sak_"
DEFAULT_KEY_FILE = "/apps/data/config/api_key_enc.key"


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return PREFIX + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip(
        "="
    )


def key_file_from(config_path: Path) -> Path:
    """API_KEY_ENC_KEY_FILE from service.env, or its default beside the other secrets."""
    try:
        for line in config_path.read_text().splitlines():
            name, _, value = line.strip().partition("=")
            if name.strip() == "API_KEY_ENC_KEY_FILE" and value.strip():
                return Path(value.strip())
    except OSError:
        pass
    return Path(os.environ.get("API_KEY_ENC_KEY_FILE", DEFAULT_KEY_FILE))


class Sealer:
    """AES-256-GCM over one key file. `kid` names the key, so rows record which one sealed them."""

    def __init__(self, path: Path):
        self.path = path

    def _key(self) -> bytes:
        raw = self.path.read_bytes()
        if len(raw) != 32:
            raise RuntimeError(f"{self.path} must hold exactly 32 bytes")
        return raw

    @property
    def kid(self) -> str:
        return hashlib.sha256(self._key()).hexdigest()[:16]

    def seal(self, plaintext: str, aad: bytes) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        return AESGCM(self._key()).encrypt(nonce, plaintext.encode(), aad), nonce

    def open(self, ciphertext: bytes, nonce: bytes, aad: bytes) -> str:
        return AESGCM(self._key()).decrypt(nonce, ciphertext, aad).decode()


def aad(key_id, username: str, community: str | None) -> bytes:
    return f"{key_id}|{username}|{community or ''}".encode()


@dataclass(frozen=True)
class KeyRow:
    """One api_keys row as authentication and the listing use it."""

    id: uuid.UUID
    username: str
    role: str
    community: str | None
    admin_kid: str | None


class ApiKeys:
    def __init__(self, sealer: Sealer):
        self.sealer = sealer

    # ── issuing and listing ────────────────────────────────────────────────────────────────
    def create(
        self,
        conn,
        *,
        username: str,
        role: str,
        community: str | None,
        label: str | None,
        expires_days: int | None,
        created_by: str,
        admin_kid: str | None,
    ) -> tuple[dict, str]:
        """-> (the new row, its key). The key is answered once, here and in the listing."""
        key_id, key = uuid.uuid4(), new_key()
        ciphertext, nonce = self.sealer.seal(key, aad(key_id, username, community))
        expires = (
            datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
        )
        row = conn.execute(
            "INSERT INTO api_keys (id, hash, ciphertext, nonce, enc_kid, username, role, "
            "admin_kid, community, label, created_by, expires) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                key_id,
                digest(key),
                ciphertext,
                nonce,
                self.sealer.kid,
                username,
                role,
                admin_kid,
                community,
                label,
                created_by,
                expires,
            ),
        ).fetchone()
        return row, key

    def value(self, row) -> str | None:
        """The key itself, decrypted for the admin's listing; None once its value is erased."""
        if row["ciphertext"] is None:
            return None
        return self.sealer.open(
            bytes(row["ciphertext"]),
            bytes(row["nonce"]),
            aad(row["id"], row["username"], row["community"]),
        )

    def page(self, conn, *, after, limit, community, username, include_revoked) -> list:
        """Keys in creation order after the (created, id) position `after`."""
        clauses, args = [], []
        if after is not None:
            clauses.append("(created, id) > (%s, %s)")
            args += list(after)
        if community is not None:
            clauses.append("community = %s")
            args.append(community)
        if username is not None:
            clauses.append("username = %s")
            args.append(username)
        if not include_revoked:
            clauses.append("revoked IS NULL")
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        return conn.execute(
            f"SELECT * FROM api_keys {where}ORDER BY created, id LIMIT %s",
            (*args, limit),
        ).fetchall()

    def row(self, conn, key_id):
        return conn.execute(
            "SELECT * FROM api_keys WHERE id = %s", (key_id,)
        ).fetchone()

    def revoke(self, conn, key_id, by: str):
        """Stop the key and erase its value; the row stays as the record of who held it.
        Revoking a revoked key answers it unchanged."""
        return conn.execute(
            "UPDATE api_keys SET revoked = COALESCE(revoked, now()), "
            "revoked_by = COALESCE(revoked_by, %s), ciphertext = NULL, nonce = NULL "
            "WHERE id = %s RETURNING *",
            (by, key_id),
        ).fetchone()

    # ── authentication ─────────────────────────────────────────────────────────────────────
    def find(self, conn, key: str) -> KeyRow | None:
        """The live key `key` names, counting its use; None for an unknown, revoked or expired
        key."""
        row = conn.execute(
            "UPDATE api_keys SET last_used = now(), uses = uses + 1 "
            "WHERE hash = %s AND revoked IS NULL AND (expires IS NULL OR expires > now()) "
            "RETURNING id, username, role, community, admin_kid",
            (digest(key),),
        ).fetchone()
        return KeyRow(**row) if row else None

    def live(self, conn, key_id) -> KeyRow | None:
        """The key by id while it is still live: a stream re-checks its key this way."""
        row = conn.execute(
            "SELECT id, username, role, community, admin_kid FROM api_keys "
            "WHERE id = %s AND revoked IS NULL AND (expires IS NULL OR expires > now())",
            (key_id,),
        ).fetchone()
        return KeyRow(**row) if row else None

    # ── upkeep ─────────────────────────────────────────────────────────────────────────────
    def sweep(self, conn) -> int:
        """Revoke every admin key bound to a retired admin key (an admin rebind), and erase the
        value of every expired key. -> how many rows changed."""
        revoked = conn.execute(
            "UPDATE api_keys SET revoked = now(), revoked_by = 'admin-rebind', "
            "ciphertext = NULL, nonce = NULL "
            "WHERE role = 'admin' AND revoked IS NULL AND NOT EXISTS "
            "(SELECT 1 FROM admin_keys a WHERE a.kid = api_keys.admin_kid AND a.active)"
        ).rowcount
        erased = conn.execute(
            "UPDATE api_keys SET ciphertext = NULL, nonce = NULL "
            "WHERE expires <= now() AND ciphertext IS NOT NULL"
        ).rowcount
        return revoked + erased
