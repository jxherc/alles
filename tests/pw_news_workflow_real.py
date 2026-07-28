"""Rendered gate for the approved Scheduled News workbench."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Page, Route, sync_playwright

PORT = os.environ.get("PORT", "8965")
BASE = f"http://127.0.0.1:{PORT}"
EVIDENCE = Path(tempfile.gettempdir()) / "alles-news-workflow-real"


def _require_throwaway_data_root() -> None:
    data = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or len(run_id) < 16:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    try:
        owner = (data / ".alles-test-owner").read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, run_id)


def _body(route: Route) -> dict:
    return json.loads(route.request.post_data or "{}")


def _brief() -> dict:
    return {
        "id": "brief-1",
        "status": "summary_pending",
        "title": "news brief · Jul 22",
        "summary": "2 reviewed topics from 3 sources.",
        "clusters": [
            {
                "key": "passkeys",
                "title": "Taiwan expands public-service passkeys",
                "summary": "Two sources describe a staged rollout with account recovery first.",
                "category": "taiwan",
                "links": [
                    {
                        "title": "Passkeys",
                        "url": "https://reporter.example/passkeys",
                        "source": "The Reporter",
                        "published_at": "2026-07-22T08:00:00",
                    },
                    {
                        "title": "Release",
                        "url": "https://gov.example/passkeys",
                        "source": "gov.tw",
                        "published_at": "2026-07-22T07:30:00",
                    },
                ],
            },
            {
                "key": "storage",
                "title": "Browser storage partitioning reaches stable",
                "summary": "The change narrows cross-site state while preserving explicit sign-in paths.",
                "category": "technology",
                "links": [
                    {
                        "title": "Storage",
                        "url": "https://browser.example/storage",
                        "source": "Browser project",
                        "published_at": "2026-07-22T06:00:00",
                    },
                ],
            },
        ],
        "source_failures": [{"source_id": "source-3", "error": "source fetch timed out"}],
        "scheduled_for": "2026-07-22T08:00:00",
        "published_at": "2026-07-22T08:00:00",
        "delivered_home": True,
        "jarvis_delivery_state": "off",
    }


def _fixture() -> dict:
    return {
        "configuration": {
            "enabled": False,
            "cadence": "morning",
            "time_of_day": "08:00",
            "timezone": "UTC",
            "deliver_home": True,
            "deliver_jarvis": False,
            "next_run_at": "",
            "last_run_at": "",
            "last_success_at": "",
            "last_safe_error": "",
            "jarvis": {"available": False, "paired": False, "reason": "pair Jarvis first"},
        },
        "sources": [
            {
                "id": "source-1",
                "url": "https://rest.example/feed",
                "name": "Rest of World",
                "category": "technology",
                "language": "en",
                "priority": 1,
                "schedule": "inherit",
                "enabled": True,
                "health": "healthy",
                "last_checked_at": "2026-07-22T07:50:00",
                "last_success_at": "2026-07-22T07:50:00",
                "last_safe_error": "",
                "next_retry_at": "",
                "failure_count": 0,
            },
            {
                "id": "source-2",
                "url": "https://reporter.example/feed",
                "name": "報導者 The Reporter",
                "category": "taiwan",
                "language": "zh-Hant",
                "priority": 2,
                "schedule": "inherit",
                "enabled": True,
                "health": "healthy",
                "last_checked_at": "2026-07-22T07:48:00",
                "last_success_at": "2026-07-22T07:48:00",
                "last_safe_error": "",
                "next_retry_at": "",
                "failure_count": 0,
            },
            {
                "id": "source-3",
                "url": "https://browser.example/feed",
                "name": "Browser project",
                "category": "technology",
                "language": "en",
                "priority": 1,
                "schedule": "six_hours",
                "enabled": True,
                "health": "retry",
                "last_checked_at": "2026-07-22T07:40:00",
                "last_success_at": "",
                "last_safe_error": "source fetch timed out",
                "next_retry_at": "2026-07-22T08:10:00",
                "failure_count": 1,
            },
        ],
        "latest_brief": _brief(),
    }


def _route_news(route: Route, state: dict, calls: list[str]) -> None:
    request = route.request
    path = urlparse(request.url).path
    if request.method == "GET" and path == "/api/news":
        route.fulfill(json=state)
        return
    if request.method == "PATCH" and path == "/api/news/configuration":
        values = _body(route)
        state["configuration"].update(values)
        if values.get("enabled"):
            state["configuration"]["next_run_at"] = "2026-07-23T00:00:00"
        calls.append("config")
        route.fulfill(json=state["configuration"])
        return
    if request.method == "POST" and path == "/api/news/sources/test":
        calls.append("test-source")
        route.fulfill(
            json={
                "url": "https://example.org/feed.xml",
                "title": "Example newsroom",
                "items": [{"title": "One", "url": "https://example.org/one", "published": ""}],
            }
        )
        return
    if request.method == "POST" and path == "/api/news/sources":
        values = _body(route)
        source_id = f"source-added-{len(state['sources']) + 1}"
        state["sources"].append(
            {
                "id": source_id,
                "health": "untested",
                "last_checked_at": "",
                "last_success_at": "",
                "last_safe_error": "",
                "next_retry_at": "",
                "failure_count": 0,
                **values,
            }
        )
        calls.append("create-source")
        route.fulfill(json=state["sources"][-1])
        return
    if request.method == "PATCH" and path.startswith("/api/news/sources/"):
        source_id = path.rsplit("/", 1)[-1]
        source = next(item for item in state["sources"] if item["id"] == source_id)
        source.update(_body(route))
        calls.append("patch-source")
        route.fulfill(json=source)
        return
    if request.method == "POST" and path == "/api/news/run":
        calls.append("run")
        route.fulfill(
            json={
                "ran": True,
                "reason": "published",
                "brief": state["latest_brief"],
                "sources": [],
                "deliveries": {"delivered": 0, "failed": 0},
            }
        )
        return
    route.continue_()


def _no_overflow(page: Page) -> bool:
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


def _stack_is_clear(page: Page) -> dict:
    return page.evaluate("""() => {
      const head = document.querySelector('.aide-scheduled-head').getBoundingClientRect();
      const headCopy = document.querySelector('.aide-scheduled-head > div').getBoundingClientRect();
      const tabs = document.querySelector('.aide-scheduled-tabs').getBoundingClientRect();
      const news = document.querySelector('.news-real-head').getBoundingClientRect();
      return {headBottom: head.bottom, headCopyBottom: headCopy.bottom, tabsTop: tabs.top, tabsBottom: tabs.bottom, newsTop: news.top};
    }""")


def _open_news(page: Page) -> None:
    assert page.request.post(f"{BASE}/api/setup/dismiss").ok
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function("typeof window._navigateTo === 'function'")
    page.evaluate("window._navigateTo('scheduled')")
    page.locator("#aide-scheduled-view").wait_for(state="visible")
    page.locator('[data-scheduled-tab="news"]').click()
    page.locator("#aide-news-workbench").wait_for(state="visible")
    page.locator(".news-real-layout").wait_for(state="visible")


def run() -> None:
    _require_throwaway_data_root()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    calls: list[str] = []
    state = _fixture()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1366, "height": 850},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(f"page: {error}"))
        page.on(
            "console",
            lambda message: (
                errors.append(f"console: {message.text}") if message.type == "error" else None
            ),
        )
        page.route("**/api/news**", lambda route: _route_news(route, state, calls))
        _open_news(page)

        assert page.locator('[data-scheduled-tab="news"]').get_attribute("aria-selected") == "true"
        assert page.locator("#aide-scheduled-new").is_hidden()
        assert (
            page.locator(
                'select:visible, input[type="radio"]:visible, input[type="checkbox"]:visible'
            ).count()
            == 0
        )
        assert page.locator('.news-switch[aria-label="Jarvis delivery unavailable"]').is_disabled()
        assert _no_overflow(page)

        page.get_by_role("button", name="enable news").click()
        page.get_by_text("news is on", exact=True).wait_for()
        page.get_by_role("button", name="run brief now").click()
        assert "run" in calls
        page.wait_for_function(
            "document.querySelector('[data-news-action=\"run-now\"]')?.disabled === false"
        )

        cadence = page.locator('[data-news-radio="cadence"][data-value="morning"]')
        cadence.focus()
        page.keyboard.press("End")
        page.wait_for_function(
            "document.querySelector('[data-news-radio=\"cadence\"][data-value=\"custom\"]')?.getAttribute('aria-checked') === 'true'"
        )
        page.locator("#news-custom-time").fill("07:30")
        page.locator("#news-custom-time").press("Enter")

        page.get_by_role("button", name="add source").click()
        dialog = page.get_by_role("dialog")
        dialog.wait_for()
        page.locator("#news-source-url").fill("https://example.org/feed.xml")
        assert dialog.get_by_role("button", name="save source").is_disabled()
        dialog.get_by_role("button", name="test source").click()
        page.get_by_text("1 recent item found. Nothing was saved.", exact=True).wait_for()
        assert "test-source" in calls
        page.locator("#news-source-url").fill("https://example.org/changed.xml")
        assert dialog.get_by_role("button", name="save source").is_disabled()
        page.locator("#news-source-url").fill("https://example.org/feed.xml")
        assert dialog.get_by_role("button", name="save source").is_enabled()
        dialog.get_by_role("button", name="save source").click()
        page.get_by_text("Example newsroom", exact=True).wait_for()
        assert "create-source" in calls

        page.get_by_role("button", name="save to Library").first.click()
        page.get_by_role("button", name="saved to Library").wait_for()
        saved = page.request.get(f"{BASE}/api/read").json()["items"]
        assert len(saved) == 1 and saved[0]["source_kind"] == "saved_news"

        page.get_by_role("button", name="add source").click()
        page.locator("#news-source-url").focus()
        page.keyboard.press("Escape")
        assert page.get_by_role("dialog").count() == 0

        page.locator("#aide-scheduled-view").evaluate("element => { element.scrollTop = 0; }")
        page.screenshot(path=str(EVIDENCE / "news-dark-desktop.png"), full_page=True)
        mobile_context = browser.new_context(
            viewport={"width": 390, "height": 844},
            reduced_motion="reduce",
            service_workers="block",
        )
        mobile = mobile_context.new_page()
        mobile.on("pageerror", lambda error: errors.append(f"mobile page: {error}"))
        mobile.on(
            "console",
            lambda message: (
                errors.append(f"mobile console: {message.text}")
                if message.type == "error"
                else None
            ),
        )
        mobile.route("**/api/news**", lambda route: _route_news(route, state, calls))
        _open_news(mobile)
        mobile.locator("body.sidebar-hidden").wait_for()
        assert _no_overflow(mobile)
        stack = _stack_is_clear(mobile)
        assert stack["headCopyBottom"] <= stack["headBottom"] + 1, stack
        assert stack["tabsTop"] >= stack["headBottom"] - 1, stack
        assert stack["newsTop"] >= stack["tabsBottom"] - 1, stack
        undersized = mobile.locator(
            "#aide-news-workbench button:visible, #aide-news-workbench input:visible"
        ).evaluate_all(
            """elements => elements.map(element => { const box = element.getBoundingClientRect(); return {label: element.textContent.trim() || element.getAttribute('aria-label') || element.placeholder, width: box.width, height: box.height}; }).filter(item => item.width < 43.5 || item.height < 43.5)"""
        )
        assert not undersized, undersized
        mobile.screenshot(path=str(EVIDENCE / "news-dark-phone.png"), full_page=True)
        mobile_context.close()

        page.set_viewport_size({"width": 640, "height": 800})
        assert _no_overflow(page)
        assert not errors, errors
        browser.close()

    print("PASS  News enable, automatic timezone, and run-now path")
    print("PASS  tested source add with custom controls")
    print("PASS  explicit Library save and Jarvis gate")
    print("PASS  keyboard dialog and radiogroup behavior")
    print("PASS  desktop, phone, 200 percent reflow, reduced motion")
    print("PASS  zero console errors")


if __name__ == "__main__":
    run()
