"""Conditional OAuth configuration contract in owned disposable settings."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.settings as cfg
from tests._client import ApiTest


class OAuthConfigRequests(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="alles-oauth-config-")
        self.path = Path(self.temp.name) / "settings.json"
        self.settings = mock.patch.object(cfg, "_SETTINGS_FILE", self.path)
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.temp.cleanup()
        super().tearDown()

    def status(self):
        response = self.client.get("/api/mail/oauth/status")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def body(self, **changes):
        value = {
            "client_id": "owned-client",
            "client_secret": "  dummy  ",
            "redirect_base": "",
            "expected_revision": self.status().get("revision", 0),
            "recovery_scope": next(iter(self.status().get("recovery_scopes", [])), ""),
        }
        value.update(changes)
        return value

    def save(self, body):
        return self.client.post("/api/mail/oauth/config", json=body)

    def test_status_reports_one_secret_free_configuration(self):
        before = self.status()
        self.assertIs(type(before.get("revision")), int)
        self.assertEqual(before["client_id"], "")
        self.assertEqual(before["redirect_base"], "")
        self.assertFalse(before["configured"])
        self.assertFalse(before["client_secret_configured"])
        cfg.save_settings({"mail_oauth_client_id": "owned", "mail_oauth_client_secret": "dummy"})
        after = self.status()
        self.assertEqual(after["client_id"], "owned")
        self.assertTrue(after["configured"])
        self.assertTrue(after["client_secret_configured"])
        self.assertGreater(after["revision"], before["revision"])
        self.assertNotIn("dummy", json.dumps(after))

    def test_save_and_equal_retry_preserve_exact_secret_and_one_version(self):
        body = self.body()
        first = self.save(body)
        self.assertEqual(first.status_code, 200)
        second = self.save(body)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(cfg.load_settings()["mail_oauth_client_secret"], body["client_secret"])
        self.assertNotIn(body["client_secret"], self.path.read_text())
        self.assertNotIn("dummy", first.text)
        self.assertNotIn("dummy", self.client.get("/api/settings").text)

    def test_late_old_save_does_not_replace_newer_confirmed_config(self):
        older = self.body()
        newer = self.body(client_id="newer-client", client_secret="example")
        self.assertEqual(self.save(newer).status_code, 200)
        self.assertEqual(self.save(older).status_code, 409)
        self.assertEqual(self.status()["client_id"], "newer-client")
        self.assertEqual(cfg.load_settings()["mail_oauth_client_secret"], "example")

    def test_different_secret_is_not_an_equal_replay(self):
        original = self.body()
        self.assertEqual(self.save(original).status_code, 200)
        self.assertEqual(self.save({**original, "client_secret": "example"}).status_code, 409)
        self.assertEqual(cfg.load_settings()["mail_oauth_client_secret"], "  dummy  ")

    def test_legacy_settings_write_invalidates_pending_config(self):
        pending = self.body()
        response = self.client.patch(
            "/api/settings",
            json={"mail_oauth_client_id": "legacy-client", "mail_oauth_client_secret": "example"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.save(pending).status_code, 409)
        self.assertEqual(self.status()["client_id"], "legacy-client")

    def test_current_config_claim_fences_older_pending_write_without_revealing_secret(self):
        first = self.save(self.body())
        self.assertEqual(first.status_code, 200)
        pending = self.body(client_id="late-client", client_secret="example")
        kept = self.save(self.body(client_secret=None))
        self.assertEqual(kept.status_code, 200)
        self.assertGreater(kept.json()["revision"], first.json()["revision"])
        self.assertEqual(self.save(pending).status_code, 409)
        self.assertEqual(cfg.load_settings()["mail_oauth_client_secret"], "  dummy  ")

    def test_blank_redirect_clears_override(self):
        cfg.save_settings({"mail_oauth_redirect_base": "https://mail.example.invalid"})
        saved = self.save(self.body())
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["redirect_base"], "")
        self.assertNotIn("mail.example.invalid", saved.json()["redirect_uri"])

    def test_unrelated_settings_leave_config_revision_unchanged(self):
        before = self.status().get("revision", 0)
        cfg.save_settings({"theme": "light"})
        self.assertEqual(self.status().get("revision", 0), before)

    def test_missing_client_or_secret_does_not_configure_google(self):
        for changes in [
            {"client_id": ""},
            {"client_id": "  "},
            {"client_secret": None},
            {"client_secret": ""},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.save(self.body(**changes)).status_code, 400)
                self.assertFalse(self.status()["configured"])

    def test_redirect_rejects_ambiguous_or_credential_bearing_urls(self):
        for base in [
            "javascript:alert(1)",
            "http://user:dummy@example.invalid",
            "http://@example.invalid",
            "http://:@example.invalid",
            "https://example.invalid?query=1",
            "https://example.invalid#fragment",
            "https://example.invalid?",
            "https://example.invalid#",
            "http://localhost:bad",
        ]:
            with self.subTest(base=base):
                cfg.save_settings({"mail_oauth_client_id": "", "mail_oauth_client_secret": ""})
                self.assertEqual(self.save(self.body(redirect_base=base)).status_code, 400)
                self.assertFalse(self.status()["configured"])

    def test_invalid_nonblank_redirect_does_not_clear_existing_override(self):
        cfg.save_settings(
            {
                "mail_oauth_client_id": "owned",
                "mail_oauth_client_secret": "dummy",
                "mail_oauth_redirect_base": "https://mail.example.invalid",
            }
        )
        before = self.status()
        for invalid in ["/", "///"]:
            with self.subTest(invalid=invalid):
                self.assertEqual(self.save(self.body(redirect_base=invalid)).status_code, 400)
                self.assertEqual(self.status(), before)

    def test_equal_legacy_write_still_advances_configuration_version(self):
        cfg.save_settings(
            {"mail_oauth_client_id": "same-client", "mail_oauth_client_secret": "example"}
        )
        before = self.status()["revision"]
        cfg.save_settings({"mail_oauth_client_id": "same-client"})
        self.assertGreater(self.status()["revision"], before)

    def test_two_stale_sessions_cannot_both_commit_different_configurations(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        from services import mail_oauth

        revision = self.status()["revision"]
        barrier = Barrier(2)

        def attempt(client):
            barrier.wait(timeout=5)
            try:
                return mail_oauth.save_configuration(
                    client_id=client,
                    client_secret="dummy",
                    redirect_base="",
                    expected_revision=revision,
                )
            except mail_oauth.ConfigurationConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ["first-client", "second-client"]))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(
            {key: value for key, value in self.status().items() if key != "recovery_scopes"},
            winners[0],
        )

    def test_keep_unconfigured_state_fences_an_uncertain_first_setup(self):
        pending = self.body()
        kept = self.save(self.body(client_id="", client_secret=None))
        self.assertEqual(kept.status_code, 200)
        self.assertFalse(kept.json()["configured"])
        self.assertGreater(kept.json()["revision"], pending["expected_revision"])
        self.assertEqual(self.save(pending).status_code, 409)
        self.assertFalse(self.status()["configured"])

    def test_explicit_empty_pair_clears_configuration_and_equal_retry_is_safe(self):
        self.assertEqual(self.save(self.body()).status_code, 200)
        clearing = self.body(client_id="", client_secret="")
        first = self.save(clearing)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["configured"])
        self.assertFalse(first.json()["client_secret_configured"])
        self.assertEqual(cfg.load_settings()["mail_oauth_client_secret"], "")
        second = self.save(clearing)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())

    def test_status_binds_recovery_to_the_current_store(self):
        scopes = self.status().get("recovery_scopes")
        self.assertIsInstance(scopes, list)
        self.assertTrue(scopes)
        self.assertTrue(all(isinstance(scope, str) and scope for scope in scopes))

    def test_pending_configuration_cannot_write_to_another_store(self):
        pending = self.body(recovery_scope="old-store")
        response = self.save(pending)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.status()["configured"])

    def test_stale_keep_secret_after_clear_is_a_conflict(self):
        self.assertEqual(self.save(self.body()).status_code, 200)
        pending = self.body(client_secret=None)
        cfg.save_settings({"mail_oauth_client_id": "", "mail_oauth_client_secret": ""})
        before = self.status()
        self.assertEqual(self.save(pending).status_code, 409)
        self.assertEqual(self.status(), before)

    def test_stale_empty_claim_after_first_setup_is_a_conflict(self):
        pending = self.body(client_id="", client_secret=None)
        cfg.save_settings(
            {"mail_oauth_client_id": "new-client", "mail_oauth_client_secret": "example"}
        )
        before = self.status()
        self.assertEqual(self.save(pending).status_code, 409)
        self.assertEqual(self.status(), before)

    def test_bad_authorities_and_embedded_controls_preserve_configuration(self):
        cfg.save_settings(
            {
                "mail_oauth_client_id": "owned",
                "mail_oauth_client_secret": "dummy",
                "mail_oauth_redirect_base": "https://mail.example.invalid",
            }
        )
        for invalid in [
            "https://bad host.example",
            "https://bad\tname.example",
            "https://example.invalid/a\nb",
            "https://bad\\name.example",
            "https://bad^name.example",
            "http://127.0.0.999",
            "http://[v1.example]",
            "https://foo.123",
            "http:example.invalid",
            "http:/example.invalid",
            "http:///example.invalid",
            "http:////example.invalid",
        ]:
            with self.subTest(invalid=invalid):
                before = self.status()
                self.assertEqual(self.save(self.body(redirect_base=invalid)).status_code, 400)
                self.assertEqual(self.status(), before)

    def test_redirect_accepts_localhost_addresses_dns_and_international_names(self):
        for base in [
            "http://localhost:6769",
            "http://127.0.0.1:6769",
            "http://127.1",
            "http://2130706433",
            "http://[::1]:6769",
            "https://mail.example.invalid/base/",
            "https://bücher.example/base",
        ]:
            with self.subTest(base=base):
                saved = self.save(self.body(redirect_base=base))
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(saved.json()["redirect_base"], base.rstrip("/"))

    def test_unchanged_partial_claim_advances_without_changing_values(self):
        for client_id, client_secret in [("legacy-client", ""), ("", "dummy")]:
            with self.subTest(client_id=client_id):
                cfg.save_settings(
                    {"mail_oauth_client_id": client_id, "mail_oauth_client_secret": client_secret}
                )
                before = self.status()
                response = self.save(self.body(client_id=client_id, client_secret=None))
                self.assertEqual(response.status_code, 200)
                after = response.json()
                self.assertGreater(after["revision"], before["revision"])
                self.assertEqual(
                    {key: value for key, value in after.items() if key != "revision"},
                    {key: value for key, value in before.items() if key != "revision"},
                )
                self.assertEqual(cfg.load_settings()["mail_oauth_client_secret"], client_secret)

    def test_changed_partial_configuration_is_still_rejected(self):
        cfg.save_settings({"mail_oauth_client_id": "legacy-client", "mail_oauth_client_secret": ""})
        for changes in [
            {"client_id": "different-client"},
            {"redirect_base": "https://example.invalid"},
        ]:
            with self.subTest(changes=changes):
                before = self.status()
                response = self.save(
                    self.body(**{"client_id": "legacy-client", "client_secret": None, **changes})
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.status(), before)

    def test_unchanged_legacy_values_can_be_retained_before_correction(self):
        for client_id, redirect_base in [
            ("legacy-client", "http:/example.invalid"),
            (" legacy-client ", "https://example.invalid/base/"),
        ]:
            with self.subTest(redirect_base=redirect_base):
                cfg.save_settings(
                    {
                        "mail_oauth_client_id": client_id,
                        "mail_oauth_client_secret": "dummy",
                        "mail_oauth_redirect_base": redirect_base,
                    }
                )
                before = self.status()
                response = self.save(
                    self.body(client_id=client_id, client_secret=None, redirect_base=redirect_base)
                )
                self.assertEqual(response.status_code, 200)
                after = response.json()
                self.assertEqual(after["client_id"], client_id)
                self.assertEqual(after["redirect_base"], redirect_base)
                self.assertGreater(after["revision"], before["revision"])

    def test_stale_keep_cannot_acknowledge_a_secret_only_change(self):
        self.assertEqual(self.save(self.body()).status_code, 200)
        pending = self.body(client_secret=None)
        cfg.save_settings({"mail_oauth_client_secret": "newer-dummy"})
        before = self.status()
        self.assertEqual(self.save(pending).status_code, 409)
        self.assertEqual(self.status(), before)

    def test_stale_normalized_keep_cannot_substitute_the_current_secret(self):
        self.assertEqual(self.save(self.body()).status_code, 200)
        pending = self.body(client_secret=None, redirect_base="https://example.invalid/base/")
        self.assertEqual(self.save(pending).status_code, 200)
        cfg.save_settings({"mail_oauth_client_secret": "newer-dummy"})
        before = self.status()
        self.assertEqual(self.save(pending).status_code, 409)
        self.assertEqual(self.status(), before)

    def test_version_requires_nonnegative_integer(self):
        for revision in [-1, True, "0", 1.5, None]:
            with self.subTest(revision=revision):
                self.assertEqual(self.save(self.body(expected_revision=revision)).status_code, 422)

    def test_failed_persistence_does_not_advance_or_acknowledge_configuration(self):
        cfg.save_settings({"mail_oauth_client_id": "before", "mail_oauth_client_secret": "example"})
        before = self.status()
        with mock.patch.object(cfg.os, "replace", side_effect=OSError("owned failed write")):
            try:
                response = self.save(self.body())
            except OSError:
                pass
            else:
                self.assertGreaterEqual(response.status_code, 500)
        self.assertEqual(self.status(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
