"""Open subscription history stays current through payment, retry and undo."""

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

base = f"http://127.0.0.1:{os.environ['PORT']}"
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in ["existing", "empty-after-undo", "refresh-failed", "late-history"]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                timezone_id="UTC",
                service_workers="block",
                reduced_motion="reduce",
            )
            blocked = []
            errors = []
            console = []
            writes = []

            def guard(route):
                if urlparse(route.request.url).netloc != urlparse(base).netloc:
                    blocked.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", guard)
            api = context.request
            page = context.new_page()
            page.set_default_timeout(7000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            page.on(
                "request",
                lambda r: (
                    writes.append(r.post_data_json)
                    if r.url.endswith("/payments/undo") and r.method == "POST"
                    else None
                ),
            )
            record = {
                "scenario_id": "subscriptions.recovery.paid-open-history-" + case,
                "feature_id": "finance.actual-ledger",
                "profile": str(width),
                "status": "failed",
            }
            results.append(record)
            sid = None
            try:
                assert api.post(base + "/api/setup/dismiss").ok
                response = api.post(
                    base + "/api/subscriptions",
                    data={
                        "name": f"local history {width} {case}",
                        "price": 10,
                        "currency": "CAD",
                        "cycle": "custom",
                        "cycle_days": 20,
                        "next_due": (date.today() - timedelta(days=40)).isoformat(),
                    },
                )
                assert response.ok, response.text()
                sid = response.json()["id"]
                url = base + f"/api/subscriptions/{sid}"
                assert api.post(url + "/paid").ok
                page.goto(base + "/?view=subs", wait_until="networkidle")
                row = page.locator(f'.sub-item[data-id="{sid}"]')
                held = []

                def hold_history(route):
                    if not held:
                        held.append((route, route.fetch()))
                    else:
                        route.continue_()

                if case == "late-history":
                    page.route(url + "/payments", hold_history)
                row.locator('[data-act="history"]').click()
                if case == "late-history":
                    deadline = time.monotonic() + 4
                    while not held and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert len(held) == 1
                else:
                    expect(row.locator(".sub-hist-row")).to_have_count(1)
                if case == "empty-after-undo":
                    row.locator('[data-act="undo-last"]').click()
                    expect(row.locator(".sub-hist-empty")).to_have_text("no payments yet")
                    assert api.get(url + "/payments").json() == []
                before = api.get(url + "/payments").json()
                history_failed = case == "refresh-failed"

                def fail_history(route):
                    if history_failed:
                        route.fulfill(
                            status=503, json={"detail": "owned history refresh unavailable"}
                        )
                    else:
                        route.continue_()

                if case == "refresh-failed":
                    page.route(url + "/payments", fail_history)
                paid = row.locator('[data-act="paid"]')
                paid.focus()
                page.keyboard.press("Enter")
                expect(row.locator('[data-act="toggle"]')).to_be_enabled()
                page.wait_for_function(
                    'document.querySelector("#subs-view").getAttribute("aria-busy") !== "true"'
                )
                if case == "refresh-failed":
                    expect(row.locator('[role="alert"]')).to_contain_text("could not load payments")
                    expect(row.locator('[data-act="undo-last"]')).to_have_count(0)
                    page.screenshot(path=str(out / f"{width}-{case}-retry.png"))
                    history_failed = False
                    row.locator("[data-history-retry]").press("Enter")
                if case == "late-history":
                    expect(row.locator(".sub-hist-row")).to_have_count(2)
                    held[0][0].fulfill(response=held[0][1])
                expect(row.locator(".sub-hist-row")).to_have_count(len(before) + 1)
                after = api.get(url + "/payments").json()
                expected = len(before) + 1
                assert len(after) == expected
                record.update(
                    before_payments=before,
                    after_payments=after,
                    visible_history_rows=row.locator(".sub-hist-row").count(),
                    empty_text=row.locator(".sub-hist-empty").all_text_contents(),
                )
                page.screenshot(path=str(out / f"{width}-{case}-after-paid.png"))
                if case != "empty-after-undo":
                    before_writes = len(writes)
                    row.locator('[data-act="undo-last"]').click()
                    expect(row.locator('[data-act="toggle"]')).to_be_enabled()
                    page.wait_for_timeout(150)
                    record["undo_request"] = writes[before_writes:]
                    record["after_undo"] = api.get(url + "/payments").json()
                    record["visible_alerts"] = row.locator('[role="alert"]').all_text_contents()
                    page.screenshot(path=str(out / f"{width}-{case}-undo.png"))
                assert record["visible_history_rows"] == expected, record
                assert not record["empty_text"]
                if case != "empty-after-undo":
                    assert len(record["after_undo"]) == len(before), record
                assert not errors and not blocked, (errors, blocked)
                assert not [m for m in console if not (case == "refresh-failed" and "503" in m)], (
                    console
                )
                record["status"] = "passed"
            except Exception as e:
                record["error"] = str(e)
            finally:
                record.update(
                    page_errors=errors, console=console, blocked_external_requests=blocked
                )
                if sid:
                    api.delete(base + f"/api/subscriptions/{sid}")
                context.close()
                (out / "scenarios.json").write_text(json.dumps({"scenarios": results}, indent=2))
    browser.close()
print({r["scenario_id"] + "@" + r["profile"]: r["status"] for r in results})
raise SystemExit(any(r["status"] != "passed" for r in results))
