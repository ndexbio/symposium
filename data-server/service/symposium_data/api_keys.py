"""API keys: `sak_` bearer keys, the one credential every route of `/v1` takes.

A key's row is its caller's identity: its kind, role, community, Member and label.

- A **session key** is what the session management routes answer. It lasts the session TTL,
  acts as the Member or the admin it is bound to, and ends when the key that obtained it is
  retired.
- An **issued key** is made by a signed-in caller for an application, with a label, and lasts
  until it is revoked or its optional expiry. A `member` key acts as the Member who made it; a
  `non-member` key names nobody and reads what its collections' owners grant it.

Authentication hashes the presented key and looks the hash up; it decrypts nothing. An issued
key is also sealed with AES-256-GCM under the 32-byte key in API_KEY_ENC_KEY_FILE, which
start.sh writes beside the server's other secrets, so its owner can read it back. The
associated data binds each ciphertext to its own row. A session key is never shown again, so
it is stored as its hash alone.
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
    """Binds a ciphertext to its own row: its id, Member, label and community."""
    return f"{key_id}|{handle or ''}|{label}|{community}".encode()


SESSION = "session"
ISSUED = "issued"
ROW = "id, kind, role, community, handle, label, created_by, ed25519_kid"

# last_used is refreshed at most this often, so a busy key is not one hot row of writes
TOUCH_SECONDS = 60


@dataclass(frozen=True)
class KeyRow:
    """One api_keys row as authentication uses it."""

    id: uuid.UUID
    kind: str  # SESSION or ISSUED
    role: str  # admin, member or non-member
    community: str | None  # None for an admin session, which works in every community
    handle: str | None  # the Member, or the admin; None for a non-member key
    label: str | None  # issued keys only
    created_by: str
    ed25519_kid: str | None  # session keys only


class LabelInUse(Exception):
    """The issuer already holds a live key with this label."""


class ApiKeys:
    def __init__(self, sealer: Sealer):
        self.sealer = sealer

    # ── issuing ────────────────────────────────────────────────────────────────────────────
    def create_session(
        self,
        conn,
        *,
        community: str | None,
        role: str,
        handle: str,
        ed25519_kid: str,
        ttl_seconds: float,
    ) -> tuple[dict, str]:
        """A session key for a Member (`community` named) or the admin (`community` None),
        obtained with the key `ed25519_kid`. -> (the new row, its key)."""
        key = new_key()
        row = conn.execute(
            "INSERT INTO api_keys (id, hash, kind, role, community, handle, ed25519_kid, "
            "created_by, expires) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
            "now() + %s * interval '1 second') RETURNING *",
            (
                uuid.uuid4(),
                digest(key),
                SESSION,
                role,
                community,
                handle,
                ed25519_kid,
                handle,
                ttl_seconds,
            ),
        ).fetchone()
        return row, key

    def create(
        self,
        conn,
        *,
        community: str,
        role: str,
        handle: str | None,
        label: str,
        expires_days: int | None,
        created_by: str,
    ) -> tuple[dict, str]:
        """An issued key: a `member` key when `handle` names its Member, a `non-member` key
        otherwise. -> (the new row, its key). Raises LabelInUse when the issuer holds a live
        key so labelled."""
        key_id, key = uuid.uuid4(), new_key()
        ciphertext, nonce = self.sealer.seal(key, aad(key_id, handle, label, community))
        expires = (
            datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
        )
        taken = conn.execute(
            "SELECT 1 FROM api_keys WHERE community = %s AND created_by = %s AND label = %s "
            "AND kind = %s AND revoked IS NULL",
            (community, created_by, label, ISSUED),
        ).fetchone()
        if taken:
            raise LabelInUse(label)
        row = conn.execute(
            "INSERT INTO api_keys (id, hash, kind, role, community, handle, label, "
            "ciphertext, nonce, enc_kid, created_by, expires) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                key_id,
                digest(key),
                ISSUED,
                role,
                community,
                handle,
                label,
                ciphertext,
                nonce,
                self.sealer.kid,
                created_by,
                expires,
            ),
        ).fetchone()
        return row, key

    # ── listing ────────────────────────────────────────────────────────────────────────────
    def value(self, row) -> str | None:
        """An issued key itself, decrypted for its owner's listing; None once erased."""
        if row["ciphertext"] is None:
            return None
        return self.sealer.open(
            bytes(row["ciphertext"]),
            bytes(row["nonce"]),
            aad(row["id"], row["handle"], row["label"], row["community"]),
        )

    def page(self, conn, *, community, after, limit, issuer, include_revoked) -> list:
        """One community's issued keys in creation order after the (created, id) position
        `after`: those `issuer` made when it names one, every one otherwise."""
        clauses, args = ["community = %s", "kind = %s"], [community, ISSUED]
        if after is not None:
            clauses.append("(created, id) > (%s, %s)")
            args += list(after)
        if issuer is not None:
            clauses.append("created_by = %s")
            args.append(issuer)
        if not include_revoked:
            clauses.append("revoked IS NULL")
        return conn.execute(
            f"SELECT * FROM api_keys WHERE {' AND '.join(clauses)} "
            "ORDER BY created, id LIMIT %s",
            (*args, limit),
        ).fetchall()

    def row(self, conn, community: str, key_id):
        """The community's issued key `key_id`, or None, also for a key of another community."""
        return conn.execute(
            "SELECT * FROM api_keys WHERE id = %s AND community = %s AND kind = %s",
            (key_id, community, ISSUED),
        ).fetchone()

    # ── revoking ───────────────────────────────────────────────────────────────────────────
    def revoke(self, conn, community: str, key_id, by: str):
        """Stop the community's issued key, erase its value and drop the grants made to it; the
        row stays as the record of who held it. Revoking a revoked key answers it unchanged;
        None for an unknown key."""
        row = conn.execute(
            "UPDATE api_keys SET revoked = COALESCE(revoked, now()), "
            "revoked_by = COALESCE(revoked_by, %s), ciphertext = NULL, nonce = NULL "
            "WHERE id = %s AND community = %s AND kind = %s RETURNING *",
            (by, key_id, community, ISSUED),
        ).fetchone()
        if row is not None:
            conn.execute("DELETE FROM grants WHERE api_key_id = %s", (row["id"],))
        return row

    def revoke_for(self, conn, community: str, handle: str, by: str) -> int:
        """Revoke every live key of one Member in the community: the keys that act as it,
        sessions included, and the non-member keys it issued, whose grants go with them.
        -> how many issued keys."""
        rows = conn.execute(
            "UPDATE api_keys SET revoked = now(), revoked_by = %s, ciphertext = NULL, "
            "nonce = NULL WHERE community = %s AND (handle = %s OR created_by = %s) "
            "AND revoked IS NULL RETURNING id, kind",
            (by, community, handle, handle),
        ).fetchall()
        conn.execute(
            "DELETE FROM grants WHERE api_key_id = ANY(%s)", ([r["id"] for r in rows],)
        )
        return sum(1 for row in rows if row["kind"] == ISSUED)

    def end_sessions(self, conn, ed25519_kids: list[str], by: str) -> int:
        """Revoke every live session key obtained with one of these Ed25519 keys."""
        if not ed25519_kids:
            return 0
        return conn.execute(
            "UPDATE api_keys SET revoked = now(), revoked_by = %s WHERE kind = %s "
            "AND ed25519_kid = ANY(%s) AND revoked IS NULL",
            (by, SESSION, list(ed25519_kids)),
        ).rowcount

    # ── authentication ─────────────────────────────────────────────────────────────────────
    def find(self, conn, key: str) -> KeyRow | None:
        """The live key `key` names; None for an unknown, revoked or expired key. Its
        last_used is refreshed when it is older than TOUCH_SECONDS."""
        row = conn.execute(
            f"SELECT {ROW}, last_used FROM api_keys WHERE hash = %s AND revoked IS NULL "
            "AND (expires IS NULL OR expires > now())",
            (digest(key),),
        ).fetchone()
        if row is None:
            return None
        if row["last_used"] is None or row["last_used"] < datetime.now(UTC) - timedelta(
            seconds=TOUCH_SECONDS
        ):
            conn.execute(
                "UPDATE api_keys SET last_used = now() WHERE id = %s", (row["id"],)
            )
        return KeyRow(**{k: row[k] for k in KeyRow.__dataclass_fields__})

    def live(self, conn, key_id) -> KeyRow | None:
        """The key by id while it is still live: a stream re-checks its key this way."""
        row = conn.execute(
            f"SELECT {ROW} FROM api_keys WHERE id = %s AND revoked IS NULL "
            "AND (expires IS NULL OR expires > now())",
            (key_id,),
        ).fetchone()
        return KeyRow(**row) if row else None

    # ── upkeep ─────────────────────────────────────────────────────────────────────────────
    def sweep(self, conn) -> int:
        """Erase the value of every expired issued key, and delete every session that expired
        or was revoked. -> how many rows changed."""
        erased = conn.execute(
            "UPDATE api_keys SET ciphertext = NULL, nonce = NULL "
            "WHERE kind = %s AND expires <= now() AND ciphertext IS NOT NULL",
            (ISSUED,),
        ).rowcount
        deleted = conn.execute(
            "DELETE FROM api_keys WHERE kind = %s AND (expires <= now() OR revoked IS NOT NULL)",
            (SESSION,),
        ).rowcount
        return erased + deleted
