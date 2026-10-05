"""Owned Vault navigation across viewport changes, locked and unlocked."""

import base64
import json
import os
import sys
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
    master = "owned-only-navigation-password-2026"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        assert api.post("/api/vault/unlock", data={"password": master}).ok
        try:
            profiles = [
                (w, t, u, False)
                for w in (390, 1440)
                for t in ("dark", "light")
                for u in (False, True)
            ] + [(1280, t, u, True) for t in ("dark", "light") for u in (False, True)]
            for initial, theme, unlocked, native_zoom in profiles:
                options = dict(
                    viewport={"width": initial, "height": 900},
                    reduced_motion="reduce",
                    service_workers="block",
                )
                if native_zoom:
                    profile = Path(os.environ["ALLES_DATA"]) / f"zoom-{theme}-{unlocked}"
                    extension = profile / "extension"
                    extension.mkdir(parents=True)
                    (extension / "manifest.json").write_text(
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
                    (extension / "zoom.js").write_text(
                        "chrome.runtime.onInstalled.addListener(() => {});"
                    )
                    context = pw.chromium.launch_persistent_context(
                        profile / "browser",
                        channel="chromium",
                        headless=True,
                        args=[
                            f"--disable-extensions-except={extension}",
                            f"--load-extension={extension}",
                        ],
                        **options,
                    )
                else:
                    context = browser.new_context(**options)
                errors, external, console = [], [], []
                page = context.new_page()
                page.set_default_timeout(2500)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on(
                    "console",
                    lambda m: console.append(m.text) if m.type == "error" else None,
                )

                def route(r):
                    u = urlsplit(r.request.url)
                    if (u.scheme, u.netloc) != ("http", urlsplit(base).netloc):
                        external.append(r.request.url)
                        return r.abort()
                    return r.continue_()

                context.route("**/*", route)
                context.route_web_socket("**/*", lambda ws: ws.close())
                assert api.put("/api/appearance", data=from_legacy(theme, None)).ok
                record = {
                    "initial_width": initial,
                    "theme": theme,
                    "unlocked": unlocked,
                    "native_zoom": native_zoom,
                    "status": "failed",
                }
                records.append(record)
                try:
                    page.goto(base + "/?view=vault", wait_until="networkidle")
                    if unlocked:
                        page.locator("#vault-pw-input").fill(master)
                        page.locator("#vault-unlock-btn").press("Enter")
                        expect(page.locator("#vault-new-btn")).to_be_visible()
                    trigger = page.locator("#app-drawer-btn")
                    expect(trigger).to_be_visible()
                    expect(trigger).to_have_attribute("aria-label", "switch app from vault")
                    widths = (
                        (2, 1, 2, 1)
                        if native_zoom
                        else (
                            (1440, 390, 699, 701, 699)
                            if initial == 390
                            else (390, 1440, 701, 699, 701)
                        )
                    )
                    for width in widths:
                        if native_zoom:
                            worker = (
                                context.service_workers[0]
                                if context.service_workers
                                else context.wait_for_event("serviceworker")
                            )
                            assert (
                                worker.evaluate(
                                    "async ({base,zoom}) => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,zoom);return chrome.tabs.getZoom(tab.id)}",
                                    {"base": base, "zoom": width},
                                )
                                == width
                            )
                            page.wait_for_function(
                                "([size,zoom]) => innerWidth === size/zoom && devicePixelRatio === zoom",
                                arg=[initial, width],
                            )
                            shot = context.new_cdp_session(page).send(
                                "Page.captureScreenshot",
                                {"format": "png", "captureBeyondViewport": False},
                            )
                            (out / f"{initial}-{theme}-{unlocked}-zoom{width}.png").write_bytes(
                                base64.b64decode(shot["data"])
                            )
                        else:
                            page.set_viewport_size({"width": width, "height": 900})
                        page.evaluate(
                            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                        )
                        expect(trigger).to_be_visible()
                        expect(trigger).to_have_attribute("aria-label", "switch app from vault")
                        assert trigger.locator("#app-drawer-label").inner_text() == "vault"
                        trigger.press("Enter")
                        expect(page.locator("#app-drawer")).to_be_visible()
                        page.keyboard.press("Escape")
                        expect(page.locator("#app-drawer")).to_be_hidden()
                        expect(trigger).to_be_focused()
                    trigger.press("Enter")
                    page.locator('.app-drawer-item[data-view="files"]').press("Enter")
                    expect(page.locator("#files-workbench-view")).to_be_visible()
                    expect(page.locator("#app-drawer")).to_be_hidden()
                    expect(trigger).to_be_focused()
                    expect(trigger).to_have_attribute("aria-label", "switch app from files")
                    assert not errors and not external and not console
                    record["status"] = "passed"
                except Exception as e:
                    record["error"] = str(e)
                    record["trigger_visible"] = page.locator("#app-drawer-btn").is_visible()
                    record["trigger_label"] = page.locator("#app-drawer-btn").get_attribute(
                        "aria-label"
                    )
                    record["trigger_parent"] = page.locator("#app-drawer-btn").evaluate(
                        "e => e.parentElement.className"
                    )
                finally:
                    record.update(page_errors=errors, external=external, console_errors=console)
                    page.screenshot(path=str(out / f"{initial}-{theme}-{unlocked}.png"))
                    (out / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
                    context.close()
        finally:
            api.dispose()
            browser.close()
    assert all(r["status"] == "passed" for r in records), records


if __name__ == "__main__":
    run()
