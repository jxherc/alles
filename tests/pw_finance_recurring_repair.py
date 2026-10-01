"""Rendered old-Actual recurring repair flow with isolated data and simulated API states."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_finance_helpers import show_money_sections

from services.appearance import LIGHT_BASE


def run() -> None:
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    finance = f"http://finance.localhost:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text("utf-8").strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        setup = playwright.request.new_context()
        assert setup.post(base + "/api/setup/dismiss").ok
        account = setup.post(
            base + "/api/money/accounts",
            data={"name": "repair fixture", "currency": "CAD", "opening": 100},
        )
        assert account.ok, account.text()
        account_id = account.json()["id"]
        setup.dispose()
        records = []
        for profile in ("desktop", "phone"):
            if profile == "phone":
                theme = playwright.request.new_context()
                assert theme.put(
                    base + "/api/appearance",
                    data={"preset": "light", "colors": LIGHT_BASE},
                ).ok
                theme.dispose()
            context = browser.new_context(
                viewport={"width": 1440 if profile == "desktop" else 390, "height": 900},
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
                reduced_motion="reduce",
                service_workers="block",
            )
            state = {
                "phase": "needed",
                "lose_next": False,
                "posts": [],
                "posting_active": True,
                "posting_pending": False,
                "lose_posting_next": False,
                "toggles": [],
                "errors": [],
            }
            page = context.new_page()
            page.on("pageerror", lambda error: state["errors"].append(str(error)))
            page.on(
                "console",
                lambda message: (
                    state["errors"].append(message.text) if message.type == "error" else None
                ),
            )

            def response(route):
                path = urlsplit(route.request.url).path
                if path == "/api/money/recurring" and route.request.method == "GET":
                    row = {
                        "id": "old-rent",
                        "account_id": account_id,
                        "amount": -5,
                        "amount_kind": "exact",
                        "category": "housing",
                        "payee": "rent",
                        "notes": "lease",
                        "cycle": "monthly",
                        "next_date": "2026-10-01",
                        "active": state["posting_active"] and state["phase"] != "pending",
                        "repair_needed": state["phase"] != "repaired",
                        "repair_pending": state["phase"] == "pending",
                        "repair_category_id": "housing-id" if state["phase"] == "pending" else "",
                        "manageable": state["phase"] == "repaired",
                        "posting_pending": state["posting_pending"],
                        "posting_target_active": False if state["posting_pending"] else None,
                    }
                    route.fulfill(
                        status=200, content_type="application/json", body=json.dumps([row])
                    )
                elif path == "/api/money/recurring/old-rent" and route.request.method == "PATCH":
                    body = route.request.post_data_json
                    state["toggles"].append(body)
                    state["posting_active"] = body["active"]
                    if state["lose_posting_next"]:
                        state["lose_posting_next"] = False
                        state["posting_pending"] = True
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"detail":"response lost after Actual changed posting"}',
                        )
                    else:
                        state["posting_pending"] = False
                        route.fulfill(
                            status=200, content_type="application/json", body='{"id":"old-rent"}'
                        )
                elif path == "/api/money/recurring/old-rent/repair":
                    body = route.request.post_data_json
                    state["posts"].append(body)
                    assert body == {"category_id": "housing-id"}
                    if state["lose_next"]:
                        state["lose_next"] = False
                        state["phase"] = "pending"
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"detail":"response lost after Actual paused the schedule"}',
                        )
                    else:
                        state["phase"] = "repaired"
                        route.fulfill(
                            status=200, content_type="application/json", body='{"id":"old-rent"}'
                        )
                elif path == "/api/money/summary":
                    summary = route.fetch().json()
                    summary["ledger"] = "actual"
                    route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(summary)
                    )
                elif path == "/api/money/envelope":
                    envelope = {
                        "to_be_budgeted": 0,
                        "categories": [
                            {
                                "category_id": "housing-id",
                                "category": "housing",
                                "group": "bills",
                                "assigned": 0,
                                "spent": 0,
                                "available": 0,
                                "target": None,
                            }
                        ],
                        "unbound_targets": [],
                        "pending_assignments": [],
                    }
                    route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(envelope)
                    )
                else:
                    route.continue_()

            context.route("**/api/money/**", response)
            page.goto(finance, wait_until="networkidle")
            if profile == "phone":
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
            tab = page.locator('#finance-tabs [data-group-section="money"]')
            if tab.get_attribute("aria-selected") != "true":
                tab.click()
            show_money_sections(page)
            expect(page.locator("#recurring-content [data-repair-rec] ")).to_be_visible()
            action = page.get_by_role("button", name="repair posting")
            assert action.evaluate("element => element.getBoundingClientRect().height") >= 44
            action.focus()
            page.keyboard.press("Enter")
            dialog = page.get_by_role("dialog", name="choose the Actual category for rent")
            expect(dialog).to_be_visible()
            assert dialog.locator("select").count() == 0
            page.keyboard.press("Escape")
            expect(dialog).to_have_count(0)
            expect(action).to_be_focused()

            action.focus()
            page.keyboard.press("Enter")
            expect(dialog).to_be_visible()
            page.keyboard.press("Tab")
            expect(dialog.get_by_role("button", name="bills / housing")).to_be_focused()
            page.keyboard.press("Enter")
            expect(page.get_by_role("button", name="repair posting")).to_have_count(0)
            assert state["posts"] == [{"category_id": "housing-id"}]

            state["phase"] = "needed"
            state["lose_next"] = True
            page.reload(wait_until="networkidle")
            show_money_sections(page)
            page.get_by_role("button", name="repair posting").click()
            page.get_by_role("dialog").get_by_role("button", name="bills / housing").click()
            expect(page.get_by_role("button", name="retry repair")).to_be_visible()
            expect(page.locator(".money-recurring-error")).to_contain_text("repair not confirmed")
            page.screenshot(
                path=str(output / f"recurring-repair-{profile}-pending.png"), full_page=True
            )
            page.evaluate("document.documentElement.style.zoom = '2'")
            pending_card = page.locator('.money-card[data-card="recurring"]')
            assert pending_card.evaluate(
                "element => element.scrollWidth <= element.clientWidth + 1"
            )
            page.screenshot(
                path=str(output / f"recurring-repair-{profile}-zoom.png"), full_page=True
            )
            page.evaluate("document.documentElement.style.zoom = ''")
            page.reload(wait_until="networkidle")
            show_money_sections(page)
            expect(page.get_by_role("button", name="retry repair")).to_be_visible()
            page.get_by_role("button", name="retry repair").click()
            expect(page.get_by_role("button", name="retry repair")).to_have_count(0)
            assert state["posts"] == [{"category_id": "housing-id"}] * 3
            pause = page.get_by_role("button", name="pause", exact=True)
            expect(pause).to_be_visible()
            assert pause.evaluate("element => element.getBoundingClientRect().height") >= 44
            state["lose_posting_next"] = True
            pause.focus()
            page.keyboard.press("Enter")
            expect(page.get_by_role("button", name="retry pause")).to_be_focused()
            expect(page.locator(".money-recurring-error")).to_contain_text("pause not confirmed")
            page.screenshot(
                path=str(output / f"recurring-pause-{profile}-pending.png"), full_page=True
            )
            page.reload(wait_until="networkidle")
            show_money_sections(page)
            page.get_by_role("button", name="retry pause").click()
            expect(page.get_by_role("button", name="resume", exact=True)).to_be_focused()
            page.get_by_role("button", name="resume", exact=True).click()
            expect(page.get_by_role("button", name="pause", exact=True)).to_be_visible()
            assert state["toggles"] == [{"active": False}, {"active": False}, {"active": True}]
            expected_503 = "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
            assert all(error == expected_503 for error in state["errors"]), state["errors"]
            card = page.locator('.money-card[data-card="recurring"]')
            assert card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
            page.screenshot(
                path=str(output / f"recurring-repair-{profile}-done.png"), full_page=True
            )
            records.append({"profile": profile, "status": "passed", "posts": len(state["posts"])})
            context.close()
        (output / "scenarios.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        browser.close()


if __name__ == "__main__":
    run()
