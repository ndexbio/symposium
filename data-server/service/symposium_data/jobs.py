"""Background jobs of the API process: the janitor and the at-rest integrity scrub (R-F3)."""

from __future__ import annotations

import logging
import threading

from .cleanup import Cleanup
from .records import Records
from .runtime import Database, PayloadStore, Settings

log = logging.getLogger("symposium_data.jobs")


class Jobs:
    def __init__(
        self, settings: Settings, db: Database, store: PayloadStore, records: Records
    ):
        self.settings, self.db, self.store, self.records = settings, db, store, records
        self.cleanup = Cleanup(db, store, records)
        self.stop = threading.Event()
        self.threads = []

    def start(self):
        for name, interval, job in (
            ("janitor", self.settings.janitor_interval, self.sweep_pending),
            ("scrub", self.settings.scrub_interval, self.scrub),
        ):
            thread = threading.Thread(
                target=self._every, args=(interval, job), name=name, daemon=True
            )
            thread.start()
            self.threads.append(thread)

    def shutdown(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=10)

    def _every(self, interval: float, job):
        while not self.stop.wait(interval):
            try:
                job()
            except Exception:
                log.exception("background job %s failed", job.__name__)

    def sweep_pending(self) -> int:
        """Remove what a crash or a failed S3 delete left behind (R-A6): name reservations that
        never turned live, pending uploads (bytes first, then the row) and purged payloads
        whose bytes are not yet freed. It also erases the secret of every invite that expired
        unused (R-D6). -> how many items are still waiting for a retry."""
        with self.db.connection() as conn:
            self.records.forget_expired_invites(conn)
            self.records.stale_reservations(conn, self.settings.pending_ttl)
            stale = self.records.stale_pending(conn, self.settings.pending_ttl)
            purging = self.records.purging_payloads(conn)
        waiting = sum(not self.cleanup.discard_pending(row["id"]) for row in stale)
        waiting += sum(not self.cleanup.finish_purge(row["id"]) for row in purging)
        return waiting

    def scrub(self) -> int:
        """Re-hash the least recently checked payloads; a mismatch is recorded, never repaired."""
        with self.db.connection() as conn:
            batch = self.records.scrub_candidates(conn, self.settings.scrub_batch)
        mismatches = 0
        for row in batch:
            try:
                ok = self.store.digest(row["s3_key"]) == row["sha256"]
            except Exception:
                ok = False
            mismatches += not ok
            with self.db.connection() as conn:
                self.records.record_scrub(conn, row["id"], ok)
        return mismatches
