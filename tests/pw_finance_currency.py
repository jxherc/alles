"""Explicit currencies and preserved native records on an owned, synthetic local ledger."""

import base64
import json
import os
import struct
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(width, theme, False) for width in (1440, 820, 390) for theme in ("dark", "light")]
profiles += [(1440, theme, True) for theme in ("dark", "light")]
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce" if theme == "dark" else "no-preference",
                has_touch=width == 390,
            )
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        dict(
                            manifest_version=3,
                            name="owned zoom check",
                            version="1.0",
                            permissions=["tabs"],
                            background={"service_worker": "zoom.js"},
                        )
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
            errors, console, blocked, writes = [], [], [], []
            currency_refused = True
            create_refused = True

            def guard(route):
                parsed = urlsplit(route.request.url)
                if (parsed.scheme, parsed.netloc) != ("http", urlsplit(base).netloc):
                    blocked.append(route.request.url)
                    return route.abort()
                if parsed.path == "/api/money/currencies" and currency_refused:
                    return route.fulfill(status=503, json={"detail": "owned choices unavailable"})
                if parsed.path == "/api/money/accounts" and route.request.method == "POST":
                    writes.append(route.request.post_data_json)
                    if create_refused:
                        return route.fulfill(status=503, json={"detail": "owned save refused"})
                return route.continue_()

            context.route("**/*", guard)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(6000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"profile": label, "status": "failed"}
            rows.append(row)

            def capture(name):
                png = base64.b64decode(
                    context.new_cdp_session(page).send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )["data"]
                )
                assert struct.unpack("!II", png[16:24]) == (width, 900)
                (out / f"{label}-{name}.png").write_bytes(png)

            def plans():
                toggle = page.locator('[data-money-section="plans"]')
                if toggle.get_attribute("aria-expanded") != "true":
                    toggle.tap() if width == 390 else toggle.press("Enter")

            def select_currency(code):
                control = page.get_by_role("combobox", name="currency", exact=True)
                control.tap() if width == 390 else control.press("Enter")
                option = page.get_by_role("option", name=code, exact=True)
                option.tap() if width == 390 else option.click()
                expect(control).to_be_focused()
                expect(control).to_have_attribute("data-value", code)

            def account_open():
                plans()
                page.locator("#money-add-acct").press("Enter")
                expect(page.locator("#af-name")).to_be_focused()

            try:
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                assert api.patch(
                    base + "/api/settings", data={"language": "en", "timezone": "UTC"}
                ).ok
                for account in api.get(base + "/api/money/accounts").json():
                    assert api.delete(base + "/api/money/accounts/" + account["id"]).ok
                page.goto(base + "/?view=money&m=2026-10", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                            base,
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                    row["native_zoom"] = {"factor": 2, "css_width": 720, "dpr": 2}
                expect(page.locator("#af-currency-error")).to_contain_text("could not be loaded")
                page.locator("#af-name").fill("owned dollars " + label)
                page.locator("#af-open").fill("0.00")
                page.locator("#af-add").press("Enter")
                assert not writes
                expect(page.locator("#af-currency")).to_be_focused()
                expect(page.locator("#af-name")).to_have_value("owned dollars " + label)
                bounds = page.locator("#af-currency").bounding_box()
                assert bounds and bounds["height"] >= 44 and bounds["width"] >= 44
                currency_refused = False
                page.locator("#af-currency-retry").press("Enter")
                expect(page.locator("#af-currency-retry")).to_be_hidden()
                expect(page.locator("#af-currency")).to_be_focused()
                expect(page.locator("#af-open")).to_have_value("0.00")
                page.locator("#af-add").press("Enter")
                expect(page.locator("#af-currency-error")).to_contain_text("choose a currency")
                assert not writes
                select_currency("CAD")
                expect(page.locator("#af-currency-error")).to_have_text("")
                page.locator("#af-add").press("Enter")
                expect(page.locator(".toast.error").last).to_be_visible()
                expect(page.locator("#af-name")).to_have_value("owned dollars " + label)
                expect(page.locator("#af-currency")).to_have_attribute("data-value", "CAD")
                create_refused = False
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/money/accounts"
                        and response.request.method == "POST"
                    )
                ) as created:
                    page.locator("#af-add").press("Enter")
                assert created.value.ok
                account = created.value.json()
                aid = account["id"]
                assert writes[0] == writes[1] and writes[0]["currency"] == "CAD"
                expect(page.locator(f'.money-acct[data-id="{aid}"]')).to_be_attached()
                plans()
                button = page.locator(f'[data-currency-acct="{aid}"]')
                bounds = button.bounding_box()
                assert bounds and bounds["height"] >= 44 and bounds["width"] >= 44
                button.press("Enter")
                dialog = page.get_by_role(
                    "dialog", name="currency for owned dollars " + label, exact=True
                )
                expect(dialog).to_be_visible()
                dialog.get_by_role("button", name="USD", exact=True).press("Enter")
                expect(page.locator(f'.money-acct[data-id="{aid}"] .ma-kind')).to_contain_text(
                    "USD"
                )
                expect(page.locator(f'[data-currency-acct="{aid}"]')).to_be_focused()
                saved = next(
                    item
                    for item in api.get(base + "/api/money/accounts").json()
                    if item["id"] == aid
                )
                assert (
                    saved["currency_code"] == "USD"
                    and saved["original_opening_text"] == account["original_opening_text"]
                )
                planned = api.post(
                    base + "/api/money/accounts",
                    data={"name": "owned planned CAD", "currency": "CAD", "opening": 0},
                ).json()
                scheduled = api.post(
                    base + "/api/money/recurring",
                    data={
                        "account_id": planned["id"],
                        "amount": -10,
                        "payee": "owned future CAD bill",
                        "next_date": "2099-10-01",
                        "cycle": "monthly",
                        "active": False,
                    },
                )
                assert scheduled.ok
                before_schedule = scheduled.json()
                denied = api.patch(
                    base + "/api/money/accounts/" + planned["id"], data={"currency": "USD"}
                )
                assert denied.status == 409
                assert (
                    next(
                        item
                        for item in api.get(base + "/api/money/recurring").json()
                        if item["id"] == before_schedule["id"]
                    )
                    == before_schedule
                )
                # Actual POST/readback owns the row, and metadata editing must not resend its amount.
                usd = api.post(
                    base + "/api/money/transactions",
                    data={
                        "account_id": aid,
                        "date": "2026-10-01",
                        "amount": -10,
                        "payee": "owned USD expense",
                    },
                ).json()
                cad = api.post(
                    base + "/api/money/accounts",
                    data={"name": "owned CAD", "currency": "CAD", "opening": 100},
                ).json()
                assert api.post(
                    base + "/api/money/transactions",
                    data={
                        "account_id": cad["id"],
                        "date": "2026-10-01",
                        "amount": -10,
                        "payee": "owned CAD expense",
                    },
                ).ok
                page.reload(wait_until="networkidle")
                expect(page.locator(f'.txn[data-id="{usd["id"]}"] .tx-amt')).to_have_text(
                    "−USD\u00a010.00"
                )
                expect(page.locator("#money-body")).to_contain_text("mixed currencies")
                summary = page.locator(".money-summary").inner_text()
                assert "USD" in summary and "CAD" in summary and "180.00" not in summary
                plans()
                expect(page.locator(f'[data-currency-acct="{aid}"]')).to_be_disabled()
                expect(page.locator(f'[data-currency-acct="{planned["id"]}"]')).to_be_disabled()
                expect(
                    page.locator('.recur-group[data-id="' + before_schedule["id"] + '"] .rc-amt')
                ).to_contain_text("−CAD\u00a010.00")
                expect(page.locator(f'.money-acct[data-id="{aid}"] .ma-bal')).to_have_text(
                    "USD\u00a0-10.00"
                )
                page.locator(f'[data-edit-txn="{usd["id"]}"]').press("Enter")
                page.locator('.txn-edit [data-f="payee"]').fill("owned edited USD expense")
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/money/transactions/" + usd["id"]
                        and response.request.method == "PATCH"
                    )
                ) as edited:
                    page.locator(f'[data-save-txn="{usd["id"]}"]').press("Enter")
                assert edited.value.ok
                assert (
                    "amount" not in edited.value.request.post_data_json
                    and "account_id" not in edited.value.request.post_data_json
                )
                preserved = next(
                    item
                    for item in api.get(base + "/api/money/transactions?month=2026-10").json()
                    if item["id"] == usd["id"]
                )
                for key in (
                    "amount",
                    "original_amount_text",
                    "original_currency_code",
                    "base_amount_text",
                    "base_currency_code",
                    "import_identity",
                ):
                    assert preserved[key] == usd[key], (key, preserved, usd)
                expect(page.locator(f'.txn[data-id="{usd["id"]}"] .tx-payee')).to_have_text(
                    "owned edited USD expense"
                )
                capture("mixed")
                legacy = api.post(
                    base + "/api/money/accounts",
                    data={"name": "owned unknown", "currency": "$", "opening": 100},
                ).json()
                unknown = api.post(
                    base + "/api/money/transactions",
                    data={
                        "account_id": legacy["id"],
                        "date": "2026-10-01",
                        "amount": -7,
                        "payee": "owned unknown expense",
                    },
                ).json()
                second_unknown = api.post(
                    base + "/api/money/accounts",
                    data={"name": "owned unknown destination", "currency": "$", "opening": 0},
                ).json()
                page.reload(wait_until="networkidle")
                expect(page.locator(f'.txn[data-id="{unknown["id"]}"] .tx-amt')).to_have_text(
                    "−currency not set\u00a07.00"
                )
                plans()
                expect(page.locator(f'.money-acct[data-id="{legacy["id"]}"] .ma-bal')).to_have_text(
                    "currency not set\u00a093.00"
                )
                expect(page.locator('[data-card="envelope"]')).to_contain_text(
                    "combined analytics need one known currency"
                )
                if not page.locator("#tx-payee").is_visible():
                    page.locator("#money-entry-action").press("Enter")
                page.locator("#tx-transfer-toggle").press("Enter")
                for field, name in (
                    ("tr-from", "owned unknown"),
                    ("tr-to", "owned unknown destination"),
                ):
                    page.locator("#" + field).click()
                    page.get_by_role("option", name=name, exact=True).click()
                page.locator("#tr-amt").fill("5.00")
                before_transfer = api.get(base + "/api/money/transactions").json()
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/money/transfer"
                        and response.request.method == "POST"
                    )
                ) as refused:
                    page.locator("#tr-do").press("Enter")
                assert refused.value.status == 409
                expect(page.locator(".toast.error").last).to_contain_text("same known currency")
                expect(page.locator("#tr-amt")).to_have_value("5.00")
                expect(page.locator("#tr-from")).to_have_attribute("data-value", legacy["id"])
                expect(page.locator("#tr-to")).to_have_attribute("data-value", second_unknown["id"])
                assert api.get(base + "/api/money/transactions").json() == before_transfer
                page.goto(base + "/?view=finance", wait_until="networkidle")
                overview = page.locator('#finance-tabs [data-group-section="overview"]')
                if overview.get_attribute("aria-selected") != "true":
                    overview.press("Enter")
                expect(page.locator("#finance-view")).to_contain_text("USD\u00a0-10.00")
                expect(page.locator("#finance-view")).to_contain_text("CAD\u00a090.00")
                expect(page.locator("#finance-view")).to_contain_text("currency not set\u00a093.00")
                capture("overview")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                assert not errors and not blocked, (errors, blocked)
                assert (
                    len(console) == 3
                    and sum("503" in item for item in console) == 2
                    and sum("409" in item for item in console) == 1
                ), console
                row.update(
                    status="passed",
                    create_payloads=writes,
                    preserved_transaction=preserved,
                    summary=api.get(base + "/api/money/summary?month=2026-10").json(),
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                row.update(errors=errors, console=console, blocked=blocked)
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")
                context.close()
    finally:
        browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
