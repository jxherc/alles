"""Backend compatibility for canonical and legacy app hosts.

Host selection belongs to the browser router.  The server must keep serving the
same SPA shell at every supported app host without rewriting API or public-share
paths.  ``ApiTest`` gives each test an in-memory database and a throwaway data
directory, so none of these requests can touch the installed Alles data.
"""

import logging
from pathlib import Path

from tests._client import ApiTest

ROOT = Path(__file__).parents[1]
SHELL = (ROOT / "static" / "index.html").read_bytes()

# Include the phase-zero hosts, the phase-three names, and every compatibility
# name promised by the Afterlife plan.  HostGuard deliberately accepts these via
# ``*.localhost`` while the browser decides which view to show.
APP_HOSTS = (
    "localhost",
    "today.localhost",
    "home.localhost",
    "aide.localhost",
    "chat.localhost",
    "cowork.localhost",
    "jarvis.localhost",
    "mail.localhost",
    "docs.localhost",
    "notes.localhost",
    "wiki.localhost",
    "journal.localhost",
    "files.localhost",
    "gallery.localhost",
    "photos.localhost",
    "finance.localhost",
    "money.localhost",
    "subs.localhost",
    "subscriptions.localhost",
    "calendar.localhost",
    "tasks.localhost",
    "days.localhost",
    "activity.localhost",
    "server.localhost",
    "system.localhost",
    "passwords.localhost",
    "secrets.localhost",
    "vault.localhost",
    "watch.localhost",
    "habits.localhost",
    "read.localhost",
    "books.localhost",
    "health.localhost",
    "contacts.localhost",
)


class HostRouteCompatibilityTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._http_logger = logging.getLogger("alles.http")
        self._http_log_level = self._http_logger.level
        self._http_logger.setLevel(logging.WARNING)

    def tearDown(self):
        self._http_logger.setLevel(self._http_log_level)
        super().tearDown()

    def _get(self, path: str, host: str):
        return self.client.get(
            path,
            headers={"Host": host},
            follow_redirects=False,
        )

    def assert_not_redirected(self, response):
        self.assertNotIn("location", response.headers)
        self.assertNotIn(response.status_code, {301, 302, 303, 307, 308})

    def test_every_canonical_and_legacy_app_host_gets_the_exact_shell(self):
        for host in APP_HOSTS:
            with self.subTest(host=host):
                response = self._get("/", host)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, SHELL)
                self.assertTrue(response.headers["content-type"].startswith("text/html"))
                self.assert_not_redirected(response)

    def test_host_names_do_not_rewrite_api_or_public_share_paths(self):
        paths = {
            "/api/auth/me": 200,
            "/health": 200,
            "/s/missing-host-route-compatibility-token": 404,
            "/rsvp/missing-host-route-compatibility-token": 404,
            "/book/missing-host-route-compatibility-token": 404,
            "/sv/missing-host-route-compatibility-token": 404,
        }
        for host in APP_HOSTS:
            for path, expected_status in paths.items():
                with self.subTest(host=host, path=path):
                    response = self._get(path, host)
                    self.assertEqual(response.status_code, expected_status)
                    self.assert_not_redirected(response)

    def test_fragment_bookmarks_are_served_without_a_server_redirect(self):
        # URL fragments never enter the ASGI path.  A direct fragment bookmark
        # must therefore receive the shell unchanged and let the browser router
        # interpret the fragment; a Location response could lose that state.
        bookmarks = (
            ("home.localhost", "/?source=bookmark#home"),
            ("notes.localhost", "/?mode=edit#Folder%2FNote.md"),
            ("cowork.localhost", "/?run=active#jarvis"),
        )
        for host, bookmark in bookmarks:
            with self.subTest(host=host, bookmark=bookmark):
                response = self._get(bookmark, host)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, SHELL)
                self.assert_not_redirected(response)


if __name__ == "__main__":
    import unittest

    unittest.main()
