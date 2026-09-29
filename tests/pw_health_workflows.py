"""Health entry correction and recovery through real UI and local SQLite.

Only the explicit failed-save response is simulated. Run through the owned runner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for profile in ("desktop", "phone"):
            context = browser.new_context(
                viewport={"width": 1440 if profile == "desktop" else 390, "height": 900},
                service_workers="block",
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
                reduced_motion="reduce",
                locale="en-US",
                timezone_id="UTC",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(15000)
            events = {"console": [], "page_errors": [], "failed_requests": [], "http_errors": []}
            expected_failures = []
            page.on(
                "console",
                lambda msg: events["console"].append({"type": msg.type, "text": msg.text}),
            )
            page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
            page.on(
                "requestfailed",
                lambda request: events["failed_requests"].append(
                    {"url": request.url, "failure": request.failure}
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
            current = None

            def begin(name):
                nonlocal current
                current = {
                    "scenario_id": name,
                    "feature_id": "health.logs-and-habits",
                    "profile": profile,
                    "status": "failed",
                    "detail": "workflow did not finish",
                }
                records.append(current)

            def passed():
                current.update(
                    status="passed", detail="real local persistence and visible UI assertions"
                )

            def saved(note):
                return [
                    e
                    for e in context.request.get(base + "/api/health").json()["entries"]
                    if e["note"] == note
                ]

            note = f"health exact value 中文 {profile}"
            try:
                page.goto(base + "/?view=today", wait_until="networkidle")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                if profile == "phone":
                    page.locator("#today-settings").click()
                    page.locator('.s-nav-item[data-pane="themes"]').click()
                    with page.expect_response(
                        lambda response: (
                            response.url.endswith("/api/appearance")
                            and response.request.method == "PUT"
                        )
                    ) as appearance:
                        page.locator('[data-theme-mode="light"]').click()
                    assert appearance.value.ok
                    page.locator("#settings-modal-close").click()
                    page.goto(base + "/?view=health-log", wait_until="networkidle")
                    expect(page.locator("html")).to_have_attribute("data-theme", "light")
                page.goto(base + "/?view=health-log", wait_until="networkidle")
                begin("health.entry-validation")
                page.locator("#health-add-toggle").click()
                expect(page.locator("#health-value")).to_be_focused()
                page.get_by_label("value", exact=True).fill("74.25junk")
                page.get_by_label("note (optional)", exact=True).fill(note)
                page.get_by_role("button", name="add", exact=True).click()
                expect(page.locator("#health-entry-error")).to_contain_text(
                    "complete, finite number"
                )
                assert not saved(note)
                page.get_by_label("value", exact=True).fill("74.25")
                page.get_by_label("date", exact=True).fill("2026-02-30")
                page.get_by_role("button", name="add", exact=True).click()
                expect(page.locator("#health-entry-error")).to_contain_text("valid date")
                assert not saved(note)
                page.get_by_label("date", exact=True).fill("2026-09-25")
                passed()
                begin("health.entry-draft-retention")
                page.get_by_role("radio", name="7d", exact=True).click()
                expect(page.locator("#health-value")).to_have_value("74.25")
                expect(page.locator("#health-note")).to_have_value(note)
                expect(page.locator("#health-date")).to_have_value("2026-09-25")
                page.get_by_role("radio", name="30d", exact=True).click()
                expect(page.locator("#health-note")).to_have_value(note)
                passed()
                begin("health.create-edit-persistence")
                held = []

                def hold_create(route):
                    if route.request.method == "POST":
                        held.append(route)
                    else:
                        route.continue_()

                page.route(base + "/api/health", hold_create)
                page.locator("#health-value").press("Enter")
                expect(page.locator("#health-create")).to_have_text("saving…")
                expect(page.locator("#health-value")).to_be_disabled()
                page.keyboard.press("Enter")
                assert len(held) == 1, "repeated Enter submitted twice"
                held[0].continue_()
                expect(page.locator("#health-entry-form")).to_have_count(0)
                page.unroute(base + "/api/health", hold_create)
                assert len(saved(note)) == 1
                entry = saved(note)[0]
                assert entry["value"] == 74.25
                row = page.locator(f'.health-row[data-id="{entry["id"]}"]')
                expect(row.locator(".health-row-val")).to_have_text("74.25 kg")
                page.reload(wait_until="networkidle")
                row.get_by_role("button", name="edit", exact=False).click()
                expect(page.locator("#health-value")).to_have_value("74.25")
                page.get_by_label("value", exact=True).fill("72.125")
                page.get_by_label("note (optional)", exact=True).fill(note + " corrected")
                page.get_by_label("date", exact=True).fill("2026-09-24")
                page.get_by_role("button", name="save", exact=True).click()
                expect(page.locator("#health-entry-form")).to_have_count(0)
                expect(row.get_by_role("button", name="edit", exact=False)).to_be_focused()
                page.reload(wait_until="networkidle")
                expect(row.locator(".health-row-val")).to_have_text("72.125 kg")
                expect(row).to_contain_text("2026-09-24")
                entry = saved(note + " corrected")[0]
                assert entry["value"] == 72.125 and entry["date"] == "2026-09-24"
                assert not saved(note)
                passed()
                begin("health.failed-edit-retry")
                row.get_by_role("button", name="edit", exact=False).click()
                page.get_by_label("value", exact=True).fill("71.625")
                endpoint = base + f"/api/health/{entry['id']}"

                def fail(route):
                    if route.request.method == "PATCH":
                        expected_failures.append({"url": endpoint, "status": 503})
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"detail":"deliberate unavailable service"}',
                        )
                    else:
                        route.continue_()

                page.route(endpoint, fail)
                page.get_by_role("button", name="save", exact=True).click()
                expect(page.locator("#health-entry-error")).to_contain_text("save failed (503)")
                expect(page.locator("#health-value")).to_have_value("71.625")
                assert saved(note + " corrected")[0]["value"] == 72.125
                page.screenshot(
                    path=str(output / f"health-{profile}-save-error.png"), full_page=True
                )
                page.unroute(endpoint, fail)
                page.get_by_role("button", name="save", exact=True).press("Enter")
                expect(page.locator("#health-entry-form")).to_have_count(0)
                page.reload(wait_until="networkidle")
                expect(row.locator(".health-row-val")).to_have_text("71.625 kg")
                assert saved(note + " corrected")[0]["value"] == 71.625
                passed()
                begin("health.edit-cancel")
                row.get_by_role("button", name="edit", exact=False).click()
                page.get_by_label("value", exact=True).fill("999")
                page.get_by_role("button", name="cancel", exact=True).click()
                expect(row.get_by_role("button", name="edit", exact=False)).to_be_focused()
                page.reload(wait_until="networkidle")
                assert saved(note + " corrected")[0]["value"] == 71.625
                page.screenshot(
                    path=str(output / f"health-{profile}-corrected.png"), full_page=True
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                for button in row.locator("button").all():
                    box = button.bounding_box()
                    assert box and box["width"] >= 44 and box["height"] >= 44, box
                passed()
                begin("health.target-validation")
                target = page.locator('.health-card[data-kind="weight"] [data-act="set-target"]')
                target.click()
                dialog_input = page.locator(".dialog-card .dialog-input")
                dialog_input.fill("68")
                page.get_by_role("button", name="ok", exact=True).click()
                expect(target).to_contain_text("68")
                target.click()
                dialog_input.fill("7junk")
                dialog_input.press("Enter")
                expect(dialog_input).to_have_value("7junk")
                expect(dialog_input).to_have_attribute("aria-invalid", "true")
                expect(page.locator(".dialog-validation")).to_contain_text("enter a finite number")
                page.screenshot(
                    path=str(output / f"health-{profile}-target-invalid.png"), full_page=True
                )
                overview = context.request.get(base + "/api/health/overview").json()
                weight = next(item for item in overview["kinds"] if item["kind"] == "weight")
                assert weight["target"] == 68
                dialog_input.press("Escape")
                expect(target).to_be_focused()
                box = target.bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44, box
                passed()
                begin("health.target-clear-and-retry")
                target.click()
                dialog_input.fill("-1")
                page.get_by_role("button", name="ok", exact=True).click()
                expect(dialog_input).to_have_attribute("aria-invalid", "true")
                dialog_input.fill("0")
                dialog_input.press("Enter")
                expect(target).to_have_text("set target")
                target.click()
                dialog_input.fill("68")
                dialog_input.press("Enter")
                expect(target).to_contain_text("68")
                target_endpoint = base + "/api/health/target"

                def fail_target(route):
                    if route.request.method == "PUT":
                        expected_failures.append({"url": target_endpoint, "status": 503})
                        route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"detail":"deliberate unavailable service"}',
                        )
                    else:
                        route.continue_()

                page.route(target_endpoint, fail_target)
                target.click()
                dialog_input.fill("69")
                dialog_input.press("Enter")
                expect(page.locator(".toast.error")).to_contain_text("could not save target")
                expect(target).to_contain_text("68")
                page.screenshot(
                    path=str(output / f"health-{profile}-target-error.png"), full_page=True
                )
                page.unroute(target_endpoint, fail_target)
                target.click()
                dialog_input.fill("69")
                dialog_input.press("Enter")
                expect(target).to_contain_text("69")
                passed()
                if profile == "desktop":
                    begin("health.target-zoom-layout")
                    page.set_viewport_size({"width": 720, "height": 450})
                    target.click()
                    dialog_input.fill("7junk")
                    dialog_input.press("Enter")
                    expect(dialog_input).to_have_attribute("aria-invalid", "true")
                    for control in (dialog_input, *page.locator(".dialog-card button").all()):
                        box = control.bounding_box()
                        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 720, box
                        assert box["y"] >= 0 and box["y"] + box["height"] <= 450, box
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                    )
                    page.screenshot(
                        path=str(output / "health-desktop-target-zoom-layout.png"),
                        full_page=True,
                    )
                    dialog_input.press("Escape")
                    expect(target).to_be_focused()
                    page.set_viewport_size({"width": 1440, "height": 900})
                    passed()
                assert not events["page_errors"], events
                assert not events["failed_requests"], events
                assert events["http_errors"] == expected_failures, events
                errors = [e for e in events["console"] if e["type"] == "error"]
                assert len(errors) == len(expected_failures) and all(
                    "503" in e["text"] and "Failed to load resource" in e["text"] for e in errors
                ), events
            except Exception:
                page.screenshot(path=str(output / f"health-{profile}-failure.png"), full_page=True)
                raise
            finally:
                (output / f"health-{profile}-events.json").write_text(json.dumps(events, indent=2))
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.tracing.stop(path=str(output / f"health-{profile}-trace.zip"))
                context.close()
        browser.close()
    print(json.dumps({"status": "passed", "scenarios": records}))


if __name__ == "__main__":
    run()
