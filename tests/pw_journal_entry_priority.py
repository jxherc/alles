"""Write first, then find and export entries on an owned local Journal."""

import base64
import json
import os
import re
import sys
import tempfile
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
    with (
        tempfile.TemporaryDirectory(
            prefix="pw_journal_entry_priority-", dir=os.environ["ALLES_DATA"]
        ) as profiles_root,
        sync_playwright() as pw,
    ):
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in profiles:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                options = dict(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                    accept_downloads=True,
                )
                if zoom:
                    profile = Path(profiles_root) / label
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
                    "scenario_id": "journal.entry-priority",
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
                    day, previous = "2026-09-15", "2026-09-14"
                    entry, earlier = f"today's synthetic entry {label}", f"earlier memory {label}"
                    assert api.put(
                        base + "/api/journal/" + day, data={"content": "", "mood": "", "tags": ""}
                    ).ok
                    assert api.put(base + "/api/journal/" + previous, data={"content": earlier}).ok
                    page.goto(base + "/?view=journal&d=" + day, wait_until="networkidle")
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
                    editor = page.get_by_role("textbox", name="journal entry", exact=True)
                    expect(editor).to_be_enabled()
                    geometry = page.evaluate("""() => {
                        const text=document.querySelector('#jrnl-text'), history=document.querySelector('.jrnl-top');
                        return {width:innerWidth, height:innerHeight, dpr:devicePixelRatio,
                            top:text.getBoundingClientRect().top,
                            entryFirst:!!(text.compareDocumentPosition(history)&Node.DOCUMENT_POSITION_FOLLOWING)};
                    }""")
                    assert (
                        geometry["entryFirst"] and 0 < geometry["top"] < geometry["height"] * 0.65
                    ), geometry
                    capture("entry")
                    page.locator("#jrnl-today").focus()
                    page.keyboard.press("Tab")
                    expect(editor).to_be_focused()
                    editor.fill(entry)
                    page.keyboard.press("Tab")
                    mood = page.get_by_role("button", name="happy", exact=True)
                    expect(mood).to_be_focused()
                    mood.press("Space")
                    expect(mood).to_have_attribute("aria-pressed", "true")
                    page.locator("#jrnl-tags").fill("walk, local")
                    page.locator("#jrnl-save").press("Enter")
                    expect(page.locator("#jrnl-saved")).to_have_text(re.compile(r"^saved "))
                    saved = api.get(base + "/api/journal/" + day).json()
                    assert (saved["content"], saved["mood"], saved["tags"]) == (
                        entry,
                        "😄",
                        "walk, local",
                    ), saved
                    page.reload(wait_until="networkidle")
                    expect(editor).to_have_value(entry)
                    expect(mood).to_have_attribute("aria-pressed", "true")
                    page.locator("#jrnl-prev").press("Enter")
                    expect(editor).to_have_value(earlier)
                    page.locator("#jrnl-next").press("Enter")
                    expect(editor).to_have_value(entry)
                    mood.press("Space")
                    expect(mood).to_have_attribute("aria-pressed", "false")
                    expect(page.locator("#jrnl-saved")).to_have_text(re.compile(r"^saved "))
                    assert api.get(base + "/api/journal/" + day).json()["mood"] == ""
                    search = page.get_by_role("textbox", name="search entries", exact=True)
                    search.fill(earlier)
                    result = page.locator(".jrnl-search-result")
                    expect(result).to_have_count(1)
                    result.press("Enter")
                    expect(editor).to_have_value(earlier)
                    expect(editor).to_be_focused()
                    year = int(page.locator("#jrnl-heat-year").inner_text())
                    page.locator("#jrnl-heat-prev").click()
                    expect(page.locator("#jrnl-heat-year")).to_have_text(str(year - 1))
                    page.locator("#jrnl-heat-next").click()
                    expect(page.locator("#jrnl-heat-year")).to_have_text(str(year))
                    with page.expect_download() as downloaded:
                        page.locator("#jrnl-export").click()
                    assert downloaded.value.suggested_filename == "journal.md"
                    assert entry in Path(downloaded.value.path()).read_text()
                    capture("history")
                    page.locator("#jrnl-lock").click()
                    page.locator("#jl-new").fill("local-journal-passcode")
                    page.locator("#jl-new2").fill("local-journal-passcode")
                    page.locator("#jl-go").click()
                    expect(editor).to_have_value(earlier)
                    page.locator("#jrnl-lock").click()
                    page.locator('.jrnl-lockmenu [data-a="lock"]').click()
                    expect(page.locator("#jl-old")).to_be_visible()
                    expect(editor).to_have_count(0)
                    page.locator("#jl-old").fill("local-journal-passcode")
                    page.locator("#jl-go").press("Enter")
                    expect(editor).to_have_value(earlier)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert not external and not errors and not console, (external, errors, console)
                    row.update(
                        status="passed",
                        geometry=geometry,
                        checks="entry visible first, keyboard writing and mood toggle, tags/save/reload, dates, search and focus, year controls, export bytes, passcode lock/unlock, overflow, console",
                    )
                except Exception:
                    row["error"] = traceback.format_exc()
                    capture("failed")
                finally:
                    assert context.request.post(
                        base + "/api/journal/lock/disable",
                        data={"passcode": "local-journal-passcode"},
                    ).ok
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
