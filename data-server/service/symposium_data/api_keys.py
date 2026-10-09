"""API keys (api/DESIGN.md §4): `sak_` bearer keys for the Data API, each bound to one
community, found by their SHA-256 and sealed with AES-256-GCM so its owner can read one back
while no key is stored in plain text.

A Member creates its own `member` keys, as many as it likes, each named by a label and bound
to the Member's handle; the admin creates `non-member` keys for applications. The Control
API issues, lists and revokes them (`/v1/{community}/api-keys`); the Data API only
authenticates with them, and takes the Member it acts as from the key's `handle`.
Authentication hashes the presented key and looks the hash up; it decrypts nothing. Only an
owner's listing decrypts, with the 32-byte key in API_KEY_ENC_KEY_FILE, which start.sh
writes beside the server's other secrets. The associated data binds each ciphertext to its
own row.
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


def aad(key_id, handle: str | None, label: str, community: str) -> bytes:
    """Binds a ciphertext to its own row: its id, owner, label and community."""
    return f"{key_id}|{handle or ''}|{label}|{community}".encode()


@dataclass(frozen=True)
class KeyRow:
    """One api_keys row as authentication and the listing use it."""

    id: uuid.UUID
    handle: str | None  # the Member a `member` key acts as; None for a `non-member` key
    label: str
    role: str
    community: str


class LabelInUse(Exception):
    """The owner already holds a live key with this label."""


class ApiKeys:
    def __init__(self, sealer: Sealer):
        self.sealer = sealer

    # ── issuing and listing ────────────────────────────────────────────────────────────────
    def create(
        self,
        conn,
        *,
        community: str,
        handle: str | None,
        label: str,
        expires_days: int | None,
        created_by: str,
    ) -> tuple[dict, str]:
        """A `member` key when `handle` names its Member, a `non-member` key otherwise. -> (the
        new row, its key). Raises LabelInUse when the owner holds a live key so labelled."""
        key_id, key = uuid.uuid4(), new_key()
        role = "member" if handle else "non-member"
        ciphertext, nonce = self.sealer.seal(key, aad(key_id, handle, label, community))
        expires = (
            datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
        )
        taken = conn.execute(
            "SELECT 1 FROM api_keys WHERE community = %s AND label = %s "
            "AND handle IS NOT DISTINCT FROM %s AND revoked IS NULL",
            (community, label, handle),
        ).fetchone()
        if taken:
            raise LabelInUse(label)
        row = conn.execute(
            "INSERT INTO api_keys (id, hash, ciphertext, nonce, enc_kid, handle, label, "
            "role, community, created_by, expires) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                key_id,
                digest(key),
                ciphertext,
                nonce,
                self.sealer.kid,
                handle,
                label,
                role,
                community,
                created_by,
                expires,
            ),
        ).fetchone()
        return row, key

    def value(self, row) -> str | None:
        """The key itself, decrypted for its owner's listing; None once its value is erased."""
        if row["ciphertext"] is None:
            return None
        return self.sealer.open(
            bytes(row["ciphertext"]),
            bytes(row["nonce"]),
            aad(row["id"], row["handle"], row["label"], row["community"]),
        )

    def page(self, conn, *, community, after, limit, handle, include_revoked) -> list:
        """One community's keys in creation order after the (created, id) position `after`:
        one Member's own when `handle` names it, every key otherwise."""
        clauses, args = ["community = %s"], [community]
        if after is not None:
            clauses.append("(created, id) > (%s, %s)")
            args += list(after)
        if handle is not None:
            clauses.append("handle = %s")
            args.append(handle)
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

    def revoke_for(self, conn, community: str, handle: str, by: str) -> int:
        """Revoke every live key of one Member, erasing their values. -> how many."""
        return conn.execute(
            "UPDATE api_keys SET revoked = now(), revoked_by = %s, ciphertext = NULL, "
            "nonce = NULL WHERE community = %s AND handle = %s AND revoked IS NULL",
            (by, community, handle),
        ).rowcount

    # ── authentication ─────────────────────────────────────────────────────────────────────
    def find(self, conn, key: str) -> KeyRow | None:
        """The live key `key` names, counting its use; None for an unknown, revoked or expired
        key."""
        row = conn.execute(
            "UPDATE api_keys SET last_used = now(), uses = uses + 1 "
            "WHERE hash = %s AND revoked IS NULL AND (expires IS NULL OR expires > now()) "
            "RETURNING id, handle, label, role, community",
            (digest(key),),
        ).fetchone()
        return KeyRow(**row) if row else None

    def live(self, conn, key_id) -> KeyRow | None:
        """The key by id while it is still live: a stream re-checks its key this way."""
        row = conn.execute(
            "SELECT id, handle, label, role, community FROM api_keys "
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
