"""Command palette: local hits remain usable while Finance resolves or fails."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
    evidence = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for device in ("desktop", "phone"):
            calls = []
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

            def query(route):
                q = parse_qs(urlparse(route.request.url).query)["q"][0]
                calls.append(("local", q))
                route.fulfill(
                    status=200,
                    body=json.dumps(
                        {
                            "tasks": [{"id": "task-1", "title": f"{q} task", "done": False}],
                            "finance_status": "pending",
                        }
                    ),
                    content_type="application/json",
                )

            def finance(route):
                q = parse_qs(urlparse(route.request.url).query)["q"][0]
                calls.append(("finance", q))
                if q == "offline":
                    route.fulfill(
                        status=503,
                        body='{"detail":"finance unavailable"}',
                        content_type="application/json",
                    )
                else:
                    route.fulfill(
                        status=200,
                        body=json.dumps(
                            {
                                "money": [
                                    {
                                        "id": "txn-1",
                                        "payee": f"{q} charge",
                                        "amount": -12.5,
                                        "when": "2026-09-28",
                                    }
                                ],
                                "subs": [
                                    {
                                        "id": "sub-1",
                                        "name": f"{q} plan",
                                        "snippet": "CAD 12.5 · monthly",
                                    }
                                ],
                            }
                        ),
                        content_type="application/json",
                    )

            page.route("**/api/search/finance?*", finance)
            page.route("**/api/search?*", query)
            assert page.request.post(f"{base}/api/setup/dismiss").ok
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("typeof window._navigateTo === 'function'")
            page.wait_for_function(
                "document.querySelector('#search-modal')?.dataset.searchBound === 'true'"
            )
            page.evaluate("import('/static/js/search.js').then(module => module.openSearch())")
            modal = page.locator("#search-modal")
            search = page.locator("#search-input")
            expect(modal).to_be_visible()
            expect(search).to_be_focused()

            search.fill("coffee")
            task = page.get_by_role("option", name="coffee task")
            expect(task).to_be_visible()
            expect(page.locator("#search-results .search-state--loading")).to_contain_text(
                "local search is ready"
            )
            assert ("finance", "coffee") not in calls
            search.press("ArrowDown")
            search.press("ArrowDown")
            assert search.get_attribute("aria-activedescendant") == task.get_attribute("id")
            expect(page.get_by_role("option", name="coffee charge")).to_be_visible()
            expect(page.get_by_role("option", name="coffee plan")).to_be_visible()
            task = page.get_by_role("option", name="coffee task")
            assert search.get_attribute("aria-activedescendant") == task.get_attribute("id")
            assert ("finance", "coffee") in calls
            page.screenshot(path=str(artifacts / f"search-finance-{device}.png"))

            search.fill("train")
            expect(page.get_by_role("option", name="train task")).to_be_visible()
            expect(page.get_by_role("option", name="coffee charge")).to_have_count(0)
            expect(page.get_by_role("option", name="train charge")).to_be_visible()
            assert ("finance", "train") in calls

            search.fill("offline")
            expect(page.get_by_role("option", name="offline task")).to_be_visible()
            expect(page.locator("#search-results .search-state--unavailable")).to_contain_text(
                "finance search is unavailable"
            )
            expect(page.get_by_role("option", name="train charge")).to_have_count(0)
            expect(page.get_by_role("option", name="offline task")).to_be_visible()
            assert ("finance", "offline") in calls
            assert page.locator("#search-results").evaluate(
                "element => element.scrollWidth <= element.clientWidth + 1"
            )
            page.screenshot(path=str(artifacts / f"search-finance-unavailable-{device}.png"))

            search.press("Escape")
            expect(modal).to_be_hidden()
            page.evaluate(
                """async () => {
                  const { applyAppearance, PRESETS } = await import('/static/js/theme.js');
                  applyAppearance({ preset: 'light', colors: PRESETS.light.colors });
                }"""
            )
            page.evaluate("import('/static/js/search.js').then(module => module.openSearch())")
            expect(modal).to_be_visible()
            search.fill("coffee")
            expect(page.get_by_role("option", name="coffee charge")).to_be_visible()
            assert page.locator("#search-results").evaluate(
                "element => element.scrollWidth <= element.clientWidth + 1"
            )
            if device == "desktop":
                page.evaluate("document.documentElement.style.zoom = '2'")
                assert page.locator("#search-results").evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
            page.screenshot(path=str(artifacts / f"search-finance-{device}-light.png"))
            assert not page_errors, page_errors
            assert all("503" in message for message in console_errors), console_errors
            evidence.append(
                {
                    "device": device,
                    "local_first": True,
                    "selection_preserved": True,
                    "finance_unavailable_visible": True,
                    "dark_light": True,
                    "reduced_motion": True,
                    "console_errors": console_errors,
                }
            )
            context.close()
        browser.close()
    print(json.dumps(evidence))


if __name__ == "__main__":
    run()
