"""Exercise retained Files deep links after removing the retired browser."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pw_v5_literal_resting_controls import PORT, _require_owned_data


def run() -> None:
    _require_owned_data()
    folder = Path(os.environ["ALLES_DATA"]) / "files" / "cleanup-sort"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "a-large.txt").write_text("large" * 60)
    (folder / "z-small.txt").write_text("z")
    (folder / "nested").mkdir(exist_ok=True)
    errors = []
    output = Path(os.environ.get("ALLES_CLEANUP_SHOTS", "/tmp/alles-cleanup-shots"))
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900}, service_workers="block"
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            base = f"http://files.localhost:{PORT}/"
            assert page.request.post(base + "api/setup/dismiss").ok
            for entry in page.request.get(base + "api/storage-locations").json()["locations"]:
                if entry["name"].endswith(" icon fixture"):
                    assert page.request.delete(base + "api/storage-locations/" + entry["id"]).ok
            location_ids = []
            for kind in ("webdav", "s3"):
                response = page.request.post(
                    base + "api/storage-locations",
                    data={
                        "name": f"{kind} icon fixture",
                        "kind": kind,
                        "endpoint": "https://storage.example.invalid",
                        "bucket": "fixture" if kind == "s3" else "",
                        "enabled": False,
                        "credentials": {
                            "access_key_id": "fixture-key",
                            "secret_access_key": "fixture-secret",
                        }
                        if kind == "s3"
                        else {},
                    },
                )
                assert response.ok, response.text()
                location_ids.append(response.json()["id"])
            for query, expected in (
                ("sort=size&order=asc", ["nested", "z-small.txt", "a-large.txt"]),
                ("sort=name&order=desc", ["nested", "z-small.txt", "a-large.txt"]),
                ("sort=invalid&order=invalid", ["nested", "a-large.txt", "z-small.txt"]),
            ):
                page.goto(base + "?p=cleanup-sort&" + query, wait_until="networkidle")
                names = page.locator("#files-list .file-name-button")
                expect(names).to_have_text(expected)
                names.first.press("Enter")
                expect(page.locator("#files-breadcrumb")).to_contain_text("nested")
                page.locator('[data-crumb-path="cleanup-sort"]').click()
                expect(names).to_have_text(expected)
                assert page.locator("#files-breadcrumb").evaluate(
                    """el => {
                      const parent = el.parentElement.getBoundingClientRect();
                      return [el, ...el.children].every(child => {
                        const rect = child.getBoundingClientRect();
                        return rect.top >= parent.top && rect.bottom <= parent.bottom;
                      });
                    }"""
                ), "breadcrumb must stay inside its header row"
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
            expect(page.locator(f'[data-location-id="{location_ids[0]}"] svg rect')).to_have_count(
                0
            )
            expect(
                page.locator(f'[data-location-id="{location_ids[1]}"] svg ellipse')
            ).to_have_count(1)
            page.screenshot(path=str(output / f"files-{width}.png"))
            for location_id in location_ids:
                assert page.request.delete(base + "api/storage-locations/" + location_id).ok
            page.goto(f"http://aide.localhost:{PORT}/", wait_until="networkidle")
            expect(page.locator("#mic-btn")).to_be_visible()
            expect(page.locator("#live-voice-btn")).to_have_count(0)
            page.screenshot(path=str(output / f"aide-{width}.png"))
            context.close()
        browser.close()
    assert not errors, errors
    print(
        "cleanup regression gate passed: Files sorting, keyboard folder navigation, desktop/phone"
    )


if __name__ == "__main__":
    run()
