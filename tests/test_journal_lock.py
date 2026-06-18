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
        self.assertEqual(self._set("1234").status_code, 200)
        self.assertTrue(self.client.get("/api/journal/lock/status").json()["enabled"])

    def test_locked_blocks_without_token(self):
        self._set("1234")
        self.assertEqual(self.client.get("/api/journal").status_code, 403)

    def test_unlock_returns_token(self):
        self._set("1234")
        r = self._unlock("1234")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["token"])

    def test_wrong_passcode_rejected(self):
        self._set("1234")
        self.assertEqual(self._unlock("0000").status_code, 401)

    def test_token_grants_access(self):
        self._set("1234")
        tok = self._unlock("1234").json()["token"]
        r = self.client.get("/api/journal", headers={"X-Journal-Token": tok})
        self.assertEqual(r.status_code, 200)

    def test_put_blocked_when_locked(self):
        self._set("1234")
        r = self.client.put("/api/journal/2026-06-18", json={"content": "secret"})
        self.assertEqual(r.status_code, 403)

    def test_put_allowed_with_token(self):
        self._set("1234")
        tok = self._unlock("1234").json()["token"]
        r = self.client.put(
            "/api/journal/2026-06-18", json={"content": "ok"}, headers={"X-Journal-Token": tok}
        )
        self.assertEqual(r.status_code, 200)

    def test_change_requires_old(self):
        self._set("1234")
        self.assertEqual(self._set("5678", old="wrong").status_code, 401)
        self.assertEqual(self._set("5678", old="1234").status_code, 200)
        self.assertEqual(self._unlock("5678").status_code, 200)

    def test_disable_requires_passcode(self):
        self._set("1234")
        self.assertEqual(
            self.client.post("/api/journal/lock/disable", json={"passcode": "bad"}).status_code, 401
        )
        self.assertEqual(
            self.client.post("/api/journal/lock/disable", json={"passcode": "1234"}).status_code,
            200,
        )
        self.assertFalse(self.client.get("/api/journal/lock/status").json()["enabled"])
        # back to open
        self.assertEqual(self.client.get("/api/journal").status_code, 200)

    def test_lock_clears_tokens(self):
        self._set("1234")
        tok = self._unlock("1234").json()["token"]
        self.client.post("/api/journal/lock")
        r = self.client.get("/api/journal", headers={"X-Journal-Token": tok})
        self.assertEqual(r.status_code, 403)

    def test_status_never_leaks_passcode(self):
        self._set("hunter2")
        s = self.client.get("/api/journal/lock/status").json()
        self.assertNotIn("passcode", s)
        self.assertNotIn("hunter2", str(s))
