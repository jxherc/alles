"""the browser Aide runs errands in (Playwright, headless Chromium).

one persistent profile under the data folder keeps sign-ins between runs. the agent reads a page
as numbered elements and acts on them by number. three hard limits live here, not in the prompt:
- private and local addresses are off-limits, including alles itself (no reaching the home network)
- checkout and payment requests are blocked: Aide never pays; the owner finishes that step
- password and card fields are never filled by the agent
clicks that submit, book, send or buy are flagged so the permission gate can ask first.
"""

from __future__ import annotations

import base64
import ipaddress
import re
from functools import lru_cache
from urllib.parse import urlsplit

PAY_HOSTS = (
    "checkout.stripe.com",
    "js.stripe.com",
    "api.stripe.com",
    "www.paypal.com",
    "paypal.com",
    "pay.google.com",
    "apple.com/apple-pay",
    "checkout.shopify.com",
    "secure.checkout.visa.com",
    "pay.amazon.com",
    "payments.amazon.com",
    "klarna.com",
    "afterpay.com",
    "affirm.com",
)
_PAY_PATH = re.compile(
    r"/(checkout|payment|payments|pay|billing|purchase|place-?order)(/|$|\?)", re.I
)
COMMIT_WORDS = re.compile(
    r"\b(submit|send|book|reserve|buy|purchase|order|pay|checkout|check out|confirm|place|subscribe|"
    r"sign up|register|apply|donate|delete|cancel (my|order|subscription)|transfer|post|publish)\b",
    re.I,
)

_SNAPSHOT_JS = """
() => {
  const wanted = 'a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],[role=checkbox],[role=tab],[contenteditable=true]';
  const items = [];
  let n = 0;
  for (const el of document.querySelectorAll(wanted)) {
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height || getComputedStyle(el).visibility === 'hidden') continue;
    n += 1;
    el.setAttribute('data-alles-ref', String(n));
    const label = (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder || el.name || el.title || el.alt || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    items.push({
      ref: n,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      label,
      href: el.getAttribute('href') || '',
      autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
      in_form: !!el.closest('form'),
    });
    if (n >= 150) break;
  }
  return { title: document.title, url: location.href, items, text: document.body ? document.body.innerText.slice(0, 12000) : '' };
}
"""


_TAILNET = ipaddress.ip_network("100.64.0.0/10")


@lru_cache(maxsize=512)
def _host_safe(url: str) -> bool:
    """public internet only. stricter than alles's integration check: a page the agent reads can
    point anywhere, so the home network and the tailnet are refused here too."""
    from services.net_guard import resolve_safe_url

    try:
        _, addresses = resolve_safe_url(url)
    except ValueError:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or (ip.version == 4 and ip in _TAILNET):
            return False
    return bool(addresses)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def is_payment(url: str) -> bool:
    lowered = url.lower()
    host = urlsplit(lowered).netloc
    return any(
        host == h or host.endswith("." + h) or lowered.find(h) >= 0 for h in PAY_HOSTS
    ) or bool(_PAY_PATH.search(urlsplit(url).path))


def is_secret_field(item: dict) -> bool:
    label = (item.get("label") or "").lower()
    return (
        item.get("type") == "password"
        or item.get("autocomplete", "").startswith("cc-")
        or any(
            word in label
            for word in ("card number", "cvv", "cvc", "security code", "password", "expiry")
        )
    )


class _Browser:
    def __init__(self):
        self._pw = None
        self._context = None
        self._page = None
        self.items: dict[int, dict] = {}
        self.blocked: list[str] = []

    async def _ensure(self):
        if self._page and not self._page.is_closed():
            return
        from playwright.async_api import async_playwright

        from core.settings import data_dir

        profile = data_dir() / "browser" / "profile"
        profile.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._context = await self._pw.chromium.launch_persistent_context(
            str(profile), headless=True, viewport={"width": 1280, "height": 900}
        )
        await self._context.route("**/*", self._guard)
        self._page = (
            self._context.pages[0] if self._context.pages else await self._context.new_page()
        )

    async def _guard(self, route):
        request = route.request
        url = request.url
        if url.startswith(("data:", "blob:", "about:")):
            return await route.continue_()
        if not _host_safe(_origin(url)):
            self.blocked.append(f"private address {urlsplit(url).netloc}")
            return await route.abort()
        if request.method != "GET" and is_payment(url):
            # Aide never pays; the owner finishes checkout themselves
            self.blocked.append(f"payment step at {urlsplit(url).netloc}")
            return await route.abort()
        await route.continue_()

    async def navigate(self, url: str) -> str:
        if "://" in url and not re.match(r"^https?://", url, re.I):
            raise ValueError("Aide's browser opens web pages only (no file: or other schemes)")
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        if not _host_safe(_origin(url)):
            raise ValueError("that address is private or local; Aide only browses the public web")
        if is_payment(url):
            raise ValueError(
                "that's a payment page; Aide stops before paying, so finish this step yourself"
            )
        await self._ensure()
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return self._page.url

    async def snapshot(self) -> str:
        """the page as text plus numbered elements; act on them by number."""
        await self._ensure()
        data = await self._page.evaluate(_SNAPSHOT_JS)
        self.items = {item["ref"]: item for item in data["items"]}
        lines = [f"{data['title']} — {data['url']}", ""]
        for item in data["items"]:
            kind = item["tag"] + (f"[{item['type']}]" if item["type"] else "")
            extra = " (secret field: the owner fills this)" if is_secret_field(item) else ""
            lines.append(f"[{item['ref']}] {kind} {item['label']}{extra}")
        lines += ["", "page text:", data["text"]]
        if self.blocked:
            lines += ["", "blocked by alles: " + "; ".join(sorted(set(self.blocked))[-5:])]
            self.blocked.clear()
        return "\n".join(lines)[:20000]

    def describe(self, ref) -> dict:
        try:
            return self.items.get(int(ref), {})
        except (TypeError, ValueError):
            return {}

    def is_commit(self, ref) -> bool:
        item = self.describe(ref)
        if not item:
            return False
        if item["tag"] in ("button", "input") and item["type"] in ("submit", "image"):
            return True
        if item["tag"] == "button" and item["in_form"] and item["type"] in ("", "submit"):
            return True
        return bool(COMMIT_WORDS.search(item.get("label", "")))

    def _locator(self, ref_or_selector):
        ref = str(ref_or_selector).strip()
        if ref.isdigit():
            return self._page.locator(f'[data-alles-ref="{ref}"]')
        return self._page.locator(ref)

    async def click(self, ref: str) -> str:
        await self._ensure()
        await self._locator(ref).first.click(timeout=10000)
        await self._page.wait_for_load_state("domcontentloaded")
        return self._page.url

    async def type_text(self, ref: str, text: str, submit: bool = False) -> str:
        await self._ensure()
        if str(ref).isdigit() and is_secret_field(self.describe(ref)):
            raise ValueError("Aide doesn't fill passwords or card details; the owner types those")
        target = self._locator(ref).first
        await target.fill(text, timeout=10000)
        if submit:
            await target.press("Enter")
            await self._page.wait_for_load_state("domcontentloaded")
        return self._page.url

    async def select(self, ref: str, value: str) -> str:
        await self._ensure()
        await self._locator(ref).first.select_option(label=value, timeout=10000)
        return value

    async def scroll(self, direction: str = "down") -> str:
        await self._ensure()
        await self._page.mouse.wheel(0, -800 if direction == "up" else 800)
        return direction

    async def back(self) -> str:
        await self._ensure()
        await self._page.go_back(wait_until="domcontentloaded")
        return self._page.url

    async def read_text(self) -> str:
        await self._ensure()
        return (await self._page.inner_text("body"))[:20000]

    async def current_url(self) -> str:
        await self._ensure()
        return self._page.url

    async def screenshot(self) -> str:
        await self._ensure()
        png = await self._page.screenshot()
        return base64.b64encode(png).decode()

    async def close(self):
        try:
            if self._context:
                await self._context.close()
            if self._pw:
                await self._pw.stop()
        finally:
            self._pw = self._context = self._page = None
            self.items = {}


# one browser per process; runs share its profile (and sign-ins)
_b = _Browser()
