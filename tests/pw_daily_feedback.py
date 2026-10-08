"""Owned habit/date feedback, uncertain transaction recovery and selected-file restore."""

import json
import os
import re
import sys
from datetime import UTC, datetime
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
                for theme in ("dark", "light"):
                    context = browser.new_context(
                        viewport={"width": width, "height": 900},
                        timezone_id="UTC",
                        service_workers="block",
                        reduced_motion="reduce",
                    )
                    errors, console, external, creates = [], [], [], []
                    state = {"lost_ack": False, "refuse_restore": False}
                    page = context.new_page()
                    page.set_default_timeout(3000)
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "console", lambda m: console.append(m.text) if m.type == "error" else None
                    )

                    def route(r):
                        parsed = urlsplit(r.request.url)
                        if (parsed.scheme, parsed.netloc) != ("http", urlsplit(base).netloc):
                            external.append(r.request.url)
                            return r.abort()
                        if (
                            parsed.path == "/api/files/operations"
                            and r.request.method == "POST"
                            and r.request.post_data_json.get("action") == "restore"
                            and state["refuse_restore"]
                        ):
                            state["refuse_restore"] = False
                            return r.fulfill(status=403, json={"detail": "owned restore refusal"})
                        if parsed.path == "/api/money/transactions" and r.request.method == "POST":
                            creates.append(r.request.post_data_json)
                            if state["lost_ack"]:
                                response = r.fetch(max_redirects=0)
                                assert response.ok
                                state["lost_ack"] = False
                                return r.fulfill(
                                    status=503, json={"detail": "owned lost acknowledgement"}
                                )
                        return r.continue_()

                    context.route("**/*", route)
                    context.route_web_socket("**/*", lambda ws: ws.close())
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss").ok
                    assert api.patch(base + "/api/settings", data={"timezone": "UTC"}).ok
                    assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                    suffix = f"{width}-{theme}"
                    for case in ("habit", "health-date", "finance-uncertain", "trash-restore"):
                        record = {"case": case, "profile": suffix, "status": "failed"}
                        records.append(record)
                        try:
                            if case == "habit":
                                habit = api.post(
                                    base + "/api/habits",
                                    data={"name": "owned daily walk " + suffix},
                                ).json()
                                day = datetime.now(UTC).date().isoformat()
                                page.goto(base + "/?view=habits", wait_until="networkidle")
                                button = page.locator(
                                    f'.habit-card[data-id="{habit["id"]}"] [data-toggle="{day}"]'
                                )
                                expect(button).to_have_attribute("aria-pressed", "false")
                                expect(button).to_have_attribute(
                                    "aria-label", re.compile("not completed")
                                )
                                label = button.get_attribute("aria-label")
                                assert (
                                    str(datetime.now(UTC).year) in label and habit["name"] in label
                                )
                                button.press("Enter")
                                expect(button).to_have_attribute("aria-pressed", "true")
                                expect(button).to_be_focused()
                                expect(button.locator(".habit-day-state")).to_have_text("✓")
                                page.screenshot(path=str(out / (suffix + "-habit-completed.png")))
                                page.reload(wait_until="networkidle")
                                expect(button).to_have_attribute("aria-pressed", "true")
                                button.press("Space")
                                expect(button).to_have_attribute("aria-pressed", "false")
                                expect(button).to_be_focused()
                                page.reload(wait_until="networkidle")
                                expect(button).to_have_attribute("aria-pressed", "false")
                            elif case == "health-date":
                                page.goto(base + "/?view=health-log", wait_until="networkidle")
                                page.locator("#health-add-toggle").press("Enter")
                                page.locator("#health-value").fill("74.25")
                                page.locator("#health-note").fill("owned date " + suffix)
                                date = page.locator("#health-date")
                                date.fill("2026-02-31")
                                expect(date).to_have_attribute("aria-invalid", "true")
                                expect(page.locator("#health-date-help")).to_contain_text(
                                    "calendar"
                                )
                                expect(date).to_be_focused()
                                page.screenshot(path=str(out / (suffix + "-invalid-date.png")))
                                page.locator("#health-create").press("Enter")
                                expect(page.locator("#health-entry-error")).to_contain_text(
                                    "valid date"
                                )
                                expect(date).to_have_value("2026-02-31")
                                date.fill("2028-02-29")
                                expect(date).not_to_have_attribute("aria-invalid", "true")
                                page.locator("#health-create").press("Enter")
                                expect(page.locator("#health-entry-form")).to_have_count(0)
                                saved = [
                                    e
                                    for e in api.get(base + "/api/health").json()["entries"]
                                    if e["note"] == "owned date " + suffix
                                ]
                                assert len(saved) == 1 and saved[0]["date"] == "2028-02-29"
                                assert saved[0]["value"] == 74.25
                                page.reload(wait_until="networkidle")
                                expect(
                                    page.locator(f'.health-row[data-id="{saved[0]["id"]}"]')
                                ).to_contain_text("owned date " + suffix)
                            elif case == "finance-uncertain":
                                for a in api.get(base + "/api/money/accounts").json():
                                    assert api.delete(base + "/api/money/accounts/" + a["id"]).ok
                                account = api.post(
                                    base + "/api/money/accounts",
                                    data={
                                        "name": "owned acknowledgement account",
                                        "currency": "CAD",
                                        "opening": 100,
                                    },
                                ).json()
                                page.goto(base + "/?view=money", wait_until="networkidle")
                                if page.locator("#money-entry-fields").is_hidden():
                                    page.locator("#money-entry-action").press("Enter")
                                page.locator("#tx-payee").fill("owned acknowledged expense")
                                page.locator("#tx-amt").fill("10.00")
                                state["lost_ack"] = True
                                page.locator("#tx-add").press("Enter")
                                expect(page.locator("#tx-save-status")).to_contain_text(
                                    "not confirmed"
                                )
                                expect(page.locator("#tx-save-status")).to_contain_text(
                                    "retry without changing"
                                )
                                expect(page.locator("#tx-payee")).to_have_value(
                                    "owned acknowledged expense"
                                )
                                expect(page.locator("#tx-amt")).to_have_value("10.00")
                                page.wait_for_timeout(3200)
                                expect(page.locator("#tx-save-status")).to_be_visible()
                                page.screenshot(path=str(out / (suffix + "-save-uncertain.png")))
                                page.locator("#tx-payee").fill("newer expense 草稿")
                                expect(page.locator("#tx-save-status")).to_contain_text(
                                    "earlier transaction save not confirmed"
                                )
                                expect(page.locator("#tx-save-status")).not_to_contain_text(
                                    "retry without changing"
                                )
                                expect(page.locator("#tx-payee")).to_be_focused()
                                page.screenshot(
                                    path=str(out / (suffix + "-newer-draft-warning.png"))
                                )
                                page.locator("#tx-payee").fill("owned acknowledged expense")
                                expect(page.locator("#tx-save-status")).to_contain_text(
                                    "retry without changing"
                                )
                                page.locator("#tx-add").press("Enter")
                                expect(page.locator("#money-save-results")).to_contain_text(
                                    "owned acknowledged expense"
                                )
                                expect(page.locator("#tx-save-status")).to_be_hidden()
                                saved = api.get(base + "/api/money/transactions").json()
                                assert len(saved) == 1 and saved[0]["amount"] == -10
                                assert creates[-1]["request_id"] == creates[-2]["request_id"]
                                page.reload(wait_until="networkidle")
                                expect(
                                    page.locator(f'.txn[data-id="{saved[0]["id"]}"]')
                                ).to_contain_text("owned acknowledged expense")
                                assert (
                                    next(
                                        a
                                        for a in api.get(base + "/api/money/accounts").json()
                                        if a["id"] == account["id"]
                                    )["balance"]
                                    == 90
                                )
                            else:
                                name = "owned-restore-" + suffix + ".txt"
                                page.goto(base + "/?view=files", wait_until="networkidle")
                                with page.expect_file_chooser() as chooser:
                                    page.get_by_role("button", name="upload", exact=True).press(
                                        "Enter"
                                    )
                                chooser.value.set_files(
                                    {
                                        "name": name,
                                        "mimeType": "text/plain",
                                        "buffer": b"owned restore contents\n",
                                    }
                                )
                                selection = page.get_by_role(
                                    "checkbox", name="select " + name, exact=True
                                )
                                selection.click()
                                page.locator('[data-files-bulk="delete"]').press("Enter")
                                page.locator(".dialog-overlay [data-dialog-confirm]").press("Enter")
                                expect(selection).to_have_count(0)
                                page.get_by_role(
                                    "button", name="recently deleted", exact=True
                                ).press("Enter")
                                selection.click()
                                restore = page.locator('[data-files-bulk="restore"]')
                                expect(restore).to_be_visible()
                                page.screenshot(path=str(out / (suffix + "-selected-trash.png")))
                                state["refuse_restore"] = True
                                restore.press("Enter")
                                expect(page.locator(".toast.error").last).to_contain_text(
                                    "owned restore refusal"
                                )
                                expect(selection).to_have_attribute("aria-checked", "true")
                                expect(restore).to_be_focused()
                                expect(restore).to_have_attribute("aria-busy", "false")
                                restore.press("Enter")
                                expect(selection).to_have_count(0)
                                page.locator('[data-files-view="all"]').press("Enter")
                                expect(selection).to_be_visible()
                                page.reload(wait_until="networkidle")
                                expect(selection).to_be_visible()
                                row = selection.locator("xpath=..")
                                path = row.get_attribute("data-path")
                                content = api.get(
                                    base + "/api/files/read", params={"path": path}
                                ).json()
                                assert content["content"] == "owned restore contents\n"
                            assert not errors and not external
                            assert all(
                                "503" in message or "403" in message for message in console
                            ), console
                            record["status"] = "passed"
                        except Exception as e:
                            record["error"] = str(e)
                        finally:
                            record.update(
                                page_errors=errors.copy(),
                                console_errors=console.copy(),
                                external=external.copy(),
                            )
                            page.screenshot(path=str(out / (suffix + "-" + case + ".png")))
                            (out / "scenarios.json").write_text(
                                json.dumps(records, indent=2) + "\n"
                            )
                    context.close()
        finally:
            browser.close()
    assert all(r["status"] == "passed" for r in records), records


if __name__ == "__main__":
    run()
