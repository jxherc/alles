import asyncio
import unittest
from unittest import mock

from services import notify
from tests._client import ApiTest


class _Resp:
    status_code = 204


class _Resp4xx:
    status_code = 400


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


class _Client4xx:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **k):
        self.calls.append(url)
        return _Resp4xx()


def _cfg(discord="", token="", chat=""):
    return {"discord": discord, "tg_token": token, "tg_chat": chat}


class NotifyServiceTest(unittest.TestCase):
    def test_not_configured_is_noop(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg()):
            self.assertFalse(notify.configured())
            self.assertEqual(asyncio.run(notify.send("hi")), {"discord": None, "telegram": None})

    def test_sends_to_both_channels(self):
        cli = _Client()
        import services.net_guard as ng

        with (
            mock.patch.object(notify, "_targets", lambda: _cfg("https://discord/wh", "TOK", "123")),
            mock.patch.object(notify.httpx, "AsyncClient", lambda *a, **k: cli),
            mock.patch.object(ng, "is_safe_url", lambda u: True),  # fake host won't resolve; bypass guard
        ):
            self.assertTrue(notify.configured())
            res = asyncio.run(notify.send("hello world"))
        self.assertTrue(res["discord"])
        self.assertTrue(res["telegram"])
        self.assertIn("https://discord/wh", cli.calls)
        self.assertTrue(any("api.telegram.org" in u for u in cli.calls))

    def test_failure_is_swallowed(self):
        class _Boom:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                raise RuntimeError("network down")

        with (
            mock.patch.object(notify, "_targets", lambda: _cfg("https://d/wh")),
            mock.patch.object(notify.httpx, "AsyncClient", lambda *a, **k: _Boom()),
        ):
            res = asyncio.run(notify.send("x"))  # must not raise
        self.assertFalse(res["discord"])

    def test_configured_discord_only(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg(discord="https://d/wh")):
            self.assertTrue(notify.configured())

    def test_empty_text_is_noop_when_configured(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg("https://d/wh")):
            res = asyncio.run(notify.send(""))
        self.assertIsNone(res["discord"])
        self.assertIsNone(res["telegram"])

    def test_4xx_response_discord_false(self):
        with (
            mock.patch.object(notify, "_targets", lambda: _cfg("https://d/wh")),
            mock.patch.object(notify.httpx, "AsyncClient", lambda *a, **k: _Client4xx()),
        ):
            res = asyncio.run(notify.send("ping"))
        self.assertFalse(res["discord"])
        self.assertIsNone(res["telegram"])


class NotifyApiTest(ApiTest):
    def test_status_reports_configured(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg("https://d/wh")):
            self.assertTrue(self.client.get("/api/notify/status").json()["configured"])

    def test_test_route_sends_when_configured(self):
        with (
            mock.patch.object(notify, "_targets", lambda: _cfg("https://d/wh")),
            mock.patch.object(notify.httpx, "AsyncClient", lambda *a, **k: _Client()),
        ):
            r = self.client.post("/api/notify/test")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_test_route_400_when_unconfigured(self):
        with mock.patch.object(notify, "_targets", lambda: _cfg()):
            self.assertEqual(self.client.post("/api/notify/test").status_code, 400)


if __name__ == "__main__":
    unittest.main()
