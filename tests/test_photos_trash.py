import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from core.database import Photo, TrashItem
from services import photos_store as ps
from services import trash
from tests._client import ApiTest

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f1f0000000049454e44ae426082"
)


class PhotosTrashTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "photos" / ".thumbs").mkdir(parents=True)
        (root / "data").mkdir()
        self._patches = [
            mock.patch.object(ps, "photos_dir", lambda: root / "photos"),
            mock.patch.object(ps, "thumbs_dir", lambda: root / "photos" / ".thumbs"),
            mock.patch.object(trash, "data_dir", lambda: root / "data"),
        ]
        for p in self._patches:
            p.start()
        self.root = root

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _photo(self, name="p.png", *, is_video=False):
        data = b"\x00\x00ftypmp42moov" if is_video else _PNG
        (self.root / "photos" / name).write_bytes(data)
        if not is_video:
            (self.root / "photos" / ".thumbs" / name).write_bytes(_PNG)
        d = self.db()
        ph = Photo(
            filename=name, thumb="" if is_video else name, original_name=name, is_video=is_video
        )
        d.add(ph)
        d.commit()
        pid = ph.id
        d.close()
        return pid

    def test_delete_soft_hides_from_list(self):
        pid = self._photo()
        self.client.delete(f"/api/photos/{pid}")
        listing = self.client.get("/api/photos/list").json()
        ids = [it["id"] for m in listing["moments"] for it in m["items"]]
        self.assertNotIn(pid, ids)
        # file is kept on disk (recoverable)
        self.assertTrue((self.root / "photos" / "p.png").exists())

    def test_delete_records_trash(self):
        pid = self._photo()
        self.client.delete(f"/api/photos/{pid}")
        self.assertEqual(self.db().query(TrashItem).filter_by(kind="photo", ref=pid).count(), 1)

    def test_trash_lists_deleted(self):
        pid = self._photo()
        self.client.delete(f"/api/photos/{pid}")
        tr = self.client.get("/api/photos/trash").json()
        self.assertTrue(any(t["id"] == pid for t in tr))

    def test_video_trash_item_carries_video_render_data(self):
        pid = self._photo("clip.mp4", is_video=True)
        self.client.delete(f"/api/photos/{pid}")
        item = next(t for t in self.client.get("/api/photos/trash").json() if t["id"] == pid)
        self.assertTrue(item["is_video"])
        self.assertEqual(item["thumb"], f"/api/photos/thumb/{pid}")
        self.assertEqual(item["original"], f"/api/photos/original/{pid}")

    def test_video_without_thumb_does_not_serve_original_as_thumb(self):
        pid = self._photo("clip.mp4", is_video=True)
        self.client.delete(f"/api/photos/{pid}")
        r = self.client.get(f"/api/photos/thumb/{pid}")
        self.assertEqual(r.status_code, 404)

    def test_restore_unhides(self):
        pid = self._photo()
        self.client.delete(f"/api/photos/{pid}")
        r = self.client.post(f"/api/photos/{pid}/restore")
        self.assertEqual(r.status_code, 200)
        listing = self.client.get("/api/photos/list").json()
        ids = [it["id"] for m in listing["moments"] for it in m["items"]]
        self.assertIn(pid, ids)

    def test_restore_removes_trash_item(self):
        pid = self._photo()
        self.client.delete(f"/api/photos/{pid}")
        self.client.post(f"/api/photos/{pid}/restore")
        self.assertEqual(self.db().query(TrashItem).filter_by(ref=pid).count(), 0)

    def test_search_excludes_deleted(self):
        pid = self._photo("beach.png")
        self.client.delete(f"/api/photos/{pid}")
        hits = self.client.get("/api/photos/search", params={"q": "beach"}).json()
        ids = [it["id"] for m in hits["moments"] for it in m["items"]]
        self.assertNotIn(pid, ids)

    def test_delete_unknown_404(self):
        self.assertEqual(self.client.delete("/api/photos/nope").status_code, 404)

    def test_restore_non_deleted_404(self):
        pid = self._photo()
        self.assertEqual(self.client.post(f"/api/photos/{pid}/restore").status_code, 404)

    def test_purge_photo_hard_deletes(self):
        pid = self._photo()
        self.client.delete(f"/api/photos/{pid}")
        d = self.db()
        it = d.query(TrashItem).filter_by(ref=pid).first()
        it.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        d.commit()
        trash.purge_expired(d)
        self.assertIsNone(d.get(Photo, pid))
        self.assertFalse((self.root / "photos" / "p.png").exists())
