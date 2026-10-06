"""Verify ledger entry, optional filters, management access and total recovery."""

import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tests"))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 820, 390, 320] for t in ["light", "dark"]] + [
    (1440, t, True) for t in ["light", "dark"]
]
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 844},
                service_workers="block",
                reduced_motion="reduce" if theme == "dark" else "no-preference",
                timezone_id="UTC",
                has_touch=width <= 390,
            )
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / f"zoom-{theme}"
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned zoom check",
                            "version": "1.0",
                            "permissions": ["tabs"],
                            "background": {"service_worker": "zoom.js"},
                        }
                    )
                )
                (extension / "zoom.js").write_text(
                    "chrome.runtime.onInstalled.addListener(() => {});"
                )
                context = pw.chromium.launch_persistent_context(
                    profile / "browser",
                    channel="chromium",
                    headless=True,
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    **options,
                )
            else:
                context = browser.new_context(**options)
            external, errors, console, requests = [], [], [], []
            reject = False
            hold_save = False
            held_saves = []
            hold_tag = False
            held_tags = []
            forecast_mode = "normal"
            held = []
            large_amounts = False

            def route(r):
                url = urlparse(r.request.url)
                if (url.scheme, url.netloc) != (urlparse(base).scheme, urlparse(base).netloc):
                    external.append(r.request.url)
                    return r.abort()
                if (
                    hold_tag
                    and url.path == "/api/money/transactions"
                    and url.query.startswith("tag=")
                ):
                    held_tags.append(r)
                    return None
                if url.path == "/api/money/transactions" and r.request.method == "POST":
                    requests.append(r.request.post_data_json)
                    if hold_save:
                        held_saves.append(r)
                        return None
                    if reject:
                        return r.fulfill(status=503, json={"detail": "owned save failed"})
                if url.path == "/api/money/forecast":
                    if forecast_mode == "error":
                        return r.fulfill(status=503, json={"detail": "owned forecast unavailable"})
                    if forecast_mode == "hold":
                        held.append(r)
                        return None
                if large_amounts and url.path in ["/api/money/summary", "/api/money/forecast"]:
                    response = r.fetch()
                    payload = response.json()
                    payload.update(
                        currency="CAD",
                        net_worth=12345678.9,
                        expense=1234567.89,
                        projected=12345678.9,
                    )
                    return r.fulfill(response=response, json=payload)
                return r.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda ws: ws.close())
            page = context.new_page()
            page.set_default_timeout(6000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
            if not rows:
                page.goto(base + "/?view=money", wait_until="networkidle")
                expect(page.locator("#money-body")).to_contain_text("no accounts yet")
                expect(page.locator("#money-entry-action")).to_have_count(0)
                assert api.post(
                    base + "/api/money/accounts",
                    data={"name": "garden budget", "currency": "CAD", "opening": 200},
                ).ok
            page.goto(base + "/?view=money", wait_until="networkidle")
            if zoom:
                worker = (
                    context.service_workers[0]
                    if context.service_workers
                    else context.wait_for_event("serviceworker")
                )
                assert (
                    worker.evaluate(
                        "async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,2);return chrome.tabs.getZoom(t.id)}",
                        base,
                    )
                    == 2
                )
                page.wait_for_function(
                    "innerWidth===720 && innerHeight===422 && devicePixelRatio===2"
                )
            compact = page.evaluate("matchMedia('(max-width: 720px)').matches")
            entry = page.locator("#money-entry-fields")
            action = page.locator("#money-entry-action")
            totals = page.locator("#money-summary-toggle")
            expect(action).to_be_visible()
            expect(page.locator("#money-management")).to_be_hidden()
            expect(page.locator("#money-manage-toggle")).to_have_attribute("aria-expanded", "false")
            expect(page.locator("#txn-amount-range")).to_be_hidden()
            if compact:
                expect(entry).to_be_hidden()
                expect(action).to_have_class(re.compile(r"\bprimary\b"))
                expect(totals).to_have_attribute("aria-expanded", "false")
                expect(page.locator("[data-secondary-total]:visible")).to_have_count(0)
            else:
                expect(entry).to_be_visible()
                expect(action).not_to_have_class(re.compile(r"\bprimary\b"))
                expect(totals).to_be_hidden()
                expect(page.locator(".ms-card:visible")).to_have_count(5)
            if entry.is_visible():
                expect(action).to_have_text("close entry")
                page.locator("#tx-payee").focus()
            else:
                action.tap() if width <= 390 else action.press("Enter")
            expect(page.locator("#tx-payee")).to_be_focused()
            expect(action).to_have_text("close entry")
            expect(page.get_by_role("button", name="add transaction", exact=True)).to_have_count(1)
            expect(action).not_to_have_class(re.compile(r"\bprimary\b"))
            payee = "garden supplies " + label + " 中文"
            page.locator("#tx-payee").fill(payee)
            page.locator("#tx-payee").focus()
            action.evaluate("button => button.click()")
            expect(entry).to_be_hidden()
            expect(action).to_be_focused()
            action.press("Enter")
            expect(page.locator("#tx-payee")).to_have_value(payee)
            expect(page.locator("#tx-payee")).to_be_focused()
            page.locator("#tx-cat").fill("garden")
            tag = "garden-" + label
            page.locator("#tx-tags").fill(tag)
            page.locator("#tx-amt").fill("18.75")
            if compact:
                action.press("Enter")
                expect(entry).to_be_hidden()
                expect(action).to_be_focused()
                action.press("Enter")
                expect(page.locator("#tx-payee")).to_have_value(payee)
                expect(page.locator("#tx-amt")).to_have_value("18.75")
                if not zoom:
                    page.locator("#tx-payee").focus()
                    page.set_viewport_size({"width": 1440, "height": 844})
                    expect(page.locator("#tx-payee")).to_have_value(payee)
                    page.set_viewport_size({"width": width, "height": 844})
                    expect(page.locator("#tx-payee")).to_be_focused()
                    expect(entry).to_be_visible()
                    expect(action).to_have_text("close entry")
                    action.focus()
                    page.set_viewport_size({"width": 1440, "height": 844})
                    expect(action).to_have_text("close entry")
                    expect(action).to_be_focused()
                    page.set_viewport_size({"width": width, "height": 844})
                    action.press("Enter")
                    expect(entry).to_be_hidden()
                    action.press("Enter")
                    expect(page.locator("#tx-payee")).to_have_value(payee)
            before = api.get(base + "/api/money/transactions").json()
            reject = True
            page.locator("#tx-add").press("Enter")
            expect(page.locator("#tx-save-status")).to_contain_text("save not confirmed")
            expect(entry).to_be_visible()
            expect(page.locator("#tx-payee")).to_have_value(payee)
            expect(page.locator("#tx-amt")).to_have_value("18.75")
            assert len(api.get(base + "/api/money/transactions").json()) == len(before)
            reject = False
            with page.expect_response(
                lambda r: (
                    urlparse(r.url).path == "/api/money/transactions" and r.request.method == "POST"
                )
            ) as saved:
                page.locator("#tx-add").press("Enter")
            assert saved.value.ok
            transaction = saved.value.json()
            row = page.locator(f'.txn[data-id="{transaction["id"]}"]')
            expect(row).to_contain_text(payee)
            assert transaction["amount"] == -18.75
            assert len(api.get(base + "/api/money/transactions").json()) == len(before) + 1
            if compact:
                expect(entry).to_be_hidden()
                expect(page.locator(f'[data-undo-saved="{transaction["id"]}"]')).to_be_focused()
            action.press("Enter")
            held_payee = "held expense " + label
            page.locator("#tx-payee").fill(held_payee)
            page.locator("#tx-amt").fill("1.25")
            hold_save = True
            page.locator("#tx-add").press("Enter")
            for _ in range(100):
                if held_saves:
                    break
                page.wait_for_timeout(20)
            assert len(held_saves) == 1
            page.locator("#money-next").focus()
            hold_save = False
            held_saves.pop().continue_()
            expect(page.locator(".txn").filter(has_text=held_payee)).to_be_visible()
            expect(page.locator("#money-next")).to_be_focused()
            assert len(api.get(base + "/api/money/transactions").json()) == len(before) + 2
            page.reload(wait_until="networkidle")
            expect(row).to_contain_text(payee)
            page.locator("#money-body").evaluate(
                "e=>{for(let p=e;p;p=p.parentElement)p.scrollTop=0}"
            )
            first = page.locator("#txn-rows .txn").first.bounding_box()
            if width <= 390:
                assert first["y"] + first["height"] <= 844, first

            def shot(name):
                capture = context.new_cdp_session(page).send(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                (out / f"{label}-{name}.png").write_bytes(base64.b64decode(capture["data"]))

            shot("ledger")
            search = page.locator("#txn-search")
            search.fill(payee)
            expect(page.locator("#txn-rows .txn")).to_have_count(1)
            expect(row).to_contain_text(payee)
            amount_range = page.locator("#txn-range-toggle")
            if width <= 390:
                amount_range.tap()
            else:
                amount_range.press("Enter")
            expect(page.locator("#txn-min")).to_be_focused()
            page.locator("#txn-max").fill("5")
            expect(amount_range).to_have_text("clear range")
            expect(page.locator("#txn-rows .txn")).to_have_count(0)
            shot("amount-range")
            amount_range.press("Enter")
            expect(amount_range).to_be_focused()
            expect(amount_range).to_have_attribute("aria-expanded", "false")
            expect(page.locator("#txn-amount-range")).to_be_hidden()
            expect(search).to_have_value(payee)
            expect(row).to_contain_text(payee)
            search.fill("")
            expect(page.locator("#txn-rows .txn")).to_have_count(len(before) + 2)
            amount_range.press("Enter")
            hold_tag = True
            row.locator(".tx-tag[data-tag]").click()
            for _ in range(100):
                if held_tags:
                    break
                page.wait_for_timeout(20)
            assert len(held_tags) == 1
            amount_range.press("Enter")
            expect(page.locator("#txn-rows .txn")).to_have_count(len(before) + 2)
            hold_tag = False
            with page.expect_response(lambda r: "/api/money/transactions?tag=" in r.url) as late:
                held_tags.pop().continue_()
            assert late.value.ok
            page.wait_for_timeout(50)
            expect(page.locator("#txn-rows .txn")).to_have_count(len(before) + 2)
            expect(page.locator(".txn-tagfilter")).to_have_count(0)
            row.locator(".tx-tag[data-tag]").click()
            expect(page.locator(".txn-tagfilter")).to_contain_text(tag)
            current_month = page.locator(".money-txns h2").inner_text()
            page.locator("#money-next").press("Enter")
            expect(page.locator(".money-txns h2")).not_to_have_text(current_month)
            expect(page.locator(".txn-tagfilter")).to_have_count(0)
            page.locator("#money-prev").press("Enter")
            expect(row).to_be_visible()
            manage = page.locator("#money-manage-toggle")
            if width <= 390:
                manage.tap()
            else:
                manage.press("Enter")
            expect(page.locator("#money-management")).to_be_visible()
            manage.press("Tab")
            expect(page.locator("#money-export")).to_be_focused()
            with page.expect_download() as downloaded:
                page.keyboard.press("Enter")
            export = Path(os.environ["ALLES_DATA"]) / f"{label}-transactions.csv"
            downloaded.value.save_as(export)
            assert payee in export.read_text()
            page.locator("#money-connect").press("Enter")
            bank = page.get_by_role("dialog", name="bank connections", exact=True)
            expect(bank).to_be_visible()
            bank.get_by_role("button", name="close", exact=True).press("Enter")
            expect(bank).to_have_count(0)
            expect(page.locator("#money-connect")).to_be_focused()
            shot("management")
            manage.press("Enter")
            expect(page.locator("#money-management")).to_be_hidden()
            expect(manage).to_be_focused()
            plans = page.locator('[data-money-section="plans"]')
            plans.press("Enter")
            accounts_task = page.locator('[data-money-task="accounts"]')
            expect(accounts_task).to_have_attribute("aria-pressed", "true")
            expect(page.locator("#money-task-accounts")).to_be_visible()
            expect(page.locator("#bf-cat")).to_be_hidden()
            expect(page.locator("#gl-name")).to_be_hidden()
            expect(page.locator("#rc-payee")).to_be_hidden()
            page.locator("#money-add-acct").press("Enter")
            page.locator("#af-name").fill("exact account draft 中文")
            for task, field in [
                ("budgets", "bf-cat"),
                ("schedules", "rc-payee"),
                ("goals", "gl-name"),
            ]:
                choice = page.locator(f'[data-money-task="{task}"]')
                choice.tap() if width <= 390 else choice.press("Enter")
                expect(choice).to_have_attribute("aria-pressed", "true")
                expect(choice).to_be_focused()
                expect(page.locator("#money-task-accounts")).to_be_hidden()
                page.locator("#" + field).fill("exact " + task + " draft 中文")
            accounts_task.press("Enter")
            expect(page.locator("#af-name")).to_have_value("exact account draft 中文")
            for task, field in [
                ("budgets", "bf-cat"),
                ("schedules", "rc-payee"),
                ("goals", "gl-name"),
            ]:
                page.locator(f'[data-money-task="{task}"]').press("Enter")
                expect(page.locator("#" + field)).to_have_value("exact " + task + " draft 中文")
            shot("chosen-management")
            accounts_task.press("Enter")
            plans.press("Enter")
            if compact:
                totals.press("Enter")
                expect(totals).to_have_attribute("aria-expanded", "true")
                expect(page.locator(".ms-card:visible")).to_have_count(5)
                shot("totals")
                totals.press("Enter")
                expect(page.locator("[data-secondary-total]:visible")).to_have_count(0)
                expect(totals).to_be_focused()
                if not zoom:
                    page.set_viewport_size({"width": 1440, "height": 844})
                    expect(totals).to_be_hidden()
                    expect(action).to_be_focused()
                    page.set_viewport_size({"width": width, "height": 844})
            forecast_mode = "error"
            page.reload(wait_until="networkidle")
            if compact:
                expect(totals).to_contain_text("forecast unavailable")
                totals.press("Enter")
            retry = page.locator("#forecast-retry")
            expect(retry).to_be_visible()
            forecast_mode = "hold"
            retry.press("Enter")
            expect(retry).to_be_disabled()
            for _ in range(100):
                if held:
                    break
                page.wait_for_timeout(20)
            assert len(held) == 1
            if compact:
                totals.press("Enter")
                expect(page.locator("#money-projection")).to_be_hidden()
            if entry.is_hidden():
                action.press("Enter")
            page.locator("#tx-payee").fill("newer exact draft during forecast 中文")
            page.locator("#tx-amt").fill("7.25")
            page.locator("#tx-payee").focus()
            forecast_mode = "normal"
            held.pop().continue_()
            expect(page.locator("#money-projection .ms-val")).to_be_attached()
            expect(page.locator("#tx-payee")).to_be_focused()
            expect(page.locator("#tx-payee")).to_have_value(
                "newer exact draft during forecast 中文"
            )
            expect(page.locator("#tx-amt")).to_have_value("7.25")
            if compact:
                expect(page.locator("#money-projection")).to_be_hidden()
                expect(totals).not_to_contain_text("unavailable")
                action.press("Enter")
            if not compact:
                for retry_fails in [True, False]:
                    forecast_mode = "error"
                    page.reload(wait_until="networkidle")
                    forecast_mode = "hold"
                    retry.press("Enter")
                    expect(retry).to_be_disabled()
                    for _ in range(100):
                        if held:
                            break
                        page.wait_for_timeout(20)
                    assert len(held) == 1
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(totals).to_have_attribute("aria-expanded", "true")
                    expect(page.locator("#money-projection")).to_be_visible()
                    forecast_mode = "normal"
                    response = held.pop()
                    if retry_fails:
                        response.fulfill(status=503, json={"detail": "owned retry unavailable"})
                        expect(retry).to_be_enabled()
                        expect(retry).to_be_focused()
                    else:
                        response.continue_()
                        expect(page.locator("#money-projection .ms-val")).to_be_visible()
                        expect(page.locator("#money-projection")).to_be_focused()
                    page.set_viewport_size({"width": width, "height": 844})
            large_amounts = True
            page.reload(wait_until="networkidle")
            if compact:
                totals.press("Enter")
            expect(page.locator(".money-summary")).to_contain_text("12,345,678.90")
            assert page.locator(".ms-card").evaluate_all(
                "els=>els.every(e=>e.scrollWidth<=e.clientWidth+1)"
            )
            page.locator(".money-summary").scroll_into_view_if_needed()
            shot("large-amounts")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            assert len(requests) == 3, requests
            # Existing-entry and edit drafts have separate owners through cancellation and saves.
            large_amounts = False
            forecast_mode = "normal"
            page.reload(wait_until="networkidle")
            entry = page.locator("#money-entry-fields")
            if entry.is_hidden():
                page.locator("#money-entry-action").press("Enter")
            draft_values = {
                "tx-payee": "independent new draft 草稿 " + label,
                "tx-cat": "new draft category",
                "tx-tags": "draft-tag",
                "tx-amt": "23.45",
            }
            for field, value in draft_values.items():
                page.locator("#" + field).fill(value)
            page.evaluate("window.ownedEntryNode = document.getElementById('money-entry-fields')")
            draft_choices = page.evaluate(
                "Object.fromEntries(['tx-date','tx-acct','tx-sign'].map(id=>[id,document.getElementById(id).dataset.value]))"
            )
            target_id = transaction["id"]
            edit_action = page.locator(f'[data-edit-txn="{target_id}"]')
            edit = page.locator(f'.txn-edit[data-id="{target_id}"]')

            def check_new_draft():
                assert page.evaluate(
                    "document.getElementById('money-entry-fields') === window.ownedEntryNode"
                )
                for field, value in draft_values.items():
                    expect(page.locator("#" + field)).to_have_value(value)
                assert (
                    page.evaluate(
                        "Object.fromEntries(['tx-date','tx-acct','tx-sign'].map(id=>[id,document.getElementById(id).dataset.value]))"
                    )
                    == draft_choices
                )

            def stored_target():
                response = api.get(base + "/api/money/transactions")
                assert response.ok
                return next(item for item in response.json() if item["id"] == target_id)

            original = stored_target()
            edit_action.press("Enter")
            expect(
                edit.get_by_role("heading", name="edit " + original["payee"], exact=True)
            ).to_be_visible()
            expect(edit.locator('[data-f="payee"]')).to_be_focused()
            expect(entry).to_be_hidden()
            expect(page.locator("#money-entry-action")).to_be_hidden()
            expect(page.locator(".money-txns .btn.primary:visible")).to_have_count(1)
            check_new_draft()
            edit.locator('[data-f="payee"]').fill("cancelled edit 草稿")
            shot("transaction-edit")
            edit.locator("[data-cancel-txn]").press("Enter")
            expect(edit).to_have_count(0)
            expect(edit_action).to_be_focused()
            expect(entry).to_be_visible()
            check_new_draft()
            assert stored_target() == original
            edit_mode = "reject"
            held_edits, edit_requests = [], []
            edit_pattern = "**/api/money/transactions/" + target_id

            def edit_response(route):
                target = urlparse(route.request.url)
                assert (target.scheme, target.netloc) == ("http", urlparse(base).netloc)
                assert route.request.method == "PATCH"
                edit_requests.append(route.request.post_data_json)
                if edit_mode == "reject":
                    route.fulfill(status=503, json={"detail": "owned edit save rejected"})
                elif edit_mode == "hold":
                    held_edits.append(route)
                else:
                    route.continue_()

            page.route(edit_pattern, edit_response)
            edit_action.press("Enter")
            edited_payee = "saved edit 草稿 " + label
            edit.locator('[data-f="payee"]').fill(edited_payee)
            edit.locator("[data-save-txn]").press("Enter")
            expect(page.get_by_text("save failed", exact=True).last).to_be_visible()
            expect(edit.locator('[data-f="payee"]')).to_have_value(edited_payee)
            expect(edit.locator("[data-save-txn]")).to_be_focused()
            expect(entry).to_be_hidden()
            check_new_draft()
            assert stored_target() == original
            shot("transaction-edit-rejected")
            edit_mode = "normal"
            edit.locator("[data-save-txn]").press("Enter")
            expect(edit).to_have_count(0)
            expect(edit_action).to_be_focused()
            expect(entry).to_be_visible()
            check_new_draft()
            changed = stored_target()
            assert changed["payee"] == edited_payee
            for field in ("id", "account_id", "amount", "date", "category", "tags"):
                assert changed[field] == original[field]
            shot("transaction-edit-saved")
            edit_action.press("Enter")
            final_payee = edited_payee + " final"
            edit.locator('[data-f="payee"]').fill(final_payee)
            edit_mode = "hold"
            edit.locator("[data-save-txn]").press("Enter")
            for _ in range(100):
                if held_edits:
                    break
                page.wait_for_timeout(20)
            assert len(held_edits) == 1
            page.locator("#txn-search").click()
            expect(page.locator("#txn-search")).to_be_focused()
            pending = held_edits.pop()
            result = pending.fetch(max_redirects=0)
            assert result.ok
            pending.fulfill(response=result)
            expect(edit).to_have_count(0)
            expect(page.locator("#txn-search")).to_be_focused()
            check_new_draft()
            assert stored_target()["payee"] == final_payee
            assert len(edit_requests) == 3
            for navigation in ("month", "filter"):
                before_navigation = stored_target()
                wanted = "retained " + navigation + " edit 草稿 " + label

                def leave_edit_list():
                    if navigation == "month":
                        page.locator("#money-next").press("Enter")
                        expect(page.locator("#txn-rows > .money-empty-sm")).to_have_text(
                            "no transactions this month"
                        )
                    else:
                        page.locator("#txn-search").fill("owned no match " + label)
                        expect(page.locator("#txn-rows > .money-empty-sm")).to_have_text(
                            "no matches"
                        )
                    expect(edit).to_be_visible()
                    expect(edit.locator("[data-edit-context]")).to_be_visible()
                    expect(edit.locator('[data-f="payee"]')).to_have_value(wanted)
                    assert page.evaluate(
                        "window.ownedInlineEdit === document.querySelector('.txn-edit')"
                    )
                    expect(entry).to_be_hidden()
                    expect(page.locator("#money-entry-action")).to_be_hidden()
                    expect(page.locator(".money-txns .btn.primary:visible")).to_have_count(1)
                    check_new_draft()

                def return_edit_list():
                    if navigation == "month":
                        page.locator("#money-prev").press("Enter")
                    else:
                        page.locator("#txn-search").fill("")

                edit_action.press("Enter")
                edit.locator('[data-f="payee"]').fill(wanted)
                page.evaluate("window.ownedInlineEdit = document.querySelector('.txn-edit')")
                leave_edit_list()
                shot("transaction-edit-" + navigation)
                return_edit_list()
                expect(edit.locator("[data-edit-context]")).to_be_hidden()
                expect(edit.locator('[data-f="payee"]')).to_have_value(wanted)
                leave_edit_list()
                prior_writes = len(edit_requests)
                edit.locator("[data-cancel-txn]").press("Enter")
                expect(edit).to_have_count(0)
                expect(page.locator("#txn-search")).to_be_focused()
                expect(entry).to_be_visible()
                check_new_draft()
                assert len(edit_requests) == prior_writes
                assert stored_target() == before_navigation
                return_edit_list()
                expect(edit_action).to_be_visible()
                edit_action.press("Enter")
                edit.locator('[data-f="payee"]').fill(wanted)
                page.evaluate("window.ownedInlineEdit = document.querySelector('.txn-edit')")
                leave_edit_list()
                edit_mode = "reject"
                edit.locator("[data-save-txn]").press("Enter")
                expect(page.get_by_text("save failed", exact=True).last).to_be_visible()
                expect(edit.locator("[data-save-txn]")).to_be_focused()
                expect(edit.locator('[data-f="payee"]')).to_have_value(wanted)
                check_new_draft()
                assert stored_target() == before_navigation
                shot("transaction-edit-" + navigation + "-rejected")
                edit_mode = "hold"
                edit.locator("[data-save-txn]").press("Enter")
                for _ in range(100):
                    if held_edits:
                        break
                    page.wait_for_timeout(20)
                assert len(held_edits) == 1
                page.locator("#txn-search").click()
                pending = held_edits.pop()
                result = pending.fetch(max_redirects=0)
                assert result.ok
                pending.fulfill(response=result)
                expect(edit).to_have_count(0)
                expect(page.locator("#txn-search")).to_be_focused()
                expect(entry).to_be_visible()
                check_new_draft()
                assert len(edit_requests) == prior_writes + 2
                assert edit_requests[-1] == edit_requests[-2]
                assert "amount" not in edit_requests[-1]
                assert "account_id" not in edit_requests[-1]
                changed = stored_target()
                assert changed["payee"] == wanted
                for field in (
                    "id",
                    "account_id",
                    "amount",
                    "date",
                    "category",
                    "tags",
                    "original_amount_text",
                    "original_currency_code",
                    "base_amount_text",
                    "base_currency_code",
                    "import_identity",
                ):
                    assert changed[field] == before_navigation[field]
                shot("transaction-edit-" + navigation + "-saved")
                return_edit_list()
                expect(edit_action).to_be_visible()
                final_payee = wanted
            page.unroute(edit_pattern, edit_response)
            page.reload(wait_until="networkidle")
            expect(edit_action).to_be_visible()
            assert stored_target()["payee"] == final_payee
            shot("transaction-edit-reload")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            assert not errors and not external, (errors, external)
            assert console == [
                "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
            ] * (5 if compact else 8), console
            rows.append(
                {
                    "profile": label,
                    "compact": compact,
                    "first_transaction": first,
                    "status": "passed",
                    "edit_recovery": "single labelled edit, same new draft node and exact fields, cancel without write and row focus, rejected save retained/retry, same record readback, same editor through month/filter with clear context, cancel/search focus, rejected save/retry/unchanged native and base records, newer search focus, reload",
                    "checks": "leading transaction action; optional amount filter clears without losing text query; late tag response ignored after range clear; month change clears tag; touch/keyboard; manage export and bank close/focus; no-account entry; exact saved expense, entry close/reopen/resize draft and focus preservation, held save respects newer focus, refused save/retry/no duplicate, all totals, held forecast recovery/newer focus and resize, large currency amounts, actual native zoom",
                }
            )
            (out / "scenarios.json").write_text(
                json.dumps([dict(r, scenario_id="finance.compact-ledger") for r in rows], indent=2)
            )
            with (out / "console.jsonl").open("a") as log:
                log.write(
                    json.dumps(
                        {
                            "profile": label,
                            "page_errors": errors,
                            "console_errors": console,
                            "expected": f"{5 if compact else 8} synthetic503 responses",
                        }
                    )
                    + "\n"
                )
            context.close()
    finally:
        browser.close()
