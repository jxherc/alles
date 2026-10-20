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


class _Site(BaseHTTPRequestHandler):
    posts: list[str] = []

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(_PAGE)

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


if __name__ == "__main__":
    unittest.main()
