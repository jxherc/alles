"""Creations uses one generated Photo owner and keeps upload deletion distinct."""

from __future__ import annotations

import io
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from browser_gate_safety import require_server_ownership
from PIL import Image
from playwright.sync_api import expect, sync_playwright


def _seed(data: Path, profile: str) -> tuple[str, str, str, Path]:
    buffer = io.BytesIO()
    Image.new("RGB", (180, 140), (109, 76, 51)).save(buffer, "PNG")
    photos = data / "photos"
    gallery = data / "gallery"
    photos.mkdir(exist_ok=True)
    gallery.mkdir(exist_ok=True)
    generated = f"{profile}-generated"
    personal = f"{profile}-personal"
    hidden = f"{profile}-hidden"
    upload = f"{profile}-upload"
    for name in (generated, personal, hidden):
        (photos / f"{name}.png").write_bytes(buffer.getvalue())
    upload_file = gallery / f"{upload}.png"
    upload_file.write_bytes(buffer.getvalue())
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    with sqlite3.connect(data / "aide.db") as db:
        db.execute(
            "INSERT INTO photos (id, filename, original_name, caption, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (generated, f"{generated}.png", "generated.png", "copper landscape", "generated", now),
        )
        db.execute(
            "INSERT INTO photos (id, filename, original_name, created_at) VALUES (?, ?, ?, ?)",
            (personal, f"{personal}.png", "personal.png", now),
        )
        db.execute(
            "INSERT INTO photos (id, filename, original_name, source, hidden, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (hidden, f"{hidden}.png", "hidden.png", "generated", 1, now),
        )
        db.execute(
            "INSERT INTO gallery_images (id, filename, prompt, source, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (upload, upload_file.name, "study image", "upload", now),
        )
    return generated, personal, hidden, upload_file


def run() -> None:
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    records = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for profile, width, theme in (
            ("desktop-light", 1440, "light"),
            ("tablet-dark", 720, "dark"),
            ("phone-light", 390, "light"),
            ("phone-dark", 390, "dark"),
        ):
            generated, personal, hidden, upload_file = _seed(data, profile)
            upload = upload_file.stem
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                is_mobile=width == 390,
                has_touch=width == 390,
                reduced_motion="reduce",
                service_workers="block",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(12000)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    errors.append(message.text)
                    if message.type == "error" and "503" not in message.text
                    else None
                ),
            )
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                page.goto(base + "/?view=today", wait_until="networkidle")
                page.locator("#today-settings").click()
                page.locator('.s-nav-item[data-pane="themes"]').click()
                page.locator(f'[data-theme-mode="{theme}"]').click()
                page.locator("#settings-modal-close").click()
                page.goto(base + "/?app=gallery", wait_until="networkidle")
                assert (page.locator("html").get_attribute("data-theme") or "dark") == theme
                expect(page.locator("#gallery-view")).to_be_visible()
                expect(page.locator("#gallery-view .page-view-title")).to_have_text("creations")
                generated_card = page.locator(f'.gallery-item[data-id="{generated}"]')
                upload_card = page.locator(f'.gallery-item[data-id="{upload}"]')
                expect(generated_card).to_be_visible()
                expect(upload_card).to_be_visible()
                expect(page.locator(f'.gallery-item[data-id="{personal}"]')).to_have_count(0)
                expect(page.locator(f'.gallery-item[data-id="{hidden}"]')).to_have_count(0)
                expect(generated_card.locator(".gallery-open")).to_have_attribute(
                    "href", f"/api/photos/original/{generated}"
                )
                expect(generated_card.locator("img")).to_have_js_property("complete", True)
                assert generated_card.locator("img").evaluate("image => image.naturalWidth > 0")
                for card in (generated_card, upload_card):
                    for target in (card.locator(".gallery-open"), card.locator(".gallery-del")):
                        box = target.bounding_box()
                        assert box and box["width"] >= 44 and box["height"] >= 44, box
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                page.screenshot(path=str(output / f"{profile}-creations.png"), full_page=True)
                if width == 1440:
                    page.evaluate("document.body.style.zoom = '2'")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    expect(generated_card).to_be_visible()
                    page.screenshot(path=str(output / f"{profile}-zoom-200.png"), full_page=True)
                    page.evaluate("document.body.style.zoom = ''")

                page.locator("#gallery-prompt-input").click()
                page.keyboard.press("Tab")
                opener = page.locator("#gallery-grid .gallery-open").first
                expect(opener).to_be_focused()
                with page.expect_popup() as popup:
                    page.keyboard.press("Enter")
                popup.value.close()
                page.keyboard.press("Tab")
                expect(page.locator("#gallery-grid .gallery-del").first).to_be_focused()

                remove = generated_card.get_by_role("button", name="move to trash copper landscape")
                remove.click()
                confirm = page.get_by_role("alertdialog")
                expect(confirm).to_be_visible()
                expect(confirm.get_by_role("button", name="cancel")).to_be_focused()
                page.keyboard.press("Escape")
                expect(generated_card).to_be_visible()
                expect(remove).to_be_focused()

                def reject(route):
                    if route.request.method == "DELETE":
                        route.fulfill(status=503, content_type="application/json", body="{}")
                    else:
                        route.continue_()

                pattern = f"**/api/photos/{generated}"
                page.route(pattern, reject)
                remove.click()
                with page.expect_response(
                    lambda response: (
                        response.url.endswith(f"/api/photos/{generated}")
                        and response.request.method == "DELETE"
                    )
                ) as failed:
                    confirm.get_by_role("button", name="confirm").click()
                assert failed.value.status == 503
                expect(remove).to_be_enabled()
                expect(generated_card).to_be_visible()
                page.unroute(pattern, reject)

                remove.click()
                confirm.get_by_role("button", name="confirm").click()
                expect(generated_card).to_have_count(0)
                with sqlite3.connect(data / "aide.db") as db:
                    assert db.execute(
                        "SELECT deleted_at FROM photos WHERE id=?", (generated,)
                    ).fetchone()[0]
                expect(upload_card).to_be_visible()

                upload_card.get_by_role("button", name="delete permanently study image").click()
                expect(confirm).to_contain_text("cannot be restored")
                confirm.get_by_role("button", name="confirm").click()
                expect(upload_card).to_have_count(0)
                assert not upload_file.exists()
                assert not errors, errors
                records.append(
                    {
                        "scenario_id": "aide.creations-mixed-ownership",
                        "profile": profile,
                        "status": "passed",
                        "generated_id": generated,
                        "upload_id": upload,
                    }
                )
                page.screenshot(path=str(output / f"{profile}-after-removal.png"), full_page=True)
            finally:
                context.tracing.stop(path=str(output / f"{profile}-trace.zip"))
                context.close()
        browser.close()
    (output / "scenarios.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


if __name__ == "__main__":
    run()
