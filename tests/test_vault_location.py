from tests._client import VaultApiTest


class VaultLocationTest(VaultApiTest):
    def test_vault_location_endpoint(self):
        r = self.client.get("/api/vault-location")
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["path"])  # resolves to the (isolated) vault dir
        self.assertTrue(j["obsidian"].startswith("obsidian://open?path="))

    def test_vault_dir_is_a_settable_field(self):
        from routes.settings import SettingsPatch

        self.assertIn("vault_dir", SettingsPatch.model_fields)

    def test_vault_location_per_file_deeplink(self):
        r = self.client.get("/api/vault-location", params={"path": "Notes/foo.md"}).json()
        self.assertTrue(r["obsidian"].startswith("obsidian://open?path="))
        self.assertIn("Notes", r["obsidian"])  # points at the file, not just the vault

    def test_obsidian_plugin_download(self):
        import io
        import zipfile

        r = self.client.get("/api/download/obsidian-plugin")
        self.assertEqual(r.status_code, 200)
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        self.assertIn("alles/manifest.json", names)
        self.assertIn("alles/main.js", names)
