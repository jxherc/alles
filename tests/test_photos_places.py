import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

import core.settings
from core.database import Photo
from tests._client import ApiTest


def _png_bytes(color=(120, 90, 200), size=(40, 30)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class PhotosPlacesTests(ApiTest):
    def setUp(self):
        super().setUp()
        # isolate the on-disk photo library so upload/collage don't touch real data/
        self._tmp = tempfile.mkdtemp(prefix="alles7b-")
        self._prev_data = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev_data is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev_data
        super().tearDown()

    def _photo(self, name="pic.jpg", lat=None, lon=None, taken=None, **kw):
        db = self.db()
        exif = {}
        if lat is not None and lon is not None:
            exif = {"lat": lat, "lon": lon}
        p = Photo(
            filename="stored-" + name,
            original_name=name,
            exif=json.dumps(exif),
            taken_at=taken,
            **kw,
        )
        db.add(p)
        db.commit()
        pid = p.id
        db.close()
        return pid

    def _upload(self, name="u.png", color=(10, 20, 30)):
        r = self.client.post(
            "/api/photos/upload",
            files={"file": (name, _png_bytes(color), "image/png")},
        )
        return r.json()["id"]

    # ---- map ----
    def test_map_returns_located_only(self):
        loc = self._photo(lat=37.77, lon=-122.41)
        self._photo(name="nogps.jpg")  # no gps
        d = self.client.get("/api/photos/map").json()
        ids = [pt["id"] for pt in d["points"]]
        self.assertEqual(ids, [loc])

    def test_map_excludes_hidden(self):
        self._photo(lat=1.0, lon=2.0, hidden=True)
        d = self.client.get("/api/photos/map").json()
        self.assertEqual(d["points"], [])

    def test_map_excludes_deleted(self):
        self._photo(lat=1.0, lon=2.0, deleted_at=datetime.utcnow())
        d = self.client.get("/api/photos/map").json()
        self.assertEqual(d["points"], [])

    def test_map_point_shape(self):
        self._photo(lat=10.5, lon=20.25, caption="cliff")
        pt = self.client.get("/api/photos/map").json()["points"][0]
        for k in ("id", "lat", "lon", "thumb", "caption"):
            self.assertIn(k, pt)
        self.assertEqual(pt["lat"], 10.5)
        self.assertEqual(pt["lon"], 20.25)

    def test_map_empty_when_no_gps(self):
        self._photo(name="a.jpg")
        self._photo(name="b.jpg")
        d = self.client.get("/api/photos/map").json()
        self.assertEqual(d["count"], 0)

    # ---- memories ----
    def test_memories_on_this_day_prior_years(self):
        a = self._photo(name="2025.jpg", taken=datetime(2025, 6, 19, 12, 0))
        b = self._photo(name="2024.jpg", taken=datetime(2024, 6, 19, 9, 0))
        d = self.client.get("/api/photos/memories?date=2026-06-19").json()
        ids = [it["id"] for g in d["groups"] for it in g["items"]]
        self.assertIn(a, ids)
        self.assertIn(b, ids)

    def test_memories_excludes_other_days(self):
        self._photo(name="off.jpg", taken=datetime(2025, 6, 18, 12, 0))
        d = self.client.get("/api/photos/memories?date=2026-06-19").json()
        self.assertEqual(d["count"], 0)

    def test_memories_excludes_current_year(self):
        self._photo(name="now.jpg", taken=datetime(2026, 6, 19, 12, 0))
        d = self.client.get("/api/photos/memories?date=2026-06-19").json()
        self.assertEqual(d["count"], 0)

    def test_memories_groups_sorted_recent_first(self):
        self._photo(name="old.jpg", taken=datetime(2022, 6, 19, 12, 0))
        self._photo(name="new.jpg", taken=datetime(2025, 6, 19, 12, 0))
        d = self.client.get("/api/photos/memories?date=2026-06-19").json()
        years_ago = [g["years_ago"] for g in d["groups"]]
        self.assertEqual(years_ago, sorted(years_ago))  # 1, 4 → most recent year first

    def test_memories_excludes_hidden(self):
        self._photo(name="h.jpg", taken=datetime(2025, 6, 19, 12, 0), hidden=True)
        d = self.client.get("/api/photos/memories?date=2026-06-19").json()
        self.assertEqual(d["count"], 0)

    def test_memories_default_date_today(self):
        today = datetime.utcnow()
        self._photo(name="ly.jpg", taken=today.replace(year=today.year - 1))
        d = self.client.get("/api/photos/memories").json()
        self.assertGreaterEqual(d["count"], 1)

    # ---- collage ----
    def test_collage_creates_new_photo(self):
        a = self._upload("a.png", (200, 0, 0))
        b = self._upload("b.png", (0, 200, 0))
        before = self.client.get("/api/photos/list").json()["count"]
        r = self.client.post("/api/photos/collage", json={"ids": [a, b]})
        self.assertEqual(r.status_code, 200)
        self.assertIn("id", r.json())
        after = self.client.get("/api/photos/list").json()["count"]
        self.assertEqual(after, before + 1)

    def test_collage_empty_400(self):
        r = self.client.post("/api/photos/collage", json={"ids": []})
        self.assertEqual(r.status_code, 400)

    def test_collage_skips_unknown_ids(self):
        a = self._upload("a.png", (200, 0, 0))
        r = self.client.post("/api/photos/collage", json={"ids": [a, "does-not-exist"]})
        self.assertEqual(r.status_code, 200)

    def test_make_collage_dimensions(self):
        from services import photos_store as ps

        paths = []
        for i, c in enumerate([(200, 0, 0), (0, 200, 0), (0, 0, 200)]):
            p = Path(self._tmp) / f"src{i}.png"
            p.write_bytes(_png_bytes(c, (60, 40)))
            paths.append(p)
        raw = ps.make_collage(paths, cols=2, cell=100)
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        # 3 images, 2 cols -> 2 rows; width = 2*100, height = 2*100 (square cells)
        self.assertEqual(img.size, (200, 200))
