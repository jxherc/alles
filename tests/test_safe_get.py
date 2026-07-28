"""net_guard.safe_get re-checks the SSRF guard on EVERY redirect hop (shared by calendar ICS
fetch + research webpage fetch). a public url that 302s to internal must be refused."""

import asyncio
import gzip
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
    def test_public_media_fails_closed_through_fake_ip_dns(self):
        def resolve(host, _port):
            address = "198.18.0.20" if host == "example.com" else "198.18.3.91"
            return [(2, 1, 6, "", (address, 0))]

        with mock.patch.object(net_guard.socket, "getaddrinfo", side_effect=resolve):
            self.assertFalse(net_guard.is_public_url("https://s.yimg.com/image.jpg"))

    def test_bound_url_preserves_semicolon_path_parameters(self):
        parsed, addresses = net_guard._resolve_public_url(
            "https://8.8.8.8/image;version=2?size=large"
        )
        self.assertEqual(
            net_guard._bound_url(parsed, addresses[0]),
            "https://8.8.8.8/image;version=2?size=large",
        )

    def test_public_media_never_allows_literal_fake_ip_or_private_dns(self):
        def resolve(host, _port):
            address = "198.18.0.20" if host == "example.com" else "127.0.0.1"
            return [(2, 1, 6, "", (address, 0))]

        with mock.patch.object(net_guard.socket, "getaddrinfo", side_effect=resolve):
            self.assertFalse(net_guard.is_public_url("https://198.18.3.91/image.jpg"))
            self.assertFalse(net_guard.is_public_url("https://private.example/image.jpg"))

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

    def test_public_fetch_binds_request_to_validated_address_and_limits_body(self):
        seen = {}

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def build_request(self, method, url, **kwargs):
                seen["url"] = url
                seen["headers"] = kwargs["headers"]
                seen["extensions"] = kwargs["extensions"]
                return httpx.Request(
                    method,
                    url,
                    headers=kwargs["headers"],
                    extensions=kwargs["extensions"],
                )

            async def send(self, request, stream=False):
                return httpx.Response(
                    200,
                    headers={"content-type": "image/png"},
                    content=b"12345",
                    request=request,
                )

        with (
            mock.patch.object(
                net_guard.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
            ),
            mock.patch.object(httpx, "AsyncClient", Client),
        ):
            with self.assertRaisesRegex(ValueError, "byte limit"):
                asyncio.run(
                    net_guard.safe_get_public_async("https://example.com/image.png", max_bytes=4)
                )

        self.assertEqual(seen["url"], "https://93.184.216.34/image.png")
        self.assertEqual(seen["headers"]["host"], "example.com")
        self.assertEqual(seen["extensions"]["sni_hostname"], b"example.com")

    def test_public_fetch_retries_each_validated_address(self):
        attempted = []

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def build_request(self, method, url, **kwargs):
                return httpx.Request(method, url, **kwargs)

            async def send(self, request, stream=False):
                attempted.append(str(request.url))
                if request.url.host == "2001:4860:4860::8888":
                    raise httpx.ConnectError("ipv6 unavailable", request=request)
                return httpx.Response(200, content=b"ok", request=request)

        with (
            mock.patch.object(
                net_guard.socket,
                "getaddrinfo",
                return_value=[
                    (10, 1, 6, "", ("2001:4860:4860::8888", 0, 0, 0)),
                    (2, 1, 6, "", ("8.8.8.8", 0)),
                ],
            ),
            mock.patch.object(httpx, "AsyncClient", Client),
        ):
            response = asyncio.run(net_guard.safe_get_public_async("https://example.com/image"))

        self.assertEqual(response.content, b"ok")
        self.assertEqual(
            attempted,
            ["https://[2001:4860:4860::8888]/image", "https://8.8.8.8/image"],
        )

    def test_bounded_public_fetch_drops_headers_for_already_decoded_content(self):
        payload = b"decoded public payload"

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def build_request(self, method, url, **kwargs):
                return httpx.Request(method, url, **kwargs)

            async def send(self, request, stream=False):
                compressed = gzip.compress(payload)
                return httpx.Response(
                    200,
                    headers={
                        "content-encoding": "gzip",
                        "content-length": str(len(compressed)),
                        "content-type": "text/plain",
                    },
                    content=compressed,
                    request=request,
                )

        with (
            mock.patch.object(
                net_guard.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
            ),
            mock.patch.object(httpx, "AsyncClient", Client),
        ):
            response = asyncio.run(
                net_guard.safe_get_public_async(
                    "https://example.com/compressed.txt",
                    max_bytes=len(payload),
                )
            )

        self.assertEqual(response.content, payload)
        self.assertNotIn("content-encoding", response.headers)
        self.assertEqual(response.headers["content-length"], str(len(payload)))

    def test_public_fetch_idna_encodes_host_header_and_sni(self):
        seen = {}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, **kwargs):
                seen["url"] = url
                seen["headers"] = kwargs["headers"]
                seen["extensions"] = kwargs["extensions"]
                return httpx.Request(method, url, **kwargs)

            async def send(self, request, stream=False):
                return httpx.Response(200, content=b"ok", request=request)

        with (
            mock.patch.object(
                net_guard.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
            ),
            mock.patch.object(httpx, "AsyncClient", Client),
        ):
            response = asyncio.run(net_guard.safe_get_public_async("https://bücher.example/x"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["url"], "https://93.184.216.34/x")
        self.assertEqual(seen["headers"]["host"], "xn--bcher-kva.example")
        self.assertEqual(seen["extensions"]["sni_hostname"], b"xn--bcher-kva.example")

    def test_public_redirect_to_another_hostname_uses_a_fresh_tls_pool(self):
        clients = []
        seen_sni = []

        class Client:
            def __init__(self, *args, **kwargs):
                clients.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def build_request(self, method, url, **kwargs):
                return httpx.Request(method, url, **kwargs)

            async def send(self, request, stream=False):
                seen_sni.append(request.extensions["sni_hostname"])
                if len(clients) == 1:
                    return httpx.Response(
                        302,
                        headers={"location": "https://second.example/final"},
                        request=request,
                    )
                return httpx.Response(200, content=b"ok", request=request)

        with (
            mock.patch.object(
                net_guard.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
            ),
            mock.patch.object(httpx, "AsyncClient", Client),
        ):
            response = asyncio.run(net_guard.safe_get_public_async("https://first.example/start"))

        self.assertEqual(response.content, b"ok")
        self.assertEqual(len(clients), 2)
        self.assertEqual(seen_sni, [b"first.example", b"second.example"])
