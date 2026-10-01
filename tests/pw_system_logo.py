"""Browser gate for square, single-loop operating-system logos on System."""

import json
import os
from functools import lru_cache
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8046")
URL = f"http://server.localhost:{PORT}/"


@lru_cache(maxsize=1)
def _base_stats() -> dict:
    with urlopen(f"http://127.0.0.1:{PORT}/api/system/stats", timeout=15) as response:
        return json.load(response)


def _stats_for(platform: str) -> str:
    body = json.loads(json.dumps(_base_stats()))
    body["host"]["platform"] = platform
    body["host"]["os"] = platform
    return json.dumps(body)


def _check(browser, viewport: dict[str, int], mobile: bool, platform: str, expected: str) -> None:
    context = browser.new_context(
        viewport=viewport,
        is_mobile=mobile,
        service_workers="block",
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text)
            if message.type == "error" and "favicon" not in message.text.lower()
            else None
        ),
    )
    stats = _stats_for(platform)
    page.route(
        "**/api/system/stats",
        lambda route: route.fulfill(status=200, content_type="application/json", body=stats),
    )
    page.goto(URL, wait_until="domcontentloaded")
    logo = page.locator(f'.nf-logo[data-os="{expected}"]')
    logo.wait_for(state="visible")
    box = logo.bounding_box()
    art_box = logo.locator(".nf-logo-art").bounding_box()
    glyph_box = logo.locator(".nf-logo-glyphs").bounding_box()
    assert box is not None and art_box is not None and glyph_box is not None
    assert abs(box["width"] - box["height"]) <= 1
    assert abs(art_box["width"] - art_box["height"]) <= 1
    assert abs(glyph_box["width"] - glyph_box["height"]) <= 1
    assert logo.get_attribute("aria-label")
    assert logo.locator(".nf-logo-glyphs").inner_text().strip()
    loop = logo.evaluate(
        """el => {
          const animations = el.getAnimations({subtree: true});
          const timing = animations.map(animation => ({
            name: animation.animationName,
            duration: animation.effect.getTiming().duration,
            infinite: animation.effect.getTiming().iterations === Infinity,
          }));
          animations.forEach(animation => { animation.pause(); animation.currentTime = 0; });
          const snapshot = () => {
            const art = getComputedStyle(el.querySelector('.nf-logo-glyphs'));
            return [art.backgroundPosition, art.filter];
          };
          const start = snapshot();
          animations.forEach(animation => { animation.currentTime = 6000; });
          return {timing, start, end: snapshot()};
        }"""
    )
    assert [item["name"] for item in loop["timing"]] == ["logo-cycle"]
    assert all(item["duration"] == 6000 for item in loop["timing"])
    assert all(item["infinite"] for item in loop["timing"])
    assert loop["start"] == loop["end"]
    page.emulate_media(reduced_motion="reduce")
    assert logo.evaluate("el => el.getAnimations({subtree: true}).length") == 0
    page.emulate_media(reduced_motion="no-preference")
    size = "mobile" if mobile else "desktop"
    page.screenshot(path=f"/tmp/alles-system-{expected}-{size}.png", full_page=True)
    if expected == "darwin" and not mobile:
        page.evaluate("""() => {
            const root = document.documentElement;
            root.dataset.theme = 'light';
            root.style.setProperty('--bg', '#f5f4f1');
            root.style.setProperty('--text', '#111111');
            root.style.setProperty('--panel', '#efede9');
            root.style.setProperty('--faint', '#d4d2ce');
            root.style.setProperty('--muted', '#767676');
        }""")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.screenshot(path="/tmp/alles-system-darwin-light.png", full_page=True)
    assert not errors, errors
    page.unroute_all(behavior="ignoreErrors")
    page.close()
    context.close()


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        platforms = [
            ("darwin", "darwin"),
            ("windows", "windows"),
            ("linux", "linux"),
            ("haiku", "generic"),
        ]
        for platform, expected in platforms:
            _check(browser, {"width": 1440, "height": 900}, False, platform, expected)
            _check(browser, {"width": 390, "height": 844}, True, platform, expected)
        browser.close()
    print(
        "system logo browser gate passed: all OS glyph blocks and canvases are square with one seamless loop"
    )


if __name__ == "__main__":
    main()
