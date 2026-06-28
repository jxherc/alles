import io
import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (40, 160, 90)).save(buf, "PNG")
    return buf.getvalue()


class ShareAlbumTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles7c1-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    def _album(self, name="Trip"):
        return self.client.post("/api/photos/albums", json={"name": name}).json()["id"]

    def _upload(self, name="p.png"):
        return self.client.post(
            "/api/photos/upload", files={"file": (name, _png(), "image/png")}
        ).json()["id"]

    def _add(self, pid, aid):
        self.client.patch(f"/api/photos/{pid}", json={"album_id": aid})

    def _mint(self, aid):
        return self.client.post("/api/share", json={"kind": "album", "ref": aid}).json()["token"]

    def test_album_mint_via_share_api(self):
        aid = self._album()
        tok = self._mint(aid)
        self.assertTrue(tok)
        got = self.client.get(f"/api/share?kind=album&ref={aid}").json()
        self.assertEqual(got["token"], tok)

    def test_album_viewer_renders_grid(self):
        aid = self._album()
        a = self._upload("a.png")
        self._add(a, aid)
        tok = self._mint(aid)
        html = self.client.get(f"/s/{tok}").text
        self.assertIn(f"/s/{tok}/{a}", html)

    def test_album_viewer_unknown_404(self):
        self.assertEqual(self.client.get("/s/nope-nope").status_code, 404)

    def test_album_viewer_revoked_404(self):
        aid = self._album()
        tok = self._mint(aid)
        self.client.request("DELETE", "/api/share", json={"kind": "album", "ref": aid})
        self.assertEqual(self.client.get(f"/s/{tok}").status_code, 404)

    def test_album_child_serves_member(self):
        aid = self._album()
        a = self._upload("a.png")
        self._add(a, aid)
        tok = self._mint(aid)
        r = self.client.get(f"/s/{tok}/{a}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("image/"))
        # public image responses must carry nosniff so a browser can't sniff them into a doc
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")

    def test_album_child_non_member_404(self):
        aid = self._album()
        a = self._upload("a.png")
        self._add(a, aid)
        other = self._upload("b.png")  # not in the album
        tok = self._mint(aid)
        self.assertEqual(self.client.get(f"/s/{tok}/{other}").status_code, 404)

    def test_album_child_hidden_404(self):
        aid = self._album()
        a = self._upload("a.png")
        self._add(a, aid)
        self.client.patch(f"/api/photos/{a}", json={"hidden": True})
        tok = self._mint(aid)
        self.assertEqual(self.client.get(f"/s/{tok}/{a}").status_code, 404)

    def test_album_child_deleted_404(self):
        aid = self._album()
        a = self._upload("a.png")
        self._add(a, aid)
        self.client.delete(f"/api/photos/{a}")  # soft-delete
        tok = self._mint(aid)
        self.assertEqual(self.client.get(f"/s/{tok}/{a}").status_code, 404)

    def test_album_grid_excludes_hidden_deleted(self):
        aid = self._album()
        live = self._upload("live.png")
        hid = self._upload("hid.png")
        gone = self._upload("gone.png")
        for p in (live, hid, gone):
            self._add(p, aid)
        self.client.patch(f"/api/photos/{hid}", json={"hidden": True})
        self.client.delete(f"/api/photos/{gone}")
        tok = self._mint(aid)
        html = self.client.get(f"/s/{tok}").text
        self.assertIn(f"/s/{tok}/{live}", html)
        self.assertNotIn(hid, html)
        self.assertNotIn(gone, html)

    def test_albums_count_excludes_hidden_deleted_and_empty_is_zero(self):
        a = self._album("Counted")
        self._album("EmptyOne")
        live = self._upload("l.png")
        hid = self._upload("h.png")
        gone = self._upload("g.png")
        for p in (live, hid, gone):
            self._add(p, a)
        self.client.patch(f"/api/photos/{hid}", json={"hidden": True})
        self.client.delete(f"/api/photos/{gone}")
        counts = {r["name"]: r["count"] for r in self.client.get("/api/photos/albums").json()}
        self.assertEqual(counts["Counted"], 1)   # only the live photo counts
        self.assertEqual(counts["EmptyOne"], 0)  # an album with no photos reports 0

    def test_album_empty_ok(self):
        aid = self._album("Empty")
        tok = self._mint(aid)
        r = self.client.get(f"/s/{tok}")
        self.assertEqual(r.status_code, 200)

    def test_single_photo_share_has_nosniff(self):
        pid = self._upload("solo.png")
        tok = self.client.post("/api/share", json={"kind": "photo", "ref": pid}).json()["token"]
        r = self.client.get(f"/s/{tok}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("image/"))
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
