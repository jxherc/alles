from core.database import Photo
from tests._client import ApiTest


class PhotoFavoritesTests(ApiTest):
    def setUp(self):
        super().setUp()
        d = self.db()
        d.add_all([
            Photo(filename="a.jpg", favorite=True, original_name="a"),
            Photo(filename="b.jpg", favorite=False, original_name="b"),
            Photo(filename="c.jpg", favorite=True, original_name="c"),
        ])
        d.commit()
        d.close()

    def _items(self, **params):
        d = self.client.get("/api/photos/list", params=params).json()
        return [it for m in d["moments"] for it in m["items"]], d["count"]

    def test_all_when_no_filter(self):
        items, count = self._items()
        self.assertEqual(count, 3)

    def test_favorites_only(self):
        items, count = self._items(favorites="true")
        self.assertEqual(count, 2)
        self.assertTrue(all(it["favorite"] for it in items))

    def test_favorites_false_returns_all(self):
        _, count = self._items(favorites="false")
        self.assertEqual(count, 3)

    def test_favorites_names(self):
        items, _ = self._items(favorites="true")
        self.assertEqual(sorted(it["original_name"] for it in items), ["a", "c"])

    def test_fmt_includes_favorite_and_exif(self):
        items, _ = self._items()
        self.assertIn("favorite", items[0])
        self.assertIn("exif", items[0])

    def test_patch_sets_favorite(self):
        pid = self._items()[0][0]["id"]
        self.client.patch(f"/api/photos/{pid}", json={"favorite": True})
        got = [it for it in self._items(favorites="true")[0] if it["id"] == pid]
        self.assertEqual(len(got), 1)

    def test_patch_unsets_favorite(self):
        items, _ = self._items(favorites="true")
        pid = items[0]["id"]
        self.client.patch(f"/api/photos/{pid}", json={"favorite": False})
        remaining = [it["id"] for it in self._items(favorites="true")[0]]
        self.assertNotIn(pid, remaining)

    def test_empty_favorites(self):
        d = self.db()
        for p in d.query(Photo).all():
            p.favorite = False
        d.commit()
        d.close()
        items, count = self._items(favorites="true")
        self.assertEqual(count, 0)
        self.assertEqual(items, [])
