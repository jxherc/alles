"""Phase 6 live browser gate for Andromeda.

Search, paging, favicon, and media requests reach the real Alles backend and the
configured managed SearXNG. Only appearance is isolated so both themes can be
checked without changing the owner's saved appearance.
"""

import json
import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8030")
HOME = f"http://127.0.0.1:{PORT}"
URL = f"http://andromeda.localhost:{PORT}/"
SCREENSHOT_DIR = Path(os.environ.get("SCREENSHOT_DIR", "/tmp/alles-andromeda-live"))

THEMES = {
    "dark": {
        "_stored": True,
        "preset": "dark",
        "colors": {
            "bg": "#090909",
            "text": "#f0f0f0",
            "panel": "#121212",
            "faint": "#777777",
            "accent": "#818cf8",
        },
        "font": "sans",
        "density": "comfortable",
        "bgPattern": "none",
        "frosted": False,
    },
    "light": {
        "_stored": True,
        "preset": "light",
        "colors": {
            "bg": "#f5f4f1",
            "text": "#111111",
            "panel": "#efede9",
            "faint": "#666666",
            "accent": "#686fd8",
        },
        "font": "sans",
        "density": "comfortable",
        "bgPattern": "none",
        "frosted": False,
    },
}


def _require_safe_live_gate() -> None:
    if os.environ.get("ALLES_ALLOW_NETWORK_TESTS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise RuntimeError("set ALLES_ALLOW_NETWORK_TESTS=1 for this opt-in network gate")
    if os.environ.get("ALLES_TEST_DATA", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the isolated Andromeda gate")
    raw = os.environ.get("ALLES_DATA", "").strip()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if not raw or len(run_id) < 16:
        raise RuntimeError("set the isolated Andromeda data root and unique run id")
    data = Path(raw).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    try:
        owner = (data / ".alles-test-owner").read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this browser run")
    require_server_ownership(HOME, run_id)


def wait_for_count(page, selector: str, count: int, timeout: int = 30_000) -> None:
    page.wait_for_function(
        "([selector, count]) => document.querySelectorAll(selector).length >= count",
        arg=[selector, count],
        timeout=timeout,
    )


def wait_for_category(page, selector: str, timeout: int = 45_000) -> int:
    page.wait_for_function(
        "([selector]) => {"
        "  const count = document.querySelectorAll(selector).length;"
        "  const empty = document.querySelector('[data-andromeda-view]:not([hidden]) .andromeda-empty');"
        "  return count > 0 || (empty && !empty.textContent.startsWith('finding '));"
        "}",
        arg=[selector],
        timeout=timeout,
    )
    return page.locator(selector).count()


def run_case(
    browser, width: int, height: int, size: str, theme_name: str, page_images: bool
) -> None:
    appearance = THEMES[theme_name]
    context = browser.new_context(
        viewport={"width": width, "height": height},
        reduced_motion="reduce",
        service_workers="block",
    )
    context.add_init_script(
        "localStorage.setItem('alles-appearance', " + json.dumps(json.dumps(appearance)) + ");"
    )
    page = context.new_page()
    errors: list[str] = []
    search_responses: list[tuple[int, str]] = []
    page.on("pageerror", lambda error: errors.append(f"page: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"console: {message.text}") if message.type == "error" else None
        ),
    )
    page.on(
        "response",
        lambda response: (
            search_responses.append((response.status, response.url))
            if "/api/andromeda/" in response.url
            else None
        ),
    )
    appearance_json = json.dumps(appearance)
    page.route(
        "**/api/appearance",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=appearance_json,
        ),
    )

    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("#andromeda-view", state="visible")
    page.locator("#andromeda-query").fill("open source self hosted software !ai")
    page.locator("#andromeda-form").press("Enter")
    wait_for_count(page, ".andromeda-result-title", 5)
    assert page.locator("#andromeda-overview").is_hidden()

    categories = (
        ("images", ".andromeda-image-card", 30),
        ("news", ".andromeda-news-card", 20),
        ("videos", ".andromeda-video-card", 20),
    )
    for category, selector, minimum in categories:
        page.locator(f'[data-andromeda-category="{category}"]').click()
        count = wait_for_category(page, selector)
        assert count > 0, f"managed SearXNG returned no {category} results"
        if count < minimum:
            assert page.locator("#andromeda-more-results").is_hidden(), (
                category,
                count,
                "a short provider page must be marked exhausted",
            )
        assert page.locator("#andromeda-overview").is_hidden()
        assert page.locator(f'[data-andromeda-view="{category}"]').is_visible()
        assert page.locator("select:visible").count() == 0
        assert page.locator('input[type="checkbox"]:visible').count() == 0
        assert page.locator('input[type="radio"]:visible').count() == 0

        if category == "images":
            required_images = min(15, count)
            page.wait_for_function(
                "required => [...document.querySelectorAll('.andromeda-image-card img')]"
                ".filter(img => img.complete && img.naturalWidth > 0).length >= required",
                arg=required_images,
                timeout=45_000,
            )
            loaded = page.locator(".andromeda-image-card img").evaluate_all(
                "imgs => imgs.filter(img => img.complete && img.naturalWidth > 0).length"
            )
            assert loaded >= required_images, f"only {loaded} image thumbnails loaded"
            if page_images and page.locator("#andromeda-more-results").is_visible():
                before = count
                page.locator("#andromeda-more-results").click()
                page.wait_for_function(
                    "([selector, before]) => {"
                    "  const more = document.querySelector('#andromeda-more-results');"
                    "  return document.querySelectorAll(selector).length > before || more.hidden;"
                    "}",
                    arg=[selector, before],
                    timeout=45_000,
                )
                after = page.locator(selector).count()
                assert after > before or page.locator("#andromeda-more-results").is_hidden()
        elif category == "news":
            assert page.locator(".andromeda-news-title").count() == count
        else:
            thumbnail_count = page.locator(".andromeda-video-card img").count()
            required_thumbnails = min(5, thumbnail_count)
            if required_thumbnails:
                page.wait_for_function(
                    "required => [...document.querySelectorAll('.andromeda-video-card img')]"
                    ".filter(img => img.complete && img.naturalWidth > 0).length >= required",
                    arg=required_thumbnails,
                    timeout=45_000,
                )
            working = page.locator(".andromeda-video-card img").evaluate_all(
                "imgs => imgs.filter(img => img.complete && img.naturalWidth > 0).length"
            )
            assert working >= required_thumbnails, f"only {working} video thumbnails loaded"
            assert page.locator('.andromeda-video-card[href^="http"]').count() == count

    page.locator('[data-andromeda-category="all"]').click()
    wait_for_count(page, ".andromeda-result-title", 5)
    assert page.locator("#andromeda-query").input_value().endswith(" !ai")
    assert page.locator("#andromeda-overview").is_hidden()
    metrics = page.locator("#andromeda-view").evaluate(
        """root => ({
          rootOverflow: root.scrollWidth - root.clientWidth,
          docOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          bottomPadding: parseFloat(getComputedStyle(root.querySelector('.andromeda-result-column')).paddingBottom),
          theme: document.documentElement.dataset.theme || 'dark',
        })"""
    )
    assert metrics["rootOverflow"] <= 1 and metrics["docOverflow"] <= 1, metrics
    assert metrics["bottomPadding"] >= 96, metrics
    assert metrics["theme"] == ("light" if theme_name == "light" else "dark")
    assert any(status == 200 and "/api/andromeda/search" in url for status, url in search_responses)
    assert not [item for item in search_responses if item[0] >= 500], search_responses
    assert not errors, errors

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_DIR / f"{size}-{theme_name}.png"), full_page=True)
    context.close()


def main() -> None:
    _require_safe_live_gate()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        run_case(browser, 1440, 1000, "desktop", "dark", True)
        run_case(browser, 1440, 1000, "desktop", "light", False)
        run_case(browser, 390, 844, "mobile", "dark", False)
        run_case(browser, 390, 844, "mobile", "light", False)
        browser.close()
    print("live Andromeda browser gate passed with managed SearXNG")


if __name__ == "__main__":
    main()
