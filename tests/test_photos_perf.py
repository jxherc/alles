"""phase 4 — served aspect_ratio + blur-up preview, /list paging, and the backfill."""

import io

from PIL import Image

from core.database import Photo
from services import photos_store
from tests._client import ApiTest


def _img(w, h):
    im = Image.new("RGB", (w, h), (80, 90, 160))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


def _items(d):
    return [i for m in d.get("moments", []) for i in m["items"]]


class PhotosPerfTests(ApiTest):
    def _upload(self, name, w, h):
        return self.client.post(
            "/api/photos/upload", files={"file": (name, _img(w, h), "image/jpeg")}
        ).json()

    def test_upload_sets_perf_fields(self):
        d = self._upload("a.jpg", 1600, 900)
        self.assertAlmostEqual(d["aspect_ratio"], 1600 / 900, places=2)
        self.assertTrue(d["preview"].startswith("data:image/jpeg;base64,"))
        self.assertGreater(len(d["preview"]), 40)

    def test_paging_next_cursor(self):
        for i in range(5):
            self._upload(f"p{i}.jpg", 800, 600)
        p0 = self.client.get("/api/photos/list?limit=2&offset=0").json()
        self.assertEqual(len(_items(p0)), 2)
        self.assertEqual(p0["next"], 2)
        last = self.client.get("/api/photos/list?limit=2&offset=4").json()
        self.assertEqual(len(_items(last)), 1)
        self.assertIsNone(last["next"])

    def test_no_limit_returns_all_without_next(self):
        for i in range(3):
            self._upload(f"q{i}.jpg", 800, 600)
        d = self.client.get("/api/photos/list").json()
        self.assertEqual(len(_items(d)), 3)
        self.assertNotIn("next", d)  # unpaged response has no cursor

    def test_backfill_populates_missing(self):
        # simulate a pre-phase-4 row: import, then null out the perf fields
        d = self._upload("b.jpg", 1200, 800)
        db = self.db()
        p = db.get(Photo, d["id"])
        p.checksum = None
        p.preview = ""
        p.aspect_ratio = None
        db.commit()
        db.close()
        db = self.db()
        n = photos_store.backfill_perf(db)
        db.close()
        self.assertGreaterEqual(n, 1)
        d2 = next(i for i in _items(self.client.get("/api/photos/list").json()) if i["id"] == d["id"])
        self.assertTrue(d2["preview"].startswith("data:image/jpeg;base64,"))
        self.assertAlmostEqual(d2["aspect_ratio"], 1200 / 800, places=2)

    def test_backfill_is_noop_second_run(self):
        self._upload("c.jpg", 800, 800)
        db = self.db()
        photos_store.backfill_perf(db)  # first run (already set on import → likely 0)
        n2 = photos_store.backfill_perf(db)  # nothing left missing
        db.close()
        self.assertEqual(n2, 0)
