"""10e — a DOM-level browser automation tool for the agent (Playwright/CDP).

Distinct from pixel computer-use (pyautogui): this drives a real headless Chromium by selector —
navigate, read, click, type, screenshot. One lazily-launched session persists across an agent run's
turns (the run shares a single event loop), so the agent can browse statefully.
"""

import base64


class _Browser:
    def __init__(self):
        self._pw = None
        self._browser = None
        self._page = None

    async def _ensure(self):
        if self._page:
            return
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch()
        self._page = await self._browser.new_page()

    async def navigate(self, url: str) -> str:
        await self._ensure()
        await self._page.goto(url, wait_until="domcontentloaded")
        return self._page.url

    async def read_text(self) -> str:
        await self._ensure()
        return (await self._page.inner_text("body"))[:20000]

    async def click(self, selector: str) -> str:
        await self._ensure()
        await self._page.click(selector, timeout=8000)
        return self._page.url

    async def type_text(self, selector: str, text: str) -> str:
        await self._ensure()
        await self._page.fill(selector, text, timeout=8000)
        return await self._page.input_value(selector)

    async def current_url(self) -> str:
        await self._ensure()
        return self._page.url

    async def screenshot(self) -> str:
        await self._ensure()
        png = await self._page.screenshot()
        return base64.b64encode(png).decode()

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        finally:
            self._pw = self._browser = self._page = None


# one session per process / agent run
_b = _Browser()
