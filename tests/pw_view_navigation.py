"""Every specialist view remains discoverable when its tab strip overflows."""

import base64
import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    profiles = [(w, t, False) for w in (1440, 820, 390, 320) for t in ("light", "dark")]
    profiles += [(1440, t, True) for t in ("light", "dark")]
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in profiles:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                options = dict(
                    timezone_id="UTC",
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                    accept_downloads=True,
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
                external, errors, console = [], [], []

                def route(request):
                    if urlparse(request.request.url).netloc != urlparse(base).netloc:
                        external.append(request.request.url)
                        return request.abort()
                    return request.continue_()

                context.route("**/*", route)
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                row = {
                    "scenario_id": "navigation.view-scroll",
                    "profile": label,
                    "status": "failed",
                }
                rows.append(row)

                def capture(name):
                    screenshot = context.new_cdp_session(page).send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )
                    (output / f"{label}-{name}.png").write_bytes(
                        base64.b64decode(screenshot["data"])
                    )

                try:
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss").ok
                    assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                    assert api.patch(
                        base + "/api/settings",
                        data={
                            "language": "en",
                        },
                    ).ok
                    page.goto(base + "/?view=plan", wait_until="networkidle")
                    if zoom:
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        assert (
                            worker.evaluate(
                                "async base => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                                base,
                            )
                            == 2
                        )
                        page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                    groups = {
                        "plan": ("plan-view", 7),
                        "inbox": ("inbox-view", 3),
                        "library": ("library-view", 3),
                        "health": ("health-group-view", 3),
                        "finance": ("finance-view", 4),
                        "docs": ("docs-workbench-view", 2),
                        "files": ("files-workbench-view", 2),
                        "vault": ("vault-workbench-view", 1),
                        "server": ("server-workbench-view", 9),
                    }
                    checked = []
                    for group, (root_id, count) in groups.items():
                        page.goto(base + "/?view=" + group, wait_until="networkidle")
                        root = page.locator("#" + root_id)
                        expect(root).to_be_visible()
                        strip = root.locator(".specialist-view-strip")
                        tabs = strip.locator('[role="tab"]')
                        expect(tabs).to_have_count(count)
                        more = strip.get_by_role("button", name="more views", exact=True)
                        previous = strip.get_by_role("button", name="previous views", exact=True)
                        original_section = root.get_attribute("data-section")
                        original_url = page.url
                        seen = set()

                        def visible_labels():
                            return strip.locator('[role="tablist"]').evaluate(
                                "e=>{const r=e.getBoundingClientRect();return [...e.querySelectorAll('[role=tab]')].filter(b=>{const v=b.getBoundingClientRect();return v.left>=r.left-1&&v.right<=r.right+1}).map(b=>b.textContent.trim())}"
                            )

                        if more.is_visible():
                            for _ in range(count + 1):
                                seen.update(visible_labels())
                                if more.get_attribute("aria-disabled") == "true":
                                    break
                                more.press("Enter")
                                expect(more).to_be_focused()
                            else:
                                raise AssertionError("view strip did not reach its end")
                            assert len(seen) == count, (group, seen)
                            expect(more).to_have_attribute("aria-disabled", "true")
                            more.press("Enter")
                            assert root.get_attribute("data-section") == original_section
                            assert page.url == original_url
                            if group in ("plan", "server"):
                                capture(group + "-end")
                            for _ in range(count + 1):
                                if previous.get_attribute("aria-disabled") == "true":
                                    break
                                previous.press("Enter")
                            else:
                                raise AssertionError("view strip did not return to its start")
                            expect(previous).to_have_attribute("aria-disabled", "true")
                        else:
                            expect(previous).to_be_hidden()
                            assert len(visible_labels()) == count
                        if group in ("plan", "server"):
                            capture(group + "-start")
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        checked.append(group)
                        if group == "plan":
                            tabs.first.press("End")
                            expect(tabs.last).to_be_focused()
                            expect(tabs.last).to_have_attribute("aria-selected", "true")
                            tabs.last.press("Home")
                            expect(tabs.first).to_be_focused()
                            expect(tabs.first).to_have_attribute("aria-selected", "true")
                            toggle = root.locator("[data-specialist-sidebar-toggle]")
                            toggle.press("Enter")
                            expect(strip).to_be_hidden()
                            page.reload(wait_until="networkidle")
                            expect(strip).to_be_hidden()
                            toggle.press("Enter")
                            expect(strip).to_be_visible()
                    assert not external and not errors and not console, (external, errors, console)
                    row.update(
                        status="passed",
                        groups=checked,
                        checks="all nine groups, every view revealable, scroll does not navigate, disabled bounds preserve focus, keyboard Home/End selects, collapse/reload/restore, themes/reduced motion/native200 fullCDP, no page overflow or console errors",
                    )
                except Exception:
                    row["error"] = traceback.format_exc()
                    capture("failed")
                finally:
                    row.update(
                        page_errors=errors, console_errors=console, blocked_external=external
                    )
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
        finally:
            browser.close()
    assert all(row["status"] == "passed" for row in rows), rows


if __name__ == "__main__":
    run()
