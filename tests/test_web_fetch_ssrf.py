"""_web_fetch follows redirects manually so EVERY hop is SSRF-checked — with httpx
follow_redirects=True a public url could 302 to the cloud-metadata / localhost address and the
guard (which only saw the first url) would never catch it."""

import asyncio
import unittest
from unittest import mock

from services import agent_tools as at


class _Resp:
    def __init__(self, redirect=None, text="", ctype="text/plain"):
        self.is_redirect = redirect is not None
        self.headers = {"location": redirect} if redirect else {"content-type": ctype}
        self.text = text

    def raise_for_status(self):
        pass


def _client(responses):
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
            return _Resp(text="(default)")

    return _C


class WebFetchSSRFTest(unittest.TestCase):
    def test_redirect_to_internal_is_blocked(self):
        # public IP literal (no DNS) → 302 to cloud-metadata; the hop must be re-checked and refused
        resp = {"93.184.216.34": _Resp(redirect="http://169.254.169.254/latest/meta-data/")}
        with mock.patch.object(at.httpx, "AsyncClient", _client(resp)):
            out = asyncio.run(at._web_fetch("http://93.184.216.34/r"))
        self.assertTrue(out["error"])
        self.assertIn("internal", out["output"])

    def test_redirect_to_localhost_is_blocked(self):
        resp = {"93.184.216.34": _Resp(redirect="http://127.0.0.1:8000/api/settings")}
        with mock.patch.object(at.httpx, "AsyncClient", _client(resp)):
            out = asyncio.run(at._web_fetch("http://93.184.216.34/r"))
        self.assertTrue(out["error"])

    def test_public_to_public_redirect_followed(self):
        resp = {
            "93.184.216.34/start": _Resp(redirect="http://8.8.8.8/end"),
            "8.8.8.8/end": _Resp(text="final content"),
        }
        with mock.patch.object(at.httpx, "AsyncClient", _client(resp)):
            out = asyncio.run(at._web_fetch("http://93.184.216.34/start"))
        self.assertFalse(out["error"])
        self.assertIn("final content", out["output"])
