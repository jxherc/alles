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
    Image.new("RGB", (16, 16), (200, 100, 50)).save(buf, "PNG")
    return buf.getvalue()


class ContactsDepthTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles8c1-")
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

    def _contact(self, name="Ada"):
        return self.client.post("/api/contacts", json={"name": name}).json()["id"]

    def _field(self, cid, **body):
        return self.client.post(f"/api/contacts/{cid}/fields", json=body)

    def _get(self, cid):
        return next(x for x in self.client.get("/api/contacts").json() if x["id"] == cid)

    def test_add_field(self):
        cid = self._contact()
        r = self._field(cid, kind="email", label="work", value="ada@work.com")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["value"], "ada@work.com")

    def test_field_kinds(self):
        cid = self._contact()
        for k in ("email", "phone", "address", "url", "social", "custom"):
            self.assertEqual(self._field(cid, kind=k, value="x").status_code, 200)

    def test_list_fields_in_fmt(self):
        cid = self._contact()
        self._field(cid, kind="phone", label="mobile", value="555-1212")
        self.assertEqual(self._get(cid)["fields"][0]["label"], "mobile")

    def test_delete_field(self):
        cid = self._contact()
        fid = self._field(cid, kind="email", value="a@b.com").json()["id"]
        self.client.delete(f"/api/contacts/{cid}/fields/{fid}")
        self.assertEqual(len(self._get(cid)["fields"]), 0)

    def test_set_avatar(self):
        cid = self._contact()
        r = self.client.post(
            f"/api/contacts/{cid}/avatar", files={"file": ("a.png", _png(), "image/png")}
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self._get(cid)["avatar"])

    def test_get_avatar(self):
        cid = self._contact()
        self.client.post(
            f"/api/contacts/{cid}/avatar", files={"file": ("a.png", _png(), "image/png")}
        )
        r = self.client.get(f"/api/contacts/{cid}/avatar")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("image/"))

    def test_avatar_unknown_404(self):
        cid = self._contact()
        self.assertEqual(self.client.get(f"/api/contacts/{cid}/avatar").status_code, 404)

    def test_set_me_card(self):
        cid = self._contact()
        self.client.patch(f"/api/contacts/{cid}", json={"is_me": True})
        self.assertTrue(self._get(cid)["is_me"])

    def test_me_card_is_singular(self):
        a = self._contact("A")
        b = self._contact("B")
        self.client.patch(f"/api/contacts/{a}", json={"is_me": True})
        self.client.patch(f"/api/contacts/{b}", json={"is_me": True})
        me = [x for x in self.client.get("/api/contacts").json() if x["is_me"]]
        self.assertEqual(len(me), 1)
        self.assertEqual(me[0]["id"], b)

    def test_get_me(self):
        cid = self._contact()
        self.client.patch(f"/api/contacts/{cid}", json={"is_me": True})
        self.assertEqual(self.client.get("/api/contacts/me").json()["id"], cid)

    def test_custom_field_label(self):
        cid = self._contact()
        r = self._field(cid, kind="custom", label="nickname", value="Countess")
        self.assertEqual(r.json()["label"], "nickname")
