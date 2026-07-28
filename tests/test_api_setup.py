import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from core.database import ModelEndpoint
from tests._client import ApiTest


class SetupStatusApiTest(ApiTest):
    def test_unconfigured_on_fresh_install(self):
        st = self.client.get("/api/setup/status").json()
        self.assertFalse(st["configured"])
        self.assertEqual(st["endpoints"], 0)

    def test_endpoint_without_models_is_not_configured(self):
        d = self.db()
        d.add(ModelEndpoint(name="Empty", base_url="http://x", cached_models="[]"))
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 1)
        self.assertFalse(st["configured"])  # enabled but no usable models yet
        self.assertEqual(st["endpoints_with_models"], 0)

    def test_configured_once_an_endpoint_has_models(self):
        d = self.db()
        d.add(
            ModelEndpoint(name="DeepSeek", base_url="http://x", cached_models=json.dumps(["chat"]))
        )
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertTrue(st["configured"])
        self.assertEqual(st["endpoints_with_models"], 1)

    def test_disabled_endpoint_does_not_count(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="Off", base_url="http://x", cached_models=json.dumps(["m"]), enabled=False
            )
        )
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 0)  # only enabled endpoints are counted
        self.assertFalse(st["configured"])

    def test_multiple_endpoints_counted(self):
        d = self.db()
        d.add(ModelEndpoint(name="A", base_url="http://a", cached_models=json.dumps(["m1"])))
        d.add(ModelEndpoint(name="B", base_url="http://b", cached_models=json.dumps(["m2"])))
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 2)
        self.assertEqual(st["endpoints_with_models"], 2)
        self.assertTrue(st["configured"])

    def test_mixed_enabled_disabled(self):
        d = self.db()
        d.add(ModelEndpoint(name="On", base_url="http://on", cached_models=json.dumps(["x"])))
        d.add(
            ModelEndpoint(
                name="Off", base_url="http://off", cached_models=json.dumps(["y"]), enabled=False
            )
        )
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 1)
        self.assertEqual(st["endpoints_with_models"], 1)
        self.assertTrue(st["configured"])

    def test_add_endpoint_appears_in_models_list(self):
        r = self.client.post(
            "/api/models/endpoint",
            json={"name": "Local", "base_url": "http://localhost:11434", "api_key": ""},
        )
        self.assertEqual(r.status_code, 200)
        ep = r.json()
        self.assertEqual(ep["name"], "Local")
        self.assertIn("id", ep)

    def test_delete_endpoint(self):
        r = self.client.post(
            "/api/models/endpoint",
            json={"name": "Temp", "base_url": "http://tmp", "api_key": ""},
        )
        eid = r.json()["id"]
        # should appear in list
        eps = self.client.get("/api/models").json()
        ids = [e["id"] for e in eps]
        self.assertIn(eid, ids)
        # delete
        dr = self.client.delete(f"/api/models/endpoint/{eid}")
        self.assertEqual(dr.status_code, 200)
        self.assertTrue(dr.json()["ok"])
        # gone
        eps2 = self.client.get("/api/models").json()
        self.assertNotIn(eid, [e["id"] for e in eps2])

    def test_endpoints_with_models_zero_when_none_have_models(self):
        d = self.db()
        d.add(ModelEndpoint(name="Empty1", base_url="http://e1", cached_models="[]"))
        d.add(ModelEndpoint(name="Empty2", base_url="http://e2", cached_models="[]"))
        d.commit()
        d.close()
        st = self.client.get("/api/setup/status").json()
        self.assertEqual(st["endpoints"], 2)
        self.assertEqual(st["endpoints_with_models"], 0)
        self.assertFalse(st["configured"])


class ResumableSetupApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-setup-state-")
        self.root = Path(self.tmp.name)
        self.settings = self.root / "settings.json"
        self.settings_patch = mock.patch.object(core.settings, "_SETTINGS_FILE", self.settings)
        self.settings_patch.start()
        core.settings._clear_settings_cache()

    def tearDown(self):
        core.settings._clear_settings_cache()
        self.settings_patch.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _step(self, step, values):
        return self.client.patch("/api/setup/step", json={"step": step, "values": values})

    def test_fresh_state_has_server_owned_progress_and_path_preview(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.root / "data")}):
            response = self.client.get("/api/setup/status")
        self.assertEqual(response.status_code, 200)
        state = response.json()["setup"]
        self.assertEqual(state["version"], 1)
        self.assertEqual(state["next_step"], "basics")
        self.assertFalse(state["completed"])
        self.assertTrue(state["keep_vault_inside_alles"])
        self.assertEqual(state["vault_preview"], str(Path.home() / "Alles" / "Vault"))
        self.assertEqual(state["files_preview"], str(Path.home() / "Alles" / "Files"))

    def test_completed_step_resumes_from_server_not_browser_storage(self):
        saved = self._step(
            "basics",
            {"username": "jxh", "language": "en", "region": "TW", "timezone": "Asia/Taipei"},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["setup"]["next_step"], "access")
        core.settings._clear_settings_cache()
        resumed = self.client.get("/api/setup/status").json()["setup"]
        self.assertEqual(resumed["next_step"], "access")
        self.assertEqual(core.settings.load_settings()["username"], "jxh")

    def test_default_files_step_creates_only_visible_vault_and_files_after_save(self):
        visible = self.root / "Visible Alles"
        vault = visible / "Vault"
        files = visible / "Files"
        self.assertFalse(visible.exists())
        response = self._step(
            "files",
            {
                "keep_vault_inside_alles": True,
                "vault_path": str(vault),
                "files_path": str(files),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(vault.is_dir())
        self.assertTrue(files.is_dir())
        settings = core.settings.load_settings()
        self.assertEqual(settings["vault_dir"], str(vault.resolve()))
        self.assertEqual(settings["files_dir"], str(files.resolve()))

    def test_files_step_resumes_at_the_optional_companion_choice(self):
        vault = self.root / "Resume Vault"
        files = self.root / "Resume Files"
        vault.mkdir()
        files.mkdir()
        values = {
            "keep_vault_inside_alles": False,
            "vault_path": str(vault),
            "files_path": str(files),
            "companion_reviewed": False,
        }
        saved = self._step("files", values)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(saved.json()["setup"]["files_companion_pending"])
        self.assertEqual(saved.json()["setup"]["next_step"], "files")

        core.settings._clear_settings_cache()
        resumed = self.client.get("/api/setup/status").json()["setup"]
        self.assertTrue(resumed["files_companion_pending"])
        self.assertEqual(resumed["next_step"], "files")

        continued = self._step("files", {**values, "companion_reviewed": True})
        self.assertEqual(continued.status_code, 200, continued.text)
        self.assertFalse(continued.json()["setup"]["files_companion_pending"])
        self.assertEqual(continued.json()["setup"]["next_step"], "basics")

    def test_existing_vault_is_connected_without_modification(self):
        vault = self.root / "Existing Vault"
        files = self.root / "Existing Files"
        vault.mkdir()
        files.mkdir()
        note = vault / "note.md"
        note.write_text("owner text", "utf-8")
        before = sorted(path.relative_to(vault) for path in vault.rglob("*"))
        response = self._step(
            "files",
            {
                "keep_vault_inside_alles": False,
                "vault_path": str(vault),
                "files_path": str(files),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(note.read_text("utf-8"), "owner text")
        self.assertEqual(before, sorted(path.relative_to(vault) for path in vault.rglob("*")))
        self.assertFalse((vault / ".obsidian").exists())

    def test_files_and_vault_roots_cannot_contain_each_other(self):
        files = self.root / "Existing Files"
        vault = files / "Vault"
        vault.mkdir(parents=True)
        response = self._step(
            "files",
            {
                "keep_vault_inside_alles": False,
                "vault_path": str(vault),
                "files_path": str(files),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_setup_step")
        self.assertIn("do not contain each other", response.json()["detail"])

    def test_obsidian_companion_requires_explicit_approval(self):
        vault = self.root / "Vault"
        files = self.root / "Files"
        vault.mkdir()
        files.mkdir()
        self._step(
            "files",
            {
                "keep_vault_inside_alles": False,
                "vault_path": str(vault),
                "files_path": str(files),
            },
        )
        status = self.client.get("/api/setup/obsidian")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["vault_connected"])
        self.assertFalse((vault / ".obsidian").exists())

        refused = self.client.post("/api/setup/obsidian", json={"approve": False})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "explicit_approval_required")
        self.assertFalse((vault / ".obsidian").exists())

        installed = self.client.post("/api/setup/obsidian", json={"approve": True})
        self.assertEqual(installed.status_code, 200)
        self.assertTrue(installed.json()["companion_installed"])
        self.assertTrue((vault / ".obsidian" / "plugins" / "obsidian-alles" / "main.js").is_file())

    def test_obsidian_companion_needs_a_connected_vault(self):
        response = self.client.post("/api/setup/obsidian", json={"approve": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "vault_not_connected")

    def test_public_access_step_rejects_incomplete_https_policy(self):
        response = self._step("access", {"profile": "public"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_setup_access")

    def test_public_access_accepts_the_normal_root_slash(self):
        with mock.patch("services.setup_state.auth_enabled", return_value=True):
            response = self._step(
                "access",
                {
                    "profile": "public",
                    "public_url": "https://alles.example/",
                    "base_domain": "alles.example",
                    "trusted_hosts": "alles.example,*.alles.example",
                    "forwarded_allow_ips": "127.0.0.1",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(core.settings.load_settings()["public_url"], "https://alles.example")

    def test_leaving_public_access_clears_every_public_routing_value(self):
        core.settings.save_settings(
            {
                "access_profile": "public",
                "public_url": "https://alles.example",
                "base_domain": "alles.example",
                "trusted_hosts": "alles.example,*.alles.example",
                "forwarded_allow_ips": "127.0.0.1",
            }
        )

        response = self._step("access", {"profile": "device"})

        self.assertEqual(response.status_code, 200, response.text)
        saved = core.settings.load_settings()
        self.assertEqual(saved["access_profile"], "device")
        for key in ("public_url", "base_domain", "trusted_hosts", "forwarded_allow_ips"):
            self.assertEqual(saved[key], "", key)

    def test_public_access_rejects_broad_hosts_and_collectively_everywhere_proxies(self):
        base = {
            "profile": "public",
            "public_url": "https://alles.example/",
            "base_domain": "alles.example",
            "trusted_hosts": "alles.example,*.alles.example",
            "forwarded_allow_ips": "127.0.0.1",
        }
        cases = (
            (
                {
                    **base,
                    "public_url": "https://*",
                    "base_domain": "*",
                    "trusted_hosts": "*,*.*",
                },
                "concrete DNS host",
            ),
            (
                {
                    **base,
                    "public_url": "https://example",
                    "base_domain": "example",
                    "trusted_hosts": "example,*.example",
                },
                "concrete DNS host",
            ),
            ({**base, "trusted_hosts": "alles.example,*.alles.example,*"}, "trusted hosts"),
            (
                {**base, "trusted_hosts": "alles.example,*.alles.example,*.other.example"},
                "trusted hosts",
            ),
            ({**base, "forwarded_allow_ips": "0.0.0.0/1,128.0.0.0/1"}, "proxies"),
            ({**base, "forwarded_allow_ips": "::/1,8000::/1"}, "proxies"),
        )
        with mock.patch("services.setup_state.auth_enabled", return_value=True):
            for payload, message in cases:
                with self.subTest(payload=payload):
                    response = self._step("access", payload)
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertIn(message, response.text)

    def test_network_access_is_never_persisted_before_owner_authentication(self):
        with mock.patch("services.setup_state.auth_enabled", return_value=False):
            response = self._step("access", {"profile": "lan"})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("owner password", response.text)
        self.assertEqual(core.settings.load_settings().get("access_profile", "device"), "device")

    def test_searxng_search_step_requires_a_safe_instance_url(self):
        refused = self._step(
            "ai_search",
            {"search_provider": "searxng", "searxng_url": "http://search.example.com"},
        )
        self.assertEqual(refused.status_code, 400)
        accepted = self._step(
            "ai_search",
            {"search_provider": "searxng", "searxng_url": "https://search.example.com"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["setup"]["search_provider"], "searxng")
        self.assertEqual(accepted.json()["setup"]["searxng_url"], "https://search.example.com")
        settings = core.settings.load_settings()
        self.assertEqual(settings["search_provider"], "searxng")
        self.assertEqual(settings["searxng_url"], "https://search.example.com")

    def test_searxng_search_step_preserves_ipv6_loopback_brackets(self):
        accepted = self._step(
            "ai_search",
            {"search_provider": "searxng", "searxng_url": "http://[::1]"},
        )

        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(core.settings.load_settings()["searxng_url"], "http://[::1]")

    def test_dismiss_and_resume_are_durable(self):
        dismissed = self.client.post("/api/setup/dismiss")
        self.assertEqual(dismissed.status_code, 200)
        self.assertTrue(dismissed.json()["setup"]["dismissed"])
        resumed = self.client.post("/api/setup/resume")
        self.assertEqual(resumed.status_code, 200)
        self.assertFalse(resumed.json()["setup"]["dismissed"])
