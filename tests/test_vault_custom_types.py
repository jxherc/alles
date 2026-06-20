"""ui-8e — customizable vault entry types: add a type with named fields + widths, persisted, and used
to create/reveal entries. Backed by a `vault_custom_types` setting."""

import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest


class VaultCustomTypes(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles8e-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        self.tok = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["token"]
        self.h = {"X-Vault-Token": self.tok}

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    WIFI = {
        "label": "Wi-Fi",
        "fields": [
            {"key": "ssid", "label": "network", "width": "half"},
            {"key": "wifi_pw", "label": "password", "width": "half", "kind": "secret"},
            {"key": "notes", "label": "notes", "width": "full", "kind": "textarea"},
        ],
    }

    def _put(self, key, body):
        return self.client.put(f"/api/vault/custom-types/{key}", json=body, headers=self.h)

    def test_empty_initially(self):
        r = self.client.get("/api/vault/custom-types", headers=self.h).json()
        self.assertEqual(r.get("types", {}), {})

    def test_put_and_get(self):
        self.assertEqual(self._put("wifi", self.WIFI).status_code, 200)
        types = self.client.get("/api/vault/custom-types", headers=self.h).json()["types"]
        self.assertIn("wifi", types)
        self.assertEqual(types["wifi"]["label"], "Wi-Fi")
        self.assertEqual([f["key"] for f in types["wifi"]["fields"]], ["ssid", "wifi_pw", "notes"])

    def test_widths_preserved_and_validated(self):
        self._put("wifi", self.WIFI)
        f = self.client.get("/api/vault/custom-types", headers=self.h).json()["types"]["wifi"][
            "fields"
        ]
        self.assertEqual(f[0]["width"], "half")
        # a bogus width is normalised to full
        bad = {"label": "X", "fields": [{"key": "a", "label": "a", "width": "weird"}]}
        self._put("x", bad)
        fx = self.client.get("/api/vault/custom-types", headers=self.h).json()["types"]["x"][
            "fields"
        ]
        self.assertEqual(fx[0]["width"], "full")

    def test_rename_field_updates(self):
        self._put("wifi", self.WIFI)
        body = {"label": "Wi-Fi", "fields": [{"key": "ssid", "label": "SSID name", "width": "full"}]}
        self._put("wifi", body)
        f = self.client.get("/api/vault/custom-types", headers=self.h).json()["types"]["wifi"][
            "fields"
        ]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["label"], "SSID name")

    def test_missing_label_rejected(self):
        r = self._put("bad", {"label": "", "fields": [{"key": "a", "label": "a"}]})
        self.assertEqual(r.status_code, 400)

    def test_needs_a_field(self):
        r = self._put("bad", {"label": "X", "fields": []})
        self.assertEqual(r.status_code, 400)

    def test_delete(self):
        self._put("wifi", self.WIFI)
        self.client.delete("/api/vault/custom-types/wifi", headers=self.h)
        types = self.client.get("/api/vault/custom-types", headers=self.h).json()["types"]
        self.assertNotIn("wifi", types)

    def test_entry_of_custom_type_roundtrips(self):
        self._put("wifi", self.WIFI)
        eid = self.client.post(
            "/api/vault",
            json={"name": "home wifi", "type": "wifi", "fields": {"ssid": "MyNet", "wifi_pw": "p@ss"}},
            headers=self.h,
        ).json()["id"]
        rev = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()
        self.assertEqual(rev["fields"]["ssid"], "MyNet")
        self.assertEqual(rev["fields"]["wifi_pw"], "p@ss")


if __name__ == "__main__":
    import unittest

    unittest.main()
