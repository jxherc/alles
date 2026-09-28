"""Activity's partial Finance state and retry in a real isolated browser."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert os.environ["ALLES_TEST_DATA"] == "1"
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert (data / ".alles-test-owner").read_text("utf-8").strip() == run_id
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, run_id)
    artifacts = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    today = datetime.now(UTC).replace(tzinfo=None).isoformat()
    task = {
        "ts": today,
        "type": "task",
        "app": "tasks",
        "title": "saved task",
        "subtitle": "completed",
        "view": "tasks",
        "id": "task-1",
    }
    money = {
        "ts": today,
        "type": "money",
        "app": "money",
        "title": "current charge",
        "subtitle": "−12.50",
        "view": "money",
        "id": "txn-1",
    }
    evidence = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for device in ("desktop", "phone"):
            state = {"mode": "partial"}
            context = browser.new_context(
                viewport={"width": 1440 if device == "desktop" else 390, "height": 900},
                is_mobile=device == "phone",
                has_touch=device == "phone",
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page_errors = []
            console_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text) if message.type == "error" else None
                ),
            )

            def feed(route):
                if state["mode"] == "error":
                    route.fulfill(
                        status=503, body='{"detail":"offline"}', content_type="application/json"
                    )
                    return
                partial = state["mode"] == "partial"
                route.fulfill(
                    status=200,
                    body=json.dumps(
                        {
                            "events": [task] if partial else [task, money],
                            "types": ["task", "money", "sub"],
                            "partial_sources": ["money", "sub"] if partial else [],
                        }
                    ),
                    content_type="application/json",
                )

            def summary(route):
                partial = state["mode"] == "partial"
                route.fulfill(
                    status=200,
                    body=json.dumps(
                        {
                            "days": 30,
                            "total": 1 if partial else 2,
                            "by_type": [{"type": "task", "count": 1}],
                            "busiest": None,
                            "partial_sources": ["money", "sub"] if partial else [],
                        }
                    ),
                    content_type="application/json",
                )

            page.route("**/api/timeline?*", feed)
            page.route("**/api/timeline/summary?*", summary)
            page.goto(base, wait_until="domcontentloaded")
            if page.locator("#setup-skip").is_visible():
                page.locator("#setup-skip").click()
            page.wait_for_function("typeof window._navigateTo === 'function'")
            page.evaluate("window._navigateTo('activity')")
            expect(page.locator("#activity-view")).to_be_visible()
            expect(page.locator("#activity-body .activity-status")).to_contain_text(
                "finance activity is unavailable"
            )
            expect(page.locator("#activity-summary")).to_contain_text("1 available events")
            expect(page.locator("#activity-body .activity-row")).to_have_count(1)
            expect(page.get_by_role("button", name="tasks, saved task, completed")).to_be_visible()
            assert (
                page.locator(".activity-retry").evaluate(
                    "element => element.getBoundingClientRect().height"
                )
                >= 44
            )
            assert (
                page.locator(".activity-row").evaluate(
                    "element => element.getBoundingClientRect().height"
                )
                >= 44
            )
            assert page.locator("#activity-body").evaluate(
                "element => element.scrollWidth <= element.clientWidth + 1"
            )
            page.screenshot(path=str(artifacts / f"activity-partial-{device}.png"))

            state["mode"] = "complete"
            page.locator(".activity-retry").click()
            expect(page.locator("#activity-body .activity-status")).to_have_count(0)
            expect(page.locator("#activity-body .activity-row")).to_have_count(2)
            expect(page.locator("#activity-summary")).to_contain_text("2 events")
            assert page.evaluate("document.activeElement.classList.contains('activity-row')")
            page.evaluate(
                "window.__activityNav = ''; window._navigateTo = view => window.__activityNav = view"
            )
            page.locator(".activity-row").first.focus()
            page.keyboard.press("Enter")
            assert page.evaluate("window.__activityNav") in {"tasks", "money"}
            page.evaluate("window.__activityNav = ''")
            page.locator(".activity-row").first.press("Space")
            assert page.evaluate("window.__activityNav") in {"tasks", "money"}

            state["mode"] = "error"
            page.locator('.act-seg .seg-opt[data-d="7"]').click()
            expect(page.locator("#activity-body .activity-status")).to_contain_text(
                "couldn’t load activity"
            )
            state["mode"] = "complete"
            page.locator(".activity-retry").click()
            expect(page.locator("#activity-body .activity-row")).to_have_count(2)
            expect(page.locator("#activity-body .activity-status")).to_have_count(0)
            assert page.evaluate("document.activeElement.classList.contains('activity-row')")
            page.evaluate(
                """async () => {
                  const { applyAppearance, PRESETS } = await import('/static/js/theme.js');
                  applyAppearance({ preset: 'light', colors: PRESETS.light.colors });
                }"""
            )
            assert (
                page.evaluate("getComputedStyle(document.body).backgroundColor")
                == "rgb(244, 243, 240)"
            )
            page.screenshot(path=str(artifacts / f"activity-recovered-{device}-light.png"))
            if device == "desktop":
                page.evaluate("document.documentElement.style.zoom = '2'")
                assert page.locator("#activity-body").evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
            assert not page_errors, page_errors
            assert all("503" in message for message in console_errors), console_errors
            evidence.append(
                {
                    "device": device,
                    "partial_retry": True,
                    "keyboard_rows": True,
                    "full_error_retry": True,
                    "reduced_motion": True,
                    "console_errors": console_errors,
                }
            )
            context.close()
        browser.close()
    print(json.dumps(evidence))


if __name__ == "__main__":
    run()
