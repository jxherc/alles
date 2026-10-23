"""Verify acknowledged edits and durable undo recovery on owned local data."""

import base64
import json
import os
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1]),
    str(Path(__file__).resolve().parents[1] / "tests"),
]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def owned_context(pw, browser, width, zoom, label):
    options = dict(
        viewport={"width": width, "height": 844 if width == 390 else 900},
        service_workers="block",
        reduced_motion="reduce",
        has_touch=width == 390,
    )
    if not zoom:
        return browser.new_context(**options)
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
    (extension / "zoom.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
    return pw.chromium.launch_persistent_context(
        profile / "browser",
        channel="chromium",
        headless=True,
        args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        **options,
    )


def native_zoom(ctx, page, base):
    worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    assert (
        worker.evaluate(
            "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
            base,
        )
        == 2
    )
    page.wait_for_function("innerWidth===720 && innerHeight===450 && devicePixelRatio===2")


def capture(ctx, page, path, width):
    png = base64.b64decode(
        ctx.new_cdp_session(page).send(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
        )["data"]
    )
    assert struct.unpack(">II", png[16:24]) == (width, 844 if width == 390 else 900)
    Path(path).write_bytes(png)


def close_sidebar(page):
    if (
        page.evaluate("matchMedia('(max-width:700px)').matches")
        and page.locator("#aide-sidebar").is_visible()
    ):
        page.keyboard.press("Escape")


base = "http://127.0.0.1:" + os.environ["PORT"]
origin = urlsplit(base)
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in [
            (w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")
        ] + [(1440, t, True) for t in ("light", "dark")]:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            ctx = owned_context(pw, browser, width, zoom, label)
            external = []
            errors = []
            console = []
            patches = []

            def boundary(route):
                u = urlsplit(route.request.url)
                if (u.scheme, u.netloc) != (origin.scheme, origin.netloc):
                    external.append(route.request.url)
                    return route.abort()
                if (
                    u.path.startswith("/api/money/transactions/")
                    and route.request.method == "PATCH"
                ):
                    patches.append(route.request.post_data_json)
                return route.continue_()

            ctx.route("**/*", boundary)
            ctx.route_web_socket("**/*", lambda ws: (external.append(ws.url), ws.close()))
            page = ctx.new_page()
            page.set_default_timeout(8000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            api = ctx.request
            row = {
                "profile": label,
                "native_zoom": zoom,
                "status": "failed",
                "purpose": "acknowledgment recovery; actual owned backend across eight profiles",
            }
            rows.append(row)
            try:
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.patch(
                    base + "/api/settings", data={"timezone": "UTC", "language": "en"}
                ).ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                for old in api.get(base + "/api/money/accounts").json():
                    assert api.delete(base + "/api/money/accounts/" + old["id"]).ok
                account = api.post(
                    base + "/api/money/accounts",
                    data={"name": "owned baseline " + theme, "currency": "USD", "opening": 100},
                ).json()
                txn = api.post(
                    base + "/api/money/transactions",
                    data={
                        "account_id": account["id"],
                        "date": datetime.now(UTC).date().isoformat(),
                        "amount": -10,
                        "payee": "owned edit baseline " + theme,
                    },
                ).json()
                page.goto(base + "/?view=money", wait_until="networkidle")
                if zoom:
                    native_zoom(ctx, page, base)
                page.locator('[data-edit-txn="' + txn["id"] + '"]').click()
                editor = page.locator('.txn-edit[data-id="' + txn["id"] + '"]')
                editor.locator('[data-f="amount"]').fill("20")

                def fail_refresh(route):
                    if route.request.method == "GET":
                        return route.fulfill(
                            status=503, json={"detail": "owned acknowledged edit refresh failure"}
                        )
                    return route.continue_()

                page.route("**/api/money/transactions?*", fail_refresh, times=1)
                with page.expect_response(
                    lambda r: urlsplit(r.url).path == "/api/money/transactions" and r.status == 503
                ):
                    editor.locator("[data-save-txn]").click()
                expect(editor).to_be_visible()
                first = api.get(base + "/api/money/transactions").json()
                assert next(t for t in first if t["id"] == txn["id"])["amount"] == -20
                editor.locator('[data-f="amount"]').fill("10")
                with page.expect_response(
                    lambda r: (
                        urlsplit(r.url).path == "/api/money/transactions/" + txn["id"]
                        and r.request.method == "PATCH"
                    )
                ):
                    editor.locator("[data-save-txn]").click()
                expect(editor).to_have_count(0)
                second = api.get(base + "/api/money/transactions").json()
                actual = next(t for t in second if t["id"] == txn["id"])
                row["edit"] = {
                    "first_readback": first,
                    "second_readback": second,
                    "patches": patches,
                    "intended_amount": -10,
                    "actual_amount": actual["amount"],
                    "fix_verified": actual["amount"] == -10 and patches[-1].get("amount") == -10,
                }
                assert row["edit"]["fix_verified"], row["edit"]
                capture(ctx, page, out / f"{label}-stale-edit-red.png", width)
                if page.locator("#money-entry-fields").is_hidden():
                    page.locator("#money-entry-action").click()
                expect(page.locator("#tx-payee")).to_be_visible()
                page.locator("#tx-payee").fill("owned receipt quota " + theme)
                page.locator("#tx-amt").fill("4.25")
                page.evaluate(
                    """() => {window.ownedReceiptQuota=true;const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(this===sessionStorage && key==='alles:finance-saved-transactions' && window.ownedReceiptQuota)throw new DOMException('synthetic receipt quota','QuotaExceededError');return original.call(this,key,value);};}"""
                )
                with page.expect_response(
                    lambda r: (
                        urlsplit(r.url).path == "/api/money/transactions"
                        and r.request.method == "POST"
                    )
                ) as response:
                    page.locator("#tx-add").click()
                saved = response.value.json()
                assert response.value.ok and saved["undo"], saved
                expect(page.locator('[data-undo-saved="' + saved["id"] + '"]')).to_be_visible()
                pointers = page.evaluate(
                    "({saved:sessionStorage.getItem('alles:finance-saved-transactions'),creation:sessionStorage.getItem('alles:finance-create:transaction')})"
                )
                expect(page.locator("#tx-payee")).to_have_value("owned receipt quota " + theme)
                expect(page.locator("#tx-amt")).to_have_value("4.25")
                expect(page.locator("#tx-save-status")).to_contain_text(
                    "transaction saved. could not keep undo for reload."
                )
                assert (
                    json.loads(pointers["creation"])["request_id"] == saved["undo"]["request_id"]
                ), pointers
                assert not any(
                    item["id"] == saved["id"] for item in json.loads(pointers["saved"] or "[]")
                )
                page.locator("#tx-save-status").evaluate(
                    "el=>el.scrollIntoView({block:'center',behavior:'instant'})"
                )
                box = page.locator("#tx-save-status").bounding_box()
                assert (
                    box
                    and box["y"] >= 0
                    and box["y"] + box["height"] <= page.evaluate("innerHeight")
                ), box
                capture(ctx, page, out / f"{label}-saved-storage-warning.png", width)
                page.reload(wait_until="networkidle")
                expect(page.locator("#tx-save-status")).to_contain_text(
                    "an earlier transaction may already be saved."
                )
                if page.locator("#money-entry-fields").is_hidden():
                    page.locator("#money-entry-action").click()
                page.locator("#tx-payee").fill("owned receipt quota " + theme)
                page.locator("#tx-amt").fill("4.25")
                with page.expect_response(
                    lambda r: (
                        urlsplit(r.url).path == "/api/money/transactions"
                        and r.request.method == "POST"
                    )
                ) as retried:
                    page.locator("#tx-add").click()
                again = retried.value.json()
                assert (
                    retried.value.ok
                    and again["id"] == saved["id"]
                    and again["undo"]["request_id"] == saved["undo"]["request_id"]
                ), again
                expect(page.locator("#tx-payee")).to_have_value("")
                after = page.evaluate(
                    "({saved:sessionStorage.getItem('alles:finance-saved-transactions'),creation:sessionStorage.getItem('alles:finance-create:transaction')})"
                )
                assert after["creation"] is None and any(
                    item["id"] == saved["id"] and item["request_id"] == saved["undo"]["request_id"]
                    for item in json.loads(after["saved"])
                ), after
                current = api.get(base + "/api/money/transactions").json()
                assert (
                    len([t for t in current if t["payee"] == "owned receipt quota " + theme]) == 1
                )
                page.reload(wait_until="networkidle")
                expect(page.locator('[data-undo-saved="' + saved["id"] + '"]')).to_be_visible()
                page.locator('[data-saved-txn="' + saved["id"] + '"]').evaluate(
                    "el=>el.scrollIntoView({block:'center',behavior:'instant'})"
                )
                capture(ctx, page, out / f"{label}-undo-recovered.png", width)
                page.locator('[data-undo-saved="' + saved["id"] + '"]').press("Enter")
                expect(page.locator('[data-saved-txn="' + saved["id"] + '"]')).to_contain_text(
                    "transaction undone."
                )
                remaining = api.get(base + "/api/money/transactions").json()
                assert not any(t["id"] == saved["id"] for t in remaining)
                row["receipt"] = {
                    "saved": saved,
                    "pointers_during_quota": pointers,
                    "replayed": again,
                    "pointers_recovered": after,
                    "saved_list": current,
                    "after_undo": remaining,
                    "fix_verified": True,
                    "recovery": "known save warning/exact input retained, original UUID durable, reload/re-enter same values returns original record, second reload preserves undo, actual undo verified",
                }
                if page.locator("#money-entry-fields").is_hidden():
                    page.locator("#money-entry-action").click()
                page.locator("#tx-payee").fill("owned direct undo quota " + theme)
                page.locator("#tx-amt").fill("4.25")
                page.evaluate(
                    """() => {window.ownedReceiptQuota=true;const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(this===sessionStorage && key==='alles:finance-saved-transactions' && window.ownedReceiptQuota)throw new DOMException('synthetic receipt quota','QuotaExceededError');return original.call(this,key,value);};}"""
                )
                with page.expect_response(
                    lambda r: (
                        urlsplit(r.url).path == "/api/money/transactions"
                        and r.request.method == "POST"
                    )
                ) as direct_response:
                    page.locator("#tx-add").click()
                direct = direct_response.value.json()
                assert direct_response.value.ok
                expect(page.locator("#tx-save-status")).to_contain_text(
                    "transaction saved. could not keep undo for reload."
                )
                direct_pointer = page.evaluate(
                    "JSON.parse(sessionStorage.getItem('alles:finance-create:transaction'))"
                )
                assert direct_pointer["request_id"] == direct["undo"]["request_id"]
                page.evaluate("window.ownedReceiptQuota=false")
                page.locator('[data-undo-saved="' + direct["id"] + '"]').press("Enter")
                expect(
                    page.locator('[data-saved-txn="' + direct["id"] + '"]').first
                ).to_contain_text("transaction undone.")
                assert (
                    page.evaluate("sessionStorage.getItem('alles:finance-create:transaction')")
                    is None
                )
                expect(page.locator("#tx-payee")).to_have_value("owned direct undo quota " + theme)
                with page.expect_response(
                    lambda r: (
                        urlsplit(r.url).path == "/api/money/transactions"
                        and r.request.method == "POST"
                    )
                ) as replacement_response:
                    page.locator("#tx-add").click()
                replacement = replacement_response.value.json()
                assert (
                    replacement_response.value.ok
                    and replacement["id"] != direct["id"]
                    and replacement["undo"]["request_id"] != direct["undo"]["request_id"]
                )
                expect(page.locator("#tx-payee")).to_have_value("")
                direct_readback = api.get(base + "/api/money/transactions").json()
                assert not any(t["id"] == direct["id"] for t in direct_readback) and any(
                    t["id"] == replacement["id"] for t in direct_readback
                )
                row["direct_undo"] = {
                    "saved": direct,
                    "pointer_during_quota": direct_pointer,
                    "new_transaction": replacement,
                    "readback": direct_readback,
                    "fix_verified": True,
                }
                assert (
                    not external
                    and not errors
                    and console
                    == [
                        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
                    ]
                ), (external, errors, console)
                row.update(status="passed", page_errors=errors, console=console, external=external)
                print(theme, "acknowledged edit and undo storage recovery verified", flush=True)
            finally:
                (out / "outcomes.json").write_text(json.dumps(rows, indent=2))
                ctx.close()
    finally:
        browser.close()
