"""The S3 health check answers within a readiness probe's 1 s timeout, whether the store is
down or hung."""

import socket
import time

import pytest

from symposium_data.runtime import PayloadStore, Settings


def store_at(tmp_path, port: int) -> PayloadStore:
    env = tmp_path / "service.env"
    env.write_text(
        "DATABASE_URL=postgresql://u:p@127.0.0.1:5432/symposium_data\n"
        f"S3_ENDPOINT=http://127.0.0.1:{port}\n"
        "S3_ACCESS_KEY=ak\nS3_SECRET_KEY=sk\nSERVER_ID=6f1c\n"
        "TOKEN_KEY_FILE=/apps/data/config/token_ed25519.pem\n"
    )
    return PayloadStore(Settings(str(env), environ={}))


@pytest.fixture
def listener():
    # accepts connections into its backlog and never answers: a hung store
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    yield sock
    sock.close()


def timed_health(store) -> tuple[bool, float]:
    start = time.monotonic()
    healthy = store.healthy()
    return healthy, time.monotonic() - start


def test_a_stopped_store_is_unhealthy_at_once(tmp_path, listener):
    port = listener.getsockname()[1]
    listener.close()  # nothing listens on the port now
    healthy, elapsed = timed_health(store_at(tmp_path, port))
    assert healthy is False and elapsed < 1


def test_a_hung_store_is_unhealthy_within_the_probe_timeout(tmp_path, listener):
    healthy, elapsed = timed_health(store_at(tmp_path, listener.getsockname()[1]))
    assert healthy is False and elapsed < 1
