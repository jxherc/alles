"""Possessive task titles survive Home review, cancellation, acceptance and Plan reload."""

import json
import os
import sys
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (1440, 390):
                for theme in ("light", "dark"):
                    label = f"{width}-{theme}"
                    context = browser.new_context(
                        viewport={"width": width, "height": 900},
                        timezone_id="UTC",
                        service_workers="block",
                        reduced_motion="reduce",
                    )
                    page = context.new_page()
                    page.set_default_timeout(6000)
                    errors, console, external = [], [], []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "console", lambda m: console.append(m.text) if m.type == "error" else None
                    )

                    def local_only(route):
                        target = urlsplit(route.request.url)
                        if (target.scheme, target.netloc) != ("http", urlsplit(base).netloc):
                            external.append(route.request.url)
                            return route.abort()
                        route.continue_()

                    context.route("**/*", local_only)
                    context.route_web_socket("**/*", lambda socket: socket.close())
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss").ok
                    assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                    assert api.patch(base + "/api/settings", data={"timezone": "UTC"}).ok
                    record = {"profile": label, "status": "failed", "cases": []}
                    records.append(record)
                    try:
                        for variant, original, expected in (
                            (
                                "straight",
                                "prepare tomorrow's reading",
                                "prepare tomorrow's reading",
                            ),
                            ("curly", "prepare tomorrow’s reading", "prepare tomorrow’s reading"),
                            ("plain", "prepare reading tomorrow", "prepare reading"),
                        ):
                            page.goto(base + "/?view=today", wait_until="networkidle")
                            entry = page.locator("#today-capture-input")
                            submit = page.locator('#today-capture [type="submit"]')
                            before = api.get(base + "/api/tasks").json()
                            due = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
                            entry.fill(original)
                            entry.press("Enter")
                            expect(page.locator("#capture-title")).to_be_focused()
                            expect(page.locator("#capture-title")).to_have_value(expected)
                            assert page.locator("#capture-due").evaluate("e=>e.value") == due
                            assert api.get(base + "/api/tasks").json() == before
                            page.locator("#capture-title").fill("cancelled draft")
                            page.locator("#capture-cancel").press("Enter")
                            expect(entry).to_have_value(original)
                            expect(submit).to_be_focused()
                            assert api.get(base + "/api/tasks").json() == before
                            submit.press("Enter")
                            expect(page.locator("#capture-title")).to_have_value(expected)
                            page.locator("#capture-notes").fill("reviewed synthetic note")
                            page.screenshot(path=str(out / f"{label}-{variant}-review.png"))
                            with page.expect_response(
                                lambda r: (
                                    r.url == base + "/api/tasks" and r.request.method == "POST"
                                )
                            ) as accepted:
                                page.locator("#capture-accept").press("Enter")
                            response = accepted.value
                            assert response.ok, response.text()
                            saved = response.json()
                            assert saved["title"] == expected and saved["due_date"] == due
                            assert saved["notes"] == "reviewed synthetic note"
                            assert saved["source"]["excerpt"] == original
                            expect(page.locator(".capture-status")).to_contain_text("saved in plan")
                            expect(entry).to_have_value("")
                            page.locator("#capture-open").press("Enter")
                            expect(page.locator("#te-title")).to_have_value(expected)
                            page.reload(wait_until="networkidle")
                            expect(page.locator("#te-title")).to_have_value(expected)
                            expect(page.locator("#te-due")).to_have_value(due)
                            page.locator(".task-editor .capture-source summary").press("Enter")
                            expect(page.locator(".task-editor .capture-source pre")).to_have_text(
                                original
                            )
                            rows = api.get(base + "/api/tasks").json()
                            assert len(rows) == len(before) + 1
                            readback = next(row for row in rows if row["id"] == saved["id"])
                            assert readback["title"] == expected and readback["due_date"] == due
                            assert readback["source"]["excerpt"] == original
                            page.screenshot(path=str(out / f"{label}-{variant}-reloaded.png"))
                            assert api.delete(base + "/api/tasks/" + saved["id"]).ok
                            record["cases"].append(
                                dict(
                                    variant=variant,
                                    title=expected,
                                    due_date=due,
                                    cancel_without_write=True,
                                    reviewed_note=True,
                                    exact_saved_record=saved["id"],
                                    plan_reload=True,
                                    original_source=True,
                                )
                            )
                        assert not errors and not console and not external
                        record["status"] = "passed"
                    except Exception:
                        record["failure"] = traceback.format_exc()
                        page.screenshot(path=str(out / f"{label}-failure.png"))
                    finally:
                        record.update(page_errors=errors, console_errors=console, external=external)
                        context.close()
                        (out / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
        finally:
            browser.close()
    assert len(records) == 4 and all(row["status"] == "passed" for row in records), records


if __name__ == "__main__":
    run()
