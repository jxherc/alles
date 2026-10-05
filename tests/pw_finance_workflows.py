"""Local/manual Finance UI and SQLite workflows; no Actual or bank integration.

Only one save acknowledgment is replaced with a synthetic 503 after the real
backend commits. All inputs use rendered controls. Run via the owned browser runner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_finance_helpers import show_money_sections
from pw_settings_helpers import choose_settings_section

AMOUNT_ERROR = "enter a number using a decimal point, e.g. 1234.56"
INVALID_AMOUNTS = ("1,234.56", "12.34garbage", "Infinity")


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    finance = base + "/?view=finance"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []

    def checkpoint():
        (output / "scenarios.json").write_text(json.dumps(records, indent=2))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for profile in ("desktop", "phone"):
            theme = "light" if profile == "phone" else "dark"
            context = browser.new_context(
                viewport={"width": 390 if profile == "phone" else 1440, "height": 900},
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
                service_workers="block",
                reduced_motion="reduce",
                locale="en-US",
                timezone_id="UTC",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(15000)
            events = {
                "console": [],
                "page_errors": [],
                "failed_requests": [],
                "http_errors": [],
                "money_requests": [],
            }
            evidence = {
                "profile": profile,
                "theme": theme,
                "browser": browser.version,
                "scope": "local/manual ledger only; no Actual integration or live provider",
                "simulation": "one real committed create response replaced with synthetic HTTP 503",
                "screenshots": [],
            }
            expected_failures = []
            lost_next = False
            page.on(
                "console",
                lambda msg: events["console"].append({"type": msg.type, "text": msg.text}),
            )
            page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
            page.on(
                "requestfailed",
                lambda request: events["failed_requests"].append(
                    {"url": request.url, "error": request.failure}
                ),
            )
            page.on(
                "response",
                lambda response: (
                    events["http_errors"].append({"url": response.url, "status": response.status})
                    if response.status >= 400
                    else None
                ),
            )
            page.on(
                "request",
                lambda request: (
                    events["money_requests"].append(
                        {
                            "url": request.url,
                            "method": request.method,
                            "body": request.post_data_json,
                        }
                    )
                    if "/api/money/" in request.url
                    else None
                ),
            )

            def route_request(route):
                nonlocal lost_next
                parsed = urlsplit(route.request.url)
                if (parsed.scheme, parsed.netloc) != (urlsplit(base).scheme, urlsplit(base).netloc):
                    route.abort("blockedbyclient")
                elif (
                    lost_next
                    and parsed.path == "/api/money/transactions"
                    and route.request.method == "POST"
                ):
                    lost_next = False
                    response = route.fetch()
                    assert response.status == 200
                    evidence["committed_before_lost_ack"] = {
                        "request": route.request.post_data_json,
                        "response": response.json(),
                    }
                    expected_failures.append({"url": route.request.url, "status": 503})
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"simulated lost acknowledgment after committed local save"}',
                    )
                else:
                    route.continue_()

            context.route("**/*", route_request)
            context.route_web_socket("**/*", lambda ws: ws.close())

            def begin(name):
                record = {
                    "scenario_id": f"finance.{name}",
                    "feature_id": "finance.actual-ledger",
                    "profile": profile,
                    "status": "failed",
                    "detail": "workflow did not finish",
                    "scope": "local/manual only",
                    "trace": f"finance-{profile}-trace.zip",
                }
                records.append(record)
                checkpoint()
                return record

            def passed(record, detail):
                record.update(status="passed", detail=detail)
                checkpoint()

            def api(path):
                response = context.request.get(base + path)
                assert response.ok, response.text()
                return response.json()

            def shot(name, locator=None):
                if locator is not None:
                    locator.scroll_into_view_if_needed()
                path = f"finance-{profile}-{name}.png"
                page.screenshot(path=str(output / path), full_page=True)
                evidence["screenshots"].append(path)

            def open_money():
                expect(page.locator("#finance-view")).to_be_visible()
                tab = page.locator('#finance-tabs [data-group-section="money"]')
                # Reload already restored Money. Reclicking it starts another load
                # that can replace the rows during the persistence/geometry checks.
                if tab.get_attribute("aria-selected") != "true":
                    tab.click()
                show_money_sections(page)
                expect(tab).to_have_attribute("aria-selected", "true")
                expect(page.locator("#money-body")).to_be_visible()

            def choose_account(name):
                page.locator("#money-entry-action").click()
                page.locator("#tx-acct").click()
                page.get_by_role("option", name=name, exact=True).click()

            def invalid_amount(input_control, submit, value, message=None):
                input_control.fill(value)
                before = len(events["money_requests"])
                submit.click()
                expect(message or page.locator(".toast.error").last).to_contain_text(
                    "enter a statement balance using a decimal point" if message else AMOUNT_ERROR
                )
                expect(input_control).to_have_value(value)
                assert len(events["money_requests"]) == before, "invalid value reached the API"

            def create_transaction(payee, amount):
                page.locator("#money-entry-action").click()
                page.locator("#tx-payee").fill(payee)
                page.locator("#tx-cat").fill(category)
                page.locator("#tx-tags").fill("fixture,测试")
                page.locator("#tx-amt").fill(amount)
                with page.expect_response(
                    lambda r: (
                        urlsplit(r.url).path == "/api/money/transactions"
                        and r.request.method == "POST"
                    )
                ) as response:
                    page.locator("#tx-add").click()
                return response.value

            account_name = f"{profile} 家庭日常 checking account fixture"
            original_payee = f"{profile} 周末 grocery purchase — synthetic fixture"
            corrected_payee = f"{profile} 更正 grocery purchase — long synthetic fixture"
            category = "家庭日常 groceries and household fixture"
            try:
                page.goto(base + "/?view=today", wait_until="networkidle")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                page.locator("#today-settings").click()
                choose_settings_section(page, "themes")
                with page.expect_response(
                    lambda r: r.url.endswith("/api/appearance") and r.request.method == "PUT"
                ) as appearance:
                    page.locator(f'[data-theme-mode="{theme}"]').click()
                assert appearance.value.ok
                page.locator("#settings-modal-close").click()
                page.goto(finance, wait_until="networkidle")
                if theme == "light":
                    expect(page.locator("html")).to_have_attribute("data-theme", "light")
                else:
                    expect(page.locator("html")).not_to_have_attribute("data-theme", "light")
                open_money()
                validation = begin("local-amount-validation")
                expect(
                    page.locator("#af-name").or_(page.locator("#money-add-acct"))
                ).to_be_visible()
                if not page.locator("#af-name").is_visible():
                    page.get_by_role("button", name="+ account", exact=True).click()
                page.locator("#af-name").fill(account_name)
                for invalid in INVALID_AMOUNTS:
                    invalid_amount(page.locator("#af-open"), page.locator("#af-add"), invalid)
                page.locator("#af-open").fill("1234.56")
                for invalid in INVALID_AMOUNTS[:2]:
                    invalid_amount(page.locator("#af-low"), page.locator("#af-add"), invalid)
                page.locator("#af-low").fill("")
                assert not any(a["name"] == account_name for a in api("/api/money/accounts"))
                persistence = begin("local-create-edit-persistence")
                with page.expect_response(
                    lambda r: r.url.endswith("/api/money/accounts") and r.request.method == "POST"
                ) as created:
                    page.locator("#af-add").click()
                assert created.value.ok
                account = created.value.json()
                aid = account["id"]
                page.locator(f'.money-acct[data-id="{aid}"]').wait_for(state="attached")
                show_money_sections(page)
                expect(page.locator(f'.money-acct[data-id="{aid}"]')).to_be_visible()
                assert account["opening"] == 1234.56 and account["low_balance"] == 0
                choose_account(account_name)
                page.locator("#tx-payee").fill(original_payee)
                for invalid in INVALID_AMOUNTS:
                    invalid_amount(page.locator("#tx-amt"), page.locator("#tx-add"), invalid)
                assert not any(t["account_id"] == aid for t in api("/api/money/transactions"))
                created = create_transaction(original_payee, "12.34")
                assert created.ok
                txn = created.json()
                tid = txn["id"]
                row = page.locator(f'.txn[data-id="{tid}"]')
                expect(row.locator(".tx-payee")).to_have_text(original_payee)
                assert txn["amount"] == -12.34 and txn["original_amount_text"] == "-12.34"
                assert (
                    next(a for a in api("/api/money/accounts") if a["id"] == aid)["balance"]
                    == 1222.22
                )
                row.locator(".tx-edit").click()
                edit = page.locator(f'.txn-edit[data-id="{tid}"]')
                for invalid in INVALID_AMOUNTS:
                    invalid_amount(
                        edit.locator('[data-f="amount"]'), edit.locator("[data-save-txn]"), invalid
                    )
                assert (
                    next(t for t in api("/api/money/transactions") if t["id"] == tid)["amount"]
                    == -12.34
                )
                edit.locator('[data-f="amount"]').fill("56.78")
                edit.locator('[data-f="payee"]').fill(corrected_payee)
                # Real keyboard activation of the save control.
                edit.locator("[data-save-txn]").focus()
                page.keyboard.press("Enter")
                expect(row.locator(".tx-payee")).to_have_text(corrected_payee)
                row.locator(".tx-edit").click()
                edit.locator('[data-f="amount"]').fill("99.99")
                edit.locator("[data-cancel-txn]").click()
                expect(row.locator(".tx-edit")).to_be_visible()
                row.locator(".tx-clear").click()
                expect(row.locator(".tx-clear")).to_have_class("tx-clear on")
                page.reload(wait_until="networkidle")
                show_money_sections(page)
                open_money()
                expect(row.locator(".tx-payee")).to_have_text(corrected_payee)
                expect(row.locator(".tx-clear")).to_have_class("tx-clear on")
                saved = next(t for t in api("/api/money/transactions") if t["id"] == tid)
                assert (
                    saved["amount"] == -56.78
                    and saved["original_amount_text"] == "-56.78"
                    and saved["cleared"]
                )
                assert (
                    next(a for a in api("/api/money/accounts") if a["id"] == aid)["balance"]
                    == 1177.78
                )
                evidence["persisted_transaction"] = saved
                shot("edited-reloaded", row)
                passed(
                    persistence,
                    "UI account1234.56, expense12.34, edit56.78, cancel99.99, clear, reload; exact SQLite API amounts and balance",
                )
                reconciliation = begin("local-reconcile")
                page.locator(f'[data-rc-acct="{aid}"]').click()
                statement = page.locator(f"#rc-stmt-{aid}")
                reconcile_button = page.locator(f'[data-rc-run="{aid}"]')
                reconcile_output = page.locator(f"#rc-out-{aid}")
                for invalid in INVALID_AMOUNTS:
                    invalid_amount(statement, reconcile_button, invalid, reconcile_output)
                passed(
                    validation,
                    "grouped, garbage and non-finite values rejected visibly without API requests in create/edit/reconcile; grouped+garbage also reject low-balance input",
                )
                statement.fill("1177.78")
                reconcile_button.click()
                expect(reconcile_output).to_contain_text("reconciled")
                statement.fill("1177.79")
                reconcile_button.click()
                expect(reconcile_output).to_contain_text("off by $0.01")
                exact = api(f"/api/money/accounts/{aid}/reconcile?statement=1177.78")
                assert exact["reconciled"] and exact["difference"] == 0
                mismatch = api(f"/api/money/accounts/{aid}/reconcile?statement=1177.79")
                assert not mismatch["reconciled"] and mismatch["difference"] == 0.01
                shot("reconciled", reconcile_output)
                passed(
                    reconciliation,
                    "cleared exact balance matches; one-cent mismatch visible and returned by real API",
                )
                retry = begin("local-retry-once")
                choose_account(account_name)
                lost_next = True
                retry_payee = f"{profile} retry after lost acknowledgment fixture"
                response = create_transaction(retry_payee, "23.45")
                assert response.status == 503
                expect(page.locator(".toast.error").last).to_have_text("couldn't add transaction")
                expect(page.locator("#tx-amt")).to_have_value("23.45")
                assert (
                    len([t for t in api("/api/money/transactions") if t["payee"] == retry_payee])
                    == 1
                )
                shot("lost-save-acknowledgment", page.locator("#tx-add"))
                # Retry exact retained form through the actual pointer, never replay from test API.
                with page.expect_response(
                    lambda r: (
                        urlsplit(r.url).path == "/api/money/transactions"
                        and r.request.method == "POST"
                    )
                ) as replay:
                    page.locator("#tx-add").click()
                assert replay.value.ok
                expect(page.locator("#tx-amt")).to_have_value("")
                assert replay.value.json() == evidence["committed_before_lost_ack"]["response"]
                creates = [
                    e["body"]
                    for e in events["money_requests"]
                    if e["method"] == "POST"
                    and e["url"].endswith("/transactions")
                    and e["body"]["payee"] == retry_payee
                ]
                assert len(creates) == 2 and creates[0] == creates[1] and creates[0]["request_id"]
                page.reload(wait_until="networkidle")
                show_money_sections(page)
                open_money()
                retried = [t for t in api("/api/money/transactions") if t["payee"] == retry_payee]
                assert len(retried) == 1 and retried[0]["amount"] == -23.45
                assert (
                    next(a for a in api("/api/money/accounts") if a["id"] == aid)["balance"]
                    == 1154.33
                )
                evidence["retry_requests"] = creates
                evidence["retry_persisted_rows"] = retried
                passed(
                    retry,
                    "real save committed; only response replaced503; same request_id UI retry returns original row, one23.45 debit after reload",
                )
                if profile == "phone":
                    readability = begin("local-phone-readability")
                    row.scroll_into_view_if_needed()
                    geometry = row.evaluate("""row => Object.fromEntries(['tx-payee','tx-cat','tx-acct','tx-date','tx-amt','tx-actions','tx-del'].map(cls => {
                        const el=row.querySelector('.'+cls), r=el.getBoundingClientRect();
                        return [cls,{x:r.x,right:r.right,width:r.width,height:r.height,text:el.textContent}];
                    }))""")
                    evidence["phone_row_geometry"] = geometry
                    for key, box in geometry.items():
                        assert (
                            box["width"] >= 30
                            and box["height"] > 0
                            and box["x"] >= 0
                            and box["right"] <= 390
                        ), (key, box)
                    expect(row.locator(".tx-payee")).to_have_text(corrected_payee)
                    expect(row.locator(".tx-cat")).to_have_text(category)
                    expect(row.locator(".tx-acct")).to_have_text(account_name)
                    for control in row.locator("button").all():
                        control.click(trial=True)
                        box = control.bounding_box()
                        assert box and box["width"] >= 44 and box["height"] >= 44, box
                    # Real action and keyboard focus, beyond geometry/actionability checks.
                    row.locator(".tx-edit").click()
                    edit.locator("[data-cancel-txn]").click()
                    row.locator(".tx-edit").focus()
                    page.keyboard.press("Tab")
                    expect(row.locator(".tx-clear")).to_be_focused()
                    shot("populated-row", row)
                    page.locator("#txn-range-toggle").click()
                    page.locator("#txn-max").click()
                    filter_box = page.locator("#txn-max").bounding_box()
                    assert (
                        filter_box
                        and filter_box["x"] >= 0
                        and filter_box["x"] + filter_box["width"] <= 390
                    )
                    assert page.locator("#money-body").evaluate(
                        "e => e.scrollWidth <= e.clientWidth"
                    )
                    passed(
                        readability,
                        "390px light mixed-language row identity visible; actions44px/reachable, edit/cancel and keyboard focus work; filter and panel fit",
                    )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                assert not events["page_errors"] and not events["failed_requests"], events
                assert events["http_errors"] == expected_failures, events
                errors = [e for e in events["console"] if e["type"] == "error"]
                assert (
                    len(errors) == 1
                    and "503" in errors[0]["text"]
                    and "Failed to load resource" in errors[0]["text"]
                ), events
            except Exception as exc:
                evidence["error"] = str(exc)
                shot("failure")
                raise
            finally:
                (output / f"finance-{profile}-events.json").write_text(json.dumps(events, indent=2))
                (output / f"finance-{profile}-evidence.json").write_text(
                    json.dumps(evidence, indent=2)
                )
                checkpoint()
                context.tracing.stop(path=str(output / f"finance-{profile}-trace.zip"))
                context.close()
        browser.close()
    print(json.dumps({"status": "passed", "scenarios": records}))


if __name__ == "__main__":
    run()
