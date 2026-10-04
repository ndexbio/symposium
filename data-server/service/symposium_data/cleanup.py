"""Removing payload bytes safely across S3 and PostgreSQL, which share no transaction.

The rule (R-A6): the row that records the intent exists before the bytes are touched; the
bytes are removed first; the row is completed only after that succeeds. When S3 fails, the
row is left as it is, still saying "these bytes are garbage", and the janitor retries. Every
object in the bucket is therefore always accounted for by a row.
"""

from __future__ import annotations

import logging
import time

from .records import Records
from .runtime import Database, PayloadStore

log = logging.getLogger("symposium_data.cleanup")


class PendingBatch:
    """Payloads uploaded ahead of the one transaction that commits them all (an import, a
    port). Their heartbeat keeps the janitor away while the work goes on: it expires only work
    that has stopped (R-A6)."""

    def __init__(self, db: Database, records: Records, interval: float):
        self.db, self.records, self.interval = db, records, interval
        self.pids, self.last = [], time.monotonic()

    def add(self, pid):
        self.pids.append(pid)

    def beat(self, now: bool = False):
        """Touch every payload of the batch, at most once per interval unless `now`."""
        if self.pids and (now or time.monotonic() - self.last >= self.interval):
            with self.db.connection() as conn:
                self.records.touch_pending_many(conn, self.pids)
            self.last = time.monotonic()


class Cleanup:
    def __init__(self, db: Database, store: PayloadStore, records: Records):
        self.db, self.store, self.records = db, store, records

    def discard_pending(self, pid) -> bool:
        """An unreferenced upload: bytes first, row second. -> True when fully removed."""
        with self.db.connection() as conn:
            row = self.records.pending_payload(conn, pid)
        if row is None:
            return True
        try:
            self.store.remove(row["s3_key"], row["upload_id"])
        except Exception:
            log.warning(
                "could not remove the bytes of pending payload %s; will retry", pid
            )
            with self.db.connection() as conn:
                self.records.expire_pending(conn, pid)
            return False
        with self.db.connection() as conn:
            self.records.drop_pending(conn, pid)
        return True

    def finish_purge(self, pid) -> bool:
        """A purged payload: bytes first, then 'purging' -> 'purged'. -> True when freed."""
        with self.db.connection() as conn:
            row = self.records.purging_payload(conn, pid)
        if row is None:
            return True
        try:
            self.store.remove(row["s3_key"])
        except Exception:
            log.warning(
                "could not free the bytes of purged payload %s; will retry", pid
            )
            return False
        with self.db.connection() as conn:
            self.records.mark_purged(conn, pid)
        return True
