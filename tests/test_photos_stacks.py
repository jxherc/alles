"""phase 6 — exact-duplicate detection + photo stacking."""

import io

from PIL import Image

from core.database import Photo
from tests._client import ApiTest


def _img(w, h):
    im = Image.new("RGB", (w, h), (80, 90, 160))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


def _items(d):
    return [i for m in d.get("moments", []) for i in m["items"]]


def _ids(d):
    return [i["id"] for i in _items(d)]


class PhotosStackDupTests(ApiTest):
    def _photo(self, name="f.jpg", **kw):
        db = self.db()
        p = Photo(filename="stored-" + name, original_name=name, **kw)
        db.add(p)
        db.commit()
        pid = p.id
        db.close()
        return pid

    # ---- duplicate detection (review-based: imports keep both, /duplicates surfaces them) ----
    def test_reupload_surfaces_in_duplicates(self):
        data = _img(800, 600)
        a = self.client.post(
            "/api/photos/upload", files={"file": ("a.jpg", data, "image/jpeg")}
        ).json()
        b = self.client.post(
            "/api/photos/upload", files={"file": ("a2.jpg", data, "image/jpeg")}
        ).json()
        self.assertNotEqual(a["id"], b["id"])  # both rows kept
        d = self.client.get("/api/photos/duplicates").json()
        self.assertEqual(len(d["groups"]), 1)
        self.assertCountEqual([i["id"] for i in d["groups"][0]["items"]], [a["id"], b["id"]])

    def test_duplicates_groups_same_checksum(self):
        a = self._photo(checksum="abc123")
        b = self._photo(name="b.jpg", checksum="abc123")
        self._photo(name="c.jpg", checksum="unique")
        d = self.client.get("/api/photos/duplicates").json()
        self.assertEqual(len(d["groups"]), 1)
        self.assertCountEqual([i["id"] for i in d["groups"][0]["items"]], [a, b])

    # ---- stacking ----
    def test_stack_collapses_timeline_to_cover(self):
        a = self._photo(width=1600, height=1000)  # largest → cover
        b = self._photo(name="b.jpg", width=800, height=600)
        c = self._photo(name="c.jpg", width=400, height=400)
        r = self.client.post("/api/photos/stack", json={"ids": [a, b, c]}).json()
        self.assertEqual(r["count"], 3)
        self.assertEqual(r["cover"], a)
        d = self.client.get("/api/photos/list").json()
        self.assertEqual(_ids(d), [a])  # only the cover is on the timeline
        cover = _items(d)[0]
        self.assertEqual(cover["stack_count"], 3)

    def test_stack_members_cover_first_then_unstack(self):
        a = self._photo(width=1600, height=1000)
        b = self._photo(name="b.jpg", width=800, height=600)
        r = self.client.post("/api/photos/stack", json={"ids": [a, b]}).json()
        mem = self.client.get(f"/api/photos/stack/{r['cover']}").json()
        self.assertEqual(len(mem["items"]), 2)
        self.assertEqual(mem["items"][0]["id"], r["cover"])
        self.client.post("/api/photos/unstack", json={"id": r["cover"]})
        self.assertEqual(len(_ids(self.client.get("/api/photos/list").json())), 2)

    def test_stack_merges_existing_stack(self):
        a = self._photo(width=1600, height=1000)
        b = self._photo(name="b.jpg", width=800, height=600)
        c = self._photo(name="c.jpg", width=1200, height=900)
        self.client.post("/api/photos/stack", json={"ids": [a, b]})  # stack of 2
        r = self.client.post("/api/photos/stack", json={"ids": [a, c]}).json()  # add c, absorbs b
        self.assertEqual(r["count"], 3)

    def test_stack_needs_two(self):
        a = self._photo()
        self.assertEqual(self.client.post("/api/photos/stack", json={"ids": [a]}).status_code, 400)
