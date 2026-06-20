import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from core.database import Photo
from tests._client import ApiTest


def _items(d):
    out = []
    for m in d.get("moments", []):
        out.extend(m["items"])
    return out


class PhotosOrganizeTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        super().tearDown()

    def _photo(self, name="pic.jpg", **kw):
        db = self.db()
        p = Photo(filename="stored-" + name, original_name=name, **kw)
        db.add(p)
        db.commit()
        pid = p.id
        db.close()
        return pid

    def _patch(self, pid, **body):
        return self.client.patch(f"/api/photos/{pid}", json=body)

    def _unlock(self, pw="test123"):
        return self.client.post("/api/vault/unlock", json={"password": pw}).json()["token"]

    # ---- caption / keywords ----
    def test_patch_sets_caption(self):
        pid = self._photo()
        d = self._patch(pid, caption="sunset over the bay").json()
        self.assertEqual(d["caption"], "sunset over the bay")

    def test_patch_sets_keywords(self):
        pid = self._photo()
        d = self._patch(pid, keywords=["beach", "sunset"]).json()
        self.assertEqual(d["keywords"], ["beach", "sunset"])

    def test_keywords_normalized(self):
        pid = self._photo()
        d = self._patch(pid, keywords=["  Beach ", "BEACH", "Sunset"]).json()
        self.assertEqual(d["keywords"], ["beach", "sunset"])

    def test_list_carries_caption_keywords(self):
        pid = self._photo()
        self._patch(pid, caption="hello", keywords=["a", "b"])
        items = _items(self.client.get("/api/photos/list").json())
        it = next(i for i in items if i["id"] == pid)
        self.assertEqual(it["caption"], "hello")
        self.assertEqual(it["keywords"], ["a", "b"])

    def test_search_matches_caption(self):
        pid = self._photo()
        self._patch(pid, caption="mountain trip 2026")
        items = _items(self.client.get("/api/photos/search?q=mountain").json())
        self.assertTrue(any(i["id"] == pid for i in items))

    def test_search_matches_keyword(self):
        pid = self._photo()
        self._patch(pid, keywords=["hiking"])
        items = _items(self.client.get("/api/photos/search?q=hiking").json())
        self.assertTrue(any(i["id"] == pid for i in items))

    # ---- hidden / locked ----
    def test_patch_hide_excludes_from_list(self):
        pid = self._photo()
        self._patch(pid, hidden=True)
        items = _items(self.client.get("/api/photos/list").json())
        self.assertFalse(any(i["id"] == pid for i in items))

    def test_hidden_requires_unlock_403(self):
        self._photo(hidden=True)
        r = self.client.get("/api/photos/hidden")
        self.assertEqual(r.status_code, 403)

    def test_hidden_lists_when_unlocked(self):
        pid = self._photo(hidden=True)
        tok = self._unlock()
        items = _items(self.client.get("/api/photos/hidden", headers={"X-Vault-Token": tok}).json())
        self.assertTrue(any(i["id"] == pid for i in items))

    # ---- favorites filter (regression coverage) ----
    def test_favorites_filter_only_favs(self):
        fav = self._photo(name="fav.jpg", favorite=True)
        self._photo(name="plain.jpg", favorite=False)
        items = _items(self.client.get("/api/photos/list?favorites=true").json())
        ids = [i["id"] for i in items]
        self.assertEqual(ids, [fav])
