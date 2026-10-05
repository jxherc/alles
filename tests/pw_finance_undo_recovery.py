"""Owned undo recovery, newer drafts/focus and receipt disclosure cases."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (1440, 390):
                for case in (
                    "dismiss",
                    "first-account",
                    "receipt-focus",
                    "receipt-focus-success",
                    "empty-retry",
                    "unknown-reply",
                    "unknown-outcome",
                    "entry-focus",
                    "recurring-edit",
                    "history",
                    "during-refresh",
                    "entry-action-focus",
                    "earlier-focus",
                    "late-save-undo",
                    "chosen-undo-reload",
                    "duplicate-save",
                    "management-focus",
                    "task-focus",
                    "row-action-focus",
                    "shared-tag-focus",
                    "summary-focus",
                    "reload-read-summary",
                    "reload-read-accounts",
                ):
                    if case == "summary-focus" and width == 1440:
                        continue  # This disclosure is only visible at compact widths.
                    context = browser.new_context(
                        viewport={"width": width, "height": 900},
                        has_touch=width == 390,
                        service_workers="block",
                        reduced_motion="reduce",
                        timezone_id="UTC",
                    )
                    state = {
                        "hold": True,
                        "fail_summary": False,
                        "hold_save": False,
                        "hold_refresh": False,
                        "fail_recurring": False,
                    }
                    held, held_refresh, errors, console, external = [], [], [], [], []
                    page = context.new_page()
                    page.set_default_timeout(2500)
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            console.append(message.text) if message.type == "error" else None
                        ),
                    )

                    def route(request):
                        parsed = urlsplit(request.request.url)
                        if (parsed.scheme, parsed.netloc) != ("http", urlsplit(base).netloc):
                            external.append(request.request.url)
                            return request.abort()
                        if parsed.path == "/api/money/recurring" and state["hold_refresh"]:
                            held_refresh.append(request)
                            return
                        if (
                            parsed.path == "/api/money/transactions"
                            and request.request.method == "POST"
                            and state["hold_save"]
                        ):
                            held.append(request)
                            return
                        if parsed.path == "/api/money/recurring" and state["fail_recurring"]:
                            return request.fulfill(
                                status=503, json={"detail": "owned failed schedule read"}
                            )
                        if case == "recurring-edit" and parsed.path == "/api/money/summary":
                            payload = request.fetch().json()
                            payload["ledger"] = "actual"
                            return request.fulfill(status=200, json=payload)
                        if case == "recurring-edit" and parsed.path == "/api/money/recurring":
                            return request.fulfill(
                                status=200,
                                json=[
                                    {
                                        "id": "owned-linked-rent",
                                        **schedule_current,
                                        "payee": "owned landlord",
                                        "category": "housing",
                                        "amount_kind": "exact",
                                        "editable": True,
                                        "manageable": True,
                                    }
                                ],
                            )
                        if parsed.path == "/api/money/recurring/owned-linked-rent/edit-options":
                            return request.fulfill(
                                status=200,
                                json={
                                    "current": schedule_current,
                                    "accounts": [
                                        {"id": account["id"], "name": "owned recovery account"}
                                    ],
                                    "payees": [{"id": "landlord", "name": "owned landlord"}],
                                    "categories": [{"id": "housing", "name": "housing"}],
                                },
                            )
                        if (
                            parsed.path
                            == (
                                "/api/money/accounts"
                                if case == "reload-read-accounts"
                                else "/api/money/summary"
                            )
                            and state["fail_summary"]
                        ):
                            return request.fulfill(
                                status=503, json={"detail": "owned temporary read failure"}
                            )
                        if (
                            parsed.path.endswith("/undo")
                            and request.request.method == "POST"
                            and state["hold"]
                        ):
                            held.append(request)
                            return
                        request.continue_()

                    context.route("**/*", route)
                    context.route_web_socket("**/*", lambda socket: socket.close())
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss").ok
                    for account in api.get(base + "/api/money/accounts").json():
                        assert api.delete(base + "/api/money/accounts/" + account["id"]).ok
                    account = api.post(
                        base + "/api/money/accounts",
                        data={"name": "owned recovery account", "currency": "CAD", "opening": 100},
                    ).json()
                    schedule_current = {
                        "account_id": account["id"],
                        "payee_id": "landlord",
                        "category_id": "housing",
                        "amount": -5,
                        "notes": "owned lease",
                        "cycle": "monthly",
                        "cycle_days": 30,
                        "next_date": "2099-10-01",
                        "active": True,
                    }
                    month = datetime.now(UTC).strftime("%Y-%m")
                    page.goto(base + "/?view=money&m=" + month, wait_until="networkidle")
                    saved = []
                    for number in (1, 2):
                        if page.locator("#money-entry-fields").is_hidden():
                            page.locator("#money-entry-action").press("Enter")
                        page.locator("#tx-payee").fill(f"owned recovery expense {number}")
                        page.locator("#tx-amt").fill("2.50")
                        if case == "shared-tag-focus":
                            page.locator("#tx-tags").fill("owned-shared")
                        with page.expect_response(
                            lambda response: (
                                urlsplit(response.url).path == "/api/money/transactions"
                                and response.request.method == "POST"
                            )
                        ) as result:
                            page.locator("#tx-add").press("Enter")
                        assert result.value.ok
                        saved.append(result.value.json())
                        expect(
                            page.locator(f'[data-undo-saved="{saved[-1]["id"]}"]')
                        ).to_be_visible()
                    page.wait_for_load_state("networkidle")
                    expect(page.locator(".txn")).to_have_count(2)
                    first, second = saved
                    history = page.locator("#money-saved-history")
                    expect(history).to_have_attribute("aria-expanded", "false")
                    expect(page.locator(f'[data-undo-saved="{first["id"]}"]')).to_be_hidden()
                    expect(page.locator(f'[data-undo-saved="{second["id"]}"]')).to_be_visible()
                    if case not in ("history", "earlier-focus"):
                        history.press("Enter")
                        expect(history).to_have_attribute("aria-expanded", "true")
                    first_receipt = page.locator(f'[data-saved-txn="{first["id"]}"]')
                    record = {"case": case, "width": width, "status": "failed"}
                    records.append(record)
                    try:
                        if case == "duplicate-save":
                            if history.get_attribute("aria-expanded") == "true":
                                history.press("Enter")
                            if page.locator("#money-entry-fields").is_hidden():
                                page.locator("#money-entry-action").press("Enter")
                            page.locator("#tx-payee").fill("owned duplicate submit")
                            page.locator("#tx-amt").fill("3.10")
                            state["hold_save"] = True
                            page.locator("#tx-add").press("Enter")
                            for _ in range(100):
                                if held:
                                    break
                                page.wait_for_timeout(10)
                            assert len(held) == 1
                            page.locator("#tx-add").press("Enter")
                            expect(
                                page.get_by_text(
                                    "transaction creation is already in progress", exact=True
                                )
                            ).to_be_visible()
                            expect(page.locator("#tx-save-status")).to_have_text(
                                "saving transaction…"
                            )
                            assert len(held) == 1
                            pending = held.pop()
                            response = pending.fetch()
                            assert response.ok
                            created = response.json()
                            state["hold_save"] = False
                            pending.fulfill(response=response)
                            expect(page.locator(f'.txn[data-id="{created["id"]}"]')).to_have_count(
                                1
                            )
                            page.wait_for_load_state("networkidle")
                            expect(
                                page.locator(f'[data-saved-txn="{created["id"]}"]')
                            ).to_be_visible()
                            assert len(api.get(base + "/api/money/transactions").json()) == 3
                            page.reload(wait_until="networkidle")
                            expect(
                                page.locator(f'[data-saved-txn="{created["id"]}"]')
                            ).to_be_visible()
                        elif case == "late-save-undo":
                            if page.locator("#money-entry-fields").is_hidden():
                                page.locator("#money-entry-action").press("Enter")
                            page.locator("#tx-payee").fill("owned delayed expense")
                            page.locator("#tx-amt").fill("3.10")
                            state["hold_save"] = True
                            page.locator("#tx-add").press("Enter")
                            for _ in range(100):
                                if held:
                                    break
                                page.wait_for_timeout(10)
                            assert len(held) == 1
                            save_reply = held.pop()
                            page.locator(f'[data-undo-saved="{first["id"]}"]').press("Enter")
                            assert len(held) == 1
                            undo_reply = held.pop()
                            response = undo_reply.fetch()
                            assert response.ok and response.json()["outcome"] == "undone"
                            undo_reply.fulfill(response=response)
                            expect(page.locator(f'.txn[data-id="{first["id"]}"]')).to_have_count(0)
                            expect(first_receipt).to_be_visible()
                            expect(first_receipt).to_contain_text("transaction undone")
                            response = save_reply.fetch()
                            assert response.ok
                            created = response.json()
                            state["hold_save"] = False
                            save_reply.fulfill(response=response)
                            expect(page.locator(f'.txn[data-id="{created["id"]}"]')).to_have_count(
                                1
                            )
                            page.wait_for_load_state("networkidle")
                            expect(first_receipt).to_be_visible()
                            expect(first_receipt).to_contain_text("transaction undone")
                            rows = api.get(base + "/api/money/transactions").json()
                            assert {row["id"] for row in rows} == {second["id"], created["id"]}
                            pointers = page.evaluate(
                                "JSON.parse(sessionStorage.getItem('alles:finance-saved-transactions'))"
                            )
                            assert pointers[-1]["id"] == first["id"]
                            if page.locator("#money-entry-fields").is_hidden():
                                page.locator("#money-entry-action").press("Enter")
                            expect(page.locator("#tx-save-status")).to_be_hidden()
                            page.reload(wait_until="networkidle")
                            expect(first_receipt).to_be_visible()
                            expect(first_receipt).to_contain_text("transaction undone")
                            assert len(pointers) == 3
                            assert any(
                                row["request_id"] == first["undo"]["request_id"]
                                and row["state"] == "undone"
                                for row in pointers
                            )
                        elif case == "history":
                            before = api.get(base + "/api/money/transactions").json()
                            history.focus()
                            history.press("Enter")
                            expect(history).to_have_attribute("aria-expanded", "true")
                            earlier = page.locator(f'[data-undo-saved="{first["id"]}"]')
                            expect(earlier).to_be_visible()
                            assert earlier.bounding_box()["height"] >= 44
                            earlier.focus()
                            history.evaluate("button => button.click()")
                            expect(history).to_have_attribute("aria-expanded", "false")
                            expect(history).to_be_focused()
                            expect(earlier).to_be_hidden()
                            pointers = page.evaluate(
                                "JSON.parse(sessionStorage.getItem('alles:finance-saved-transactions'))"
                            )
                            assert len(pointers) == 2
                            assert api.get(base + "/api/money/transactions").json() == before
                        elif case in ("entry-focus", "during-refresh", "earlier-focus"):
                            if page.locator("#money-entry-fields").is_hidden():
                                page.locator("#money-entry-action").press("Enter")
                            page.locator("#tx-payee").fill("owned focus expense")
                            page.locator("#tx-amt").fill("3.10")
                            state["hold_save"] = True
                            page.locator("#tx-add").press("Enter")
                            for _ in range(100):
                                if held:
                                    break
                                page.wait_for_timeout(10)
                            assert len(held) == 1
                            if case == "during-refresh":
                                state["hold_refresh"] = True
                            elif case == "earlier-focus":
                                page.locator(f'[data-undo-saved="{second["id"]}"]').focus()
                            else:
                                page.locator("#tx-cat").focus()
                            pending_response = held.pop()
                            response = pending_response.fetch()
                            assert response.ok
                            result = response.json()
                            state["hold_save"] = False
                            # The held response has committed, but no newer value was typed.
                            pending_response.fulfill(response=response)
                            if case != "during-refresh":
                                expect(
                                    page.locator(f'[data-saved-txn="{result["id"]}"]')
                                ).to_contain_text("transaction saved")
                            if case == "during-refresh":
                                for _ in range(100):
                                    if held_refresh:
                                        break
                                    page.wait_for_timeout(10)
                                assert len(held_refresh) == 1
                                if page.locator("#money-entry-fields").is_hidden():
                                    page.locator("#money-entry-action").press("Enter")
                                page.locator("#tx-payee").fill("new during refresh 草稿")
                                page.locator("#tx-amt").fill("73.10")
                                page.locator("#tx-payee").focus()
                                read = held_refresh.pop()
                                state["hold_refresh"] = False
                                read.fulfill(response=read.fetch())
                                expect(
                                    page.locator(f'.txn[data-id="{result["id"]}"]')
                                ).to_have_count(1)
                                expect(page.locator("#tx-payee")).to_have_value(
                                    "new during refresh 草稿"
                                )
                                expect(page.locator("#money-entry-fields")).to_be_visible()
                                expect(page.locator("#tx-payee")).to_be_focused()
                            elif case == "earlier-focus":
                                expect(
                                    page.locator(f'[data-undo-saved="{second["id"]}"]')
                                ).to_be_focused()
                                expect(
                                    page.locator(f'[data-undo-saved="{second["id"]}"]')
                                ).to_be_visible()
                            else:
                                expect(page.locator("#tx-cat")).to_be_focused()
                                expect(page.locator("#money-entry-fields")).to_be_visible()
                        elif case == "empty-retry":
                            for item in saved:
                                page.locator(f'[data-dismiss-saved="{item["id"]}"]').click()
                            state["fail_summary"] = True
                            page.locator("#money-next").press("Enter")
                            retry = page.locator("#money-result-retry")
                            expect(retry).to_be_visible()
                            state["fail_summary"] = False
                            retry.focus()
                            retry.press("Enter")
                            expect(retry).to_have_count(0)
                            record["active"] = page.evaluate("document.activeElement.id")
                            expect(page.locator("#money-entry-action")).to_be_focused()
                        else:
                            page.locator(f'[data-undo-saved="{first["id"]}"]').press("Enter")
                            assert len(held) == 1
                            pending = held.pop()
                            if case == "chosen-undo-reload":
                                response = pending.fetch()
                                assert response.ok and response.json()["outcome"] == "undone"
                                pending.fulfill(response=response)
                                expect(
                                    page.locator(f'.txn[data-id="{first["id"]}"]')
                                ).to_have_count(0)
                                page.wait_for_load_state("networkidle")
                                expect(first_receipt).to_be_visible()
                                expect(first_receipt).to_contain_text("transaction undone")
                                page.reload(wait_until="networkidle")
                                expect(first_receipt).to_be_visible()
                                expect(first_receipt).to_contain_text("transaction undone")
                            elif case == "shared-tag-focus":
                                expect(page.locator('[data-tag="owned-shared"]')).to_have_count(2)
                                target = page.locator(
                                    f'.txn[data-id="{second["id"]}"] [data-tag="owned-shared"]'
                                )
                                target.focus()
                                response = pending.fetch()
                                assert response.ok
                                pending.fulfill(response=response)
                                expect(
                                    page.locator(f'.txn[data-id="{first["id"]}"]')
                                ).to_have_count(0)
                                expect(target).to_be_focused()
                            elif case in (
                                "management-focus",
                                "task-focus",
                                "row-action-focus",
                                "summary-focus",
                            ):
                                if case == "management-focus":
                                    target = page.locator('[data-money-section="plans"]')
                                elif case == "task-focus":
                                    if page.locator("#money-section-plans").is_hidden():
                                        page.locator('[data-money-section="plans"]').click()
                                    target = page.locator('[data-money-task="goals"]')
                                elif case == "summary-focus":
                                    target = page.locator("#money-summary-toggle")
                                else:
                                    target = page.locator(f'[data-edit-txn="{second["id"]}"]')
                                target.focus()
                                response = pending.fetch()
                                assert response.ok
                                pending.fulfill(response=response)
                                expect(
                                    page.locator(f'.txn[data-id="{first["id"]}"]')
                                ).to_have_count(0)
                                expect(target).to_be_focused()
                            elif case in ("reload-read-summary", "reload-read-accounts"):
                                pending.fulfill(
                                    status=503, json={"detail": "owned unconfirmed undo"}
                                )
                                expect(first_receipt).to_contain_text("undo not confirmed")
                                state["fail_summary"] = True
                                page.reload(wait_until="networkidle")
                                retry = page.locator(f'[data-undo-saved="{first["id"]}"]')
                                expect(retry).to_be_visible()
                                expect(page.locator("#money-result-retry")).to_be_visible()
                                retry.press("Enter")
                                assert len(held) == 1
                                original = held.pop()
                                assert original.request.post_data_json == {
                                    "request_id": first["undo"]["request_id"]
                                }
                                response = original.fetch()
                                assert response.ok and response.json()["outcome"] == "undone"
                                original.fulfill(response=response)
                                expect(first_receipt).to_contain_text("transaction undone")
                                page.wait_for_load_state("networkidle")
                                expect(first_receipt).to_be_visible()
                                rows = api.get(base + "/api/money/transactions").json()
                                assert [row["id"] for row in rows] == [second["id"]]
                                state["fail_summary"] = False
                                page.locator("#money-result-retry").press("Enter")
                                expect(page.locator("#money-result-retry")).to_have_count(0)
                                expect(
                                    page.locator(f'.txn[data-id="{second["id"]}"]')
                                ).to_have_count(1)
                                expect(first_receipt).to_be_visible()
                                expect(first_receipt).to_contain_text("transaction undone")
                                expect(first_receipt).not_to_contain_text("NaN")
                                expect(first_receipt).not_to_contain_text("undefined")
                                expect(page.locator("#money-save-results")).to_be_focused()
                            elif case == "entry-action-focus":
                                page.locator("#money-entry-action").focus()
                                response = pending.fetch()
                                assert response.ok
                                pending.fulfill(response=response)
                                expect(first_receipt).to_contain_text("transaction undone")
                                expect(page.locator("#money-entry-action")).to_be_focused()
                            elif case == "recurring-edit":
                                plans = page.locator("#money-section-plans")
                                if plans.is_hidden():
                                    page.locator('[data-money-section="plans"]').click()
                                page.locator('[data-money-task="schedules"]').click()
                                page.locator('[data-edit-rec="owned-linked-rent"]').press("Enter")
                                expect(page.locator("#rce-amount")).to_be_visible()
                                page.locator("#rce-amount").fill("73.10")
                                page.locator("#rce-amount").focus()
                                state["fail_recurring"] = True
                                pending.fulfill(
                                    status=409,
                                    json={
                                        "detail": "undo is unavailable for Actual transactions; review before deleting"
                                    },
                                )
                                expect(first_receipt).to_contain_text("unavailable for Actual")
                                expect(page.locator("#rce-amount")).to_have_value("73.10")
                                expect(page.locator("#rce-amount")).to_be_focused()
                                expect(page.locator("#money-result-retry")).to_be_visible()
                                state["fail_recurring"] = False
                                page.locator("#money-result-retry").press("Enter")
                                expect(page.locator("#money-result-retry")).to_have_count(0)
                                expect(page.locator("#rce-amount")).to_have_value("73.10")
                                record["simulated_canonical_read_and_refusal"] = True
                            elif case == "dismiss":
                                dismiss = page.locator(f'[data-dismiss-saved="{first["id"]}"]')
                                record["dismiss_disabled"] = dismiss.is_disabled()
                                if dismiss.is_enabled():
                                    dismiss.click()
                                history.press("Enter")
                                response = pending.fetch()
                                assert response.ok
                                pending.fulfill(
                                    status=503, json={"detail": "owned reply lost after reversal"}
                                )
                                expect(first_receipt).to_contain_text("undo not confirmed")
                                pointers = page.evaluate(
                                    "JSON.parse(sessionStorage.getItem('alles:finance-saved-transactions'))"
                                )
                                assert any(
                                    item["request_id"] == first["undo"]["request_id"]
                                    for item in pointers
                                )
                                expect(
                                    page.locator(f'[data-dismiss-saved="{first["id"]}"]')
                                ).to_be_disabled()
                            elif case == "first-account":
                                assert api.delete(base + "/api/money/accounts/" + account["id"]).ok
                                page.locator("#money-next").press("Enter")
                                expect(page.locator("#money-body")).to_contain_text(
                                    "no accounts yet"
                                )
                                page.locator("#af-name").fill("new first account 草稿")
                                page.locator("#af-open").fill("73.10")
                                page.locator("#af-name").focus()
                                response = pending.fetch()
                                assert (
                                    response.ok and response.json()["outcome"] == "already_removed"
                                )
                                pending.fulfill(response=response)
                                expect(first_receipt).to_contain_text("already removed")
                                record["draft"] = page.locator("#af-name").input_value()
                                expect(page.locator("#af-name")).to_have_value(
                                    "new first account 草稿"
                                )
                                expect(page.locator("#af-open")).to_have_value("73.10")
                                expect(page.locator("#af-name")).to_be_focused()
                            elif case in ("receipt-focus", "receipt-focus-success"):
                                newer = page.locator(f'[data-undo-saved="{second["id"]}"]')
                                newer.focus()
                                if case == "receipt-focus-success":
                                    response = pending.fetch()
                                    assert response.ok and response.json()["outcome"] == "undone"
                                    pending.fulfill(response=response)
                                    expect(first_receipt).to_contain_text("transaction undone")
                                    expect(
                                        page.locator(f'.txn[data-id="{first["id"]}"]')
                                    ).to_have_count(0)
                                else:
                                    pending.fulfill(
                                        status=503, json={"detail": "owned undo not confirmed"}
                                    )
                                    expect(first_receipt).to_contain_text("undo not confirmed")
                                record["active"] = page.evaluate(
                                    "document.activeElement.dataset.undoSaved || document.activeElement.tagName"
                                )
                                expect(newer).to_be_focused()
                            else:
                                payload = (
                                    {"ok": False, "outcome": "undone"}
                                    if case == "unknown-reply"
                                    else {"ok": True, "outcome": "unknown"}
                                )
                                pending.fulfill(status=200, json=payload)
                                expect(first_receipt).to_contain_text("undo not confirmed")
                                assert any(
                                    row["id"] == first["id"]
                                    for row in api.get(base + "/api/money/transactions").json()
                                )
                        page.wait_for_load_state("networkidle")
                        assert not errors and not external, (errors, external)
                        assert all(
                            "503 (Service Unavailable)" in message or "409 (Conflict)" in message
                            for message in console
                        ), console
                        record["status"] = "passed"
                    except Exception as error:
                        record["error"] = type(error).__name__ + ": " + str(error)[:1600]
                    finally:
                        record.update(page_errors=errors, console_errors=console, external=external)
                        page.screenshot(path=str(out / f"{width}-{case}.png"))
                        context.close()
                        (out / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
        finally:
            browser.close()
    assert all(record["status"] == "passed" for record in records), [
        (record["case"], record["width"]) for record in records if record["status"] != "passed"
    ]


if __name__ == "__main__":
    run()
