import tempfile
import time
from pathlib import Path

import core.settings as cfg
from services import mail_oauth
from tests._client import ApiTest


class MailOAuthTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._orig_file = cfg._SETTINGS_FILE
        cfg._SETTINGS_FILE = Path(tempfile.mkdtemp()) / "settings.json"
        cfg.save_settings({"mail_oauth_client_id": "cid123", "mail_oauth_client_secret": "sec456"})
        self._orig_refresh = mail_oauth.refresh_access

    def tearDown(self):
        mail_oauth.refresh_access = self._orig_refresh
        cfg._SETTINGS_FILE = self._orig_file
        super().tearDown()

    def test_configured(self):
        self.assertTrue(mail_oauth.configured())

    def test_not_configured(self):
        cfg.save_settings({"mail_oauth_client_id": "", "mail_oauth_client_secret": ""})
        self.assertFalse(mail_oauth.configured())

    def test_redirect_default(self):
        self.assertEqual(mail_oauth.redirect_uri(),
                         "http://localhost:8000/api/mail/oauth/google/callback")

    def test_redirect_custom_base(self):
        cfg.save_settings({"mail_oauth_redirect_base": "https://mail.example.com/"})
        self.assertEqual(mail_oauth.redirect_uri(),
                         "https://mail.example.com/api/mail/oauth/google/callback")

    def test_xoauth2_format(self):
        self.assertEqual(mail_oauth.xoauth2("me@gmail.com", "TOKEN"),
                         "user=me@gmail.com\x01auth=Bearer TOKEN\x01\x01")

    def test_state_is_one_time(self):
        st = mail_oauth.make_state()
        self.assertTrue(mail_oauth.check_state(st))
        self.assertFalse(mail_oauth.check_state(st))   # consumed
        self.assertFalse(mail_oauth.check_state("bogus"))

    def test_auth_url(self):
        url = mail_oauth.auth_url("STATE1")
        self.assertIn("client_id=cid123", url)
        self.assertIn("mail.google.com", url)
        self.assertIn("state=STATE1", url)
        self.assertIn("access_type=offline", url)

    def test_ensure_token_valid_skips_refresh(self):
        mail_oauth.refresh_access = lambda rt: (_ for _ in ()).throw(AssertionError("no refresh"))
        acct = {"oauth_access_token": "good", "oauth_expires_at": time.time() + 3600,
                "oauth_refresh_token": "r"}
        self.assertEqual(mail_oauth.ensure_access_token(acct), "good")

    def test_ensure_token_refreshes_when_expired(self):
        calls = {}

        def fake_refresh(rt):
            calls["rt"] = rt
            return {"access_token": "fresh", "expires_in": 3600}

        mail_oauth.refresh_access = fake_refresh
        acct = {"oauth_access_token": "stale", "oauth_expires_at": 1, "oauth_refresh_token": "rtok"}
        tok = mail_oauth.ensure_access_token(acct)
        self.assertEqual(tok, "fresh")
        self.assertEqual(calls["rt"], "rtok")
        self.assertEqual(acct["oauth_access_token"], "fresh")
