import os
import tempfile
import time
import uuid
from pathlib import Path
from unittest import mock

import routes.uploads as up
from tests._client import ApiTest


class UploadsApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = up.UPLOAD_DIR
        up.UPLOAD_DIR = Path(self._tmp.name)

    def tearDown(self):
        up.UPLOAD_DIR = self._orig_dir
        self._tmp.cleanup()
        super().tearDown()

    def test_upload_serve_delete(self):
        r = self.client.post(
            "/api/uploads", files={"file": ("notes.txt", b"hello world", "text/plain")}
        )
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["name"], "notes.txt")
        self.assertEqual(j["size"], 11)
        self.assertEqual(j["type"], "text/plain")
        uid = j["id"]
        self.assertEqual(self.client.get(f"/api/uploads/{uid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/uploads/{uid}").json(), {"ok": True})
        self.assertEqual(self.client.get(f"/api/uploads/{uid}").status_code, 404)

    def test_too_large_rejected(self):
        orig = up.MAX_SIZE
        up.MAX_SIZE = 8
        try:
            r = self.client.post(
                "/api/uploads",
                files={"file": ("big.bin", b"123456789", "application/octet-stream")},
            )
            self.assertEqual(r.status_code, 400)
        finally:
            up.MAX_SIZE = orig

    def test_missing_404(self):
        self.assertEqual(self.client.get("/api/uploads/nope").status_code, 404)
        self.assertEqual(self.client.delete("/api/uploads/nope").status_code, 404)

    def test_upload_returns_id_and_metadata(self):
        r = self.client.post("/api/uploads", files={"file": ("pic.png", b"\x89PNG", "image/png")})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn("id", j)
        self.assertEqual(j["type"], "image/png")
        self.assertEqual(j["size"], 4)

    def test_client_upload_id_allows_cancellation_after_the_response_is_lost(self):
        upload_id = str(uuid.uuid4())
        uploaded = self.client.post(
            "/api/uploads",
            data={"upload_id": upload_id},
            files={"file": ("cancel.txt", b"private", "text/plain")},
        )

        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["id"], upload_id)
        cancelled = self.client.delete(f"/api/uploads/{upload_id}", params={"pending": True})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(self.client.get(f"/api/uploads/{upload_id}").status_code, 404)
        retried = self.client.post(
            "/api/uploads",
            data={"upload_id": upload_id},
            files={"file": ("retry.txt", b"retry", "text/plain")},
        )
        self.assertEqual(retried.status_code, 409, retried.text)
        self.assertIn("upload cancelled", retried.text)
        retried_again = self.client.post(
            "/api/uploads",
            data={"upload_id": upload_id},
            files={"file": ("retry-again.txt", b"retry", "text/plain")},
        )
        self.assertEqual(retried_again.status_code, 409, retried_again.text)
        self.assertTrue(up._cancellation_path(upload_id).exists())

    def test_generated_upload_id_roundtrips_through_pending_delete(self):
        uploaded = self.client.post(
            "/api/uploads", files={"file": ("cancel.txt", b"private", "text/plain")}
        )
        upload_id = uploaded.json()["id"]
        self.assertEqual(str(uuid.UUID(upload_id)), upload_id)
        cancelled = self.client.delete(f"/api/uploads/{upload_id}", params={"pending": True})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(self.client.get(f"/api/uploads/{upload_id}").status_code, 404)

    def test_upload_id_is_unique_across_normal_and_incognito_stores(self):
        upload_id = str(uuid.uuid4())
        normal = self.client.post(
            "/api/uploads",
            data={"upload_id": upload_id},
            files={"file": ("normal.txt", b"normal", "text/plain")},
        )
        self.assertEqual(normal.status_code, 200, normal.text)
        private = self.client.post(
            "/api/uploads?incognito=true",
            data={"upload_id": upload_id},
            files={"file": ("private.txt", b"private", "text/plain")},
        )
        self.assertEqual(private.status_code, 409, private.text)

    def test_cancellation_that_wins_the_race_prevents_later_persistence(self):
        upload_id = str(uuid.uuid4())
        cancelled = self.client.delete(f"/api/uploads/{upload_id}", params={"pending": True})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)

        uploaded = self.client.post(
            "/api/uploads",
            data={"upload_id": upload_id},
            files={"file": ("cancel.txt", b"private", "text/plain")},
        )

        self.assertEqual(uploaded.status_code, 409, uploaded.text)
        self.assertIn("upload cancelled", uploaded.text)
        self.assertEqual(self.client.get(f"/api/uploads/{upload_id}").status_code, 404)

    def test_pending_cancellation_markers_expire_and_stay_bounded(self):
        expired_id = str(uuid.uuid4())
        current_ids = [str(uuid.uuid4()) for _ in range(3)]
        self.assertEqual(
            self.client.delete(f"/api/uploads/{expired_id}", params={"pending": True}).status_code,
            200,
        )
        expired = up._cancellation_path(expired_id)
        old = time.time() - up.CANCELLATION_TTL_SECONDS - 1
        expired.touch()
        expired.chmod(0o600)
        os.utime(expired, (old, old))

        with mock.patch.object(up, "MAX_CANCELLATION_MARKERS", 2):
            for upload_id in current_ids:
                response = self.client.delete(f"/api/uploads/{upload_id}", params={"pending": True})
                self.assertEqual(response.status_code, 200, response.text)

        markers = list((up.upload_dir() / ".cancelled").iterdir())
        self.assertLessEqual(len(markers), 2)
        self.assertFalse(expired.exists())

    def test_read_only_cancellation_prune_keeps_an_exact_full_set(self):
        marker_ids = [str(uuid.uuid4()) for _ in range(2)]
        directory = up.upload_dir() / ".cancelled"
        directory.mkdir(parents=True)
        for upload_id in marker_ids:
            up._cancellation_path(upload_id).touch()

        with mock.patch.object(up, "MAX_CANCELLATION_MARKERS", len(marker_ids)):
            up._prune_cancellations()

        self.assertEqual(
            {path.name for path in directory.iterdir()},
            set(marker_ids),
        )

    def test_upload_multiple_independent_ids(self):
        a = self.client.post("/api/uploads", files={"file": ("a.txt", b"aaa", "text/plain")}).json()
        b = self.client.post("/api/uploads", files={"file": ("b.txt", b"bbb", "text/plain")}).json()
        self.assertNotEqual(a["id"], b["id"])

    def test_upload_exact_size_limit_ok(self):
        orig = up.MAX_SIZE
        up.MAX_SIZE = 5
        try:
            r = self.client.post(
                "/api/uploads", files={"file": ("ok.bin", b"12345", "application/octet-stream")}
            )
            self.assertEqual(r.status_code, 200)
        finally:
            up.MAX_SIZE = orig

    def test_delete_removes_file_from_disk(self):
        r = self.client.post(
            "/api/uploads", files={"file": ("tmp.txt", b"data", "text/plain")}
        ).json()
        uid = r["id"]
        files_before = list(Path(self._tmp.name).iterdir())
        self.assertEqual(len(files_before), 1)
        self.client.delete(f"/api/uploads/{uid}")
        files_after = list(Path(self._tmp.name).iterdir())
        self.assertEqual(len(files_after), 0)

    def test_delete_twice_second_is_404(self):
        r = self.client.post("/api/uploads", files={"file": ("x.txt", b"x", "text/plain")}).json()
        uid = r["id"]
        self.assertEqual(self.client.delete(f"/api/uploads/{uid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/uploads/{uid}").status_code, 404)

    def test_upload_no_extension_stores_fine(self):
        r = self.client.post(
            "/api/uploads", files={"file": ("noext", b"raw", "application/octet-stream")}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "noext")
