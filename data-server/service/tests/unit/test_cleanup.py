"""The intent-first rule: bytes are removed before the row is completed, and a failed S3
delete leaves the row in place for the janitor."""

from contextlib import contextmanager

import pytest
from botocore.exceptions import ClientError

from symposium_data.cleanup import Cleanup
from symposium_data.runtime import PayloadStore


class FakeDb:
    @contextmanager
    def connection(self):
        yield None


class FakeRecords:
    def __init__(self, pending=None, purging=None):
        self.pending, self.purging = dict(pending or {}), dict(purging or {})
        self.expired, self.events = [], []

    def pending_payload(self, _conn, pid):
        return self.pending.get(pid)

    def drop_pending(self, _conn, pid):
        self.events.append(("drop_row", pid))
        self.pending.pop(pid)

    def expire_pending(self, _conn, pid):
        self.expired.append(pid)

    def purging_payload(self, _conn, pid):
        return self.purging.get(pid)

    def mark_purged(self, _conn, pid):
        self.events.append(("mark_purged", pid))
        self.purging.pop(pid)


class FakeStore:
    def __init__(self, records, fail=False):
        self.records, self.fail = records, fail

    def remove(self, key, upload_id=None):
        if self.fail:
            raise RuntimeError("S3 is down")
        self.records.events.append(("remove_bytes", key))


ROW = {"id": "p1", "s3_key": "payloads/p1", "upload_id": "u1"}


def test_discard_removes_bytes_before_the_row():
    records = FakeRecords(pending={"p1": ROW})
    assert Cleanup(FakeDb(), FakeStore(records), records).discard_pending("p1") is True
    assert records.events == [("remove_bytes", "payloads/p1"), ("drop_row", "p1")]


def test_a_failed_discard_keeps_the_row_and_expires_it_for_the_janitor():
    records = FakeRecords(pending={"p1": ROW})
    assert (
        Cleanup(FakeDb(), FakeStore(records, fail=True), records).discard_pending("p1")
        is False
    )
    assert (
        "p1" in records.pending and records.expired == ["p1"] and records.events == []
    )


def test_discarding_an_already_removed_upload_is_a_no_op():
    records = FakeRecords()
    assert (
        Cleanup(FakeDb(), FakeStore(records), records).discard_pending("gone") is True
    )


def test_purge_frees_bytes_before_marking_purged():
    records = FakeRecords(purging={"p1": ROW})
    assert Cleanup(FakeDb(), FakeStore(records), records).finish_purge("p1") is True
    assert records.events == [("remove_bytes", "payloads/p1"), ("mark_purged", "p1")]


def test_a_failed_purge_stays_purging():
    records = FakeRecords(purging={"p1": ROW})
    assert (
        Cleanup(FakeDb(), FakeStore(records, fail=True), records).finish_purge("p1")
        is False
    )
    assert "p1" in records.purging and records.events == []


class RecordingS3:
    def __init__(self, abort_error=None):
        self.abort_error, self.calls = abort_error, []

    def abort_multipart_upload(self, **kw):
        self.calls.append("abort")
        if self.abort_error:
            raise self.abort_error

    def delete_object(self, **kw):
        self.calls.append("delete")


def _store(s3):
    store = PayloadStore.__new__(PayloadStore)
    store.s3, store.bucket, store.fault_injection = s3, "b", False
    return store


def test_remove_aborts_then_deletes_and_tolerates_a_finished_upload():
    gone = ClientError({"Error": {"Code": "NoSuchUpload"}}, "AbortMultipartUpload")
    s3 = RecordingS3(abort_error=gone)
    _store(s3).remove("k", "u1")
    assert s3.calls == ["abort", "delete"]


def test_remove_raises_on_any_other_abort_error():
    denied = ClientError({"Error": {"Code": "AccessDenied"}}, "AbortMultipartUpload")
    s3 = RecordingS3(abort_error=denied)
    with pytest.raises(ClientError):
        _store(s3).remove("k", "u1")
    assert s3.calls == ["abort"]
