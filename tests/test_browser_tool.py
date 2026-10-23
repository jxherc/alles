import asyncio
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from services import browser_tool as bt

# playwright is an optional dep (not in requirements.txt) — skip the whole module without it
try:
    import playwright  # noqa: F401

    _HAVE_PW = True
except Exception:
    _HAVE_PW = False

_PAGE = b"""<!doctype html><html><head><title>shop</title></head><body>
<h1 id="t">hello browser</h1>
<button id="b" onclick="document.getElementById('t').innerText='clicked now'">go</button>
<input id="inp" placeholder="your name">
<input type="password" placeholder="password">
<select id="size"><option>small</option><option>large</option></select>
<form method="post" action="/checkout"><button>Place order</button></form>
</body></html>"""

_LOGIN = b"""<!doctype html><html><head><title>sign in</title></head><body>
<input id="pw" type="password" style="position:absolute;left:20px;top:20px;width:200px;height:30px">
<input id="who" style="position:absolute;left:20px;top:80px;width:200px;height:30px">
</body></html>"""


class _Site(BaseHTTPRequestHandler):
    posts: list[str] = []

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "text/html")
        if self.path.startswith("/login"):
            self.send_header("set-cookie", "sid=owner-session; Path=/; Max-Age=3600")
        self.end_headers()
        self.wfile.write(_LOGIN if self.path.startswith("/login") else _PAGE)

    def do_POST(self):
        _Site.posts.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ordered")

    def log_message(self, *args):
        pass


@unittest.skipUnless(_HAVE_PW, "playwright not installed")
class BrowserToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"ALLES_DATA": self.data.name})
        self.env.start()
        # this test site is on loopback, which the real guard refuses
        self.local = mock.patch.object(
            bt, "_host_safe", lambda url: url.startswith("http://127.0.0.1")
        )
        self.local.start()
        _Site.posts.clear()

    def tearDown(self):
        self.local.stop()
        self.env.stop()
        self.data.cleanup()

    def run_async(self, coro):
        # playwright objects belong to the loop that made them, so close in the same one
        async def wrapped():
            try:
                return await coro
            finally:
                await bt._b.close()

        return asyncio.run(wrapped())

    def test_pages_read_as_numbered_elements_and_clicks_work(self):
        async def go():
            await bt._b.navigate(self.url)
            page = await bt._b.snapshot()
            go_ref = next(r for r, item in bt._b.items.items() if item["label"] == "go")
            await bt._b.click(str(go_ref))
            return page, await bt._b.read_text()

        page, after = self.run_async(go())
        self.assertIn("shop", page)
        self.assertIn("] button go", page)
        self.assertIn("(secret field: the owner fills this)", page)
        self.assertIn("clicked now", after)

    def test_typing_select_and_secret_fields(self):
        async def go():
            await bt._b.navigate(self.url)
            await bt._b.snapshot()
            refs = {item["label"]: ref for ref, item in bt._b.items.items()}
            await bt._b.type_text(str(refs["your name"]), "eric")
            name = await bt._b._page.input_value("#inp")
            await bt._b.select(
                str(next(r for r, i in bt._b.items.items() if i["tag"] == "select")), "large"
            )
            size = await bt._b._page.input_value("#size")
            with self.assertRaises(ValueError):
                await bt._b.type_text(str(refs["password"]), "hunter2")
            return name, size

        self.assertEqual(self.run_async(go()), ("eric", "large"))

    def test_submit_like_clicks_are_flagged_and_payments_are_blocked(self):
        async def go():
            await bt._b.navigate(self.url)
            await bt._b.snapshot()
            order = next(r for r, i in bt._b.items.items() if i["label"] == "Place order")
            go_ref = next(r for r, i in bt._b.items.items() if i["label"] == "go")
            flags = (bt._b.is_commit(order), bt._b.is_commit(go_ref))
            await bt._b.click(str(order))
            await asyncio.sleep(0.3)
            return flags, await bt._b.snapshot()

        flags, page = self.run_async(go())
        self.assertEqual(flags, (True, False))
        self.assertEqual(_Site.posts, [])  # the checkout POST never left the browser
        self.assertIn("blocked by alles: payment step", page)

    def test_private_and_payment_addresses_are_refused_by_default(self):
        self.local.stop()
        try:
            for url in ("http://127.0.0.1:6769/", "http://192.168.1.1/", "file:///etc/passwd"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    self.run_async(bt._b.navigate(url))
            with self.assertRaises(ValueError):
                self.run_async(bt._b.navigate("https://checkout.stripe.com/pay/cs_test"))
        finally:
            self.local.start()

    def test_tools_return_pages_and_the_gate_asks_before_submitting(self):
        from services import agent_tools

        async def go():
            opened = await agent_tools._browse("browse_open", {"url": self.url})
            order = next(r for r, i in bt._b.items.items() if i["label"] == "Place order")
            asks = agent_tools.decide_permission(
                "browse_click", {"ref": str(order)}, "full_auto", []
            )
            plain = agent_tools.decide_permission("browse_click", {"ref": "1"}, "full_auto", [])
            shot = await agent_tools._browse("browse_screenshot", {})
            return opened, asks, plain, shot

        opened, asks, plain, shot = self.run_async(go())
        self.assertIn("[1]", opened["output"])
        self.assertEqual((asks, plain), ("ask", "allow"))
        self.assertTrue(shot["image"].startswith("data:image/png;base64,iVBOR"))
        self.assertIn("browse_open", agent_tools.UNTRUSTED_TOOLS)

    def test_owner_signs_in_through_the_live_view_and_aide_waits(self):
        from services import agent_tools

        async def go():
            await bt._b.owner_open(self.url + "login", 480, 640)
            frame = await bt._b.owner_frame()
            await bt._b.owner_click(30, 30)  # the password field
            await bt._b.owner_type("hunter2")
            typed = await bt._b._page.input_value("#pw")
            # Aide is locked out while the owner is in there
            locked = await agent_tools._browse("browse_read", {})
            # even if a snapshot ran now, the typed password never becomes a label
            page = await bt._b.snapshot()
            sites = await bt._b.owner_close()
            after = await agent_tools._browse("browse_read", {})
            cookies = await bt._b._context.cookies()
            size = bt._b._page.viewport_size
            return frame, typed, locked, page, sites, after, cookies, size

        frame, typed, locked, page, sites, after, cookies, size = self.run_async(go())
        self.assertTrue(frame.startswith(b"\xff\xd8"))  # jpeg
        self.assertEqual(typed, "hunter2")
        self.assertTrue(locked["error"])
        self.assertIn("signing in", locked["output"])
        self.assertNotIn("hunter2", page)
        self.assertIn("secret field", page)
        self.assertIn("sign in to a site", page)
        self.assertEqual([row["site"] for row in sites], ["127.0.0.1"])
        self.assertNotIn("error", after)  # Aide can browse again, on a blank page
        self.assertIn("about:blank", after["output"])
        self.assertTrue(any(c["name"] == "sid" for c in cookies))
        self.assertEqual(size, {"width": 1280, "height": 900})

    def test_fast_owner_actions_land_in_order(self):
        # tap, type, tap, type sent back to back must not mix keystrokes across the fields
        async def go():
            await bt._b.owner_open(self.url + "login")
            await asyncio.gather(
                bt._b.owner_click(30, 95),
                bt._b.owner_type("owner@example.test"),
                bt._b.owner_click(30, 35),
                bt._b.owner_type("hunter2-hunter2"),
            )
            return (
                await bt._b._page.input_value("#who"),
                await bt._b._page.input_value("#pw"),
            )

        self.assertEqual(self.run_async(go()), ("owner@example.test", "hunter2-hunter2"))

    def test_sign_out_clears_the_site_and_forget_wipes_the_profile(self):
        async def go():
            await bt._b.owner_open(self.url + "login")
            await bt._b.owner_close()
            listed = [row["site"] for row in bt.signed_in_sites()]
            left = await bt._b.sign_out("127.0.0.1")
            cookies = await bt._b._context.cookies()
            await bt._b.owner_open(self.url + "login")
            await bt._b.owner_close()
            await bt._b.forget_everything()
            return listed, left, cookies

        listed, left, cookies = self.run_async(go())
        self.assertEqual(listed, ["127.0.0.1"])
        self.assertEqual((left, cookies), ([], []))
        self.assertEqual(bt.signed_in_sites(), [])
        self.assertFalse(os.path.exists(os.path.join(self.data.name, "browser", "profile")))

    def test_an_abandoned_live_view_lets_aide_back_in(self):
        from services import agent_tools

        async def go():
            await bt._b.owner_open(self.url)
            bt._b.owner_at -= 3600  # tab closed an hour ago
            with self.assertRaises(LookupError):
                await bt._b.owner_frame()
            return await agent_tools._browse("browse_read", {})

        self.assertNotIn("error", self.run_async(go()))

    def test_owner_keys_are_a_short_list(self):
        async def go():
            await bt._b.owner_open(self.url)
            await bt._b.owner_key("Tab")
            with self.assertRaises(ValueError):
                await bt._b.owner_key("Meta+Q")

        self.run_async(go())

    def test_live_view_refuses_private_addresses(self):
        self.local.stop()
        try:
            with self.assertRaises(ValueError):
                self.run_async(bt._b.owner_open("http://100.100.1.1/"))
            self.assertFalse(bt._b.owner_active())
        finally:
            self.local.start()


class SiteGroupingTests(unittest.TestCase):
    def test_site_of(self):
        self.assertEqual(bt.site_of("login.example.com"), "example.com")
        self.assertEqual(bt.site_of("www.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(bt.site_of(".accounts.google.com"), "google.com")
        self.assertEqual(bt.site_of("127.0.0.1"), "127.0.0.1")


@unittest.skipUnless(_HAVE_PW, "playwright not installed")
class SignInRouteTests(unittest.TestCase):
    """the http side: owner sessions only, and what the owner types never reaches a log."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ, {"ALLES_DATA": self.data.name, "AUTH_ENABLED": "false"}
        )
        self.env.start()
        self.local = mock.patch.object(
            bt, "_host_safe", lambda url: url.startswith("http://127.0.0.1")
        )
        self.local.start()

    def tearDown(self):
        self.local.stop()
        self.env.stop()
        self.data.cleanup()

    def test_the_whole_flow_over_http(self):
        import logging

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from core.api_errors import ApiError, api_error_handler
        from routes import aide

        app = FastAPI()
        app.add_exception_handler(ApiError, api_error_handler)
        app.include_router(aide.router)

        records = []
        handler = logging.Handler(logging.DEBUG)
        handler.emit = lambda record: records.append(record.getMessage() + repr(record.__dict__))
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            with TestClient(app) as client:
                denied = client.get(
                    "/api/aide/browser/sites", headers={"authorization": "Bearer alles_x"}
                )
                opened = client.post(
                    "/api/aide/browser/signin",
                    json={"url": self.url + "login", "width": 480, "height": 640},
                )
                frame = client.get("/api/aide/browser/signin/frame")
                client.post("/api/aide/browser/signin/click", json={"x": 30, "y": 30})
                typed = client.post("/api/aide/browser/signin/type", json={"text": "hunter2"})
                bad_key = client.post("/api/aide/browser/signin/type", json={"key": "Meta+Q"})
                done = client.post("/api/aide/browser/signin/done")
                closed = client.get("/api/aide/browser/signin/frame")
                listed = client.get("/api/aide/browser/sites")
                unknown = client.delete("/api/aide/browser/sites/nope.example")
                out = client.delete("/api/aide/browser/sites/127.0.0.1")
                client.portal.call(bt._b.close)
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertEqual(opened.json()["width"], 480)
        self.assertEqual(frame.headers["content-type"], "image/jpeg")
        self.assertEqual(frame.headers["cache-control"], "no-store")
        self.assertEqual(typed.status_code, 200)
        self.assertEqual(bad_key.status_code, 400)
        self.assertEqual([row["site"] for row in done.json()["sites"]], ["127.0.0.1"])
        self.assertEqual(closed.status_code, 409)
        self.assertEqual(listed.json()["sites"][0]["site"], "127.0.0.1")
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(out.json()["sites"], [])
        self.assertFalse(any("hunter2" in line for line in records))


if __name__ == "__main__":
    unittest.main()
