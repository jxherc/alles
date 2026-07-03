"""phase 7c — offline reverse-geocoding + the Places (Explore) endpoints."""

import json

from core.database import Photo
from services import places
from tests._client import ApiTest


def _items(d):
    return [i for m in d.get("moments", []) for i in m["items"]]


class PhotosExploreTests(ApiTest):
    def _photo(self, lat=None, lon=None, name="f.jpg", **kw):
        ex = {}
        if lat is not None:
            ex["lat"], ex["lon"] = lat, lon
        db = self.db()
        p = Photo(filename="s-" + name, original_name=name, exif=json.dumps(ex), **kw)
        db.add(p)
        db.commit()
        pid = p.id
        db.close()
        return pid

    def test_nearest_resolves_major_city(self):
        self.assertEqual(places.nearest(48.8566, 2.3522)["city"], "Paris")  # not "Paris 04"
        t = places.nearest(35.6762, 139.6503)
        self.assertEqual(t["city"], "Tokyo")
        self.assertEqual(t["country"], "Japan")

    def test_places_groups_by_city_sorted_by_count(self):
        for _ in range(3):
            self._photo(48.8566, 2.3522)  # Paris
        self._photo(35.6762, 139.6503)  # Tokyo
        self._photo()  # no GPS → excluded
        d = self.client.get("/api/photos/places").json()
        by = {p["city"]: p["count"] for p in d["places"]}
        self.assertEqual(by.get("Paris"), 3)
        self.assertEqual(by.get("Tokyo"), 1)
        self.assertEqual(d["places"][0]["city"], "Paris")  # most photos first

    def test_place_returns_only_matching(self):
        p = self._photo(48.8566, 2.3522)
        self._photo(35.6762, 139.6503)
        ids = [i["id"] for i in _items(self.client.get("/api/photos/place?cc=FR&city=Paris").json())]
        self.assertEqual(ids, [p])

    def test_places_excludes_ungeotagged(self):
        self._photo()  # no GPS
        self.assertEqual(self.client.get("/api/photos/places").json()["places"], [])
