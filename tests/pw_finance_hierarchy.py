"""Verify the compact ledger, preserved entry drafts and secondary-total recovery."""

import base64
import json
import os
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
            forecast_mode = "normal"
            held = []
            large_amounts = False

            def route(r):
                url = urlparse(r.request.url)
                if url.netloc != urlparse(base).netloc:
                    external.append(r.request.url)
                    return r.abort()
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
                assert api.post(
                    base + "/api/money/accounts", data={"name": "garden budget", "opening": 200}
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
            if compact:
                expect(entry).to_be_hidden()
                expect(totals).to_have_attribute("aria-expanded", "false")
                expect(page.locator("[data-secondary-total]:visible")).to_have_count(0)
            else:
                expect(entry).to_be_visible()
                expect(totals).to_be_hidden()
                expect(page.locator(".ms-card:visible")).to_have_count(5)
            action.press("Enter")
            expect(page.locator("#tx-payee")).to_be_focused()
            payee = "garden supplies " + label + " 中文"
            page.locator("#tx-payee").fill(payee)
            page.locator("#tx-cat").fill("garden")
            page.locator("#tx-amt").fill("18.75")
            if compact:
                page.locator("#money-entry-close").press("Enter")
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
                    expect(page.locator("#money-entry-close")).to_be_visible()
                    page.locator("#money-entry-close").focus()
                    page.set_viewport_size({"width": 1440, "height": 844})
                    expect(page.locator("#money-entry-close")).to_be_hidden()
                    expect(action).to_be_focused()
                    page.set_viewport_size({"width": width, "height": 844})
                    action.press("Enter")
                    expect(page.locator("#tx-payee")).to_have_value(payee)
            before = api.get(base + "/api/money/transactions").json()
            reject = True
            page.locator("#tx-add").press("Enter")
            expect(page.locator(".toast.error").last).to_contain_text("couldn't add transaction")
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
                expect(row.locator(".tx-edit")).to_be_focused()
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
                page.locator("#money-entry-close").press("Enter")
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
            assert not errors and not external, (errors, external)
            assert console == [
                "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
            ] * (2 if compact else 5), console
            rows.append(
                {
                    "profile": label,
                    "compact": compact,
                    "first_transaction": first,
                    "status": "passed",
                    "checks": "exact saved expense, entry close/reopen/resize draft and focus preservation, held save respects newer focus, refused save/retry/no duplicate, all totals, held forecast recovery/newer focus and resize, large currency amounts, actual native zoom",
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
                            "expected": f"{2 if compact else 5} synthetic503 responses",
                        }
                    )
                    + "\n"
                )
            context.close()
    finally:
        browser.close()
