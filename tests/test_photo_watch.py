import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
import services.photo_sync as photo_sync
from core.settings import save_settings
from tests._client import ApiTest


def _png(path, color=(70, 120, 180)):
    from PIL import Image

    Image.new("RGB", (20, 20), color).save(path, "PNG")


def _items(d):
    return [p for m in d.get("moments", []) for p in m["items"]]


class PhotoWatchTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles7c3-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        # isolate the sync dedup state to this test
        self._state = Path(self._tmp) / "sync_state.json"
        self.stp = mock.patch.object(photo_sync, "_STATE", self._state)
        self.stp.start()
        # the folder that gets "watched"
        self.watch = Path(self._tmp) / "incoming"
        self.watch.mkdir()

    def tearDown(self):
        self.stp.stop()
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    def _count(self):
        return self.client.get("/api/photos/list").json()["count"]

    def test_no_setting_noop(self):
        res = photo_sync.run_watch()
        self.assertIn("skipped", res)
        self.assertEqual(self._count(), 0)

    def test_missing_folder_noop(self):
        save_settings({"photos_watch_folder": str(Path(self._tmp) / "nope")})
        res = photo_sync.run_watch()
        self.assertIn("skipped", res)
        self.assertEqual(self._count(), 0)

    def test_imports_new_files(self):
        _png(self.watch / "a.png")
        _png(self.watch / "b.png")
        save_settings({"photos_watch_folder": str(self.watch)})
        res = photo_sync.run_watch()
        self.assertEqual(res["imported"], 2)
        self.assertEqual(self._count(), 2)

    def test_idempotent_second_run(self):
        _png(self.watch / "a.png")
        save_settings({"photos_watch_folder": str(self.watch)})
        photo_sync.run_watch()
        res2 = photo_sync.run_watch()
        self.assertEqual(res2["imported"], 0)
        self.assertEqual(self._count(), 1)

    def test_ignores_non_images(self):
        _png(self.watch / "a.png")
        (self.watch / "notes.txt").write_text("not an image")
        save_settings({"photos_watch_folder": str(self.watch)})
        photo_sync.run_watch()
        self.assertEqual(self._count(), 1)

    def test_returns_counts(self):
        _png(self.watch / "a.png")
        save_settings({"photos_watch_folder": str(self.watch)})
        res = photo_sync.run_watch()
        for k in ("imported", "skipped", "failed"):
            self.assertIn(k, res)

    def test_picks_up_added_file(self):
        _png(self.watch / "a.png")
        save_settings({"photos_watch_folder": str(self.watch)})
        photo_sync.run_watch()
        _png(self.watch / "b.png")
        res2 = photo_sync.run_watch()
        self.assertEqual(res2["imported"], 1)
        self.assertEqual(self._count(), 2)

    def test_respects_limit(self):
        for n in "abc":
            _png(self.watch / f"{n}.png")
        save_settings({"photos_watch_folder": str(self.watch)})
        res = photo_sync.run_watch(limit=2)
        self.assertEqual(res["imported"], 2)
