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
from pw_finance_helpers import show_money_sections

from services.appearance import LIGHT_BASE


def run() -> None:
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    finance = base + "/?view=finance"
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
            held_posts = []
            held_retries = []
            page = context.new_page()
            page.on("pageerror", lambda error: state["errors"].append(str(error)))
            page.on(
                "console",
                lambda message: (
                    state["errors"].append(message.text) if message.type == "error" else None
                ),
            )

            def response(route):
                parsed = urlsplit(route.request.url)
                if (parsed.scheme, parsed.netloc) != (urlsplit(base).scheme, urlsplit(base).netloc):
                    state["errors"].append("blocked external request: " + route.request.url)
                    return route.abort()
                path = parsed.path
                if path == "/api/money/recurring" and route.request.method == "GET":
                    rows = []
                    if state["phase"] in {
                        "pending",
                        "done",
                        "posting_pending",
                        "edit_pending",
                        "edit_review",
                    }:
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
                                "posting_pending": state["phase"] == "posting_pending",
                                "posting_target_active": False,
                                "create_pending": state["phase"] == "pending",
                                "create_needs_review": False,
                                "edit_pending": state["phase"] in {"edit_pending", "edit_review"},
                                "edit_needs_review": state["phase"] == "edit_review",
                                "manageable": state["phase"] != "pending",
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
                    if state.get("hold_retry"):
                        held_retries.append(route)
                        return
                    state["phase"] = "done"
                    route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
                elif "/api/money/recurring/" in path and route.request.method == "PATCH":
                    held_posts.append(route)
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

            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if (urlsplit(route.request.url).scheme, urlsplit(route.request.url).netloc)
                    == (urlsplit(base).scheme, urlsplit(base).netloc)
                    else route.abort()
                ),
            )
            context.route_web_socket("**/*", lambda ws: ws.close())
            context.route("**/api/money/**", response)
            page.goto(finance, wait_until="networkidle")
            tab = page.locator('#finance-tabs [data-group-section="money"]')
            if tab.get_attribute("aria-selected") != "true":
                tab.click()
            show_money_sections(page, task="schedules")
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
            page.evaluate(
                "localStorage.setItem('money-hidden-cards', JSON.stringify(['recurring']))"
            )
            page.reload(wait_until="networkidle")
            show_money_sections(page, task="accounts")
            expect(card).to_be_visible()
            expect(card.locator(".card-hide")).to_be_disabled()
            expect(page.locator('[data-money-section="plans"]')).to_be_disabled()
            assert page.evaluate("JSON.parse(localStorage.getItem('money-hidden-cards'))") == [
                "recurring"
            ]
            retry = card.get_by_role("button", name="retry creation")
            expect(retry).to_be_visible()
            retry.focus()
            page.keyboard.press("Enter")
            expect(retry).to_have_count(0)
            expect(card).to_be_hidden()
            schedules_choice = page.locator('[data-money-task="schedules"]')
            expect(schedules_choice).to_be_visible()
            expect(schedules_choice).to_be_focused()
            assert page.evaluate("JSON.parse(localStorage.getItem('money-hidden-cards'))") == [
                "recurring"
            ]
            restore = page.get_by_role("button", name="restore 1 hidden card", exact=True)
            expect(restore).to_be_visible()
            assert restore.bounding_box()["height"] >= 44
            page.screenshot(path=str(output / f"recurring-create-{profile}-hidden-confirmed.png"))
            restore.focus()
            restore.press("Enter")
            expect(restore).to_be_hidden()
            expect(schedules_choice).to_be_focused()
            assert page.evaluate("JSON.parse(localStorage.getItem('money-hidden-cards'))") == []
            expect(card.get_by_role("button", name="pause")).to_be_visible()
            expect(card.locator(".card-hide")).to_be_enabled()
            expect(page.locator('[data-money-section="plans"]')).to_be_enabled()
            page.locator('[data-money-task="goals"]').click()
            expect(card).to_be_hidden()
            page.locator('[data-money-task="schedules"]').click()
            assert len(state["requests"]) == 1, state["requests"]
            assert state["retries"] == [f"/api/money/recurring/{request['request_id']}/retry"], (
                state["retries"]
            )
            state["phase"] = "pending"
            state["hold_retry"] = True
            page.reload(wait_until="networkidle")
            show_money_sections(page, task="schedules")
            retry = card.get_by_role("button", name="retry creation")
            retry.focus()
            retry.press("Enter")
            goals_choice = page.locator('[data-money-task="goals"]')
            goals_choice.click()
            # Model focus moving to non-focusable content after a deliberate task choice.
            goals_choice.evaluate("button => button.blur()")
            assert page.evaluate("document.activeElement === document.body")
            assert len(held_retries) == 1
            state["phase"] = "done"
            state["hold_retry"] = False
            held_retries.pop().fulfill(
                status=200, content_type="application/json", body='{"ok":true}'
            )
            expect(retry).to_have_count(0)
            expect(goals_choice).to_have_attribute("aria-pressed", "true")
            expect(page.locator("#money-task-goals")).to_be_visible()
            expect(card).to_be_hidden()
            assert page.evaluate("document.activeElement === document.body")
            assert len(state["requests"]) == 1
            assert len(state["retries"]) == 2
            page.screenshot(path=str(output / f"recurring-create-{profile}-newer-task.png"))
            # A newer transaction draft also ends ownership after focus moves to body.
            state["phase"] = "pending"
            state["hold_retry"] = True
            page.reload(wait_until="networkidle")
            show_money_sections(page, task="schedules")
            retry = card.get_by_role("button", name="retry creation")
            retry.focus()
            retry.press("Enter")
            if page.locator("#money-entry-fields").is_hidden():
                page.locator("#money-entry-action").click()
            newer_payee = page.locator("#tx-payee")
            newer_payee.fill("newer entry draft 草稿")
            newer_payee.evaluate("input => input.blur()")
            assert page.evaluate("document.activeElement === document.body")
            assert len(held_retries) == 1
            state["phase"] = "done"
            state["hold_retry"] = False
            held_retries.pop().fulfill(
                status=200, content_type="application/json", body='{"ok":true}'
            )
            expect(retry).to_have_count(0)
            expect(newer_payee).to_have_value("newer entry draft 草稿")
            assert page.evaluate("document.activeElement === document.body")
            assert len(state["requests"]) == 1 and len(state["retries"]) == 3
            page.screenshot(path=str(output / f"recurring-create-{profile}-newer-entry.png"))
            # Attention can make a disclosure/hide/restore control unavailable after a write.
            for transition in ("plans", "hide", "restore", "newer"):
                state["phase"] = "done"
                page.reload(wait_until="networkidle")
                show_money_sections(page, task="schedules")
                if card.is_hidden():
                    restore = page.get_by_role("button", name="restore 1 hidden card", exact=True)
                    restore.focus()
                    restore.press("Enter")
                    expect(card).to_be_visible()
                pause = card.get_by_role("button", name="pause", exact=True)
                pause.focus()
                pause.press("Enter")
                assert len(held_posts) == 1
                if transition == "newer":
                    page.locator("#rc-add").focus()
                    expect(page.locator("#rc-add")).to_be_focused()
                elif transition == "plans":
                    plans = page.locator('[data-money-section="plans"]')
                    plans.focus()
                    plans.press("Enter")
                    expect(page.locator("#money-section-plans")).to_be_hidden()
                elif transition == "hide":
                    card.locator(".card-hide").focus()
                    expect(card.locator(".card-hide")).to_be_focused()
                else:
                    card.locator(".card-hide").click()
                    restore = page.get_by_role("button", name="restore 1 hidden card", exact=True)
                    restore.focus()
                    expect(restore).to_be_focused()
                state["phase"] = "posting_pending"
                held_posts.pop().fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"posting response not confirmed"}',
                )
                expect(card.get_by_text("pause not confirmed", exact=False).first).to_be_visible()
                choice = page.locator('[data-money-task="schedules"]')
                expect(choice).to_be_visible()
                expect(choice).to_be_focused()
                expect(card.locator(".card-hide")).to_be_disabled()
                expect(page.locator('[data-money-section="plans"]')).to_be_disabled()
                if transition == "restore":
                    expect(restore).to_be_hidden()
                    assert page.evaluate(
                        "JSON.parse(localStorage.getItem('money-hidden-cards'))"
                    ) == ["recurring"]
                page.screenshot(
                    path=str(output / f"recurring-create-{profile}-attention-{transition}.png")
                )
            state["phase"] = "edit_pending"
            page.reload(wait_until="networkidle")
            show_money_sections(page, task="schedules")
            retry_edit = card.get_by_role("button", name="retry edit")
            expect(retry_edit).to_be_visible()
            expect(card.get_by_text("edit not confirmed", exact=False)).to_be_visible()
            expect(card.locator(".rc-next")).to_have_text("pending")
            expect(card.get_by_role("button", name="pause")).to_have_count(0)
            assert retry_edit.evaluate("element => element.getBoundingClientRect().height") >= 44
            retry_edit.focus()
            page.keyboard.press("Enter")
            expect(retry_edit).to_have_count(0)
            assert (
                state["retries"][-1] == f"/api/money/recurring/{request['request_id']}/edit/retry"
            )
            state["phase"] = "edit_review"
            page.reload(wait_until="networkidle")
            show_money_sections(page, task="schedules")
            expect(
                card.get_by_text("review the schedule there before retrying", exact=False)
            ).to_be_visible()
            expect(card.get_by_role("button", name="retry edit")).to_have_count(0)
            expect(card.locator(".rc-next")).to_have_text("pending")
            page.screenshot(
                path=str(output / f"recurring-create-{profile}-edit-review.png"), full_page=True
            )
            card.screenshot(path=str(output / f"recurring-create-{profile}-edit-card.png"))
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
            records.append(
                {
                    "profile": profile,
                    "status": "passed",
                    "saved_hide_confirmation_restore": True,
                    "held_newer_task": True,
                    "held_newer_entry_focus": True,
                    "attention_focus_transitions": ["plans", "hide", "restore", "newer"],
                }
            )
            context.close()

        (output / "scenarios.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        browser.close()


if __name__ == "__main__":
    run()
