import asyncio
import tempfile
import unittest
from pathlib import Path

from services import browser_tool as bt

_HTML = """<!doctype html><html><body>
<h1 id="t">hello browser</h1>
<button id="b" onclick="document.getElementById('t').innerText='clicked now'">go</button>
<input id="inp">
</body></html>"""


def _page_url():
    d = tempfile.mkdtemp(prefix="browtool-")
    p = Path(d) / "page.html"
    p.write_text(_HTML, "utf-8")
    return p.as_uri()


class BrowserToolTests(unittest.TestCase):
    def test_navigate_and_read(self):
        url = _page_url()

        async def go():
            try:
                landed = await bt._b.navigate(url)
                txt = await bt._b.read_text()
                return landed, txt
            finally:
                await bt._b.close()

        landed, txt = asyncio.run(go())
        self.assertIn("hello browser", txt)
        self.assertTrue(landed.startswith("file:"))

    def test_current_url(self):
        url = _page_url()

        async def go():
            try:
                await bt._b.navigate(url)
                return await bt._b.current_url()
            finally:
                await bt._b.close()

        self.assertTrue(asyncio.run(go()).startswith("file:"))

    def test_click_changes_dom(self):
        url = _page_url()

        async def go():
            try:
                await bt._b.navigate(url)
                await bt._b.click("#b")
                return await bt._b.read_text()
            finally:
                await bt._b.close()

        self.assertIn("clicked now", asyncio.run(go()))

    def test_type_into_input(self):
        url = _page_url()

        async def go():
            try:
                await bt._b.navigate(url)
                return await bt._b.type_text("#inp", "abc123")
            finally:
                await bt._b.close()

        self.assertEqual(asyncio.run(go()), "abc123")

    def test_screenshot_returns_png_b64(self):
        url = _page_url()

        async def go():
            try:
                await bt._b.navigate(url)
                return await bt._b.screenshot()
            finally:
                await bt._b.close()

        shot = asyncio.run(go())
        self.assertTrue(shot.startswith("iVBOR"))  # PNG magic in base64

    def test_close_resets(self):
        url = _page_url()

        async def go():
            await bt._b.navigate(url)
            await bt._b.close()
            return bt._b._page

        self.assertIsNone(asyncio.run(go()))


class BrowserToolAgentTests(unittest.TestCase):
    def test_tool_browse_open_and_read(self):
        import services.agent_tools as at

        url = _page_url()

        async def go():
            try:
                o = await at.execute("browse_open", {"url": url})
                r = await at.execute("browse_read", {})
                return o, r
            finally:
                await bt._b.close()

        o, r = asyncio.run(go())
        self.assertFalse(o.get("error"))
        self.assertIn("hello browser", r.get("output", ""))

    def test_tool_browse_click(self):
        import services.agent_tools as at

        url = _page_url()

        async def go():
            try:
                await at.execute("browse_open", {"url": url})
                await at.execute("browse_click", {"selector": "#b"})
                return await at.execute("browse_read", {})
            finally:
                await bt._b.close()

        self.assertIn("clicked now", asyncio.run(go()).get("output", ""))

    def test_tool_browse_type(self):
        import services.agent_tools as at

        url = _page_url()

        async def go():
            try:
                await at.execute("browse_open", {"url": url})
                return await at.execute("browse_type", {"selector": "#inp", "text": "hello"})
            finally:
                await bt._b.close()

        self.assertFalse(asyncio.run(go()).get("error"))


if __name__ == "__main__":
    unittest.main()
