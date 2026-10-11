"""The admin key file (R-D4): who the server admin is, decided at every start-up from
`admin_pub_<handle>.key`, in `/apps/` or in `/apps/admin-key/` (where the Helm chart mounts it
from a Secret), and the backup of the established admin.

Nobody has a shell on the server, so the key file is the only way the admin's key is given or
changed. The API reads it when it starts and never writes to the apps directory itself; the
backup lives under data/config, which the service owns.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .auth import PublicKeys
from .records import Records
from .runtime import Database
from .wire import NAME

log = logging.getLogger("symposium_data.admin_key")

KEY_FILE = re.compile(r"^admin_pub_(.+)\.key$")
HANDLE = re.compile(NAME)

NOT_PROVIDED = "admin key not provided"
AMBIGUOUS = "ambiguous admin key files"
INVALID = "admin key invalid"
MISSING = "admin key missing"


@dataclass(frozen=True)
class AdminMode:
    """The outcome of a start-up: operational with the admin's handle and fingerprint and the
    action taken (bound, unchanged, rebound, backup), or non-operational with a reason."""

    operational: bool
    reason: str | None = None
    action: str | None = None
    handle: str | None = None
    fingerprint: str | None = None


class InvalidKey(Exception):
    pass


class AdminKeyFile:
    def __init__(self, apps: Path, db: Database, records: Records, keys: PublicKeys):
        self.apps = Path(apps)
        self.backup = self.apps / "data" / "config" / "admin_pub.backup"
        self.places = (self.apps, self.apps / "admin-key")
        self.db, self.records, self.keys = db, records, keys

    def resolve(self) -> AdminMode:
        files = {}
        for place in self.places:
            for path in sorted(place.glob("admin_pub_*.key")):
                handle = KEY_FILE.match(path.name).group(1)
                if handle in files:
                    return self.non_operational(
                        AMBIGUOUS,
                        f"two key files for '{handle}', keep exactly one: "
                        f"{files[handle]} and {path}",
                    )
                files[handle] = path
        with self.db.connection() as conn:
            bound = self.records.config(conn, "admin")
            if bound is None:
                return self.first_bind(conn, files)
            return self.established(conn, bound, files)

    def where(self) -> str:
        return " or ".join(str(place) for place in self.places)

    # ── not initialized ─────────────────────────────────────────────────────────────────────
    def first_bind(self, conn, files: dict) -> AdminMode:
        if not files:
            return self.non_operational(
                NOT_PROVIDED,
                f"no admin key file: place admin_pub_<handle>.key in {self.where()}",
            )
        if len(files) > 1:
            names = ", ".join(path.name for path in files.values())
            return self.non_operational(
                AMBIGUOUS, f"several admin key files, keep exactly one: {names}"
            )
        [(handle, path)] = files.items()
        try:
            jwk = self.read_key(handle, path)
        except InvalidKey as e:
            return self.non_operational(INVALID, str(e))
        kid = self.keys.thumbprint(jwk)
        self.records.bind_admin(conn, handle, kid, jwk)
        self.save_backup(handle, jwk)
        log.warning("admin '%s' bound, fingerprint %s", handle, kid)
        return AdminMode(True, action="bound", handle=handle, fingerprint=kid)

    # ── initialized ─────────────────────────────────────────────────────────────────────────
    def established(self, conn, bound: str, files: dict) -> AdminMode:
        for handle, path in files.items():
            if handle != bound:
                log.error(
                    "ignored %s: it names '%s', but this server's admin is '%s'; "
                    "the admin handle never changes",
                    path.name,
                    handle,
                    bound,
                )
        if bound in files:
            try:
                jwk = self.read_key(bound, files[bound])
            except InvalidKey as e:
                return self.non_operational(INVALID, str(e))
            mode = self.use_key(conn, bound, jwk, "unchanged")
            self.save_backup(bound, jwk)
            return mode
        jwk = self.read_backup(bound)
        if jwk is None:
            return self.non_operational(
                MISSING,
                f"admin_pub_{bound}.key is missing and there is no backup of the admin's "
                f"key; place admin_pub_{bound}.key in {self.where()}",
            )
        log.warning(
            "admin_pub_%s.key is missing: running from the backup of the admin's key",
            bound,
        )
        return self.use_key(conn, bound, jwk, "backup")

    def use_key(self, conn, handle: str, jwk: dict, action: str) -> AdminMode:
        """Make `jwk` the admin's one active key, rebinding when it is not already."""
        kid = self.keys.thumbprint(jwk)
        if kid not in {row["kid"] for row in self.records.admin_keys(conn)}:
            self.records.rebind_admin(conn, handle, kid, jwk)
            log.warning(
                "admin '%s' rebound to a new key, fingerprint %s; the old keys are retired",
                handle,
                kid,
            )
            action = "rebound"
        return AdminMode(True, action=action, handle=handle, fingerprint=kid)

    # ── files ───────────────────────────────────────────────────────────────────────────────
    def read_key(self, handle: str, path: Path) -> dict:
        if not HANDLE.match(handle):
            raise InvalidKey(f"{path.name}: '{handle}' is not a valid handle")
        try:
            jwk = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            raise InvalidKey(f"{path.name}: not a JSON public key ({e})") from None
        if not isinstance(jwk, dict):
            raise InvalidKey(f"{path.name}: not a JSON public key")
        if "d" in jwk:
            raise InvalidKey(
                f"{path.name}: this is a PRIVATE key; place only the public key on the server"
            )
        try:
            self.keys.validate(jwk)
        except ValueError as e:
            raise InvalidKey(f"{path.name}: {e}") from None
        return jwk

    def read_backup(self, handle: str) -> dict | None:
        try:
            saved = json.loads(self.backup.read_text())
            jwk = saved["jwk"]
            self.keys.validate(jwk)
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return jwk if saved.get("handle") == handle else None

    def save_backup(self, handle: str, jwk: dict):
        content = json.dumps({"handle": handle, "jwk": jwk}, sort_keys=True)
        if self.backup.exists() and self.backup.read_text() == content:
            return
        partial = self.backup.with_suffix(".partial")
        partial.write_text(content)
        os.chmod(partial, 0o644)
        os.replace(partial, self.backup)

    def non_operational(self, reason: str, detail: str) -> AdminMode:
        log.error("NOT OPERATIONAL (%s): %s", reason, detail)
        return AdminMode(False, reason=reason)
