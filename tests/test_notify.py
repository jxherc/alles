import asyncio
import unittest
from unittest import mock

from services import notify
from tests._client import ApiTest


class _Resp:
    status_code = 204


class _Client:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **k):
        self.calls.append(url)
        return _Resp()


def _cfg(discord="", token="", chat=""):
    return {"discord": discord, "tg_token": token, "tg_chat": chat}


class NotifyServiceTest(unittest.TestCase):
    def test_not_configured_is_noop(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg()):
            self.assertFalse(notify.configured())
            self.assertEqual(asyncio.run(notify.send("hi")), {"discord": None, "telegram": None})

    def test_sends_to_both_channels(self):
        cli = _Client()
        with mock.patch.object(notify, "_targets", lambda: _cfg("https://discord/wh", "TOK", "123")), \
             mock.patch.object(notify.httpx, "AsyncClient", lambda *a, **k: cli):
            self.assertTrue(notify.configured())
            res = asyncio.run(notify.send("hello world"))
        self.assertTrue(res["discord"])
        self.assertTrue(res["telegram"])
        self.assertIn("https://discord/wh", cli.calls)
        self.assertTrue(any("api.telegram.org" in u for u in cli.calls))

    def test_failure_is_swallowed(self):
        class _Boom:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k): raise RuntimeError("network down")
        with mock.patch.object(notify, "_targets", lambda: _cfg("https://d/wh")), \
             mock.patch.object(notify.httpx, "AsyncClient", lambda *a, **k: _Boom()):
            res = asyncio.run(notify.send("x"))   # must not raise
        self.assertFalse(res["discord"])


class NotifyApiTest(ApiTest):
    def test_status_reports_configured(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg("https://d/wh")):
            self.assertTrue(self.client.get("/api/notify/status").json()["configured"])

    def test_test_route_sends_when_configured(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg("https://d/wh")), \
             mock.patch.object(notify.httpx, "AsyncClient", lambda *a, **k: _Client()):
            r = self.client.post("/api/notify/test")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_test_route_400_when_unconfigured(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg()):
            self.assertEqual(self.client.post("/api/notify/test").status_code, 400)


if __name__ == "__main__":
    unittest.main()
