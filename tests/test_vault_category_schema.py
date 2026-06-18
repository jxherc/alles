import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cs
from routes.vault import _default_schema
from tests._client import ApiTest


class VaultCategorySchemaTests(ApiTest):
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

    # ── default schema inference ──────────────────────────────────────────────
    def test_default_schema_password(self):
        self.assertEqual(_default_schema("password"), ["username", "password", "url", "notes"])

    def test_default_schema_login_account(self):
        self.assertEqual(_default_schema("login"), ["username", "password", "url", "notes"])
        self.assertEqual(_default_schema("account"), ["username", "password", "url", "notes"])

    def test_default_schema_card(self):
        self.assertEqual(_default_schema("card"), ["card"])

    def test_default_schema_note(self):
        self.assertEqual(_default_schema("note"), ["notes"])

    def test_default_schema_api_key(self):
        self.assertEqual(_default_schema("api key"), ["password", "url", "notes"])

    def test_default_schema_general_fallback(self):
        self.assertEqual(_default_schema("general"), ["password", "notes"])
        self.assertEqual(_default_schema("whatever-custom"), ["password", "notes"])

    # ── categories endpoint carries schemas ───────────────────────────────────
    def test_categories_includes_schemas(self):
        d = self.client.get("/api/vault/categories", headers=self.h).json()
        self.assertIn("categories", d)
        self.assertIn("schemas", d)
        # every listed category has a fields list
        for c in d["categories"]:
            self.assertIn(c, d["schemas"])
            self.assertIsInstance(d["schemas"][c]["fields"], list)
        self.assertEqual(d["schemas"]["card"]["fields"], ["card"])
        self.assertEqual(
            d["schemas"]["password"]["fields"], ["username", "password", "url", "notes"]
        )

    # ── put / persist a custom schema ──────────────────────────────────────────
    def test_put_schema_persists_and_get_reflects(self):
        r = self.client.put(
            "/api/vault/category-schema",
            json={"name": "wifi", "fields": ["password", "notes"]},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["fields"], ["password", "notes"])
        d = self.client.get("/api/vault/categories", headers=self.h).json()
        self.assertIn("wifi", d["categories"])
        self.assertEqual(d["schemas"]["wifi"]["fields"], ["password", "notes"])

    def test_put_schema_filters_unknown_fields(self):
        r = self.client.put(
            "/api/vault/category-schema",
            json={"name": "thing", "fields": ["username", "bogus", "password", "xyz"]},
            headers=self.h,
        )
        self.assertEqual(r.json()["fields"], ["username", "password"])

    def test_put_schema_requires_name(self):
        r = self.client.put(
            "/api/vault/category-schema",
            json={"name": "  ", "fields": ["password"]},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 400)

    def test_put_schema_saved_in_settings(self):
        self.client.put(
            "/api/vault/category-schema",
            json={"name": "servers", "fields": ["username", "password"]},
            headers=self.h,
        )
        self.assertEqual(
            cs.load_settings().get("vault_category_schemas", {}).get("servers"),
            ["username", "password"],
        )

    def test_put_schema_requires_unlock(self):
        r = self.client.put(
            "/api/vault/category-schema", json={"name": "x", "fields": ["password"]}
        )  # no token
        self.assertEqual(r.status_code, 403)

    # ── a custom-category entry still round-trips ─────────────────────────────
    def test_create_with_custom_category_roundtrips(self):
        self.client.put(
            "/api/vault/category-schema",
            json={"name": "wifi", "fields": ["password", "notes"]},
            headers=self.h,
        )
        eid = self.client.post(
            "/api/vault",
            json={
                "name": "Home WiFi",
                "category": "wifi",
                "type": "password",
                "fields": {"password": "letmein", "notes": "ssid: home"},
            },
            headers=self.h,
        ).json()["id"]
        got = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()
        self.assertEqual(got["fields"]["password"], "letmein")
        self.assertEqual(got["fields"]["notes"], "ssid: home")
