"""Files names its reversible deletion, preserving cancellation and exact restoration."""

import base64
import json
import os
import sys
import traceback
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
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        browser = pw.chromium.launch()
        try:
            for width, zoom in ((1440, 1), (390, 1), (1440, 2)):
                for theme in ("light", "dark"):
                    label = f"{width}-{theme}-zoom{zoom}"
                    options = dict(
                        viewport={"width": width, "height": 900},
                        reduced_motion="reduce",
                        service_workers="block",
                    )
                    if zoom == 2:
                        profile = Path(os.environ["ALLES_DATA"]) / label
                        ext = profile / "extension"
                        ext.mkdir(parents=True)
                        (ext / "manifest.json").write_text(
                            json.dumps(
                                {
                                    "manifest_version": 3,
                                    "name": "owned zoom check",
                                    "version": "1.0",
                                    "permissions": ["tabs"],
                                    "background": {"service_worker": "zoom.js"},
                                }
                            )
                        )
                        (ext / "zoom.js").write_text(
                            "chrome.runtime.onInstalled.addListener(() => {});"
                        )
                        context = pw.chromium.launch_persistent_context(
                            profile / "browser",
                            channel="chromium",
                            headless=True,
                            args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"],
                            **options,
                        )
                    else:
                        context = browser.new_context(**options)
                    errors, console, external = [], [], []
                    page = context.new_page()
                    page.set_default_timeout(5000)
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
                    assert api.put("/api/appearance", data=from_legacy(theme, None)).ok

                    def capture(state):
                        if zoom == 2:
                            shot = context.new_cdp_session(page).send(
                                "Page.captureScreenshot",
                                {"format": "png", "captureBeyondViewport": False},
                            )
                            (out / (label + "-" + state + ".png")).write_bytes(
                                base64.b64decode(shot["data"])
                            )
                        else:
                            page.screenshot(path=str(out / (label + "-" + state + ".png")))

                    record = {"profile": label, "status": "failed"}
                    records.append(record)
                    try:
                        owned = Path(os.environ["ALLES_DATA"])
                        assert (owned / ".alles-test-owner").read_text().strip() == os.environ[
                            "ALLES_TEST_RUN_ID"
                        ]
                        files = owned / "files"
                        files.mkdir(exist_ok=True)
                        name = "review-delete-" + label + ".txt"
                        payload = b"synthetic local recovery bytes\n"
                        (files / name).write_bytes(payload)
                        page.goto(base + "/?view=files", wait_until="networkidle")
                        if zoom == 2:
                            worker = (
                                context.service_workers[0]
                                if context.service_workers
                                else context.wait_for_event("serviceworker")
                            )
                            assert (
                                worker.evaluate(
                                    "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                                    base,
                                )
                                == 2
                            )
                            page.wait_for_function("innerWidth===720 && devicePixelRatio===2")
                        row = page.locator('.file-row[data-path="' + name + '"]')
                        expect(row).to_be_visible()
                        row.press("Enter")
                        delete = page.locator('[data-detail-action="delete"]')
                        delete.press("Enter")
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_contain_text(name)
                        expect(dialog).to_contain_text("you can restore it there")
                        expect(
                            dialog.get_by_role(
                                "button", name="move to recently deleted", exact=True
                            )
                        ).to_be_visible()
                        expect(
                            dialog.get_by_role("button", name="cancel", exact=True)
                        ).to_be_focused()
                        bounds = dialog.evaluate(
                            "e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,width:innerWidth}}"
                        )
                        assert 0 <= bounds["left"] and bounds["right"] <= bounds["width"]
                        capture("delete-review")
                        page.keyboard.press("Escape")
                        expect(dialog).to_have_count(0)
                        expect(delete).to_be_focused()
                        assert (files / name).read_bytes() == payload
                        delete.press("Enter")
                        dialog.get_by_role("button", name="cancel", exact=True).press("Enter")
                        expect(dialog).to_have_count(0)
                        expect(delete).to_be_focused()
                        assert (files / name).read_bytes() == payload
                        delete.press("Enter")
                        dialog.get_by_role(
                            "button", name="move to recently deleted", exact=True
                        ).press("Enter")
                        expect(row).to_have_count(0)
                        page.locator('[data-files-view="trash"]').press("Enter")
                        trashed = page.locator(".file-row[data-trash-id]").filter(has_text=name)
                        expect(trashed).to_have_count(1)
                        trashed.press("Enter")
                        page.locator('[data-detail-action="restore"]').press("Enter")
                        expect(trashed).to_have_count(0)
                        page.locator('[data-files-view="all"]').press("Enter")
                        expect(row).to_be_visible()
                        page.reload(wait_until="networkidle")
                        expect(row).to_be_visible()
                        row.press("Enter")
                        with page.expect_download() as downloaded:
                            page.locator("#files-detail-content a[download]").click()
                        assert Path(downloaded.value.path()).read_bytes() == payload
                        assert (files / name).read_bytes() == payload
                        assert not errors and not console and not external, (
                            errors,
                            console,
                            external,
                        )
                        capture("restored")
                        record.update(
                            status="passed",
                            action_name="move to recently deleted",
                            escape_cancel_focus=True,
                            explicit_cancel_focus=True,
                            confirmed_delete=True,
                            restore_reload_download=True,
                            geometry=bounds,
                            native_zoom=zoom,
                        )
                    except Exception:
                        record["failure"] = traceback.format_exc()
                        capture("failure")
                    finally:
                        record.update(page_errors=errors, console_errors=console, external=external)
                        context.close()
                        (out / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
        finally:
            browser.close()
    assert len(records) == 6 and all(r["status"] == "passed" for r in records), records


if __name__ == "__main__":
    run()
