"""Calendar toolbar reflow keeps primary work and secondary tools usable."""

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
                    "scenario_id": "calendar.toolbar",
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
                    page.goto(base + "/?view=calendar", wait_until="networkidle")
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
                    root = page.locator("#calendar-view")
                    expect(root).to_be_visible()
                    quick = page.locator("#cal-quick")
                    toggle = page.locator("#cal-tools-toggle")
                    compact = page.evaluate("innerWidth <= 760")
                    initial_height = root.locator(".page-view-head").bounding_box()["height"]
                    if compact:
                        expect(toggle).to_be_visible()
                        expect(quick).to_be_hidden()
                        assert initial_height <= 190, initial_height
                    else:
                        expect(toggle).to_be_hidden()
                        expect(quick).to_be_visible()
                    expect(page.locator("#cal-view .seg-opt")).to_have_count(5)
                    expect(page.locator("#cal-new-btn")).to_be_visible()
                    capture("resting")
                    for mode in ("week", "day", "agenda", "year", "month"):
                        button = page.locator(f'#cal-view [data-view="{mode}"]')
                        button.press("Enter")
                        assert page.evaluate("localStorage.getItem('cal-view')") == mode
                        expect(button).to_have_class("seg-opt active")
                    month = page.locator("#cal-month-label").inner_text()
                    page.locator("#cal-next").press("Enter")
                    assert page.locator("#cal-month-label").inner_text() != month
                    page.locator("#cal-prev").press("Enter")
                    expect(page.locator("#cal-month-label")).to_have_text(month)

                    def open_tools():
                        if not quick.is_visible():
                            toggle.tap() if width <= 390 else toggle.press("Enter")
                        expect(quick).to_be_visible()

                    open_tools()
                    draft = "owned quick draft 中文"
                    quick.fill(draft)
                    if compact:
                        quick.press("Escape")
                        expect(quick).to_be_hidden()
                        expect(toggle).to_be_focused()
                        expect(toggle).to_have_attribute("aria-expanded", "false")
                        open_tools()
                        expect(quick).to_have_value(draft)
                    if not zoom:
                        page.set_viewport_size({"width": 1440, "height": 900})
                        quick.focus()
                        page.set_viewport_size({"width": 320, "height": 900})
                        expect(quick).to_be_visible()
                        expect(quick).to_be_focused()
                        expect(toggle).to_have_attribute("aria-expanded", "true")
                        quick.press("Escape")
                        page.set_viewport_size({"width": 1440, "height": 900})
                        expect(page.locator("#cal-new-btn")).to_be_focused()
                        page.set_viewport_size({"width": width, "height": 900})
                        open_tools()
                        expect(quick).to_have_value(draft)
                    for selector in (
                        "#cal-import",
                        "#cal-export",
                        "#cal-find",
                        "#cal-sync-btn",
                        '.app-cog[data-app="calendar"]',
                    ):
                        control = root.locator(selector)
                        control.scroll_into_view_if_needed()
                        expect(control).to_be_visible()
                        bounds = control.bounding_box()
                        assert bounds["height"] >= 44 and bounds["width"] >= 44, (selector, bounds)
                    capture("tools")
                    if compact:
                        toggle.press("Enter")
                        expect(quick).to_be_hidden()
                    event_title = "owned toolbar appointment " + label
                    page.locator("#cal-new-btn").tap() if width <= 390 else page.locator(
                        "#cal-new-btn"
                    ).press("Enter")
                    page.locator("#cal-title").fill(event_title)
                    page.locator("#cal-desc").fill("owned saved details 中文")
                    with page.expect_response(
                        lambda r: r.url == base + "/api/calendar" and r.request.method == "POST"
                    ) as saved:
                        page.locator("#cal-save").press("Enter")
                    assert saved.value.ok
                    event_id = saved.value.json()["id"]
                    expect(page.locator("#cal-title")).to_have_count(0)
                    page.reload(wait_until="networkidle")
                    page.locator(f'#calendar-list .cal-chip[data-id="{event_id}"]').press("Enter")
                    expect(page.locator("#cal-title")).to_have_value(event_title)
                    expect(page.locator("#cal-desc")).to_have_value("owned saved details 中文")
                    page.locator("#cal-back").press("Enter")
                    expect(page.locator("#cal-title")).to_have_count(0)
                    open_tools()
                    free_requests = []
                    page.on(
                        "request",
                        lambda request: (
                            free_requests.append(request.url)
                            if "/api/calendar/free?" in request.url
                            else None
                        ),
                    )
                    page.locator("#cal-find").press("Enter")
                    dialog = page.get_by_role("dialog", name="how many minutes do you need?")
                    expect(dialog).to_be_visible()
                    if theme == "dark":
                        dialog.press("Escape")
                    else:
                        dialog.locator("[data-dialog-cancel]").press("Enter")
                    page.wait_for_load_state("networkidle")
                    assert not free_requests, free_requests
                    expect(page.locator(".cal-scope-ov")).to_have_count(0)
                    expect(page.locator("#cal-find")).to_be_focused()
                    page.locator("#cal-sync-btn").press("Enter")
                    expect(page.locator("#cd-url")).to_be_visible()
                    page.locator("#cd-back").press("Enter")
                    expect(page.locator("#cd-url")).to_have_count(0)
                    root.locator('.app-cog[data-app="calendar"]').press("Enter")
                    expect(page.locator(".app-settings-pop")).to_be_visible()
                    page.locator("#cal-month-label").click()
                    expect(page.locator(".app-settings-pop")).to_have_count(0)
                    today = (
                        api.get(base + "/api/calendar").json()[0]["start_dt"][:10].replace("-", "")
                    )
                    imported_title = "owned calendar import " + label
                    ics = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:owned-toolbar-{label}\r\nDTSTART:{today}T150000\r\nDTEND:{today}T160000\r\nSUMMARY:{imported_title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
                    with page.expect_file_chooser() as chooser:
                        page.locator("#cal-import").click()
                    with page.expect_response(
                        lambda r: r.url == base + "/api/calendar/import"
                    ) as imported:
                        chooser.value.set_files(
                            {
                                "name": "owned.ics",
                                "mimeType": "text/calendar",
                                "buffer": ics.encode(),
                            }
                        )
                    assert imported.value.ok and imported.value.json()["imported"] == 1
                    with page.expect_download() as downloaded:
                        page.locator("#cal-export").click()
                    export = Path(downloaded.value.path()).read_text()
                    assert event_title in export and imported_title in export
                    actual = api.get(base + "/api/calendar").json()
                    for item in actual:
                        if item["id"] == event_id or item["title"] == imported_title:
                            assert api.delete(base + "/api/calendar/" + item["id"]).ok
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                    assert not external and not errors and not console, (external, errors, console)
                    row.update(
                        status="passed",
                        toolbar_height=initial_height,
                        checks="five views/date paging, primary event save/reload, disclosure/draft/Escape/focus/resize, secondary controls reachable, find-time cancel, local sync panel only, settings, owned ICS import/export, themes/reduced motion/native200 fullCDP",
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
