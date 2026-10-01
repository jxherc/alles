"""Hidden Photos browser flow against owned temporary data and a synthetic image."""

from __future__ import annotations

import io
import json
import os
import secrets
from pathlib import Path

from browser_gate_safety import require_server_ownership
from PIL import Image
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"])
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    out.mkdir(parents=True, exist_ok=True)
    records = []
    password = secrets.token_urlsafe(24)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for profile, width in (("desktop", 1440), ("phone", 390)):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                has_touch=profile == "phone",
                is_mobile=profile == "phone",
                reduced_motion="reduce",
                service_workers="block",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(12000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                setup = context.request.post(
                    base + "/api/vault/unlock", data={"password": password}
                )
                assert setup.ok, setup.text()
                assert context.request.post(
                    base + "/api/vault/lock",
                    headers={"X-Vault-Token": setup.json()["token"]},
                ).ok

                image = Image.new("RGB", (90, 60), (24, 110, 170))
                buffer = io.BytesIO()
                image.save(buffer, "PNG")
                fixture = out / f"{profile}-private.png"
                fixture.write_bytes(buffer.getvalue())
                page.goto(base + "/?view=files", wait_until="networkidle")
                page.get_by_role("tab", name="gallery", exact=True).click()
                with page.expect_file_chooser() as picker:
                    page.get_by_role("button", name="upload", exact=True).click()
                picker.value.set_files(str(fixture))
                opener = page.get_by_role("button", name="open " + fixture.name, exact=True)
                expect(opener).to_be_visible()
                opener.click()
                page.get_by_role("button", name="hide", exact=True).click()
                expect(opener).to_have_count(0)
                record = {
                    "scenario_id": "gallery.hidden-unlock-media",
                    "profile": profile,
                    "status": "failed",
                }
                records.append(record)
                page.get_by_role("button", name="hidden", exact=True).click()
                prompt = page.get_by_role(
                    "dialog", name="vault master password to view the hidden album:"
                )
                expect(prompt).to_be_visible()
                password_field = prompt.locator("input")
                expect(password_field).to_have_attribute("type", "password")
                password_field.fill(password)
                with page.expect_response(
                    lambda r: r.url.endswith("/api/vault/unlock")
                ) as unlock_response:
                    password_field.press("Enter")
                token = unlock_response.value.json()["token"]
                opener = page.get_by_role("button", name="open " + fixture.name, exact=True)
                expect(opener).to_be_visible()
                page.wait_for_function(
                    "() => document.querySelector('#photos-grid .photos-thumb')?.naturalWidth > 0"
                )
                opener.click()
                page.wait_for_function(
                    "() => document.querySelector('#photos-lightbox-img')?.naturalWidth > 0"
                )
                expect(page.locator("#photos-close-btn")).to_be_focused()
                page.screenshot(path=str(out / f"{profile}-hidden-open.png"), full_page=True)
                page.get_by_role("button", name="edit", exact=True).click()
                page.wait_for_function("() => document.querySelector('#ie-canvas')?.width > 0")
                page.locator('#imgeditor-modal [data-act="save"]').click()
                expect(page.locator("#imgeditor-modal")).to_be_hidden()
                hidden = context.request.get(
                    base + "/api/photos/hidden", headers={"X-Vault-Token": token}
                )
                assert hidden.ok
                hidden_items = [
                    item
                    for group in hidden.json()["moments"]
                    for item in group["items"]
                    if item["original_name"] == fixture.name
                ]
                assert len(hidden_items) == 2, len(hidden_items)
                assert context.request.get(base + "/api/photos/list").json()["count"] == 0
                record.update(
                    status="passed", hidden_count=2, rendered_image=True, hidden_edit=True
                )

                record = {
                    "scenario_id": "gallery.hidden-lock-denies-bytes",
                    "profile": profile,
                    "status": "failed",
                }
                records.append(record)
                assert context.request.post(
                    base + "/api/vault/lock", headers={"X-Vault-Token": token}
                ).ok
                for item in hidden_items:
                    for kind in ("thumb", "original"):
                        response = context.request.get(base + item[kind])
                        assert response.status == 403, (item["id"], kind, response.status)
                page.screenshot(path=str(out / f"{profile}-hidden-locked.png"), full_page=True)
                assert not errors, errors
                record.update(status="passed", denied_media_requests=4, page_errors=errors)
            except Exception as error:
                if records and records[-1]["profile"] == profile:
                    records[-1]["error"] = str(error)
                page.screenshot(path=str(out / f"{profile}-failure.png"), full_page=True)
                raise
            finally:
                (out / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.tracing.stop(path=str(out / f"{profile}-trace.zip"))
                context.close()
        browser.close()
    print(f"{len(records)}/{len(records)} Hidden Photos browser scenarios passed")


if __name__ == "__main__":
    run()
