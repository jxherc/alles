"""Lost Health create responses recover one real reading, including corrections and cancellation."""

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    scenarios = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in [
                "retry",
                "conflict",
                "cancel",
                "rejected",
                "rejected-after-lost",
                "deleted-conflict",
                "deleted-after-retry",
                "deleted-after-open",
                "abandoned-lookup",
            ]:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    timezone_id="UTC",
                    reduced_motion="reduce",
                    service_workers="block",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page = context.new_page()
                errors, console, posts = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console", lambda msg: console.append(msg.text) if msg.type == "error" else None
                )
                page.on(
                    "request",
                    lambda request: (
                        posts.append(request.post_data_json)
                        if request.url == base + "/api/health" and request.method == "POST"
                        else None
                    ),
                )
                note = f"receipt {case} {width}"
                replacement = None
                result = {
                    "scenario_id": "health.create." + case,
                    "feature_id": "health.logs-and-habits",
                    "profile": "desktop" if width == 1440 else "phone",
                    "status": "failed",
                }
                scenarios.append(result)

                def rows():
                    return [
                        row
                        for row in context.request.get(base + "/api/health").json()["entries"]
                        if row["note"] == note
                    ]

                def fail(route):
                    if route.request.method != "POST":
                        route.continue_()
                        return
                    if case != "rejected":
                        response = route.fetch()
                        assert response.ok, response.text()
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic unavailable"}',
                    )

                def open_form():
                    page.locator("#health-add-toggle").click()
                    page.locator("#health-value").fill("74.25")
                    page.locator("#health-date").fill("2026-10-01")
                    page.locator("#health-note").fill(note)

                def replace_reading():
                    original_id = rows()[0]["id"]
                    assert context.request.delete(base + f"/api/health/{original_id}").ok
                    response = context.request.post(
                        base + "/api/health",
                        data={
                            "kind": "sleep",
                            "value": 8,
                            "date": "2026-10-01",
                            "note": note + " replacement",
                        },
                    )
                    assert response.ok, response.text()
                    item = response.json()
                    assert item["id"] == original_id, "fixture did not exercise SQLite ID reuse"
                    return item

                try:
                    context.request.post(base + "/api/setup/dismiss")
                    page.goto(base + "/?view=health-log", wait_until="networkidle")
                    open_form()
                    page.route(base + "/api/health", fail)
                    page.locator("#health-create").press("Enter")
                    expect(page.locator("#health-entry-error")).to_contain_text("save failed (503)")
                    expect(page.locator("#health-value")).to_have_value("74.25")
                    expect(page.locator("#health-create")).to_be_focused()
                    assert len(rows()) == (0 if case == "rejected" else 1)
                    assert posts[0].get("request_id"), posts
                    page.unroute(base + "/api/health", fail)
                    if case == "rejected-after-lost":

                        def reject_retry(route):
                            if route.request.method == "POST":
                                route.fulfill(
                                    status=400,
                                    content_type="application/json",
                                    body='{"detail":"synthetic rejected retry"}',
                                )
                            else:
                                route.continue_()

                        page.route(base + "/api/health", reject_retry)
                        page.locator("#health-create").press("Enter")
                        expect(page.locator("#health-entry-error")).to_contain_text(
                            "synthetic rejected retry"
                        )
                        expect(page.locator("#health-value")).to_have_value("74.25")
                        page.unroute(base + "/api/health", reject_retry)
                    if case in {"conflict", "abandoned-lookup"} or case.startswith("deleted-"):
                        page.locator("#health-value").fill("72.125")
                        page.locator("#health-create").press("Enter")
                        expect(page.locator("#health-entry-error")).to_contain_text(
                            "already saved with different values"
                        )
                        expect(page.locator("#health-value")).to_have_value("72.125")
                        assert len(rows()) == 1 and rows()[0]["value"] == 74.25
                        assert posts[0]["request_id"] == posts[1]["request_id"]
                        page.screenshot(path=str(output / f"conflict-{width}.png"), full_page=True)
                        open_saved = page.locator("#health-open-saved")
                        box = open_saved.bounding_box()
                        assert box and box["width"] >= 44 and box["height"] >= 44, box
                        if case == "abandoned-lookup":
                            held = []
                            pattern = base + "/api/health/requests/**"
                            page.route(pattern, lambda route: held.append(route))
                            open_saved.click()
                            expect(open_saved).to_be_disabled()
                            expect(page.locator("#health-create")).to_be_disabled()
                            page.locator("#health-cancel").click()
                            page.locator(".dialog-overlay [data-dialog-confirm]").click()
                            expect(page.locator("#health-entry-form")).to_have_count(0)
                            open_form()
                            expect(page.locator("#health-create")).to_be_enabled()
                            page.locator("#health-create").press("Enter")
                            expect(page.locator("#health-entry-form")).to_have_count(0)
                            assert len(rows()) == 2
                            assert len(held) == 1
                            held[0].fulfill(response=held[0].fetch())
                            page.unroute(pattern)
                            page.wait_for_load_state("networkidle")
                            expect(page.locator("#health-entry-form")).to_have_count(0)
                            expect(page.locator(".dialog-overlay")).to_have_count(0)
                        elif case in {"deleted-conflict", "deleted-after-retry"}:
                            replacement = replace_reading()
                            if case == "deleted-after-retry":
                                page.locator("#health-create").press("Enter")
                            else:
                                open_saved.click()
                                page.wait_for_function(
                                    "!!document.querySelector('.dialog-overlay') || document.querySelector('#health-entry-error')?.textContent.includes('deleted')"
                                )
                                if page.locator(".dialog-overlay").is_visible():
                                    page.locator(".dialog-overlay [data-dialog-confirm]").click()
                            expect(page.locator("#health-entry-error")).to_contain_text("deleted")
                            expect(open_saved).to_have_count(0)
                            expect(page.locator("#health-value")).to_have_value("72.125")
                        else:
                            open_saved.focus()
                            page.keyboard.press("Enter")
                            page.locator(".dialog-overlay [data-dialog-cancel]").click()
                            expect(page.locator("#health-value")).to_have_value("72.125")
                            page.locator("#health-open-saved").click()
                            page.locator(".dialog-overlay [data-dialog-confirm]").click()
                            expect(page.locator("#health-value")).to_have_value("74.25")
                            if case == "deleted-after-open":
                                replacement = replace_reading()
                            page.locator("#health-value").fill("72.125")
                            page.locator("#health-create").press("Enter")
                            if case == "deleted-after-open":
                                expect(page.locator("#health-entry-error")).to_contain_text(
                                    "deleted"
                                )
                            else:
                                expect(page.locator("#health-entry-form")).to_have_count(0)
                                assert len(rows()) == 1 and rows()[0]["value"] == 72.125
                    elif case in {"cancel", "rejected-after-lost"}:
                        page.locator("#health-cancel").click()
                        expect(page.locator(".dialog-card")).to_contain_text("may already be saved")
                        page.locator(".dialog-overlay [data-dialog-cancel]").click()
                        expect(page.locator("#health-value")).to_have_value("74.25")
                        page.locator("#health-cancel").click()
                        page.locator(".dialog-overlay [data-dialog-confirm]").click()
                        expect(page.locator("#health-entry-form")).to_have_count(0)
                        expect(
                            page.locator(f'.health-row[data-id="{rows()[0]["id"]}"]')
                        ).to_be_visible()
                    else:
                        if case == "rejected":
                            page.locator("#health-value").fill("72.125")
                        page.locator("#health-create").press("Enter")
                        expect(page.locator("#health-entry-form")).to_have_count(0)
                        assert len(rows()) == 1
                        assert rows()[0]["value"] == (72.125 if case == "rejected" else 74.25)
                        assert posts[0]["request_id"] == posts[1]["request_id"]
                    page.reload(wait_until="networkidle")
                    if replacement:
                        assert not rows()
                        current = next(
                            row
                            for row in context.request.get(base + "/api/health").json()["entries"]
                            if row["id"] == replacement["id"]
                        )
                        assert current["kind"] == "sleep" and current["value"] == 8, current
                        expect(
                            page.locator(f'.health-row[data-id="{current["id"]}"]')
                        ).to_be_visible()
                    else:
                        assert len(rows()) == (2 if case == "abandoned-lookup" else 1)
                        expect(
                            page.locator(f'.health-row[data-id="{rows()[0]["id"]}"]')
                        ).to_be_visible()
                    if case == "retry":
                        open_form()
                        page.locator("#health-create").press("Enter")
                        expect(page.locator("#health-entry-form")).to_have_count(0)
                        assert len(rows()) == 2, "a deliberately repeated reading was collapsed"
                        assert posts[-1]["request_id"] != posts[0]["request_id"]
                        page.reload(wait_until="networkidle")
                        assert len(rows()) == 2
                    assert not errors, errors
                    statuses = (
                        ["503", "409", "410"]
                        if case.startswith("deleted-")
                        else ["503", "409"]
                        if case in {"conflict", "abandoned-lookup"}
                        else ["503", "400"]
                        if case == "rejected-after-lost"
                        else ["503"]
                    )
                    assert len(console) == len(statuses) and all(
                        status in message for status, message in zip(statuses, console)
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "horizontal overflow"
                    )
                    result["status"] = "passed"
                except Exception as error:
                    result["error"] = str(error)
                finally:
                    page.screenshot(path=str(output / f"{case}-{width}-final.png"), full_page=True)
                    for row in rows():
                        context.request.delete(base + f"/api/health/{row['id']}")
                    if replacement:
                        context.request.delete(base + f"/api/health/{replacement['id']}")
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2))
        browser.close()
    print(json.dumps(scenarios, indent=2))
    raise SystemExit(any(row["status"] != "passed" for row in scenarios))


if __name__ == "__main__":
    run()
