"""the browser Aide runs errands in (Playwright, headless Chromium).

one persistent profile under the data folder keeps sign-ins between runs. the agent reads a page
as numbered elements and acts on them by number. three hard limits live here, not in the prompt:
- private and local addresses are off-limits, including alles itself (no reaching the home network)
- checkout and payment requests are blocked: Aide never pays; the owner finishes that step
- password and card fields are never filled by the agent
clicks that submit, book, send or buy are flagged so the permission gate can ask first.

the owner signs in through a live view: alles streams screenshots of the same page and forwards
the owner's clicks and keys. Aide is locked out while that view is open, and what the owner types
goes straight to the page (never into a snapshot, a log or the conversation).
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import re
import shutil
import time
from datetime import UTC, datetime
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
    // a password or card field's value is what the owner typed; never read it into a label
    const secret = (el.getAttribute('type') || '').toLowerCase() === 'password' || (el.getAttribute('autocomplete') || '').toLowerCase().startsWith('cc-');
    const label = (el.getAttribute('aria-label') || el.innerText || (secret ? '' : el.value) || el.placeholder || el.name || el.title || el.alt || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
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


# keys the owner can press from the live view; everything else goes in as typed text
OWNER_KEYS = ("Enter", "Tab", "Shift+Tab", "Backspace", "Escape", "ArrowUp", "ArrowDown", "Space")
_OWNER_IDLE = 120  # seconds without a frame or action before the live view counts as closed
_VIEWPORT = {"width": 1280, "height": 900}
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or"}


def site_of(host: str) -> str:
    """example.com for www.example.com or login.example.co.uk -> example.co.uk. rough, no suffix
    list; only used to group cookies for sign-out."""
    host = host.lower().strip(".")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    labels = [part for part in host.split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    keep = 3 if labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2 else 2
    return ".".join(labels[-keep:])


def _signins_path():
    from core.settings import data_dir

    return data_dir() / "browser" / "signins.json"


def signed_in_sites() -> list[dict]:
    try:
        rows = json.loads(_signins_path().read_text())
    except (OSError, ValueError):
        return []
    rows = [row for row in rows if isinstance(row, dict) and row.get("site")]
    return sorted(rows, key=lambda row: row.get("at", ""), reverse=True)


def _save_sites(rows: list[dict]):
    path = _signins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1))


class _Browser:
    def __init__(self):
        self._pw = None
        self._context = None
        self._page = None
        self.items: dict[int, dict] = {}
        self.blocked: list[str] = []
        self.owner_at = 0.0  # last owner activity in the live view; 0 = closed
        self.owner_hosts: set[str] = set()
        self.owner_site = ""
        self._owner_lock: asyncio.Lock | None = None

    async def _ensure(self):
        if self._page and not self._page.is_closed():
            return
        from playwright.async_api import async_playwright

        from core.settings import data_dir

        profile = data_dir() / "browser" / "profile"
        profile.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._context = await self._pw.chromium.launch_persistent_context(
            str(profile), headless=True, viewport=_VIEWPORT
        )
        await self._context.route("**/*", self._guard)
        self._page = (
            self._context.pages[0] if self._context.pages else await self._context.new_page()
        )
        self._page.on("framenavigated", self._track_owner_host)

    def _track_owner_host(self, frame):
        # sign-ins often hop through another site (accounts.google.com etc); sign-out clears those too
        if self.owner_at and frame == self._page.main_frame:
            host = urlsplit(frame.url).hostname
            if host:
                self.owner_hosts.add(host)

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

    @staticmethod
    def _public_url(url: str) -> str:
        url = url.strip()
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
        return url

    async def navigate(self, url: str) -> str:
        url = self._public_url(url)
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
        if any(is_secret_field(item) for item in data["items"]):
            lines += [
                "",
                "this page asks for a password or card. if it's a sign-in, ask the owner to sign in"
                " from settings → connections & tools → sign in to a site, then open it again.",
            ]
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

    # ── the owner's live view ──

    def owner_active(self) -> bool:
        return bool(self.owner_at) and time.monotonic() - self.owner_at < _OWNER_IDLE

    async def settle_owner(self) -> bool:
        """True while the owner has the live view open. a view left idle (tab closed) gets closed
        here, so Aide isn't locked out forever."""
        if self.owner_active():
            return True
        if self.owner_at:
            await self.owner_close()
        return False

    async def owner_open(self, url: str, width: int = 1280, height: int = 900) -> dict:
        url = self._public_url(url)
        await self._ensure()
        self.owner_at = time.monotonic()
        self.owner_hosts = {urlsplit(url).hostname or ""} - {""}
        self.owner_site = site_of(urlsplit(url).hostname or "")
        self.items = {}  # Aide's numbers point at a page it can't see any more
        await self._page.set_viewport_size(
            {"width": max(320, min(int(width), 1280)), "height": max(300, min(int(height), 1000))}
        )
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            await self.owner_close()
            raise
        return await self.owner_state()

    async def owner_state(self) -> dict:
        size = self._page.viewport_size or _VIEWPORT
        return {
            "open": self.owner_active(),
            "url": self._page.url,
            "title": await self._page.title(),
            "width": size["width"],
            "height": size["height"],
        }

    def _owner_page(self):
        if not self.owner_active() or not self._page or self._page.is_closed():
            raise LookupError("the sign-in view is closed; open the site again")
        self.owner_at = time.monotonic()
        return self._page

    def _in_order(self) -> asyncio.Lock:
        # clicks and typing run one at a time, or a fast tap-type-tap-type mixes keystrokes
        # across two fields
        if self._owner_lock is None:
            self._owner_lock = asyncio.Lock()
        return self._owner_lock

    async def owner_frame(self) -> bytes:
        return await self._owner_page().screenshot(type="jpeg", quality=70)

    async def owner_click(self, x: float, y: float):
        async with self._in_order():
            page = self._owner_page()
            size = page.viewport_size or _VIEWPORT
            await page.mouse.click(
                max(0, min(float(x), size["width"] - 1)), max(0, min(float(y), size["height"] - 1))
            )

    async def owner_type(self, text: str):
        # straight into whatever the owner focused on the page; nothing here keeps or logs it
        async with self._in_order():
            await self._owner_page().keyboard.type(text[:500])

    async def owner_key(self, key: str):
        if key not in OWNER_KEYS:
            raise ValueError("unknown key")
        async with self._in_order():
            await self._owner_page().keyboard.press(key)

    async def owner_scroll(self, dy: float):
        async with self._in_order():
            await self._owner_page().mouse.wheel(0, max(-2000, min(float(dy), 2000)))

    async def owner_back(self):
        async with self._in_order():
            await self._owner_page().go_back(wait_until="domcontentloaded")

    async def owner_close(self) -> list[dict]:
        """end the live view, remember which sites now hold cookies, leave a blank page."""
        hosts, opened = self.owner_hosts, self.owner_site
        self.owner_at, self.owner_hosts, self.owner_site = 0.0, set(), ""
        if not self._page or self._page.is_closed():
            return signed_in_sites()
        cookies = {site_of(c["domain"]) for c in await self._context.cookies()}
        kept = sorted({site_of(host) for host in hosts} & cookies)
        if kept and opened:
            # one row per sign-in, named after the site the owner opened
            rows = [row for row in signed_in_sites() if row["site"] != opened]
            rows.append(
                {
                    "site": opened,
                    "hosts": sorted(hosts),
                    "also": [site for site in kept if site != opened],
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            _save_sites(rows)
        # blank page + desktop size again, so Aide never lands on what the owner typed
        await self._page.goto("about:blank")
        await self._page.set_viewport_size(_VIEWPORT)
        return signed_in_sites()

    async def sign_out(self, site: str) -> list[dict]:
        """drop cookies and stored data for one site (and the sign-in hosts it used)."""
        rows = signed_in_sites()
        row = next((r for r in rows if r["site"] == site), None)
        if row is None:
            raise LookupError("no saved sign-in for that site")
        await self._ensure()
        for name in [site, *row.get("also", [])]:
            await self._context.clear_cookies(domain=re.compile(rf"(^|\.){re.escape(name)}$"))
        cdp = await self._context.new_cdp_session(self._page)
        try:
            for host in row.get("hosts", []):
                for scheme in ("https", "http"):
                    await cdp.send(
                        "Storage.clearDataForOrigin",
                        {"origin": f"{scheme}://{host}", "storageTypes": "all"},
                    )
        finally:
            await cdp.detach()
        _save_sites([r for r in rows if r["site"] != site])
        return signed_in_sites()

    async def forget_everything(self):
        """close the browser and delete its whole profile: every sign-in, cookie and cache."""
        from core.settings import data_dir

        await self.close()
        shutil.rmtree(data_dir() / "browser" / "profile", ignore_errors=True)
        _signins_path().unlink(missing_ok=True)

    async def close(self):
        try:
            if self._context:
                await self._context.close()
            if self._pw:
                await self._pw.stop()
        finally:
            self._pw = self._context = self._page = None
            self.items = {}
            self.owner_at, self.owner_hosts, self.owner_site = 0.0, set(), ""
            self._owner_lock = None


# one browser per process; runs share its profile (and sign-ins)
_b = _Browser()
