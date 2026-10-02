"""Home review, uncertain acceptance, and original capture in completed Plan history."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                timezone_id="UTC",
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(8000)
            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda entry: console.append(entry.text) if entry.type == "error" else None,
            )

            def record(name, **extra):
                rows.append(
                    {
                        "scenario_id": "home.capture." + name,
                        "profile": str(width),
                        "status": "passed",
                        **extra,
                    }
                )
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

            try:
                page.goto(base + "/?view=today", wait_until="networkidle")
                entry = page.locator("#today-capture-input")
                submit = page.locator('#today-capture [type="submit"]')
                original = f"  review report {width} tomorrow #work !  "
                before = len(api.get("/api/tasks").json())
                entry.fill(original)
                entry.press("Enter")
                expect(page.locator(".capture-review")).to_be_visible()
                expect(page.locator("#capture-title")).to_be_focused()
                expect(page.locator("#capture-title")).to_have_value(f"review report {width}")
                expect(page.locator("#capture-tags")).to_have_value("work")
                assert page.locator("#capture-due").evaluate("el => !!el.value")
                page.locator(".capture-source summary").click()
                assert page.locator(".capture-source pre").text_content() == original
                assert len(api.get("/api/tasks").json()) == before
                page.locator("#capture-title").fill("cancelled edit")
                page.locator("#capture-cancel").click()
                expect(entry).to_have_value(original)
                assert len(api.get("/api/tasks").json()) == before
                assert entry.evaluate("el => el === document.activeElement") or submit.evaluate(
                    "el => el === document.activeElement"
                )
                record("review-edit-and-cancel-without-writing")
                submit.click()
                expect(page.locator(".capture-review")).to_be_visible()
                title = f"accepted home task {width}"
                page.locator("#capture-title").fill(title)
                page.locator("#capture-tags").fill("reviewed")
                page.locator("#capture-notes").fill("accepted notes")
                sent = []

                def lose(route):
                    if route.request.method != "POST":
                        route.continue_()
                        return
                    response = route.fetch()
                    assert response.ok, response.text()
                    sent.append({"body": route.request.post_data_json, "saved": response.json()})
                    route.fulfill(status=503, json={"detail": "synthetic lost acceptance response"})

                page.route(base + "/api/tasks", lose)
                page.locator("#capture-accept").click()
                expect(page.locator(".capture-status")).to_contain_text("same acceptance")
                expect(entry).to_have_value(original)
                page.unroute(base + "/api/tasks", lose)
                assert len(sent) == 1
                saved = sent[0]["saved"]
                rid = saved["id"]
                assert saved["source"]["excerpt"] == original
                assert saved["tags"] == ["reviewed"]
                assert len(api.get("/api/tasks").json()) == before + 1
                page.reload(wait_until="networkidle")
                page.locator("#today-capture-recovery .capture-resume button").click()
                expect(page.locator(".capture-status")).to_contain_text("previous acceptance")
                with page.expect_response(
                    lambda r: r.url == base + "/api/tasks" and r.request.method == "POST"
                ) as retry:
                    page.locator("#capture-accept").click()
                assert retry.value.ok, retry.value.text()
                assert retry.value.request.post_data_json == sent[0]["body"]
                assert retry.value.json()["id"] == rid
                assert len(api.get("/api/tasks").json()) == before + 1
                record("lost-response-reload-and-same-acceptance")
                page.locator("#capture-open").click()
                expect(page.locator("#te-title")).to_have_value(title)
                page.locator(".task-editor .capture-source summary").click()
                assert page.locator(".task-editor .capture-source pre").text_content() == original
                page.locator("#te-title").fill(title + " edited")
                page.locator("#te-due").fill("2032-06-22")
                with page.expect_response(
                    lambda r: r.url == base + "/api/tasks/" + rid and r.request.method == "PATCH"
                ) as edited:
                    page.locator("#te-save").click()
                assert edited.value.ok, edited.value.text()
                page.reload(wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_value(title + " edited")
                expect(page.locator("#te-due")).to_have_value("2032-06-22")
                page.locator(".task-editor .capture-source summary").click()
                assert page.locator(".task-editor .capture-source pre").text_content() == original
                link = page.url
                page.screenshot(path=str(out / f"{width}-original-source.png"), full_page=True)
                record("exact-plan-edit-reschedule-reload-and-original-text")
                page.locator("#te-cancel").click()
                row = page.locator(f'.task-item[data-id="{rid}"]')
                with page.expect_response(
                    lambda r: r.url == base + "/api/tasks/" + rid and r.request.method == "PATCH"
                ) as done:
                    row.locator(".task-check").click()
                assert done.value.ok, done.value.text()
                page.goto(link, wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_value(title + " edited")
                page.locator(".task-editor .capture-source summary").click()
                assert page.locator(".task-editor .capture-source pre").text_content() == original
                record("completed-history-retains-original-text")
                page.locator("#te-cancel").click()
                page.goto(base + "/?view=today", wait_until="networkidle")
                entry.fill("keep after preview failure")
                page.route(
                    base + "/api/tasks/quick",
                    lambda r: r.fulfill(status=503, json={"detail": "preview unavailable"}),
                )
                submit.click()
                expect(page.locator("#today-status")).to_contain_text("could not prepare")
                expect(entry).to_have_value("keep after preview failure")
                expect(page.locator(".capture-review")).to_have_count(0)
                page.unroute(base + "/api/tasks/quick")
                submit.click()
                expect(page.locator(".capture-review")).to_be_visible()
                expect(page.locator("#capture-title")).to_be_focused()
                page.locator("#capture-cancel").click()
                record("preview-failure-keeps-input-and-retries")
                entry.fill("older pending capture")
                submit.click()
                expect(page.locator(".capture-review")).to_be_visible()
                sent.clear()
                page.route(base + "/api/tasks", lose)
                page.locator("#capture-accept").click()
                expect(page.locator(".capture-status")).to_contain_text("same acceptance")
                page.unroute(base + "/api/tasks", lose)
                page.reload(wait_until="networkidle")
                entry.fill("fresh accepted capture")
                submit.click()
                expect(page.locator(".capture-review")).to_be_visible()
                expect(page.locator("#capture-title")).to_have_value("older pending capture")
                with page.expect_response(
                    lambda r: r.url == base + "/api/tasks" and r.request.method == "POST"
                ) as older:
                    page.locator("#capture-accept").click()
                assert older.value.ok, older.value.text()
                assert older.value.json()["id"] == sent[0]["saved"]["id"]
                expect(entry).to_have_value("fresh accepted capture")
                page.locator("#capture-cancel").click()
                record("older-pending-acceptance-preserves-new-home-input")
                submit.click()
                expect(page.locator("#capture-title")).to_have_value("fresh accepted capture")
                page.locator("#capture-accept").click()
                expect(page.locator(".capture-status")).to_contain_text("saved in plan")
                expect(entry).to_have_value("")
                page.locator("#capture-cancel").click()
                expect(page.locator("#today-capture-recovery .capture-resume")).to_have_count(0)
                record("confirmed-save-clears-only-the-matching-input")
                for variant in ["submit", "notice", "note"]:
                    original = "retained capture " + variant + str(width)
                    entry.fill(original)
                    submit.click()
                    expect(page.locator(".capture-review")).to_be_visible()
                    sent.clear()
                    page.route(base + "/api/tasks", lose)
                    page.locator("#capture-accept").click()
                    expect(page.locator(".capture-status")).to_contain_text("same acceptance")
                    page.unroute(base + "/api/tasks", lose)
                    page.reload(wait_until="networkidle")
                    entry.fill(original)
                    if variant == "note":
                        page.locator("#today-capture-mode").click()
                    if variant == "submit":
                        submit.click()
                    else:
                        page.locator("#today-capture-recovery button").click()
                    expect(page.locator(".capture-review")).to_be_visible()
                    with page.expect_response(
                        lambda r: r.url == base + "/api/tasks" and r.request.method == "POST"
                    ) as same:
                        page.locator("#capture-accept").click()
                    assert same.value.ok, same.value.text()
                    assert same.value.json()["id"] == sent[0]["saved"]["id"]
                    expect(entry).to_have_value(original if variant == "note" else "")
                    page.locator("#capture-cancel").click()
                    assert (
                        len(
                            [
                                task
                                for task in api.get("/api/tasks").json()
                                if task["title"] == original
                            ]
                        )
                        == 1
                    )
                    if variant == "note":
                        page.locator("#today-capture-mode").click()
                        entry.clear()
                    record("recovered-input-" + variant)
                original = "🙂" * 3001
                entry.fill(original)
                submit.click()
                expect(page.locator(".capture-review")).to_be_visible()
                assert page.locator(".capture-source pre").text_content() == original
                page.locator("#capture-cancel").click()
                expect(entry).to_have_value(original)
                record("unicode-limit-matches-api")
                page.clock.set_fixed_time(datetime(2032, 1, 2, 0, 30, tzinfo=UTC))
                page.evaluate(
                    "async () => { const locale = await import('/static/js/i18n.js'); locale.configureLocalization({ language: 'en', region: 'CA', timezone: 'America/Toronto' }); }"
                )
                entry.fill("check tomorrow")
                with page.expect_response(base + "/api/tasks/quick") as dated:
                    submit.click()
                assert dated.value.ok, dated.value.text()
                assert dated.value.request.post_data_json["today"] == "2032-01-01"
                expect(page.locator(".capture-review")).to_be_visible()
                assert page.locator("#capture-due").evaluate("el => el.value") == "2032-01-02"
                page.locator("#capture-cancel").click()
                record("relative-dates-use-displayed-home-day")
                assert not errors, errors
                assert all("503" in text for text in console), console
                record("console", page_errors=errors, expected_console=console)
            except Exception as error:
                rows.append(
                    {
                        "scenario_id": "home.capture.failure",
                        "profile": str(width),
                        "status": "failed",
                        "error": str(error),
                        "page_errors": errors,
                        "console": console,
                    }
                )
                page.screenshot(path=str(out / f"{width}-failure.png"), full_page=True)
            finally:
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                for endpoint in ["/api/tasks", "/api/tasks/done"]:
                    for task in api.get(endpoint).json():
                        api.delete("/api/tasks/" + task["id"])
                context.close()
        api.dispose()
        browser.close()
    assert all(row["status"] == "passed" for row in rows), [
        row for row in rows if row["status"] != "passed"
    ]


if __name__ == "__main__":
    run()
