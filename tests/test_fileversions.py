import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from core.database import FileVersion, TrashItem
from services import file_operations
from services import files_store as fs
from services import fileversions as fv
from tests._client import ApiTest


class FileVersionTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "files").mkdir()
        (self.root / "data").mkdir()
        self._patches = [
            mock.patch.object(fs, "files_dir", lambda: self.root / "files"),
            mock.patch.object(fv, "data_dir", lambda: self.root / "data"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _mk(self, rel, content):
        p = fs.files_dir() / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
        return p

    # ── service ──
    def test_snapshot_creates_version(self):
        d = self.db()
        p = self._mk("a.txt", "one")
        v = fv.snapshot(d, "a.txt", p)
        self.assertIsNotNone(v)
        self.assertEqual(d.query(FileVersion).filter_by(path="a.txt").count(), 1)

    def test_snapshot_dedup_same_content(self):
        d = self.db()
        p = self._mk("a.txt", "same")
        fv.snapshot(d, "a.txt", p)
        self.assertIsNone(fv.snapshot(d, "a.txt", p))  # unchanged → no new version
        self.assertEqual(d.query(FileVersion).count(), 1)

    def test_snapshot_skips_too_big(self):
        d = self.db()
        with mock.patch.object(fv, "CAP_BYTES", 4):
            p = self._mk("big.bin", b"toolarge")
            self.assertIsNone(fv.snapshot(d, "big.bin", p))
        self.assertEqual(d.query(FileVersion).count(), 0)

    def test_snapshot_missing_file_none(self):
        d = self.db()
        self.assertIsNone(fv.snapshot(d, "ghost.txt", fs.files_dir() / "ghost.txt"))

    def test_prune_caps_history(self):
        d = self.db()
        with mock.patch.object(fv, "KEEP", 3):
            for i in range(6):
                p = self._mk("h.txt", f"content-{i}")
                fv.snapshot(d, "h.txt", p)
        self.assertEqual(d.query(FileVersion).filter_by(path="h.txt").count(), 3)

    def test_restore_copies_blob_back(self):
        d = self.db()
        p = self._mk("r.txt", "original")
        v = fv.snapshot(d, "r.txt", p)
        p.write_bytes(b"changed")
        fv.restore(d, v.id, p)
        self.assertEqual(p.read_text(), "original")

    def test_list_versions_desc(self):
        d = self.db()
        for c in ("v1", "v2", "v3"):
            p = self._mk("l.txt", c)
            fv.snapshot(d, "l.txt", p)
        vs = fv.list_versions(d, "l.txt")
        self.assertEqual(len(vs), 3)
        self.assertGreaterEqual(vs[0].created_at, vs[-1].created_at)

    def test_restore_unknown_none(self):
        d = self.db()
        self.assertIsNone(fv.restore(d, "nope", fs.files_dir() / "x.txt"))

    # ── upload route ──
    def _upload(self, name, content, path=""):
        return self.client.post(
            "/api/files/upload",
            data={"path": path},
            files={"file": (name, content.encode() if isinstance(content, str) else content)},
        )

    def test_upload_overwrite_snapshots(self):
        self._upload("v.txt", "a")
        self._upload("v.txt", "b")
        vs = self.client.get("/api/files/versions", params={"path": "v.txt"}).json()
        self.assertEqual(len(vs), 1)  # one prior version (content "a")

    def test_upload_twice_two_versions(self):
        self._upload("v.txt", "a")
        self._upload("v.txt", "b")
        self._upload("v.txt", "c")
        vs = self.client.get("/api/files/versions", params={"path": "v.txt"}).json()
        self.assertEqual(len(vs), 2)

    def test_api_delete_preserves_versions_until_trash_is_purged(self):
        self._upload("gone.txt", "a")
        self._upload("gone.txt", "b")
        d = self.db()
        v = d.query(FileVersion).filter_by(path="gone.txt").first()
        blob = fv.versions_dir() / v.stored
        self.assertTrue(blob.exists())

        r = self.client.request("DELETE", "/api/files/delete", params={"path": "gone.txt"})

        self.assertEqual(r.status_code, 200)
        d.expire_all()
        self.assertEqual(d.query(FileVersion).filter_by(path="gone.txt").count(), 0)
        self.assertTrue(blob.exists())

        trash_id = self.client.get("/api/files/trash").json()[0]["id"]
        restored = self.client.post("/api/files/trash/restore", json={"id": trash_id})
        self.assertEqual(restored.status_code, 200, restored.text)
        d.expire_all()
        self.assertEqual(d.query(FileVersion).filter_by(path="gone.txt").count(), 1)
        self.assertTrue(blob.exists())

        deleted_again = self.client.request(
            "DELETE", "/api/files/delete", params={"path": "gone.txt"}
        )
        self.assertEqual(deleted_again.status_code, 200, deleted_again.text)
        d.expire_all()
        item = d.query(TrashItem).filter_by(normalized_path="gone.txt").one()
        item.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        d.commit()
        purged = self.client.post("/api/files/trash/purge")
        self.assertEqual(purged.status_code, 200, purged.text)
        self.assertEqual(purged.json()["purged"], 1)
        self.assertFalse(blob.exists())

    def test_api_delete_does_not_purge_a_post_operation_replacement_version(self):
        self._upload("raced.txt", "old bytes")
        from routes import files as files_routes

        original_run = files_routes._run_file_operation
        replacement = {}

        def replace_after_durable_delete(db, **kwargs):
            result = original_run(db, **kwargs)
            path = self._mk("raced.txt", "replacement bytes")
            version = fv.snapshot(db, "raced.txt", path)
            replacement.update(
                {
                    "id": version.id,
                    "blob": fv.versions_dir() / version.stored,
                }
            )
            return result

        with mock.patch.object(
            files_routes,
            "_run_file_operation",
            side_effect=replace_after_durable_delete,
        ):
            response = self.client.request(
                "DELETE",
                "/api/files/delete",
                params={"path": "raced.txt"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((fs.files_dir() / "raced.txt").read_text(), "replacement bytes")
        db = self.db()
        self.assertIsNotNone(db.get(FileVersion, replacement["id"]))
        db.close()
        self.assertTrue(replacement["blob"].exists())

    def test_upload_pathological_filename_rejected(self):
        # names that strip to nothing ("." "/" "...") used to write onto the dir itself -> 500.
        # now a clean 400. (empty "" is rejected earlier by fastapi's File(...) as 422.)
        for fn in (".", "/", "..."):
            self.assertEqual(self._upload(fn, "data").status_code, 400, f"{fn!r}")

    def test_api_versions_list_shape(self):
        self._upload("s.txt", "a")
        self._upload("s.txt", "b")
        v = self.client.get("/api/files/versions", params={"path": "s.txt"}).json()[0]
        self.assertIn("id", v)
        self.assertIn("size", v)
        self.assertIn("created_at", v)

    def test_api_restore_reverts_content(self):
        self._upload("doc.txt", "first")
        self._upload("doc.txt", "second")
        vid = self.client.get("/api/files/versions", params={"path": "doc.txt"}).json()[-1]["id"]
        r = self.client.post("/api/files/versions/restore", json={"path": "doc.txt", "id": vid})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((fs.files_dir() / "doc.txt").read_text(), "first")

    def test_api_restore_unknown_404(self):
        r = self.client.post("/api/files/versions/restore", json={"path": "x.txt", "id": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_api_restore_rechecks_version_identity_after_path_claim(self):
        self._upload("raced-restore.txt", "first")
        self._upload("raced-restore.txt", "second")
        version_id = self.client.get(
            "/api/files/versions",
            params={"path": "raced-restore.txt"},
        ).json()[-1]["id"]
        original_claim = file_operations.direct_mutation_claim
        moved = False

        @contextmanager
        def move_before_claim(db, location, path):
            nonlocal moved
            if not moved:
                moved = True
                operation = file_operations.enqueue(
                    db,
                    action="move",
                    source_location_id=location.id,
                    source_path=path,
                    destination_location_id=location.id,
                    destination_path="moved-restore.txt",
                )
                file_operations.run(db, operation)
            with original_claim(db, location, path) as claim:
                yield claim

        with mock.patch(
            "routes.files.file_operations.direct_mutation_claim",
            side_effect=move_before_claim,
        ):
            response = self.client.post(
                "/api/files/versions/restore",
                json={"path": "raced-restore.txt", "id": version_id},
            )

        self.assertEqual(response.status_code, 404, response.text)
        self.assertFalse((fs.files_dir() / "raced-restore.txt").exists())
        self.assertEqual((fs.files_dir() / "moved-restore.txt").read_text(), "second")
        db = self.db()
        version = db.get(FileVersion, version_id)
        self.assertEqual(version.normalized_path, "moved-restore.txt")
        db.close()
