"""API keys (api/DESIGN.md §4): `sak_` bearer keys for the Data API, each bound to one
community, found by their SHA-256 and sealed with AES-256-GCM so the admin can read one back
while no key is stored in plain text.

The Control API issues, lists and revokes them (`/v1/{community}/api-keys`); the Data API
only authenticates with them. Authentication hashes the presented key and looks the hash up;
it decrypts nothing. Only the admin's listing decrypts, with the 32-byte key in
API_KEY_ENC_KEY_FILE, which start.sh writes beside the server's other secrets. The
associated data binds each ciphertext to its own row.
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


def aad(key_id, username: str, community: str) -> bytes:
    return f"{key_id}|{username}|{community}".encode()


@dataclass(frozen=True)
class KeyRow:
    """One api_keys row as authentication and the listing use it."""

    id: uuid.UUID
    username: str
    role: str
    community: str


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
        community: str,
        label: str | None,
        expires_days: int | None,
        created_by: str,
    ) -> tuple[dict, str]:
        """-> (the new row, its key). The key is answered once, here and in the listing."""
        key_id, key = uuid.uuid4(), new_key()
        ciphertext, nonce = self.sealer.seal(key, aad(key_id, username, community))
        expires = (
            datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
        )
        row = conn.execute(
            "INSERT INTO api_keys (id, hash, ciphertext, nonce, enc_kid, username, role, "
            "community, label, created_by, expires) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                key_id,
                digest(key),
                ciphertext,
                nonce,
                self.sealer.kid,
                username,
                role,
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

    def page(self, conn, *, community, after, limit, username, include_revoked) -> list:
        """One community's keys in creation order after the (created, id) position `after`."""
        clauses, args = ["community = %s"], [community]
        if after is not None:
            clauses.append("(created, id) > (%s, %s)")
            args += list(after)
        if username is not None:
            clauses.append("username = %s")
            args.append(username)
        if not include_revoked:
            clauses.append("revoked IS NULL")
        return conn.execute(
            f"SELECT * FROM api_keys WHERE {' AND '.join(clauses)} "
            "ORDER BY created, id LIMIT %s",
            (*args, limit),
        ).fetchall()

    def row(self, conn, community: str, key_id):
        """The community's key `key_id`, or None, also for a key of another community."""
        return conn.execute(
            "SELECT * FROM api_keys WHERE id = %s AND community = %s",
            (key_id, community),
        ).fetchone()

    def revoke(self, conn, community: str, key_id, by: str):
        """Stop the community's key and erase its value; the row stays as the record of who
        held it. Revoking a revoked key answers it unchanged; None for an unknown key."""
        return conn.execute(
            "UPDATE api_keys SET revoked = COALESCE(revoked, now()), "
            "revoked_by = COALESCE(revoked_by, %s), ciphertext = NULL, nonce = NULL "
            "WHERE id = %s AND community = %s RETURNING *",
            (by, key_id, community),
        ).fetchone()

    # ── authentication ─────────────────────────────────────────────────────────────────────
    def find(self, conn, key: str) -> KeyRow | None:
        """The live key `key` names, counting its use; None for an unknown, revoked or expired
        key."""
        row = conn.execute(
            "UPDATE api_keys SET last_used = now(), uses = uses + 1 "
            "WHERE hash = %s AND revoked IS NULL AND (expires IS NULL OR expires > now()) "
            "RETURNING id, username, role, community",
            (digest(key),),
        ).fetchone()
        return KeyRow(**row) if row else None

    def live(self, conn, key_id) -> KeyRow | None:
        """The key by id while it is still live: a stream re-checks its key this way."""
        row = conn.execute(
            "SELECT id, username, role, community FROM api_keys "
            "WHERE id = %s AND revoked IS NULL AND (expires IS NULL OR expires > now())",
            (key_id,),
        ).fetchone()
        return KeyRow(**row) if row else None

    # ── upkeep ─────────────────────────────────────────────────────────────────────────────
    def sweep(self, conn) -> int:
        """Erase the value of every expired key. -> how many rows changed."""
        return conn.execute(
            "UPDATE api_keys SET ciphertext = NULL, nonce = NULL "
            "WHERE expires <= now() AND ciphertext IS NOT NULL"
        ).rowcount
