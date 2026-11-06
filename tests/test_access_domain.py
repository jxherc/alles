"""alles access domain (nov 6): bind alles to the owner's own domain, apps after a slash or on
subdomains, without editing settings by hand"""

import io
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("ALLES_DATA", tempfile.mkdtemp(prefix="alles-access-domain-"))

import cli  # noqa: E402
from core import settings  # noqa: E402


class AccessDomainTest(unittest.TestCase):
    def setUp(self):
        self.saved = {"base_domain": "localhost", "app_urls": "", "trusted_hosts": ""}
        self.profile = "lan"
        patches = [
            mock.patch.object(settings, "load_settings", side_effect=lambda: dict(self.saved)),
            mock.patch.object(settings, "save_settings", side_effect=self.saved.update),
            mock.patch("core.server_config.access_profile", side_effect=lambda: self.profile),
            mock.patch.object(cli, "_native_layout", return_value=None),
            mock.patch.object(cli, "_port", return_value=6769),
            mock.patch.object(cli, "_restart_for_settings", return_value=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _run(self, *args):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            ok = cli.cmd_access(("domain", *args))
        return ok, out.getvalue()

    def test_a_domain_defaults_to_apps_after_a_slash(self):
        ok, text = self._run("https://Alles.Example.com/")
        self.assertTrue(ok)
        self.assertEqual(self.saved["base_domain"], "alles.example.com")
        self.assertEqual(self.saved["app_urls"], "path")
        # lan already lets any host in
        self.assertEqual(self.saved["trusted_hosts"], "")
        self.assertIn("https://alles.example.com/docs", text)
        self.assertIn("http://127.0.0.1:6769", text)

    def test_subdomains_on_this_computer_only_trust_the_domain_and_its_apps(self):
        self.profile = "device"
        ok, text = self._run("alles.example.com", "subdomain")
        self.assertTrue(ok)
        hosts = self.saved["trusted_hosts"].split(",")
        self.assertIn("localhost", hosts)
        self.assertIn("alles.example.com", hosts)
        self.assertIn("*.alles.example.com", hosts)
        self.assertIn("https://docs.alles.example.com", text)

    def test_public_access_adds_the_domain_to_its_own_hosts(self):
        self.profile = "public"
        self.saved["trusted_hosts"] = "old.example.com"
        self._run("alles.example.com")
        self.assertEqual(self.saved["trusted_hosts"], "old.example.com,alles.example.com")

    def test_off_forgets_it(self):
        self._run("alles.example.com", "subdomain")
        ok, _ = self._run("off")
        self.assertTrue(ok)
        self.assertEqual(self.saved["base_domain"], "")
        self.assertEqual(self.saved["app_urls"], "")

    def test_bad_input_is_refused_and_saves_nothing(self):
        for args in (("localhost",), ("*.example.com",), ("not a domain",), ("a.com", "both")):
            ok, text = self._run(*args)
            self.assertFalse(ok, args)
            self.assertIn("usage", text)
        self.assertEqual(self.saved["base_domain"], "localhost")

    def test_switching_lan_and_device_keeps_the_domain(self):
        self._run("alles.example.com")
        with (
            mock.patch("core.settings.auth_enabled", return_value=True),
            mock.patch("sys.stdout", new_callable=io.StringIO),
            mock.patch.object(cli, "_reachable_addresses", return_value=[]),
        ):
            cli.cmd_access(("device",))
        self.assertEqual(self.saved["base_domain"], "alles.example.com")
        self.assertIn("alles.example.com", self.saved["trusted_hosts"].split(","))


if __name__ == "__main__":
    unittest.main()
