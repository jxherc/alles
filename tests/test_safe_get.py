"""net_guard.safe_get re-checks the SSRF guard on EVERY redirect hop (shared by calendar ICS
fetch + research webpage fetch). a public url that 302s to internal must be refused."""

import asyncio
import unittest
from unittest import mock

import httpx

from services import net_guard


class _Resp:
    def __init__(self, redirect=None):
        self.is_redirect = redirect is not None
        self.headers = {"location": redirect} if redirect else {"content-type": "text/plain"}
        self.text = "" if redirect else "final content"

    def raise_for_status(self):
        pass


def _client(responses):
    class _C:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            for k, v in responses.items():
                if k in url:
                    return v
            return _Resp()

    return _C


class SafeGetTest(unittest.TestCase):
    def test_redirect_to_internal_raises(self):
        resp = {"93.184.216.34": _Resp(redirect="http://169.254.169.254/latest/meta-data/")}
        with mock.patch.object(httpx, "Client", _client(resp)):
            with self.assertRaises(ValueError):
                net_guard.safe_get("http://93.184.216.34/r")

    def test_public_redirect_followed(self):
        resp = {
            "93.184.216.34/s": _Resp(redirect="http://8.8.8.8/e"),
            "8.8.8.8/e": _Resp(),
        }
        with mock.patch.object(httpx, "Client", _client(resp)):
            r = net_guard.safe_get("http://93.184.216.34/s")
        self.assertEqual(r.text, "final content")

    def test_too_many_redirects_raises(self):
        # a loop of public hops eventually trips the cap
        resp = {"8.8.8.8": _Resp(redirect="http://8.8.8.8/next")}
        with mock.patch.object(httpx, "Client", _client(resp)):
            with self.assertRaises(ValueError):
                net_guard.safe_get("http://8.8.8.8/start")


def _aclient(responses):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            for k, v in responses.items():
                if k in url:
                    return v
            return _Resp()

    return _C


class SafeGetAsyncTest(unittest.TestCase):
    def test_async_redirect_to_internal_raises(self):
        resp = {"93.184.216.34": _Resp(redirect="http://169.254.169.254/")}
        with mock.patch.object(httpx, "AsyncClient", _aclient(resp)):
            with self.assertRaises(ValueError):
                asyncio.run(net_guard.safe_get_async("http://93.184.216.34/r"))

    def test_async_public_followed(self):
        resp = {"93.184.216.34/s": _Resp(redirect="http://8.8.8.8/e"), "8.8.8.8/e": _Resp()}
        with mock.patch.object(httpx, "AsyncClient", _aclient(resp)):
            r = asyncio.run(net_guard.safe_get_async("http://93.184.216.34/s"))
        self.assertEqual(r.text, "final content")
