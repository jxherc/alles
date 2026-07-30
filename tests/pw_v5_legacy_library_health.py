"""Real KOKUEN v5 regression gate for legacy Library and Health sections.

Run against a server whose ALLES_DATA is an owned temporary directory. This test
uses the real app, real local API, and a separate browser context; it never uses
the owner's normal data directory.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Browser, Page, sync_playwright

PORT = os.environ.get("PORT", "8148")
BASE = f"http://127.0.0.1:{PORT}"
DATA = Path(os.environ["ALLES_DATA"]).resolve()


def _require_throwaway_data_root() -> None:
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if os.environ.get("ALLES_TEST_DATA", "").lower() not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for this isolated browser gate")
    if len(run_id) < 16:
        raise RuntimeError("set a unique ALLES_TEST_RUN_ID for this browser gate")
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        DATA.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError("ALLES_DATA must be inside the system temporary directory") from exc
    if DATA == temp_root:
        raise RuntimeError("ALLES_DATA cannot be the system temporary directory itself")
    owner = DATA / ".alles-test-owner"
    if owner.read_text(encoding="utf-8").strip() != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this test run")
    require_server_ownership(BASE, run_id)


def _open(page: Page) -> None:
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("#today-view:visible", timeout=15_000)
    page.wait_for_function(
        "typeof window._navigateTo === 'function' && !document.body.classList.contains('preboot')",
        timeout=15_000,
    )
    setup = page.evaluate(
        "fetch('/api/setup/status').then(response => response.json()).then(data => data.setup)"
    )
    if not (setup.get("completed") or setup.get("dismissed")):
        page.locator("#setup-wizard").wait_for(state="visible")
        page.locator("#setup-skip").click()
        page.locator("#setup-wizard").wait_for(state="hidden")


def _assert_target(locator) -> None:
    box = locator.bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44, box


def _books(page: Page) -> None:
    page.evaluate("window._navigateTo('books')")
    page.locator("#books-view").wait_for(state="visible")
    page.locator("#books-add-toggle").click()
    choices = page.locator('#book-status [role="radio"]')
    assert choices.count() == 3
    assert page.locator("#book-status").get_attribute("role") == "radiogroup"
    for index in range(choices.count()):
        _assert_target(choices.nth(index))
    choices.first.focus()
    page.keyboard.press("End")
    page.wait_for_function(
        "document.querySelector('#book-status [role=radio]:nth-child(3)')?.getAttribute('aria-checked') === 'true'"
    )
    assert (
        page.locator('#book-status [role="radio"]')
        .nth(2)
        .evaluate("element => document.activeElement === element")
    )
    page.locator("#book-title").fill("KOKUEN field notes")
    page.locator("#book-author").fill("local test")
    page.locator("#book-create").click()
    card = page.locator('.book-card:has-text("KOKUEN field notes")')
    card.wait_for()
    ratings = card.locator('[role="radiogroup"] [role="radio"]')
    assert ratings.count() == 5
    for index in range(ratings.count()):
        _assert_target(ratings.nth(index))
    ratings.first.focus()
    with page.expect_response(
        lambda response: (
            response.url.endswith(f"/api/books/{card.get_attribute('data-id')}")
            and response.request.method == "PATCH"
            and response.request.post_data == '{"rating":5}'
        )
    ) as rating_update:
        page.keyboard.press("End")
    assert rating_update.value.ok, rating_update.value.text()
    page.wait_for_function(
        """() => [...document.querySelectorAll('.book-card')]
          .find(card => card.textContent.includes('KOKUEN field notes'))
          ?.querySelector('[role=radio][data-rate="5"]')
          ?.getAttribute('aria-checked') === 'true'"""
    )
    card.locator(".book-add-note").click()
    card.locator("textarea[data-f='notes']").fill("edited through the real application")
    book_id = card.get_attribute("data-id")
    assert book_id
    with page.expect_response(
        lambda response: (
            response.url.endswith(f"/api/books/{book_id}")
            and response.request.method == "PATCH"
            and response.request.post_data == '{"notes":"edited through the real application"}'
        )
    ) as update:
        card.locator("[data-act='save-notes']").click()
    assert update.value.ok, update.value.text()
    card.get_by_text("edited through the real application", exact=True).wait_for()
    card.locator("[data-act='del']").click()
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    card.wait_for(state="detached")


def _read(page: Page) -> None:
    response = page.request.post(
        f"{BASE}/api/read/save-news",
        data={
            "url": "https://example.test/kokuen-library-flow",
            "title": "KOKUEN saved reading",
            "excerpt": "A local, explicit saved-reading test item.",
        },
    )
    assert response.ok, response.text()
    page.evaluate("window._navigateTo('read')")
    page.locator("#read-view").wait_for(state="visible")
    filters = page.locator('.read-filter-choices [role="radio"]')
    assert filters.count() == 4
    assert page.locator(".read-filter-choices").get_attribute("role") == "radiogroup"
    for index in range(filters.count()):
        _assert_target(filters.nth(index))
    page.locator("#read-feeds-btn").click()
    page.wait_for_function(
        "document.querySelector('#read-feeds-btn')?.getAttribute('aria-pressed') === 'true'"
    )
    assert page.locator("#read-feeds-btn").get_attribute("aria-pressed") == "true"
    page.locator("#read-feeds-btn").click()
    page.wait_for_function(
        "document.querySelector('#read-feeds-btn')?.getAttribute('aria-pressed') === 'false'"
    )
    assert page.locator("#read-feeds-btn").get_attribute("aria-pressed") == "false"
    card = page.locator('.read-card:has-text("KOKUEN saved reading")')
    card.wait_for()
    card.locator("[data-act='archive']").click()
    card.wait_for(state="detached")
    filters.first.focus()
    page.keyboard.press("End")
    page.wait_for_function(
        "document.querySelector('.read-filter-choices [role=radio]:nth-child(4)')?.getAttribute('aria-checked') === 'true'"
    )
    archived = page.locator('.read-card:has-text("KOKUEN saved reading")')
    archived.wait_for()
    archived.locator("[data-act='del']").click()
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    archived.wait_for(state="detached")


def _health(page: Page) -> None:
    page.evaluate("window._navigateTo('health-log')")
    page.locator("#health-view").wait_for(state="visible")
    ranges = page.locator('.health-ranges [role="radio"]')
    assert ranges.count() == 4
    assert page.locator(".health-ranges").get_attribute("role") == "radiogroup"
    for index in range(ranges.count()):
        _assert_target(ranges.nth(index))
    ranges.first.focus()
    page.keyboard.press("End")
    page.wait_for_function(
        "document.querySelector('.health-ranges [role=radio]:nth-child(4)')?.getAttribute('aria-checked') === 'true'"
    )
    page.locator("#health-add-toggle").click()
    page.locator("#health-value").fill("71.4")
    page.locator("#health-unit").fill("kg")
    page.locator("#health-create").click()
    row = page.locator('.health-row:has-text("71.4 kg")')
    row.wait_for()
    row.locator("[data-act='del']").click()
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    row.wait_for(state="detached")


def _degraded_loads(page: Page) -> None:
    def fail_once():
        failed = False

        def route(request):
            nonlocal failed
            if not failed:
                failed = True
                request.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"forced test failure"}',
                )
            else:
                request.continue_()

        return route

    books_url = "**/api/books/overview"
    books_failure = fail_once()
    page.route(books_url, books_failure)
    page.evaluate("window._navigateTo('books')")
    books_note = page.locator("#books-body .legacy-load-note")
    books_note.wait_for(state="visible")
    assert books_note.get_attribute("data-kokuen-state") == "error"
    assert books_note.get_attribute("role") == "alert"
    assert page.locator("#books-body .empty-state").count() == 0
    books_note.get_by_role("button", name="retry").click()
    books_note.wait_for(state="detached")
    page.unroute(books_url, books_failure)

    page.evaluate("window._navigateTo('read')")
    page.locator(".read-filter-choices [role='radio']").first.click()
    page.wait_for_function(
        "document.querySelector('.read-filter-choices [role=radio]')?.getAttribute('aria-checked') === 'true'"
    )
    saved = page.request.post(
        f"{BASE}/api/read/save-news",
        data={
            "url": "https://example.test/kokuen-partial-reading",
            "title": "KOKUEN partial reading",
            "excerpt": "This item proves successful reading data stays visible.",
        },
    )
    assert saved.ok, saved.text()
    stats_url = "**/api/read/stats"
    stats_failure = fail_once()
    page.route(stats_url, stats_failure)
    page.evaluate("window._navigateTo('read')")
    read_note = page.locator("#read-body .legacy-load-note")
    read_note.wait_for(state="visible")
    assert read_note.get_attribute("data-kokuen-state") == "partial"
    assert read_note.get_attribute("role") == "alert"
    page.locator('.read-card:has-text("KOKUEN partial reading")').wait_for()
    read_note.get_by_role("button", name="retry").click()
    read_note.wait_for(state="detached")
    page.unroute(stats_url, stats_failure)

    health = page.request.post(
        f"{BASE}/api/health",
        data={"kind": "weight", "value": 72.1, "unit": "kg", "note": "partial load evidence"},
    )
    assert health.ok, health.text()
    overview_url = re.compile(r".*/api/health/overview\?days=\d+$")
    overview_failure = fail_once()
    page.route(overview_url, overview_failure)
    page.evaluate("window._navigateTo('health-log')")
    health_note = page.locator("#health-body .legacy-load-note")
    health_note.wait_for(state="visible")
    assert health_note.get_attribute("data-kokuen-state") == "partial"
    assert health_note.get_attribute("role") == "alert"
    page.locator('.health-row:has-text("72.1 kg")').wait_for()
    health_note.get_by_role("button", name="retry").click()
    health_note.wait_for(state="detached")
    page.unroute(overview_url, overview_failure)


def run() -> None:
    _require_throwaway_data_root()
    errors: list[str] = []
    forced_503_errors: list[str] = []
    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.set_default_timeout(12_000)
        page.on("pageerror", lambda error: errors.append(f"page: {error}"))

        def record_console(message) -> None:
            if message.type != "error":
                return
            if "status of 503" in message.text:
                forced_503_errors.append(message.text)
            else:
                errors.append(f"console: {message.text}")

        page.on("console", record_console)
        _open(page)
        _books(page)
        _read(page)
        _health(page)
        _degraded_loads(page)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        context.close()
        browser.close()
    assert len(forced_503_errors) == 3, forced_503_errors
    if errors:
        raise AssertionError("browser errors:\n" + "\n".join(errors))
    print("KOKUEN v5 Library and Health legacy browser gate passed")


if __name__ == "__main__":
    run()
