"""phase 5 — structured timeline filters on /list + the /facets camera list."""

import json
from datetime import datetime

from core.database import Photo
from tests._client import ApiTest


def _items(d):
    return [i for m in d.get("moments", []) for i in m["items"]]


def _ids(d):
    return [i["id"] for i in _items(d)]


class PhotosFilterTests(ApiTest):
    def _photo(self, name="f.jpg", **kw):
        db = self.db()
        p = Photo(filename="stored-" + name, original_name=name, **kw)
        db.add(p)
        db.commit()
        pid = p.id
        db.close()
        return pid

    def test_type_image_excludes_video(self):
        img = self._photo()
        vid = self._photo(name="v.mp4", is_video=True)
        ids = _ids(self.client.get("/api/photos/list?type=image").json())
        self.assertIn(img, ids)
        self.assertNotIn(vid, ids)

    def test_type_video_only(self):
        self._photo()
        vid = self._photo(name="v.mp4", is_video=True)
        self.assertEqual(_ids(self.client.get("/api/photos/list?type=video").json()), [vid])

    def test_camera_filter_token_match(self):
        canon = self._photo(exif=json.dumps({"Make": "Canon", "Model": "EOS R5"}))
        apple = self._photo(exif=json.dumps({"Make": "Apple", "Model": "iPhone 15"}))
        ids = _ids(self.client.get("/api/photos/list?camera=Canon+EOS+R5").json())
        self.assertIn(canon, ids)
        self.assertNotIn(apple, ids)

    def test_date_range(self):
        old = self._photo(taken_at=datetime(2020, 1, 1))
        new = self._photo(taken_at=datetime(2026, 6, 1))
        ids = _ids(self.client.get("/api/photos/list?from=2026-01-01&to=2026-12-31").json())
        self.assertIn(new, ids)
        self.assertNotIn(old, ids)

    def test_date_to_is_inclusive(self):
        # a photo taken at midnight on the 'to' day must still be inside the range
        p = self._photo(taken_at=datetime(2026, 6, 15, 0, 0))
        ids = _ids(self.client.get("/api/photos/list?from=2026-06-15&to=2026-06-15").json())
        self.assertIn(p, ids)

    def test_facets_lists_cameras(self):
        self._photo(exif=json.dumps({"Make": "Canon", "Model": "EOS R5"}))
        self._photo(exif=json.dumps({"Make": "Sony", "Model": "A7 IV"}))
        self._photo()  # no camera → not in facets
        cams = self.client.get("/api/photos/facets").json()["cameras"]
        self.assertIn("Canon EOS R5", cams)
        self.assertIn("Sony A7 IV", cams)

    def test_bad_date_ignored(self):
        p = self._photo(taken_at=datetime(2026, 6, 1))
        # an unparseable date must not 500 — it's just ignored
        ids = _ids(self.client.get("/api/photos/list?from=not-a-date").json())
        self.assertIn(p, ids)
