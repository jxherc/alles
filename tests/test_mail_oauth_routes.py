import tempfile
from pathlib import Path

import core.settings as cfg
from core.database import MailAccount
from services import mail_oauth
from tests._client import ApiTest


class MailOAuthRouteTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._orig_file = cfg._SETTINGS_FILE
        cfg._SETTINGS_FILE = Path(tempfile.mkdtemp()) / "settings.json"
        self._orig_ex = mail_oauth.exchange_code
        self._orig_fe = mail_oauth.fetch_email

    def tearDown(self):
        mail_oauth.exchange_code = self._orig_ex
        mail_oauth.fetch_email = self._orig_fe
        cfg._SETTINGS_FILE = self._orig_file
        super().tearDown()

    def test_status_unconfigured(self):
        r = self.client.get("/api/mail/oauth/status").json()
        self.assertFalse(r["configured"])
        self.assertTrue(r["redirect_uri"].endswith("/api/mail/oauth/google/callback"))

    def test_status_configured(self):
        cfg.save_settings({"mail_oauth_client_id": "x", "mail_oauth_client_secret": "y"})
        self.assertTrue(self.client.get("/api/mail/oauth/status").json()["configured"])

    def test_start_unconfigured_400(self):
        r = self.client.get("/api/mail/oauth/google/start", follow_redirects=False)
        self.assertEqual(r.status_code, 400)

    def test_start_redirects_to_google(self):
        cfg.save_settings({"mail_oauth_client_id": "cid", "mail_oauth_client_secret": "sec"})
        r = self.client.get("/api/mail/oauth/google/start", follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        self.assertIn("accounts.google.com", r.headers["location"])

    def test_callback_badstate(self):
        r = self.client.get("/api/mail/oauth/google/callback?code=x&state=nope",
                            follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        self.assertIn("mailoauth=badstate", r.headers["location"])

    def test_callback_creates_oauth_account(self):
        cfg.save_settings({"mail_oauth_client_id": "cid", "mail_oauth_client_secret": "sec"})
        mail_oauth.exchange_code = lambda code: {"access_token": "at", "refresh_token": "rt",
                                                 "expires_in": 3600}
        mail_oauth.fetch_email = lambda at: "me@gmail.com"
        st = mail_oauth.make_state()
        r = self.client.get(f"/api/mail/oauth/google/callback?code=abc&state={st}",
                            follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        self.assertIn("mailoauth=ok", r.headers["location"])
        d = self.db()
        a = d.query(MailAccount).filter(MailAccount.email == "me@gmail.com").first()
        self.assertIsNotNone(a)
        self.assertEqual(a.auth_type, "oauth")
        self.assertEqual(a.imap_host, "imap.gmail.com")
        self.assertEqual(a.oauth_refresh_token, "rt")
        self.assertEqual(a.password, "")
        d.close()
