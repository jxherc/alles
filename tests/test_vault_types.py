import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cs
from core.database import VaultEntry
from tests._client import ApiTest


class VaultTypedTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.sp = mock.patch.object(cs, "_SETTINGS_FILE", Path(self.tmp.name) / "settings.json")
        self.sp.start()
        tok = self.client.post("/api/vault/unlock", json={"password": "masterpw"}).json()["token"]
        self.h = {"X-Vault-Token": tok}

    def tearDown(self):
        self.sp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _create(self, **body):
        return self.client.post("/api/vault", json=body, headers=self.h)

    def test_password_fields_roundtrip(self):
        r = self._create(
            name="GitHub",
            type="password",
            fields={"password": "hunter2", "url": "https://github.com", "notes": "main"},
        )
        eid = r.json()["id"]
        got = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()
        self.assertEqual(got["type"], "password")
        self.assertEqual(got["fields"]["password"], "hunter2")
        self.assertEqual(got["fields"]["url"], "https://github.com")
        self.assertEqual(got["fields"]["notes"], "main")

    def test_card_fields_roundtrip(self):
        r = self._create(
            name="Visa",
            type="card",
            fields={
                "cardholder": "A Smith",
                "number": "4111111111111111",
                "expiry": "12/29",
                "cvv": "123",
            },
        )
        eid = r.json()["id"]
        f = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()["fields"]
        self.assertEqual(f["number"], "4111111111111111")
        self.assertEqual(f["cvv"], "123")
        self.assertEqual(f["expiry"], "12/29")

    def test_note_type(self):
        r = self._create(name="Wifi", type="note", fields={"notes": "ssid: home / pw: letmein"})
        eid = r.json()["id"]
        got = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()
        self.assertEqual(got["type"], "note")
        self.assertIn("letmein", got["fields"]["notes"])

    def test_legacy_value_create(self):
        r = self._create(name="Old", value="plainsecret")
        eid = r.json()["id"]
        f = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()["fields"]
        self.assertEqual(f["password"], "plainsecret")

    def test_type_in_list(self):
        self._create(name="C1", type="card", fields={"number": "4111111111111111"})
        rows = self.client.get("/api/vault", headers=self.h).json()
        self.assertEqual([r["type"] for r in rows if r["name"] == "C1"], ["card"])

    def test_list_has_no_secrets(self):
        self._create(name="S", type="password", fields={"password": "topsecret"})
        rows = self.client.get("/api/vault", headers=self.h).json()
        self.assertNotIn("topsecret", str(rows))

    def test_patch_fields(self):
        eid = self._create(name="P", type="password", fields={"password": "old"}).json()["id"]
        self.client.patch(
            f"/api/vault/{eid}", json={"fields": {"password": "new", "url": "x"}}, headers=self.h
        )
        f = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()["fields"]
        self.assertEqual(f["password"], "new")
        self.assertEqual(f["url"], "x")

    def test_legacy_bare_string_decrypts(self):
        # simulate pre-existing data: a bare (non-JSON) encrypted password
        from services.crypto import encrypt

        d = self.db()
        e = VaultEntry(
            name="Ancient", value_encrypted=encrypt("masterpw", "barevalue"), type="password"
        )
        d.add(e)
        d.commit()
        eid = e.id
        d.close()
        f = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()["fields"]
        self.assertEqual(f["password"], "barevalue")

    def test_value_encrypted_is_ciphertext(self):
        eid = self._create(name="E", type="password", fields={"password": "cleartext123"}).json()[
            "id"
        ]
        d = self.db()
        e = d.get(VaultEntry, eid)
        self.assertNotIn("cleartext123", e.value_encrypted)
        d.close()
