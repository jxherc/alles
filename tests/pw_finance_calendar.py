"""Configured Finance dates with real local saves, history and custom picker input."""

import base64
import json
import os
import struct
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [
    (w, t, False, "2026-11-01T02:00:00+00:00") for w in (1440, 820, 390) for t in ("dark", "light")
]
profiles += [(1440, t, True, "2026-11-01T02:00:00+00:00") for t in ("dark", "light")]
profiles += [(390, t, False, "2027-01-01T02:00:00+00:00") for t in ("dark", "light")]
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom, timestamp in profiles:
            instant = datetime.fromisoformat(timestamp).astimezone(UTC)
            configured = "UTC" if theme == "dark" else "America/Toronto"
            browser_zone = "America/Toronto" if theme == "dark" else "Asia/Tokyo"
            language = "en" if theme == "dark" else "ar"
            expected_day = instant.astimezone(ZoneInfo(configured)).date().isoformat()
            expected_month = expected_day[:7]
            label = f"{width}-{theme}-{instant.year}" + ("-native200" if zoom else "")
            options = dict(
                timezone_id=browser_zone,
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
            errors, blocked = [], []

            def guard(route):
                parsed = urlsplit(route.request.url)
                if (parsed.scheme, parsed.netloc) != ("http", urlsplit(base).netloc):
                    blocked.append(route.request.url)
                    return route.abort()
                return route.continue_()

            context.route("**/*", guard)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(6000)
            page.clock.set_fixed_time(instant)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            row = {
                "profile": label,
                "status": "failed",
                "configured_zone": configured,
                "browser_zone": browser_zone,
                "instant": timestamp,
                "language": language,
            }
            rows.append(row)

            def capture(name):
                shot = context.new_cdp_session(page).send(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                png = base64.b64decode(shot["data"])
                assert struct.unpack("!II", png[16:24]) == (width, 900)
                (out / f"{label}-{name}.png").write_bytes(png)

            def open_entry():
                if not page.locator("#tx-payee").is_visible():
                    page.locator("#money-entry-action").click()
                expect(page.locator("#tx-payee")).to_be_visible()

            try:
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                assert api.patch(
                    base + "/api/settings", data={"timezone": configured, "language": language}
                ).ok
                if not api.get(base + "/api/money/accounts").json():
                    assert api.post(
                        base + "/api/money/accounts",
                        data={"name": "owned calendar account", "currency": "CAD", "opening": 1000},
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
                            "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                            base,
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                    row["native_zoom"] = {"factor": 2, "css_width": 720, "dpr": 2}
                open_entry()
                expect(page.locator("#tx-date")).to_have_attribute("data-value", expected_day)
                assert parse_qs(urlsplit(page.url).query)["m"] == [expected_month], page.url
                row.update(
                    default_date=page.locator("#tx-date").get_attribute("data-value"),
                    month=expected_month,
                )
                capture("default")
                page.locator("#tx-payee").fill("owned default " + label)
                page.locator("#tx-amt").fill("12.34")
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/money/transactions"
                        and response.request.method == "POST"
                    )
                ) as posted:
                    page.locator("#tx-add").press("Enter")
                assert posted.value.ok
                saved = posted.value.json()
                assert (
                    saved["date"] == expected_day
                    and posted.value.request.post_data_json["date"] == expected_day
                )
                default_id = saved["id"]
                expect(page.locator(f'.txn[data-id="{default_id}"]')).to_be_visible()
                page.reload(wait_until="networkidle")
                expect(page.locator(f'.txn[data-id="{default_id}"]')).to_be_visible()
                readback = api.get(base + "/api/money/transactions?month=" + expected_month).json()
                assert (
                    next(item for item in readback if item["id"] == default_id)["date"]
                    == expected_day
                )
                open_entry()
                date = page.locator("#tx-date")
                date.focus()
                date.press("Enter")
                picker = page.locator(".date-panel")
                expect(picker).to_be_visible()
                picker.locator('[data-nav="-1"]').click()
                chosen = picker.locator('.dp-day[data-d="20"]')
                chosen.tap() if width == 390 else chosen.click()
                expect(picker).to_have_count(0)
                expect(date).to_be_focused()
                historical = date.get_attribute("data-value")
                assert historical and historical != expected_day
                historical_month = historical[:7]
                page.locator("#tx-payee").fill("owned historical " + label)
                page.locator("#tx-amt").fill("5.67")
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/money/transactions"
                        and response.request.method == "POST"
                    )
                ) as posted:
                    page.locator("#tx-add").press("Enter")
                assert posted.value.ok
                history_id = posted.value.json()["id"]
                assert posted.value.json()["date"] == historical
                assert posted.value.request.post_data_json["date"] == historical
                page.goto(base + "/?view=money&m=" + historical_month, wait_until="networkidle")
                history_row = page.locator(f'.txn[data-id="{history_id}"]')
                expect(history_row).to_be_visible()
                assert parse_qs(urlsplit(page.url).query)["m"] == [historical_month]
                history_row.locator(".tx-edit").click()
                editor = page.locator(f'.txn-edit[data-id="{history_id}"]')
                expect(editor.locator('[data-f="date"]')).to_have_attribute(
                    "data-value", historical
                )
                editor.locator('[data-f="payee"]').fill("owned edited 中文 " + label)
                endpoint = base + "/api/money/transactions/" + history_id
                with page.expect_response(
                    lambda response: response.url == endpoint and response.request.method == "PATCH"
                ) as edited:
                    editor.locator("[data-save-txn]").press("Enter")
                assert edited.value.ok and edited.value.request.post_data_json["date"] == historical
                page.reload(wait_until="networkidle")
                expect(history_row).to_contain_text("owned edited 中文 " + label)
                assert parse_qs(urlsplit(page.url).query)["m"] == [historical_month]
                stored = api.get(base + "/api/money/transactions?month=" + historical_month).json()
                assert (
                    next(item for item in stored if item["id"] == history_id)["date"] == historical
                )
                open_entry()
                expect(page.locator("#tx-date")).to_have_attribute("data-value", expected_day)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                capture("history-preserved")
                row.update(
                    default_id=default_id,
                    historical_id=history_id,
                    historical_day=historical,
                    preserved_selected_month=historical_month,
                )
                assert not errors and not blocked, (errors, blocked)
                row["status"] = "passed"
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                row.update(errors=errors, blocked=blocked)
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")
                context.close()
    finally:
        browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
