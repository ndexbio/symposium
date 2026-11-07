import pytest
from sqlalchemy.exc import OperationalError

from symposium_data.runtime import Database


class Flaky:
    """A connect() that fails `failures` times before PostgreSQL accepts connections."""

    def __init__(self, failures):
        self.failures, self.calls = failures, 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise OperationalError(
                "connect", {}, Exception("not accepting connections yet")
            )
        return self

    def close(self):
        pass


def _database():
    return Database.__new__(Database)


def test_waits_until_postgres_accepts_connections():
    connect = Flaky(failures=3)
    _database().wait_until_reachable(connect, attempts=10, pause=0)
    assert connect.calls == 4


def test_gives_up_after_the_last_attempt():
    connect = Flaky(failures=99)
    with pytest.raises(OperationalError):
        _database().wait_until_reachable(connect, attempts=5, pause=0)
    assert connect.calls == 5
