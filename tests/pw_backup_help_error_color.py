"""Owned backup-help and semantic-error regression; no provider or remote fixtures.

Run from the project root against a marker-owned browser-gate server. Native zoom
uses the same Chromium extension technique as pw_task_help.py. Checks use the real shipped application assets.
"""

import base64
import json
import os
import re
import struct
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path.cwd()
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402
from pw_settings_helpers import choose_settings_section  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

HELP = "download encrypted .alles-backup; get its recovery key from settings → backup & restore"
PROFILES = [(width, theme, False) for width in (1440, 820, 390) for theme in ("light", "dark")]
PROFILES += [(1440, theme, True) for theme in ("light", "dark")]


def rgb(value):
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    match = re.fullmatch(r"rgb(a?)\(([^)]+)\)", value)
    assert match, f"unsupported color format: {value}"
    channels = [float(channel.strip()) for channel in match[2].split(",")]
    assert len(channels) == (4 if match[1] else 3), value
    assert all(0 <= channel <= 255 for channel in channels[:3]), value
    if match[1]:
        assert channels[3] == 1, f"contrast requires opaque colors: {value}"
    return [channel / 255 for channel in channels[:3]]


def contrast(foreground, background):
    def luminance(value):
        channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb(value)]
        return sum(c * w for c, w in zip(channels, (0.2126, 0.7152, 0.0722)))

    low, high = sorted([luminance(foreground), luminance(background)])
    return (high + 0.05) / (low + 0.05)


def fits(locator):
    value = locator.evaluate("""e => {
      const r=e.getBoundingClientRect();
      return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,
        viewport:innerWidth,viewportHeight:innerHeight,overflow:e.scrollWidth-e.clientWidth};
    }""")
    assert value["left"] >= 0 and value["right"] <= value["viewport"] + 1, value
    assert value["top"] >= 0 and value["bottom"] <= value["viewportHeight"] + 1, value
    assert value["overflow"] <= 1, value
    return value


def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert (data / ".alles-test-owner").read_text() == run_id
    base = "http://127.0.0.1:" + os.environ["PORT"]
    origin = urlsplit(base)
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in PROFILES:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                row = {
                    "profile": label,
                    "status": "failed",
                    "browser_child_pid": os.getpid(),
                }
                records.append(row)
                options = dict(
                    viewport={"width": width, "height": 844 if width == 390 else 900},
                    timezone_id="UTC",
                    service_workers="block",
                    accept_downloads=True,
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                )
                if zoom:
                    profile = data / ("backup-help-" + label)
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
                events = {
                    "external": [],
                    "websockets_denied": [],
                    "page_errors": [],
                    "console_errors": [],
                    "http_errors": [],
                    "failed_requests": [],
                }

                def route(request):
                    parsed = urlsplit(request.request.url)
                    if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                        events["external"].append(request.request.url)
                        return request.abort()
                    return request.continue_()

                def deny_websocket(ws):
                    events["websockets_denied"].append(ws.url)
                    ws.close()

                context.route("**/*", route)
                context.route_web_socket("**/*", deny_websocket)
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
                page.on(
                    "console",
                    lambda msg: (
                        events["console_errors"].append(msg.text) if msg.type == "error" else None
                    ),
                )
                page.on(
                    "response",
                    lambda res: (
                        events["http_errors"].append({"url": res.url, "status": res.status})
                        if res.status >= 400
                        else None
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda req: events["failed_requests"].append(
                        {"url": req.url, "failure": req.failure}
                    ),
                )

                def capture(name):
                    session = context.new_cdp_session(page)
                    try:
                        shot = session.send(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )
                        png = base64.b64decode(shot["data"])
                        assert struct.unpack(">II", png[16:24]) == (
                            width,
                            844 if width == 390 else 900,
                        )
                        (out / f"{label}-{name}.png").write_bytes(png)
                    finally:
                        session.detach()

                def api(method, path, payload=None):
                    assert path.startswith("/api/") and not path.startswith("//")
                    response = context.request.fetch(
                        base + path, method=method, data=payload, max_redirects=0
                    )
                    assert response.ok, (path, response.status)
                    return response

                try:
                    api("POST", "/api/setup/dismiss")
                    api(
                        "PATCH",
                        "/api/settings",
                        {"language": "en", "insights_enabled": False, "user_model_distill": False},
                    )
                    api("PUT", "/api/appearance", from_legacy(theme, None))
                    page.goto(base + "/?view=chat", wait_until="networkidle")
                    expect(page.locator("#setup-wizard")).to_be_hidden()
                    if zoom:
                        row["before_zoom"] = page.evaluate(
                            "({width:innerWidth,dpr:devicePixelRatio})"
                        )
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        row["native_zoom"] = worker.evaluate(
                            """async base => {
                          const tab=(await chrome.tabs.query({})).find(t=>{try{return new URL(t.url).origin===base}catch{return false}});
                          await chrome.tabs.setZoom(tab.id,2); return chrome.tabs.getZoom(tab.id);
                        }""",
                            base,
                        )
                        assert row["native_zoom"] == 2
                        page.wait_for_function(
                            "innerWidth===720 && innerHeight===450 && devicePixelRatio===2 && visualViewport.scale===1"
                        )
                    row["viewport"] = page.evaluate(
                        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,visualScale:visualViewport.scale,cssZoom:getComputedStyle(document.documentElement).zoom})"
                    )
                    field = page.locator("#composer-ta")
                    field.fill("owned unsent question")
                    help_button = page.locator("#aide-help")
                    help_button.press("Enter")
                    dialog = page.get_by_role("dialog", name="aide help", exact=True)
                    expect(dialog.locator("[data-help-close]")).to_be_focused()
                    dialog.get_by_role("searchbox", name="search help", exact=True).fill("/backup")
                    entry = dialog.locator(".aide-help-commands [data-help-entry]:visible")
                    expect(entry).to_have_count(1)
                    row["help_text"] = entry.locator("dd").inner_text()
                    row["help_box"] = fits(entry)
                    capture("backup-help")
                    page.keyboard.press("Escape")
                    expect(dialog).to_have_count(0)
                    expect(help_button).to_be_focused()
                    expect(field).to_have_value("owned unsent question")
                    field.fill("/back")
                    popup = page.locator(".slash-popup")
                    expect(popup).to_be_visible()
                    row["autocomplete_text"] = popup.locator(".slash-desc").inner_text()
                    row["autocomplete_box"] = fits(popup)
                    row["autocomplete_ellipsis"] = popup.locator(".slash-desc").evaluate(
                        "e=>e.scrollWidth>e.clientWidth"
                    )
                    field.press("ArrowDown")
                    field.press("Tab")
                    expect(field).to_have_value("/backup")
                    expect(popup).to_have_count(0)
                    field.fill("owned unsent question")
                    help_button.press("Enter")
                    dialog.locator('[data-help-settings="models"]').press("Enter")
                    expect(page.locator("#s-pane-models")).to_be_visible()
                    choose_settings_section(page, "backup", touch=width <= 390)
                    expect(page.locator("#backup-export-btn")).to_have_text(
                        "download encrypted backup"
                    )
                    key = page.locator("#backup-key-export-btn")
                    expect(key).to_have_text("download recovery key")
                    key.scroll_into_view_if_needed()
                    row["key_button_box"] = fits(key)
                    key.focus()
                    expect(key).to_be_focused()
                    expect(page.locator("#s-pane-backup")).to_contain_text(
                        "save the recovery key somewhere separate"
                    )
                    capture("recovery-key-settings")
                    page.locator("#settings-modal-close").press("Enter")
                    expect(help_button).to_be_focused()
                    page.emulate_media(reduced_motion="reduce")
                    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                    field.fill("/todo ")
                    field.press("Enter")
                    toast = page.locator("#toast-container .toast.error").last
                    expect(toast).to_have_text("/todo requires a task")
                    row["toast_box"] = fits(toast)
                    row["toast"] = (
                        toast.evaluate("""e=>{const s=getComputedStyle(e);const r=getComputedStyle(document.documentElement);return {
                      color:s.color,background:s.backgroundColor,fontSize:s.fontSize,animation:s.animationDuration,
                      semantic:r.getPropertyValue('--error').trim(),
                      surfaces:Object.fromEntries(['bg','panel','hover','raised'].map(k=>[k,r.getPropertyValue('--'+k).trim()]))}}""")
                    )
                    row["toast_contrast"] = contrast(
                        row["toast"]["color"], row["toast"]["background"]
                    )
                    row["surface_contrast"] = {
                        name: contrast(row["toast"]["color"], color)
                        for name, color in row["toast"]["surfaces"].items()
                    }
                    expect(page.locator("#toast-container")).to_have_attribute(
                        "aria-live", "polite"
                    )
                    expect(field).to_be_focused()
                    assert all(
                        float(t.rstrip("s")) <= 0.001 for t in row["toast"]["animation"].split(",")
                    )
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    capture("error-toast")
                    assert row["help_text"] == HELP and row["autocomplete_text"] == HELP, row[
                        "help_text"
                    ]
                    assert row["toast_contrast"] >= 4.5, row["toast"]
                    assert min(row["surface_contrast"].values()) >= 4.5, row["surface_contrast"]
                    if theme == "dark":
                        assert row["toast"]["color"] == "rgb(223, 116, 116)", row["toast"]
                    assert (
                        not events["external"]
                        and not events["page_errors"]
                        and not events["console_errors"]
                    ), events
                    assert not events["http_errors"] and not events["failed_requests"], events
                    row["status"] = "passed"
                except Exception:
                    row["failure"] = traceback.format_exc()
                    capture("failed")
                finally:
                    row["events"] = events
                    (out / f"{label}-events.json").write_text(json.dumps(row, indent=2) + "\n")
                    (out / "outcomes.json").write_text(json.dumps(records, indent=2) + "\n")
                    context.close()
                print(json.dumps({"profile": label, "status": row["status"]}), flush=True)
        finally:
            browser.close()
    assert all(row["status"] == "passed" for row in records), records
    return records


if __name__ == "__main__":
    run()
