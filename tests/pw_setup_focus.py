"""Owned resumed Setup keyboard entry, step changes, refusal/retry and exits."""

import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402

from core.settings import save_settings  # noqa: E402
from services.appearance import from_legacy  # noqa: E402


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    data = Path(os.environ["ALLES_DATA"])
    assert (data / ".alles-test-owner").read_text().strip() == os.environ["ALLES_TEST_RUN_ID"]
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in [
                (w, t, False) for w in (1440, 390) for t in ("dark", "light")
            ] + [(1440, t, True) for t in ("dark", "light")]:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                options = dict(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )
                if zoom:
                    profile = Path(os.environ["ALLES_DATA"]) / label
                    extension = profile / "extension"
                    extension.mkdir(parents=True)
                    (extension / "manifest.json").write_text(
                        json.dumps(
                            dict(
                                manifest_version=3,
                                name="owned zoom check",
                                version="1.0",
                                permissions=["tabs"],
                                background={"service_worker": "zoom.js"},
                            )
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
                errors, console, external, trace = [], [], [], []
                state = {"fail_resume": False}
                page = context.new_page()
                page.set_default_timeout(3000)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)

                def route(r):
                    parsed = urlsplit(r.request.url)
                    if (parsed.scheme, parsed.netloc) != ("http", urlsplit(base).netloc):
                        external.append(r.request.url)
                        return r.abort()
                    if parsed.path == "/api/setup/resume" and state["fail_resume"]:
                        return r.fulfill(status=503, json={"detail": "owned refused setup resume"})
                    return r.continue_()

                context.route("**/*", route)
                context.route_web_socket("**/*", lambda ws: ws.close())
                api = context.request
                # Reset only the verified owned fixture's progress between profiles.
                save_settings(
                    {
                        "setup_state": {
                            "version": 1,
                            "completed_steps": [],
                            "completed": False,
                            "dismissed": False,
                            "files_companion_pending": False,
                        }
                    }
                )
                assert api.patch(
                    base + "/api/setup/step",
                    data={
                        "step": "basics",
                        "values": {"username": "owned setup", "timezone": "UTC"},
                    },
                ).ok
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                record = {"profile": label, "status": "failed"}
                records.append(record)
                try:
                    page.goto(base + "/?view=today", wait_until="networkidle")
                    if zoom:
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        assert (
                            worker.evaluate(
                                "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                            )
                            == 2
                        )
                        page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")

                    def resume():
                        page.locator("#today-settings").press("Enter")
                        general = page.locator('.s-nav-item[data-pane="general"]')
                        if not general.is_visible():
                            page.locator("#settings-section-trigger").press("Enter")
                        general.press("Enter")
                        expect(page.locator("#general-setup-btn")).to_be_visible()
                        page.locator("#general-setup-btn").press("Enter")
                        expect(page.locator("#setup-wizard")).to_be_visible()

                    def check_focus(stage):
                        page.wait_for_function(
                            "document.getElementById('setup-wizard').getAttribute('aria-busy') === 'false'"
                        )
                        focus = page.evaluate(
                            "({id:document.activeElement.id,inside:!!document.activeElement.closest('#setup-wizard'),backgroundInert:document.querySelector('.app').inert})"
                        )
                        trace.append({"stage": stage, **focus})
                        assert focus["inside"] and focus["backgroundInert"], focus
                        capture = out / (label + "-" + stage + ".png")
                        if zoom:
                            cdp = context.new_cdp_session(page)
                            pixels = cdp.send(
                                "Page.captureScreenshot", {"captureBeyondViewport": False}
                            )
                            capture.write_bytes(base64.b64decode(pixels["data"]))
                            cdp.detach()
                        else:
                            page.screenshot(path=str(capture))
                        for key in ["Tab"] * 20 + ["Shift+Tab"] * 20:
                            page.keyboard.press(key)
                            assert page.evaluate(
                                "!!document.activeElement.closest('#setup-wizard')"
                            )

                    resume()
                    expect(page.locator("#setup-title")).to_contain_text("where alles answers")
                    check_focus("access")
                    page.locator("#sw-save").press("Enter")
                    expect(page.locator("#setup-title")).to_contain_text("put your files")
                    check_focus("files")
                    page.locator("#sw-back").press("Enter")
                    expect(page.locator("#setup-title")).to_contain_text("where alles answers")
                    check_focus("back-access")
                    page.keyboard.press("Escape")
                    expect(page.locator("#setup-wizard")).to_be_hidden()
                    expect(page.locator("#today-settings")).to_be_focused()
                    assert not page.locator(".app").evaluate("e=>e.inert")
                    state["fail_resume"] = True
                    resume()
                    expect(page.locator("#sw-load-retry")).to_be_visible()
                    check_focus("refused-resume")
                    state["fail_resume"] = False
                    page.locator("#sw-load-retry").press("Enter")
                    expect(page.locator("#setup-title")).to_contain_text("put your files")
                    check_focus("retried-files")
                    page.locator("#setup-skip").press("Enter")
                    expect(page.locator("#setup-wizard")).to_be_hidden()
                    expect(page.locator("#today-settings")).to_be_focused()
                    assert not page.locator(".app").evaluate("e=>e.inert")
                    assert (
                        api.get(base + "/api/setup/status").json()["setup"]["next_step"] == "files"
                    )
                    assert not errors and not external
                    assert all("503" in m for m in console), console
                    record["status"] = "passed"
                except Exception as e:
                    record["error"] = str(e)
                finally:
                    record.update(
                        focus=trace, page_errors=errors, console_errors=console, external=external
                    )
                    page.screenshot(path=str(out / (label + ".png")))
                    (out / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
                    context.close()
        finally:
            browser.close()
    assert all(r["status"] == "passed" for r in records), records


if __name__ == "__main__":
    run()
