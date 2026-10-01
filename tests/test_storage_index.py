import tempfile
from pathlib import Path
from unittest import mock

from core.database import IndexChunk, StorageLocation
from services import storage_index
from tests._client import ApiTest


class StorageLocationIndexTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "notes").mkdir()
        (self.root / "notes" / "plan.md").write_text(
            "phase seven keeps storage locations separate", encoding="utf-8"
        )
        (self.root / "ignore.bin").write_bytes(b"\x00\xff\x00\xff")

    def tearDown(self):
        self.tmp.cleanup()
        super().tearDown()

    def _location(self) -> dict:
        response = self.client.post(
            "/api/storage-locations",
            json={
                "name": "indexed archive",
                "kind": "local",
                "access": "read_only",
                "root_path": str(self.root),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_background_index_is_location_scoped_repeatable_and_read_only(self):
        location = self._location()

        started = self.client.post(f"/api/storage-locations/{location['id']}/index")
        self.assertEqual(started.status_code, 200, started.text)

        status = self.client.get(f"/api/storage-locations/{location['id']}/index")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["state"], "completed")
        self.assertEqual(status.json()["files_indexed"], 1)

        db = self.db()
        rows = db.query(IndexChunk).filter_by(kind="file", location_id=location["id"]).all()
        self.assertTrue(rows)
        self.assertEqual({row.normalized_path for row in rows}, {"notes/plan.md"})
        self.assertIn("phase seven", " ".join(row.text for row in rows))
        first_count = len(rows)
        db.close()

        (self.root / "notes" / "plan.md").write_text(
            "phase seven was reindexed without duplicate chunks", encoding="utf-8"
        )
        second = self.client.post(f"/api/storage-locations/{location['id']}/index")
        self.assertEqual(second.status_code, 200, second.text)

        db = self.db()
        rows = db.query(IndexChunk).filter_by(kind="file", location_id=location["id"]).all()
        self.assertEqual(len(rows), first_count)
        self.assertIn("reindexed", " ".join(row.text for row in rows))
        self.assertNotIn("keeps storage", " ".join(row.text for row in rows))
        db.close()

        self.assertEqual(
            (self.root / "notes" / "plan.md").read_text(encoding="utf-8"),
            "phase seven was reindexed without duplicate chunks",
        )

    def test_unknown_location_cannot_start_indexing(self):
        response = self.client.post("/api/storage-locations/missing/index")
        self.assertEqual(response.status_code, 404)

    def test_location_cannot_be_removed_while_indexing_is_queued(self):
        location = self._location()
        storage_index.enqueue(location["id"])
        self.addCleanup(storage_index.forget, location["id"])

        response = self.client.delete(f"/api/storage-locations/{location['id']}")

        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertIsNotNone(db.get(StorageLocation, location["id"]))
        db.close()

    def test_worker_does_not_recreate_index_after_location_is_deleted(self):
        location = self._location()
        storage_index.enqueue(location["id"])
        self.addCleanup(storage_index.forget, location["id"])

        def delete_during_collection(_row):
            db = self.db()
            db.query(StorageLocation).filter_by(id=location["id"]).delete()
            db.commit()
            db.close()
            return [("notes/plan.md", "must not become an orphan")], 1

        with mock.patch.object(
            storage_index,
            "_collect",
            side_effect=delete_during_collection,
        ):
            storage_index.run(location["id"])

        db = self.db()
        self.assertEqual(
            db.query(IndexChunk).filter_by(location_id=location["id"]).count(),
            0,
        )
        db.close()

    def test_index_collection_has_a_total_text_memory_limit(self):
        row = StorageLocation(
            id="bounded-index",
            name="bounded",
            kind="local",
            access="read_only",
            root_path=str(self.root),
            enabled=True,
        )
        with self.assertRaisesRegex(RuntimeError, "too much text"):
            with mock.patch.object(storage_index, "MAX_INDEX_TEXT_BYTES", 8):
                storage_index._collect(row)

    def test_unknown_remote_size_is_indexed_through_a_bounded_read(self):
        row = StorageLocation(
            id="unknown-size-index",
            name="unknown size",
            kind="webdav",
            access="read_only",
            endpoint="https://dav.example.test",
            enabled=True,
        )
        item = {
            "path": "notes/unknown.md",
            "normalized_path": "notes/unknown.md",
            "type": "file",
            "size": None,
            "etag": '"unknown"',
        }
        payload = b"bounded unknown-size text"

        def download(_row, _path, target, **kwargs):
            self.assertIsNone(kwargs["expected_size"])
            self.assertEqual(kwargs["max_bytes"], storage_index.MAX_FILE_BYTES)
            target.write_bytes(payload)
            return {"size": len(payload), "checksum": "", "etag": '"unknown"'}

        with (
            mock.patch.object(
                storage_index.storage_backends,
                "listdir",
                return_value={"items": [item]},
            ),
            mock.patch.object(storage_index.storage_backends, "item", return_value=item),
            mock.patch.object(
                storage_index.storage_backends,
                "download",
                side_effect=download,
            ),
        ):
            records, seen = storage_index._collect(row)

        self.assertEqual(seen, 1)
        self.assertEqual(records, [("notes/unknown.md", payload.decode())])

    def test_remote_search_uses_the_location_index_without_opening_a_local_root(self):
        db = self.db()
        db.add(
            StorageLocation(
                id="remote-index",
                name="remote",
                kind="webdav",
                access="read_only",
                endpoint="https://dav.example.test",
                enabled=True,
            )
        )
        db.add(
            IndexChunk(
                kind="file",
                ref="notes/plan.md",
                location_id="remote-index",
                normalized_path="notes/plan.md",
                text="phase seven remote search works",
            )
        )
        db.commit()
        db.close()
        response = self.client.get(
            "/api/files/search",
            params={"location_id": "remote-index", "q": "remote search"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["results"][0]["path"], "notes/plan.md")
