"""Rendered recurring-create recovery in Finance, using isolated data and a simulated provider API."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

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
            data={"name": "schedule checking", "currency": "CAD", "opening": 100},
        )
        assert account.ok, account.text()
        account_id = account.json()["id"]
        assert setup.put(
            base + "/api/appearance", data={"preset": "light", "colors": LIGHT_BASE}
        ).ok
        setup.dispose()

        records = []
        for profile, width in (("desktop", 1440), ("tablet", 760), ("phone", 390)):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
                reduced_motion="reduce",
                service_workers="block",
            )
            state = {"phase": "empty", "requests": [], "retries": [], "errors": []}
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
                    rows = []
                    if state["phase"] in {"pending", "done"}:
                        request = state["requests"][0]
                        rows = [
                            {
                                "id": request["request_id"],
                                "account_id": account_id,
                                "amount": request["amount"],
                                "amount_kind": "exact",
                                "category": "housing",
                                "payee": request["payee"],
                                "notes": "",
                                "cycle": request["cycle"],
                                "next_date": request["next_date"],
                                "active": state["phase"] == "done",
                                "create_pending": state["phase"] == "pending",
                                "create_needs_review": False,
                                "manageable": state["phase"] == "done",
                            }
                        ]
                    route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(rows)
                    )
                elif path == "/api/money/recurring" and route.request.method == "POST":
                    state["requests"].append(route.request.post_data_json)
                    state["phase"] = "pending"
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"response lost after Actual saved the schedule"}',
                    )
                elif path.endswith("/retry") and "/api/money/recurring/" in path:
                    state["retries"].append(path)
                    state["phase"] = "done"
                    route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
                elif path == "/api/money/summary":
                    summary = route.fetch().json()
                    summary["ledger"] = "actual"
                    route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(summary)
                    )
                elif path == "/api/money/envelope":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
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
                        ),
                    )
                else:
                    route.continue_()

            context.route("**/api/money/**", response)
            page.goto(finance, wait_until="networkidle")
            tab = page.locator('#finance-tabs [data-group-section="money"]')
            if tab.get_attribute("aria-selected") != "true":
                tab.click()
            card = page.locator('.money-card[data-card="recurring"]')
            expect(card.get_by_text("no auto-post schedules in Actual")).to_be_visible()
            expect(card.get_by_text("payee", exact=True)).to_be_visible()
            assert card.locator("select").count() == 0
            category = card.locator("#rc-category-choice")
            assert category.evaluate("element => element.getBoundingClientRect().height") >= 44
            category.focus()
            page.keyboard.press("Enter")
            dialog = page.get_by_role("dialog", name="choose a spending category")
            expect(dialog).to_be_visible()
            page.keyboard.press("Tab")
            expect(dialog.get_by_role("button", name="no category")).to_be_focused()
            page.keyboard.press("Tab")
            page.keyboard.press("Enter")
            expect(category).to_have_text("bills / housing")
            card.get_by_label("payee").fill("rent")
            card.get_by_label("amount").fill("42.50")
            add = card.get_by_role("button", name="add schedule")
            add.focus()
            page.keyboard.press("Enter")
            retry = card.get_by_role("button", name="retry creation")
            expect(retry).to_be_visible()
            expect(
                card.get_by_text("finish the pending schedule before adding another.")
            ).to_be_visible()
            assert len(state["requests"]) == 1
            request = state["requests"][0]
            assert request["category_id"] == "housing-id", request
            assert request["amount"] == -42.5, request
            assert request["account_id"] == account_id, request
            assert re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", request["request_id"])
            page.screenshot(
                path=str(output / f"recurring-create-{profile}-pending.png"), full_page=True
            )
            page.reload(wait_until="networkidle")
            retry = card.get_by_role("button", name="retry creation")
            expect(retry).to_be_visible()
            retry.focus()
            page.keyboard.press("Enter")
            expect(retry).to_have_count(0)
            expect(card.get_by_role("button", name="pause")).to_be_visible()
            assert len(state["requests"]) == 1, state["requests"]
            assert state["retries"] == [f"/api/money/recurring/{request['request_id']}/retry"], (
                state["retries"]
            )
            page.screenshot(
                path=str(output / f"recurring-create-{profile}-done.png"), full_page=True
            )
            page.evaluate("document.documentElement.style.zoom = '2'")
            assert card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
            assert card.locator(".rc-payee").evaluate(
                "element => element.getBoundingClientRect().width > 20"
            )
            page.screenshot(
                path=str(output / f"recurring-create-{profile}-zoom.png"), full_page=True
            )
            expected_503 = "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
            assert all(error == expected_503 for error in state["errors"]), state["errors"]
            records.append({"profile": profile, "status": "passed"})
            context.close()

        (output / "scenarios.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        browser.close()


if __name__ == "__main__":
    run()
