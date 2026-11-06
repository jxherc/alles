"""apps on paths (nov 6): one address with each app after a slash, example.com/docs, as well as
the old app subdomains. the owner put alles behind their own domain and wanted /docs, /plan."""

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("ALLES_DATA", tempfile.mkdtemp(prefix="alles-app-paths-"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from core import server_config, settings  # noqa: E402
from routes import auth  # noqa: E402
from services import setup_state  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _is_shell(response) -> bool:
    return response.headers.get("content-type", "").startswith("text/html") and (
        "/static/js/app.js" in response.text
    )


class AppPathPagesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_every_app_name_opens_the_shell(self):
        for name in ("docs", "plan", "aide", "inbox", "files", "server", "mail", "notes"):
            with self.subTest(name=name):
                self.assertTrue(_is_shell(self.client.get(f"/{name}")))

    def test_a_name_that_isnt_an_app_stays_a_404(self):
        for path in ("/nope", "/favicon.ico", "/index.html"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_a_trailing_slash_goes_to_the_app(self):
        r = self.client.get("/docs/", follow_redirects=False)
        self.assertIn(r.status_code, {307, 308})
        self.assertTrue(r.headers["location"].endswith("/docs"))

    def test_health_is_the_app_for_a_browser_and_the_ping_for_everything_else(self):
        self.assertEqual(self.client.get("/health").json(), {"ok": True})
        self.assertEqual(self.client.get("/health", headers={"accept": "*/*"}).json(), {"ok": True})
        for headers in (
            {"sec-fetch-mode": "navigate"},
            {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        ):
            self.assertTrue(_is_shell(self.client.get("/health", headers=headers)), headers)
        # the deep check never turns into a page
        deep = self.client.get("/health?deep=1", headers={"accept": "text/html"})
        self.assertEqual(deep.headers["content-type"], "application/json")

    def test_the_shell_is_never_kept_and_gets_gzipped(self):
        r = self.client.get("/plan", headers={"accept-encoding": "gzip"})
        self.assertIn("no-store", r.headers["cache-control"])
        self.assertEqual(r.headers.get("content-encoding"), "gzip")

    def test_the_server_names_match_the_pages_app_keys(self):
        source = (ROOT / "static/js/subdomain.js").read_text("utf-8")
        start = source.index("export const CANONICAL_SUBDOMAIN_VIEWS")
        end = source.index("export const SUBDOMAIN_VIEWS")
        keys = set(re.findall(r"^\s{2}([a-z]+):", source[start:end], re.M))
        self.assertEqual(keys, set(app_module.APP_PATHS))


class AppUrlsSettingTest(unittest.TestCase):
    def _settings(self, **values):
        stored = {"base_domain": "localhost", "app_urls": "", **values}
        return mock.patch.object(settings, "load_settings", return_value=stored)

    def test_the_choice_and_its_default(self):
        with mock.patch.dict(os.environ, {"ALLES_APP_URLS": "", "BASE_DOMAIN": ""}):
            with self._settings():
                self.assertEqual(settings.app_urls(), "")
                self.assertFalse(settings.subdomain_apps())
            with self._settings(base_domain="alles.example.com"):
                self.assertTrue(settings.subdomain_apps())
            with self._settings(base_domain="alles.example.com", app_urls="path"):
                self.assertEqual(settings.app_urls(), "path")
                self.assertFalse(settings.subdomain_apps())
            with self._settings(app_urls="sideways"):
                self.assertEqual(settings.app_urls(), "")
        with (
            mock.patch.dict(os.environ, {"ALLES_APP_URLS": "PATH", "BASE_DOMAIN": ""}),
            self._settings(app_urls="subdomain"),
        ):
            self.assertEqual(settings.app_urls(), "path")

    def test_the_page_learns_the_choice_with_the_lock_off_and_on(self):
        client = TestClient(app_module.app)
        for locked in (False, True):
            with (
                mock.patch("routes.auth.app_urls", return_value="path"),
                mock.patch("core.settings.auth_enabled", return_value=locked),
            ):
                me = client.get("/api/auth/me")
                self.assertEqual(me.status_code, 200, locked)
                self.assertEqual(me.json()["app_urls"], "path")
                self.assertEqual(me.json()["enabled"], locked)


class SessionCookieDomainTest(unittest.TestCase):
    """a Domain the browser isn't on gets thrown away, so sign in would loop"""

    def _request(self, host):
        return mock.Mock(url=mock.Mock(hostname=host))

    def test_shared_only_on_the_domain_with_app_subdomains(self):
        with (
            mock.patch.object(auth, "base_domain", return_value="alles.example.com"),
            mock.patch.object(auth, "subdomain_apps", return_value=True),
        ):
            for host in ("alles.example.com", "docs.alles.example.com"):
                self.assertEqual(
                    auth._cookie_domain_kw(self._request(host)),
                    {"domain": "alles.example.com", "secure": True},
                    host,
                )
            for host in ("100.79.59.4", "mac.tail1234.ts.net", "localhost"):
                self.assertEqual(auth._cookie_domain_kw(self._request(host)), {}, host)

    def test_apps_on_paths_keep_the_cookie_on_its_host(self):
        with (
            mock.patch.object(auth, "base_domain", return_value="alles.example.com"),
            mock.patch.object(auth, "subdomain_apps", return_value=False),
        ):
            self.assertEqual(auth._cookie_domain_kw(self._request("alles.example.com")), {})


class PublicAccessTest(unittest.TestCase):
    def _env(self, app_urls, hosts):
        return mock.patch.dict(
            os.environ,
            {
                "ALLES_ACCESS_PROFILE": "public",
                "ALLES_PUBLIC_URL": "https://alles.example.com",
                "BASE_DOMAIN": "alles.example.com",
                "ALLES_TRUSTED_HOSTS": hosts,
                "ALLES_APP_URLS": app_urls,
            },
        )

    def test_paths_need_only_the_one_host(self):
        with self._env("path", "alles.example.com"):
            self.assertEqual(server_config.public_origin(), "https://alles.example.com")

    def test_subdomains_still_need_their_pattern(self):
        with self._env("subdomain", "alles.example.com"):
            with self.assertRaises(server_config.AccessConfigError):
                server_config.public_origin()
        with self._env("subdomain", "alles.example.com,*.alles.example.com"):
            self.assertEqual(server_config.public_origin(), "https://alles.example.com")


class SetupPublicStepTest(unittest.TestCase):
    BASE = {
        "public_url": "https://alles.example.com",
        "base_domain": "alles.example.com",
        "forwarded_allow_ips": "127.0.0.1",
    }

    def test_paths_trust_the_host_alone(self):
        patch = setup_state._valid_public(
            {**self.BASE, "app_urls": "path", "trusted_hosts": "alles.example.com"}
        )
        self.assertEqual(patch["app_urls"], "path")
        self.assertEqual(patch["trusted_hosts"], "alles.example.com")
        with self.assertRaisesRegex(setup_state.SetupStateError, "include the public host$"):
            setup_state._valid_public({**self.BASE, "app_urls": "path", "trusted_hosts": ""})
        with self.assertRaisesRegex(setup_state.SetupStateError, "unrelated"):
            setup_state._valid_public(
                {
                    **self.BASE,
                    "app_urls": "path",
                    "trusted_hosts": "alles.example.com,*.alles.example.com",
                }
            )

    def test_an_older_setup_without_the_choice_means_subdomains(self):
        with self.assertRaisesRegex(setup_state.SetupStateError, "app subdomains"):
            setup_state._valid_public({**self.BASE, "trusted_hosts": "alles.example.com"})
        patch = setup_state._valid_public(
            {**self.BASE, "trusted_hosts": "alles.example.com,*.alles.example.com"}
        )
        self.assertEqual(patch["app_urls"], "subdomain")

    def test_an_unknown_choice_is_refused(self):
        with self.assertRaisesRegex(setup_state.SetupStateError, "path or subdomain"):
            setup_state._valid_public(
                {**self.BASE, "app_urls": "both", "trusted_hosts": "alles.example.com"}
            )


if __name__ == "__main__":
    unittest.main()
