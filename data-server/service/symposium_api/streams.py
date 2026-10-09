"""The streams' shared machinery (api/DESIGN.md §5.3, §10.5): the caps on open streams,
counted in PostgreSQL so they hold across workers, and the wake-up a stream waits on.

Each open stream is one `api_streams` row, written when it opens and deleted when it closes.
Its heartbeat refreshes `seen`; a row unseen for 90 seconds belongs to a dead worker and is
swept, freeing its slot. A trigger on `versions` sends NOTIFY symposium_api on every write, and
one listener thread per process wakes the streams waiting in that process.
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid

import psycopg

from .errors import ApiError

# seconds between heartbeats, and so between a quiet stream's key re-checks; a test shortens it
HEARTBEAT = float(os.environ.get("SYMPOSIUM_DATA_API_HEARTBEAT", "30"))
STALE = 90  # seconds without a heartbeat before a stream's slot is freed
PER_KEY = 8
PER_ANONYMOUS_ADDRESS = 4
ANONYMOUS_TOTAL = 200


class Caps:
    """The limits default to api/DESIGN.md §10.5; a test passes small ones to reach each."""

    def __init__(
        self,
        db,
        total: int | None = None,
        per_key: int = PER_KEY,
        per_anonymous_address: int = PER_ANONYMOUS_ADDRESS,
        anonymous_total: int = ANONYMOUS_TOTAL,
    ):
        self.db = db
        self.total = total or int(
            os.environ.get("SYMPOSIUM_DATA_API_MAX_STREAMS", "500")
        )
        self.per_key = per_key
        self.per_anonymous_address = per_anonymous_address
        self.anonymous_total = anonymous_total

    def open(self, key_id, role: str | None, client_addr: str | None) -> uuid.UUID:
        """Take a slot, or refuse with 429 past any cap. -> the stream's id."""
        with self.db.connection() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext('symposium_api_streams'))"
            )
            conn.execute(
                "DELETE FROM api_streams WHERE seen < now() - make_interval(secs => %s)",
                (STALE,),
            )
            count = conn.execute("SELECT count(*) AS n FROM api_streams").fetchone()[
                "n"
            ]
            if key_id is not None:
                mine = conn.execute(
                    "SELECT count(*) AS n FROM api_streams WHERE key_id = %s", (key_id,)
                ).fetchone()["n"]
                if mine >= self.per_key:
                    raise ApiError(
                        429, f"this key already holds {self.per_key} open streams"
                    )
            else:
                anonymous = conn.execute(
                    "SELECT count(*) AS n FROM api_streams WHERE key_id IS NULL"
                ).fetchone()["n"]
                here = conn.execute(
                    "SELECT count(*) AS n FROM api_streams "
                    "WHERE key_id IS NULL AND client_addr = %s",
                    (client_addr,),
                ).fetchone()["n"]
                if here >= self.per_anonymous_address:
                    raise ApiError(
                        429,
                        f"this address already holds {self.per_anonymous_address} anonymous streams",
                    )
                if anonymous >= self.anonymous_total:
                    raise ApiError(
                        429, "the server holds its limit of anonymous streams"
                    )
            if count >= self.total:
                raise ApiError(429, "the server holds its limit of open streams")
            stream_id = uuid.uuid4()
            conn.execute(
                "INSERT INTO api_streams (id, key_id, role, client_addr) "
                "VALUES (%s, %s, %s, %s)",
                (stream_id, key_id, role, client_addr),
            )
            return stream_id

    def beat(self, stream_id) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE api_streams SET seen = now() WHERE id = %s", (stream_id,)
            )

    def close(self, stream_id) -> None:
        with self.db.connection() as conn:
            conn.execute("DELETE FROM api_streams WHERE id = %s", (stream_id,))


class Notifier:
    """One LISTEN connection per process; every write to `versions` wakes every waiter."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None
        # counts the writes seen; a stream that read the feed at generation g waits only while
        # it is still g, so a write landing between its read and its wait is never missed
        self.generation = 0

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._listen, name="api-notify", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()

    def _wake(self) -> None:
        with self.lock:
            self.generation += 1
            waiters = list(self.waiters)
        for loop, event in waiters:
            loop.call_soon_threadsafe(event.set)

    def _listen(self) -> None:
        while not self.stopping.is_set():
            try:
                with psycopg.connect(self.database_url, autocommit=True) as conn:
                    conn.execute("LISTEN symposium_api")
                    while not self.stopping.is_set():
                        for _ in conn.notifies(timeout=1.0):
                            self._wake()
            except psycopg.Error:
                self.stopping.wait(1.0)  # the database restarts; listen again

    async def wait(self, timeout: float, seen: int) -> bool:
        """Until a write after generation `seen`, or `timeout` seconds. -> whether a write
        woke it (at once when one already happened)."""
        event = asyncio.Event()
        entry = (asyncio.get_running_loop(), event)
        with self.lock:
            if self.generation != seen:
                return True
            self.waiters.add(entry)
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except TimeoutError:
            return False
        finally:
            with self.lock:
                self.waiters.discard(entry)
