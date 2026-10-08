"""Synthetic local scope and unrelated-dialog note recovery checks."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

base = f"http://127.0.0.1:{os.environ['PORT']}"
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
root = Path(os.environ["ALLES_DATA"])
assert (root / ".alles-test-owner").read_text().strip() == os.environ["ALLES_TEST_RUN_ID"]
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in ["vault-switch", "capture-cancel"]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            blocked = []
            errors = []
            page = context.new_page()
            page.set_default_timeout(5000)
            api = context.request
            page.on("pageerror", lambda e: errors.append(str(e)))

            def guard(route):
                if urlparse(route.request.url).netloc != urlparse(base).netloc:
                    blocked.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", guard)
            a = root / f"notes-a-{width}-{case}"
            b = root / f"notes-b-{width}-{case}"
            a.mkdir()
            b.mkdir()
            row = {
                "scenario_id": "notes.review." + case,
                "feature_id": "docs.documents-and-journal",
                "profile": str(width),
                "status": "failed",
            }
            rows.append(row)
            try:
                assert api.post(base + "/api/setup/dismiss").ok
                change = api.patch(base + "/api/settings", data={"vault_dir": str(a)})
                assert change.ok, change.text()
                page.goto(base + "/?view=today", wait_until="networkidle")
                mode = page.locator("#today-capture-mode")
                if mode.get_attribute("aria-pressed") == "true":
                    mode.click()
                entry = page.locator("#today-capture-input")
                entry.fill(f"note belongs to vault a {width} {case}")

                def fail(route):
                    if route.request.method == "POST":
                        route.fulfill(status=503, json={"detail": "synthetic pre-write failure"})
                    else:
                        route.continue_()

                page.route(base + "/api/vault-md/file", fail)
                page.locator('#today-capture [type="submit"]').click()
                retry = page.locator("#today-note-recovery .note-retry")
                expect(retry).to_be_visible()
                assert not list(a.rglob("*.md")) and not list(b.rglob("*.md"))
                page.unroute(base + "/api/vault-md/file", fail)
                if case == "vault-switch":
                    response = api.patch(base + "/api/settings", data={"vault_dir": str(b)})
                    assert response.ok, response.text()
                    with page.expect_response(
                        lambda r: (
                            r.url == base + "/api/vault-md/file" and r.request.method == "POST"
                        )
                    ) as response:
                        retry.click()
                    row["retry_status"] = response.value.status
                    page.wait_for_timeout(150)
                    row["wrong_vault_files"] = [p.name for p in b.rglob("*.md")]
                    row["saved_feedback"] = page.locator("#today-note-recovery").inner_text()
                    row["pending_count"] = page.evaluate(
                        "Object.keys(sessionStorage).filter(k=>k.startsWith('alles.note.pending.v1:')).length"
                    )
                    page.screenshot(path=str(out / f"{width}-{case}.png"))
                    assert not row["wrong_vault_files"], row
                    assert row["pending_count"] == 1, row
                    assert row["retry_status"] == 409, row
                    expect(page.locator("#today-note-recovery")).to_contain_text("vault changed")
                    assert api.patch(base + "/api/settings", data={"vault_dir": str(a)}).ok
                    retry.focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("#today-note-recovery .note-saved-open")).to_be_visible()
                    assert len(list(a.rglob("*.md"))) == 1 and not list(b.rglob("*.md"))
                else:
                    mode.click()
                    entry.fill("review a separate task")
                    page.locator('#today-capture [type="submit"]').click()
                    overlay = page.locator(".capture-overlay")
                    expect(overlay).to_be_visible()
                    overlay.get_by_role("button", name="cancel", exact=True).click()
                    expect(overlay).to_have_count(0)
                    row["pending_count"] = page.evaluate(
                        "Object.keys(sessionStorage).filter(k=>k.startsWith('alles.note.pending.v1:')).length"
                    )
                    row["retry_visible"] = retry.is_visible()
                    page.screenshot(path=str(out / f"{width}-{case}.png"))
                    assert row["pending_count"] == 1 and row["retry_visible"], row
                    retry.focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("#today-note-recovery .note-saved-open")).to_be_visible()
                    assert len(list(a.rglob("*.md"))) == 1
                assert not blocked and not errors, (blocked, errors)
                row["status"] = "passed"
            except Exception as e:
                row["error"] = str(e)
            finally:
                row.update(page_errors=errors, blocked=blocked)
                context.close()
                (out / "scenarios.json").write_text(json.dumps({"scenarios": rows}, indent=2))
    browser.close()
print(json.dumps(rows, indent=2))
raise SystemExit(any(r["status"] != "passed" for r in rows))
