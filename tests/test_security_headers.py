import asyncio
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from starlette.responses import StreamingResponse

from tests._client import VaultApiTest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP_DIRECTIVES = {
    "default-src": "'self' https://cdn.plaid.com",
    "script-src": "'self' https://cdn.plaid.com",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": "'self' data: blob: https: http:",
    "font-src": "'self'",
    "media-src": "'self' blob:",
    "connect-src": "'self' https://*.plaid.com",
    "frame-src": "'self' https://cdn.plaid.com https://secure.plaid.com",
    "worker-src": "'self'",
    "manifest-src": "'self'",
    "object-src": "'none'",
    "base-uri": "'self'",
    "frame-ancestors": "'self'",
    "form-action": "'self'",
}
# code the policy would block, matched over whole files so a tag split across lines still counts:
# an on*= attribute inside a tag (quoted, unquoted, templated, after a space or a slash), one set
# from script, string-evaluated code, and javascript: urls
BLOCKED_CODE = (
    re.compile(r"<[a-zA-Z][^<>]*[\s/]on[a-z]{3,}\s*=", re.IGNORECASE),
    re.compile(r"""setAttribute\(\s*['"]on""", re.IGNORECASE),
    re.compile(r"""new Function|\beval\(|set(?:Timeout|Interval)\(\s*['"`]"""),
    re.compile(r"""(?:href|src|action)\s*=\s*["'`]?\s*javascript:""", re.IGNORECASE),
)
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\ssrc=)[^>]*>", re.IGNORECASE)


def blocked_code(text: str) -> list[str]:
    return [m.group(0)[:80] for rx in BLOCKED_CODE for m in rx.finditer(text)]


def scanned_sources() -> list[Path]:
    """every browser script and page alles serves, and the python that builds html"""
    files = [*sorted(STATIC.rglob("*.js")), *sorted(STATIC.glob("*.html"))]
    for folder in ("routes", "services"):
        files += sorted((ROOT / folder).rglob("*.py"))
    return files


def directives(policy: str) -> dict[str, str]:
    out = {}
    for part in policy.split(";"):
        name, _, value = part.strip().partition(" ")
        if name:
            out[name] = value.strip()
    return out


class SecurityHeadersTest(VaultApiTest):
    def test_the_shell_gets_the_app_policy_and_the_other_two(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/html"))
        self.assertEqual(directives(r.headers["content-security-policy"]), APP_DIRECTIVES)
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["referrer-policy"], "strict-origin-when-cross-origin")

    def test_scripts_are_files_only(self):
        script = directives(self.client.get("/").headers["content-security-policy"])["script-src"]
        for loose in ("'unsafe-inline'", "'unsafe-eval'", "data:", "blob:", "https:", "*"):
            self.assertNotIn(loose, script.split())

    def test_json_gets_nosniff_and_referrer_but_no_csp(self):
        r = self.client.get("/api/ping")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["referrer-policy"], "strict-origin-when-cross-origin")
        self.assertNotIn("content-security-policy", r.headers)

    def test_static_scripts_get_nosniff_with_a_script_type(self):
        for path in ("/static/js/app.js", "/static/prepaint.js", "/static/shared/book.js"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
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
        self.assertEqual(directives(r.headers["content-security-policy"]), APP_DIRECTIVES)

    def test_public_pages_get_the_app_policy(self):
        for path in ("/s/missing", "/book/missing", "/rsvp/missing", "/sv/missing"):
            r = self.client.get(path)
            self.assertTrue(r.headers["content-type"].startswith("text/html"), path)
            self.assertEqual(directives(r.headers["content-security-policy"]), APP_DIRECTIVES)

    def test_the_sandbox_page_brings_its_own_policy(self):
        r = self.client.get("/static/sandbox.html")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/html"))
        policy = r.headers["content-security-policy"]
        rules = directives(policy)
        # an opaque origin: no allow-same-origin, so nothing in it reaches alles cookies or storage
        self.assertEqual(rules["sandbox"], "allow-scripts")
        self.assertIn("'unsafe-inline'", rules["default-src"].split())
        self.assertNotIn("'self'", rules["default-src"].split())
        self.assertEqual(rules["frame-ancestors"], "'self'")
        self.assertEqual(rules["object-src"], "'none'")
        self.assertEqual(r.headers["referrer-policy"], "no-referrer")
        self.assertEqual(r.headers["cache-control"], "no-cache, no-store, must-revalidate")

    def test_the_offline_shell_keeps_prepaint_but_not_the_sandbox(self):
        urls = self.client.get("/api/pwa/precache").json()["urls"]
        self.assertIn("/static/prepaint.js", urls)
        # an opaque-origin frame never goes through the service worker, so a cached copy is
        # never used; offline the frame's spot says it needs a connection instead
        self.assertNotIn("/static/sandbox.html", urls)


class ApiDocsTest(VaultApiTest):
    PATHS = ("/docs", "/redoc", "/docs/oauth2-redirect", "/openapi.json")

    def test_off_by_default(self):
        for path in self.PATHS:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 404, path)
            self.assertNotIn("content-security-policy", r.headers)

    def test_on_they_load_their_cdn_scripts_on_their_own_paths_only(self):
        with mock.patch.dict(os.environ, {"ALLES_API_DOCS": "1"}):
            schema = self.client.get("/openapi.json")
            self.assertEqual(schema.status_code, 200)
            self.assertIn("/api/ping", schema.json()["paths"])
            for path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200, path)
                rules = directives(r.headers["content-security-policy"])
                self.assertIn("https://cdn.jsdelivr.net", rules["script-src"].split(), path)
                self.assertEqual(rules["frame-ancestors"], "'self'")
        shell = directives(self.client.get("/").headers["content-security-policy"])
        self.assertNotIn("https://cdn.jsdelivr.net", shell["script-src"])

    def test_on_with_auth_they_are_owner_only(self):
        with (
            mock.patch.dict(os.environ, {"ALLES_API_DOCS": "1"}),
            mock.patch("app.auth_enabled", return_value=True),
        ):
            for path in self.PATHS:
                self.assertEqual(self.client.get(path).status_code, 401, path)
            with mock.patch("app._request_authed", return_value=True):
                for path in self.PATHS:
                    self.assertEqual(self.client.get(path).status_code, 200, path)


class InlineCodeSourceTest(unittest.TestCase):
    """the policy blocks inline scripts and on*= handlers, so none may come back"""

    def test_pages_have_no_inline_script_or_handler(self):
        for page in sorted(STATIC.glob("*.html")):
            if page.name == "sandbox.html":
                continue  # its own policy allows inline code, inside an opaque origin
            html = page.read_text(encoding="utf-8")
            self.assertEqual(INLINE_SCRIPT.findall(html), [], page.name)
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        # the pre-paint theme still runs before the first paint: a plain blocking script in head
        head = html[: html.index("</head>")]
        self.assertIn('<script src="/static/prepaint.js"></script>', head)

    def test_no_source_carries_code_the_policy_blocks(self):
        found = []
        for path in scanned_sources():
            text = path.read_text(encoding="utf-8", errors="replace")
            found += [f"{path.relative_to(ROOT)}: {hit}" for hit in blocked_code(text)]
        self.assertEqual(found, [])

    def test_the_scan_catches_each_kind(self):
        for snippet in (
            '<button onclick="go()">',
            "<img src=x onerror=go()>",
            "<button onclick=${fn}>",
            '<svg/onload="go()">',
            '<button\nonclick="go()">',
            "el.setAttribute('onclick', 'go()')",
            "new Function('return 1')",
            "eval(code)",
            "setTimeout('go()', 9)",
            '<a href="javascript:go()">',
            "location.href = 'javascript:go()'",
        ):
            self.assertTrue(blocked_code(snippet), snippet)
        for fine in (
            "a.onclick = go",
            "if (a < b && c > d) x()",
            "img.addEventListener('load', f)",
        ):
            self.assertEqual(blocked_code(fine), [], fine)

    def test_server_built_pages_load_their_scripts_from_files(self):
        from routes import mcp, models, shared, status

        session = SimpleNamespace(name="chat", model="m", messages=[])
        pages = [
            shared._rsvp_html("tok", "title", "today", "accepted"),
            shared._book_html("tok", "title", "2026-10-24", "2026-10-31", "UTC"),
            shared._vshare_html("tok"),
            shared._session_html(session),
            shared._status_html("not found", "gone"),
            shared._doc_html("doc", "<p>hi</p>"),
            shared._folder_html("folder", "tok", [("a.txt", 3)], "view"),
            shared._album_html("album", "tok", []),
            status._render("status", []),
            models._oauth_result_page(True, "").body.decode(),
            mcp._sign_in_page(False, "nope").body.decode(),
        ]
        for page in pages:
            self.assertEqual(INLINE_SCRIPT.findall(page), [])
            self.assertEqual(blocked_code(page), [])
        self.assertIn('<script src="/static/shared/rsvp.js">', pages[0])
        self.assertIn('<script src="/static/shared/book.js">', pages[1])
        self.assertIn('<script src="/static/shared/vault.js">', pages[2])
        self.assertIn('<script src="/static/shared/print.js">', pages[3])


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
