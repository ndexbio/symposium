import hashlib
import os

from symposium_data.runtime import PART_SIZE, MultipartWriter


class FakeS3:
    def __init__(self):
        self.objects, self.uploads, self.aborted = {}, {}, []

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body

    def create_multipart_upload(self, Bucket, Key):
        self.uploads[Key] = []
        return {"UploadId": "u1"}

    def upload_part(self, Bucket, Key, UploadId, PartNumber, Body):
        self.uploads[Key].append(Body)
        return {"ETag": f"e{PartNumber}"}

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        assert [p["PartNumber"] for p in MultipartUpload["Parts"]] == list(
            range(1, len(self.uploads[Key]) + 1)
        )
        self.objects[Key] = b"".join(self.uploads.pop(Key))

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted.append(Key)
        self.uploads.pop(Key, None)

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


class FakeStore:
    bucket = "b"

    def __init__(self):
        self.s3 = FakeS3()

    def put_bytes(self, key, data):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def abort(self, key, upload_id):
        self.s3.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)

    def delete(self, key):
        self.s3.delete_object(Bucket=self.bucket, Key=key)


def test_small_body_is_one_put_and_hashed():
    store = FakeStore()
    w = MultipartWriter(store, "k")
    w.write(b"abc")
    w.finish()
    assert store.s3.objects["k"] == b"abc"
    assert w.hexdigest() == hashlib.sha256(b"abc").hexdigest() and w.size == 3


def test_large_body_streams_in_parts_and_reports_the_upload():
    store, started = FakeStore(), []
    body = os.urandom(PART_SIZE * 2 + 1234)
    w = MultipartWriter(store, "k", on_upload_started=started.append)
    for i in range(0, len(body), 100_000):
        w.write(body[i : i + 100_000])
    w.finish()
    assert store.s3.objects["k"] == body
    assert started == ["u1"]
    assert w.hexdigest() == hashlib.sha256(body).hexdigest()


def test_abort_removes_a_partial_upload():
    store = FakeStore()
    w = MultipartWriter(store, "k")
    w.write(os.urandom(PART_SIZE + 1))
    w.abort()
    assert store.s3.aborted == ["k"] and "k" not in store.s3.objects
