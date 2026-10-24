import asyncio
import unittest
from pathlib import Path

from starlette.responses import StreamingResponse

from tests._client import VaultApiTest

BASE_CSP = "object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"


class SecurityHeadersTest(VaultApiTest):
    def test_the_shell_gets_all_three(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/html"))
        self.assertEqual(r.headers["content-security-policy"], BASE_CSP)
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["referrer-policy"], "strict-origin-when-cross-origin")

    def test_json_gets_nosniff_and_referrer_but_no_csp(self):
        r = self.client.get("/api/ping")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["referrer-policy"], "strict-origin-when-cross-origin")
        self.assertNotIn("content-security-policy", r.headers)

    def test_static_scripts_get_nosniff_with_a_script_type(self):
        r = self.client.get("/static/js/app.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers["content-type"])
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("content-security-policy", r.headers)

    def test_a_route_with_its_own_csp_keeps_it(self):
        vault = Path(self._vault_tmp)
        (vault / "drawing.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        (vault / "page.html").write_text("<p>hi</p>")
        svg = self.client.get("/api/vault-md/raw", params={"path": "drawing.svg"})
        self.assertEqual(
            svg.headers["content-security-policy"],
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        )
        html = self.client.get("/api/vault-md/raw", params={"path": "page.html"})
        self.assertEqual(html.headers["content-security-policy"], "sandbox; default-src 'none'")
        # the route set nosniff itself, so it must not show up twice
        self.assertEqual(html.headers["x-content-type-options"], "nosniff")

    def test_a_route_with_its_own_referrer_policy_keeps_it(self):
        r = self.client.get("/api/finance/connections/plaid/return")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["referrer-policy"], "no-referrer")
        self.assertEqual(r.headers["content-security-policy"], BASE_CSP)


def _mw(inner):
    # imported here, not at the top: import sorting would lift it above the harness, and the app
    # must never load before the harness points ALLES_DATA at a throwaway folder
    from app import SecurityHeadersMiddleware

    return SecurityHeadersMiddleware(inner)


def _run(app, scope):
    sent = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def _http_scope():
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [],
    }


class SecurityHeadersAsgiTest(unittest.TestCase):
    def test_html_that_brings_its_own_csp_is_left_alone(self):
        async def inner(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"Content-Type", b"text/html; charset=utf-8"),
                        (b"Content-Security-Policy", b"sandbox"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b"<p>hi</p>"})

        start = _run(_mw(inner), _http_scope())[0]
        csp = [v for k, v in start["headers"] if k.lower() == b"content-security-policy"]
        self.assertEqual(csp, [b"sandbox"])

    def test_a_stream_is_passed_on_chunk_by_chunk(self):
        log = []

        async def gen():
            for i in range(3):
                log.append(f"made {i}")
                yield f"data: {i}\n\n"

        inner = StreamingResponse(gen(), media_type="text/event-stream")

        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                log.append("sent " + message["body"].decode().split()[1])

        asyncio.run(_mw(inner)(_http_scope(), receive, send))
        # each chunk leaves before the next one is made, so nothing is held back
        self.assertEqual(log, ["made 0", "sent 0", "made 1", "sent 1", "made 2", "sent 2"])
        headers = dict(sent[0]["headers"])
        self.assertTrue(headers[b"content-type"].startswith(b"text/event-stream"))
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertNotIn(b"content-security-policy", headers)

    def test_websockets_and_lifespan_pass_through_untouched(self):
        for kind in ("websocket", "lifespan"):
            seen = {}

            async def inner(scope, receive, send):
                seen.update(scope=scope, receive=receive, send=send)

            async def receive():
                return {}

            async def send(message):
                pass

            scope = {"type": kind}
            asyncio.run(_mw(inner)(scope, receive, send))
            self.assertIs(seen["scope"], scope)
            self.assertIs(seen["receive"], receive)
            self.assertIs(seen["send"], send)


if __name__ == "__main__":
    unittest.main()
