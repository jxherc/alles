import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cs
from tests._client import ApiTest


class JournalLockTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.sp = mock.patch.object(cs, "_SETTINGS_FILE", Path(self.tmp.name) / "settings.json")
        self.sp.start()
        # clear any unlock tokens leaked from another test
        import routes.journal as j

        j._unlock_tokens.clear()

    def tearDown(self):
        self.sp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _set(self, passcode, old=""):
        return self.client.post("/api/journal/lock/set", json={"passcode": passcode, "old": old})

    def _unlock(self, passcode):
        return self.client.post("/api/journal/unlock", json={"passcode": passcode})

    def test_status_unset_by_default(self):
        s = self.client.get("/api/journal/lock/status").json()
        self.assertFalse(s["enabled"])

    def test_open_when_no_passcode(self):
        # with no passcode set, data endpoints are reachable without a token
        self.assertEqual(self.client.get("/api/journal").status_code, 200)

    def test_set_enables_lock(self):
        self.assertEqual(self._set("journal-passcode-one").status_code, 200)
        self.assertTrue(self.client.get("/api/journal/lock/status").json()["enabled"])

    def test_new_passcode_rejects_fewer_than_twelve_characters(self):
        response = self._set("short")
        self.assertEqual(response.status_code, 400)
        self.assertIn("at least 12", response.json()["detail"])

    def test_new_passcode_rejects_whitespace_only_input(self):
        response = self._set(" " * 12)
        self.assertEqual(response.status_code, 400)
        self.assertIn("at least 12", response.json()["detail"])

    def test_new_passcode_preserves_leading_and_trailing_whitespace(self):
        passcode = "  journal-passcode-one  "
        self.assertEqual(self._set(passcode).status_code, 200)
        self.assertEqual(self._unlock(passcode).status_code, 200)
        self.assertEqual(self._unlock(passcode.strip()).status_code, 401)

    def test_locked_blocks_without_token(self):
        self._set("journal-passcode-one")
        self.assertEqual(self.client.get("/api/journal").status_code, 403)

    def test_unlock_returns_token(self):
        self._set("journal-passcode-one")
        r = self._unlock("journal-passcode-one")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["token"])

    def test_wrong_passcode_rejected(self):
        self._set("journal-passcode-one")
        self.assertEqual(self._unlock("0000").status_code, 401)

    def test_token_grants_access(self):
        self._set("journal-passcode-one")
        tok = self._unlock("journal-passcode-one").json()["token"]
        r = self.client.get("/api/journal", headers={"X-Journal-Token": tok})
        self.assertEqual(r.status_code, 200)

    def test_put_blocked_when_locked(self):
        self._set("journal-passcode-one")
        r = self.client.put("/api/journal/2026-06-18", json={"content": "secret"})
        self.assertEqual(r.status_code, 403)

    def test_put_allowed_with_token(self):
        self._set("journal-passcode-one")
        tok = self._unlock("journal-passcode-one").json()["token"]
        r = self.client.put(
            "/api/journal/2026-06-18", json={"content": "ok"}, headers={"X-Journal-Token": tok}
        )
        self.assertEqual(r.status_code, 200)

    def test_change_requires_old(self):
        self._set("journal-passcode-one")
        self.assertEqual(self._set("journal-passcode-two", old="wrong").status_code, 401)
        self.assertEqual(
            self._set("journal-passcode-two", old="journal-passcode-one").status_code,
            200,
        )
        self.assertEqual(self._unlock("journal-passcode-two").status_code, 200)

    def test_disable_requires_passcode(self):
        self._set("journal-passcode-one")
        self.assertEqual(
            self.client.post("/api/journal/lock/disable", json={"passcode": "bad"}).status_code, 401
        )
        self.assertEqual(
            self.client.post(
                "/api/journal/lock/disable", json={"passcode": "journal-passcode-one"}
            ).status_code,
            200,
        )
        self.assertFalse(self.client.get("/api/journal/lock/status").json()["enabled"])
        # back to open
        self.assertEqual(self.client.get("/api/journal").status_code, 200)

    def test_lock_clears_tokens(self):
        self._set("journal-passcode-one")
        tok = self._unlock("journal-passcode-one").json()["token"]
        self.client.post("/api/journal/lock")
        r = self.client.get("/api/journal", headers={"X-Journal-Token": tok})
        self.assertEqual(r.status_code, 403)

    def test_status_reports_whether_the_presented_unlock_token_is_still_valid(self):
        self._set("journal-passcode-one")
        locked = self.client.get("/api/journal/lock/status").json()
        self.assertFalse(locked["unlocked"])
        token = self._unlock("journal-passcode-one").json()["token"]
        headers = {"X-Journal-Token": token}
        unlocked = self.client.get("/api/journal/lock/status", headers=headers).json()
        self.assertTrue(unlocked["unlocked"])
        self.client.post("/api/journal/lock")
        relocked = self.client.get("/api/journal/lock/status", headers=headers).json()
        self.assertFalse(relocked["unlocked"])

    def test_status_never_leaks_passcode(self):
        self._set("journal-private-pass")
        s = self.client.get("/api/journal/lock/status").json()
        self.assertNotIn("passcode", s)
        self.assertNotIn("journal-private-pass", str(s))
