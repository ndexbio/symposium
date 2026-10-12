"""The S3 health check fits inside a readiness probe's 1 s timeout by how its client is
configured, never by how fast a machine happens to be: one attempt, half a second to connect
and half a second to read. Whether the store is down or hung, it answers unhealthy."""

import socket

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


def test_the_probe_makes_one_attempt_within_the_probe_timeout(tmp_path, listener):
    config = store_at(tmp_path, listener.getsockname()[1]).probe.meta.config
    assert config.retries["total_max_attempts"] == 1
    assert config.connect_timeout + config.read_timeout <= 1


def test_a_stopped_store_is_unhealthy(tmp_path, listener):
    port = listener.getsockname()[1]
    listener.close()  # nothing listens on the port now
    assert store_at(tmp_path, port).healthy() is False


def test_a_hung_store_is_unhealthy(tmp_path, listener):
    assert store_at(tmp_path, listener.getsockname()[1]).healthy() is False
