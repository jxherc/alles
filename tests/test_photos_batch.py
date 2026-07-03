"""phase 2 — archive flag + bulk /batch endpoint (multi-select actions)."""

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


def _ids(d):
    return [i["id"] for i in _items(d)]


class PhotosBatchArchiveTests(ApiTest):
    def setUp(self):
        super().setUp()
        # trash.record / delete paths touch settings — give them an isolated file
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

    def _batch(self, ids, action, **extra):
        return self.client.post("/api/photos/batch", json={"ids": ids, "action": action, **extra})

    # ---- archive flag ----
    def test_archive_excludes_from_main_list(self):
        a = self._photo(name="a.jpg")
        b = self._photo(name="b.jpg")
        self._batch([a], "archive")
        ids = _ids(self.client.get("/api/photos/list").json())
        self.assertIn(b, ids)
        self.assertNotIn(a, ids)

    def test_archive_view_lists_archived(self):
        a = self._photo()
        self._batch([a], "archive")
        self.assertEqual(_ids(self.client.get("/api/photos/archive").json()), [a])

    def test_unarchive_restores_to_list(self):
        a = self._photo()
        self._batch([a], "archive")
        self._batch([a], "unarchive")
        self.assertIn(a, _ids(self.client.get("/api/photos/list").json()))
        self.assertEqual(_items(self.client.get("/api/photos/archive").json()), [])

    def test_archived_still_in_its_album(self):
        # archive hides from the main timeline but keeps the asset inside its album
        alb = self.client.post("/api/photos/albums", json={"name": "trip"}).json()["id"]
        a = self._photo(album_id=alb)
        self._batch([a], "archive")
        self.assertIn(a, _ids(self.client.get(f"/api/photos/list?album={alb}").json()))

    def test_patch_archive_single(self):
        a = self._photo()
        d = self.client.patch(f"/api/photos/{a}", json={"archived": True}).json()
        self.assertTrue(d["archived"])

    def test_list_carries_archived_flag(self):
        a = self._photo()
        it = next(i for i in _items(self.client.get("/api/photos/list").json()) if i["id"] == a)
        self.assertIn("archived", it)
        self.assertFalse(it["archived"])

    # ---- bulk actions ----
    def test_batch_favorite(self):
        a = self._photo()
        b = self._photo(name="b.jpg")
        r = self._batch([a, b], "favorite")
        self.assertEqual(r.json()["count"], 2)
        favs = _ids(self.client.get("/api/photos/list?favorites=true").json())
        self.assertCountEqual(favs, [a, b])

    def test_batch_album_move_and_remove(self):
        alb = self.client.post("/api/photos/albums", json={"name": "trip"}).json()["id"]
        a = self._photo()
        self._batch([a], "album", album_id=alb)
        self.assertIn(a, _ids(self.client.get(f"/api/photos/list?album={alb}").json()))
        self._batch([a], "album", album_id="")  # remove from album
        self.assertNotIn(a, _ids(self.client.get(f"/api/photos/list?album={alb}").json()))

    def test_batch_delete_then_restore(self):
        a = self._photo()
        self._batch([a], "delete")
        self.assertNotIn(a, _ids(self.client.get("/api/photos/list").json()))
        self.assertIn(a, [t["id"] for t in self.client.get("/api/photos/trash").json()])
        self._batch([a], "restore")
        self.assertIn(a, _ids(self.client.get("/api/photos/list").json()))

    def test_batch_hide(self):
        a = self._photo()
        self._batch([a], "hide")
        self.assertNotIn(a, _ids(self.client.get("/api/photos/list").json()))

    def test_batch_unknown_action_400(self):
        a = self._photo()
        self.assertEqual(self._batch([a], "nuke").status_code, 400)

    def test_batch_empty_ids_400(self):
        self.assertEqual(self._batch([], "archive").status_code, 400)
