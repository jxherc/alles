"""Rendered guarded recurring edit, deletion, and recovery with isolated data."""

from __future__ import annotations

import json
import os
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
            data={"name": "recurring fixture", "currency": "CAD", "opening": 100},
        )
        assert account.ok, account.text()
        account_id = account.json()["id"]
        setup.dispose()
        records = []

        for profile, width in (("desktop", 1440), ("phone", 390)):
            if profile == "phone":
                theme = playwright.request.new_context()
                assert theme.put(
                    base + "/api/appearance",
                    data={"preset": "light", "colors": LIGHT_BASE},
                ).ok
                theme.dispose()
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
                reduced_motion="reduce",
                service_workers="block",
            )
            state = {
                "phase": "ready",
                "lose_next": False,
                "fail_check_once": False,
                "posts": [],
                "retries": 0,
                "deletes": [],
                "delete_retries": 0,
                "lose_delete_next": False,
                "errors": [],
                "current": {
                    "account_id": account_id,
                    "payee_id": "landlord-id",
                    "amount": -5,
                    "category_id": "housing-id",
                    "notes": "lease",
                    "cycle": "monthly",
                    "cycle_days": 30,
                    "next_date": "2026-10-01",
                    "active": True,
                },
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
                    if state["fail_check_once"]:
                        state["fail_check_once"] = False
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"detail":"Actual unavailable during status check"}',
                        )
                        return
                    current = state["current"]
                    rows = (
                        [
                            {
                                "id": "linked-rent",
                                **current,
                                "category": "housing",
                                "payee": "landlord",
                                "amount_kind": "exact",
                                "manageable": state["phase"] == "ready",
                                "editable": state["phase"] == "ready",
                                "edit_pending": state["phase"] in {"pending", "review"},
                                "edit_needs_review": state["phase"] == "review",
                                "delete_pending": state["phase"]
                                in {"delete-pending", "delete-review"},
                                "delete_needs_review": state["phase"] == "delete-review",
                            },
                        ]
                        if state["phase"] != "deleted"
                        else []
                    ) + [
                        {
                            "id": "native-rent",
                            "payee": "native",
                            "amount": -3,
                            "amount_kind": "exact",
                            "cycle": "monthly",
                            "next_date": "2026-10-01",
                            "active": True,
                            "manageable": False,
                            "editable": False,
                        },
                    ]
                    route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(rows)
                    )
                elif path == "/api/money/recurring/linked-rent/edit-options":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "current": state["current"],
                                "accounts": [
                                    {"id": account_id, "name": "recurring fixture"},
                                    {"id": "savings-id", "name": "savings"},
                                ],
                                "payees": [
                                    {"id": "landlord-id", "name": "landlord"},
                                    {"id": "new-payee-id", "name": "new landlord"},
                                ],
                                "categories": [
                                    {"id": "housing-id", "name": "housing"},
                                    {"id": "rent-id", "name": "rent"},
                                ],
                            }
                        ),
                    )
                elif (
                    path == "/api/money/recurring/linked-rent/edit"
                    and route.request.method == "POST"
                ):
                    state["posts"].append(route.request.post_data_json)
                    state["current"] = route.request.post_data_json
                    if state["lose_next"]:
                        state["phase"] = "pending"
                        state["lose_next"] = False
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"detail":"response lost after Actual saved the edit"}',
                        )
                    else:
                        state["phase"] = "ready"
                        route.fulfill(
                            status=200, content_type="application/json", body='{"ok":true}'
                        )
                elif path == "/api/money/recurring/linked-rent/edit/retry":
                    state["retries"] += 1
                    state["phase"] = "ready"
                    route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
                elif path == "/api/money/recurring/linked-rent/delete":
                    state["deletes"].append(route.request.post_data_json)
                    if state["lose_delete_next"]:
                        state["phase"] = "delete-pending"
                        state["lose_delete_next"] = False
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"detail":"response lost after Actual deleted the schedule"}',
                        )
                    else:
                        state["phase"] = "deleted"
                        route.fulfill(
                            status=200, content_type="application/json", body='{"ok":true}'
                        )
                elif path == "/api/money/recurring/linked-rent/delete/retry":
                    state["delete_retries"] += 1
                    state["phase"] = "deleted"
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
                        body='{"to_be_budgeted":0,"categories":[],"unbound_targets":[],"pending_assignments":[]}',
                    )
                else:
                    route.continue_()

            context.route("**/api/money/**", response)
            page.goto(finance, wait_until="networkidle")
            tab = page.locator('#finance-tabs [data-group-section="money"]')
            if tab.get_attribute("aria-selected") != "true":
                tab.click()
            card = page.locator('.money-card[data-card="recurring"]')
            linked = card.locator('.recur-group[data-id="linked-rent"]')
            native = card.locator('.recur-group[data-id="native-rent"]')
            expect(native.get_by_role("button", name="edit native schedule")).to_have_count(0)
            edit = linked.get_by_role("button", name="edit landlord schedule")
            expect(edit).to_be_visible()
            assert edit.evaluate("element => element.getBoundingClientRect().height") >= 44
            edit.focus()
            page.keyboard.press("Enter")
            form = linked.locator(".recur-edit")
            expect(form).to_be_visible()
            expect(form.get_by_label("days between")).to_be_hidden()
            expect(linked.get_by_role("button", name="pause")).to_have_count(0)
            assert form.locator("select").count() == 0
            page.screenshot(path=str(output / f"recurring-edit-{profile}-open.png"), full_page=True)
            account_choice = form.get_by_role("button", name="account recurring fixture")
            account_choice.click()
            page.get_by_role("dialog", name="choose account").get_by_role(
                "button", name="savings"
            ).click()
            form.get_by_role("button", name="payee landlord").click()
            page.get_by_role("dialog", name="choose payee").get_by_role(
                "button", name="new landlord"
            ).click()
            form.get_by_role("button", name="category housing").click()
            page.get_by_role("dialog", name="choose category").get_by_role(
                "button", name="rent", exact=True
            ).click()
            amount = form.get_by_label("amount")
            amount.fill("5.234")
            form.get_by_role("button", name="save changes").click()
            expect(amount).to_have_value("5.234")
            assert state["posts"] == []
            amount.fill("6.25")
            cycle = form.locator("#rce-cycle")
            cycle.click()
            page.get_by_role("option", name="every n days").click()
            expect(form.get_by_label("days between")).to_be_visible()
            form.get_by_label("days between").fill("14")
            form.get_by_label("notes").fill("new lease")
            switch = form.get_by_role("switch", name="auto-post")
            switch.focus()
            page.keyboard.press("Space")
            expect(switch).to_have_attribute("aria-checked", "false")
            form.get_by_role("button", name="save changes").click()
            expect(form).to_have_count(0)
            assert len(state["posts"]) == 1, state["posts"]
            assert state["posts"][0] == {
                "account_id": "savings-id",
                "payee_id": "new-payee-id",
                "amount": -6.25,
                "category_id": "rent-id",
                "notes": "new lease",
                "cycle": "custom",
                "cycle_days": 14,
                "next_date": "2026-10-01",
                "active": False,
            }, state["posts"]
            expect(page.locator(".toast")).to_have_count(0, timeout=5000)
            page.screenshot(
                path=str(output / f"recurring-edit-{profile}-saved.png"), full_page=True
            )

            edit = linked.get_by_role("button", name="edit landlord schedule")
            edit.click()
            form = linked.locator(".recur-edit")
            expect(form.get_by_label("amount")).to_have_value("6.25")
            form.get_by_label("notes").fill("renewed lease")
            state["lose_next"] = True
            state["fail_check_once"] = True
            form.get_by_role("button", name="save changes").click()
            expect(form.get_by_label("notes")).to_have_value("renewed lease")
            expect(form.get_by_role("button", name="save changes")).to_be_disabled()
            form.get_by_role("button", name="check schedule").click()
            retry = linked.get_by_role("button", name="retry edit")
            expect(retry).to_be_visible()
            assert len(state["posts"]) == 2
            retry.focus()
            page.keyboard.press("Enter")
            expect(retry).to_have_count(0)
            assert state["retries"] == 1
            assert len(state["posts"]) == 2
            state["phase"] = "review"
            page.reload(wait_until="networkidle")
            expect(
                linked.get_by_text("review the schedule there before retrying", exact=False)
            ).to_be_visible()
            expect(linked.get_by_role("button", name="edit landlord schedule")).to_have_count(0)
            expect(linked.get_by_role("button", name="retry edit")).to_have_count(0)
            page.evaluate("document.documentElement.style.zoom = '2'")
            assert card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
            page.screenshot(
                path=str(output / f"recurring-edit-{profile}-review.png"), full_page=True
            )
            state["phase"] = "ready"
            page.reload(wait_until="networkidle")
            delete = linked.get_by_role("button", name="delete landlord schedule")
            expect(delete).to_be_visible()
            expect(native.get_by_role("button", name="delete native schedule")).to_have_count(0)
            assert delete.evaluate("element => element.getBoundingClientRect().height") >= 44
            page.screenshot(
                path=str(output / f"recurring-delete-{profile}-ready.png"), full_page=True
            )
            delete.focus()
            page.keyboard.press("Enter")
            dialog = page.get_by_role(
                "alertdialog", name="delete the landlord schedule", exact=False
            )
            expect(dialog).to_be_visible()
            expect(dialog.get_by_role("button", name="cancel")).to_be_focused()
            page.screenshot(
                path=str(output / f"recurring-delete-{profile}-confirm.png"), full_page=True
            )
            page.keyboard.press("Escape")
            expect(dialog).to_have_count(0)
            assert state["deletes"] == []
            delete.click()
            state["lose_delete_next"] = True
            dialog.get_by_role("button", name="confirm").click()
            retry_delete = linked.get_by_role("button", name="retry deletion")
            expect(retry_delete).to_be_visible()
            assert state["deletes"] == [{"confirm_id": "linked-rent"}]
            expect(linked.get_by_role("button", name="delete landlord schedule")).to_have_count(0)
            page.screenshot(
                path=str(output / f"recurring-delete-{profile}-pending.png"), full_page=True
            )
            state["phase"] = "delete-review"
            page.reload(wait_until="networkidle")
            expect(
                linked.get_by_text("review it before retrying deletion", exact=False)
            ).to_be_visible()
            expect(linked.get_by_role("button", name="retry deletion")).to_have_count(0)
            page.evaluate("document.documentElement.style.zoom = '2'")
            assert card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
            page.screenshot(
                path=str(output / f"recurring-delete-{profile}-review.png"), full_page=True
            )
            linked.screenshot(path=str(output / f"recurring-delete-{profile}-review-row.png"))
            state["phase"] = "delete-pending"
            page.reload(wait_until="networkidle")
            retry_delete = linked.get_by_role("button", name="retry deletion")
            retry_delete.focus()
            page.keyboard.press("Enter")
            expect(linked).to_have_count(0)
            expect(native).to_be_visible()
            assert state["delete_retries"] == 1
            assert len(state["deletes"]) == 1
            page.screenshot(
                path=str(output / f"recurring-delete-{profile}-gone.png"), full_page=True
            )
            expected = "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
            assert all(error == expected for error in state["errors"]), state["errors"]
            records.append({"profile": profile, "status": "passed"})
            context.close()

        (output / "scenarios.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        browser.close()


if __name__ == "__main__":
    run()
