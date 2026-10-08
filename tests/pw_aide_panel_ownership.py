"""Owned geometry, panel ownership and exact saved conversation checks."""

import base64
import json
import os
import struct
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1]),
    str(Path(__file__).resolve().parents[1] / "tests"),
]
from browser_gate_safety import require_server_ownership  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def owned_context(pw, browser, width, zoom, label):
    options = dict(
        viewport={"width": width, "height": 844 if width == 390 else 900},
        service_workers="block",
        reduced_motion="reduce",
        has_touch=width == 390,
    )
    if not zoom:
        return browser.new_context(**options)
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
    (extension / "zoom.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
    return pw.chromium.launch_persistent_context(
        profile / "browser",
        channel="chromium",
        headless=True,
        args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        **options,
    )


def native_zoom(ctx, page, base):
    worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    assert (
        worker.evaluate(
            "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
            base,
        )
        == 2
    )
    page.wait_for_function("innerWidth===720 && innerHeight===450 && devicePixelRatio===2")


def capture(ctx, page, path, width):
    png = base64.b64decode(
        ctx.new_cdp_session(page).send(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
        )["data"]
    )
    assert struct.unpack(">II", png[16:24]) == (width, 844 if width == 390 else 900)
    Path(path).write_bytes(png)


base = "http://127.0.0.1:" + os.environ["PORT"]
origin = urlsplit(base)
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []


def geometry(page):
    return page.evaluate(
        "() => {\n      const rect = id => document.getElementById(id).getBoundingClientRect().toJSON();\n      return {title:rect('aide-conversation-name'),header:document.querySelector('.main > .topbar').getBoundingClientRect().toJSON(),composer:rect('composer-ta'),panel:rect('aide-work-panel'),sidebar:rect('aide-sidebar'),sidebarHidden:document.body.classList.contains('sidebar-hidden'),cssWidth:innerWidth};\n    }"
    )


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in [
            (w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")
        ] + [(1440, t, True) for t in ("light", "dark")]:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            ctx = owned_context(pw, browser, width, zoom, label)
            errors, console, external = ([], [], [])

            def boundary(route):
                u = urlsplit(route.request.url)
                if (u.scheme, u.netloc) != (origin.scheme, origin.netloc):
                    external.append(route.request.url)
                    return route.abort()
                return route.continue_()

            ctx.route("**/*", boundary)
            ctx.route_web_socket("**/*", lambda ws: (external.append(ws.url), ws.close()))
            page = ctx.new_page()
            page.set_default_timeout(8000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            row = {"profile": label, "status": "failed"}
            rows.append(row)
            try:
                api = ctx.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                name = "owned reading conversation — exact long name résumé 中文 with a reading discussion and saved notes"
                response = api.post(base + "/api/sessions", data={"name": name})
                assert response.ok
                sid = response.json()["id"]
                page.goto(base + "/?app=aide#" + sid, wait_until="networkidle")
                if zoom:
                    native_zoom(ctx, page, base)
                page.wait_for_function("id=>window._currentSession?.id===id", arg=sid)
                expect(page.locator("#aide-conversation-name")).to_have_text(name)
                draft = "keep this exact newer question — café 中文"
                page.locator("#composer-ta").fill(draft)
                small = page.evaluate("innerWidth<=700")
                if not small and page.locator("body.sidebar-hidden").count():
                    page.locator("#sidebar-toggle-btn").click()
                if small and (not page.locator("body.sidebar-hidden").count()):
                    page.locator("#aide-sidebar-close").click()
                page.locator("#aide-work-panel-toggle").press("Enter")
                expect(page.locator("#aide-work-panel")).to_be_visible()
                expect(page.locator("#aide-work-panel-close")).to_be_focused()
                opened = geometry(page)
                row["opened"] = opened
                capture(ctx, page, out / f"{label}-panel-open.png", width)
                assert opened["composer"]["width"] >= 300, opened
                assert (
                    opened["title"]["top"] >= opened["header"]["top"]
                    and opened["title"]["bottom"] <= opened["header"]["bottom"]
                ), opened
                assert (
                    opened["title"]["left"] >= opened["header"]["left"]
                    and opened["title"]["right"] <= opened["header"]["right"]
                ), opened
                expect(page.locator("#aide-conversation-name")).to_have_attribute("title", name)
                if page.evaluate("innerWidth<=1100"):
                    assert opened["sidebarHidden"], opened
                else:
                    assert not opened["sidebarHidden"], opened
                page.keyboard.press("Escape")
                expect(page.locator("#aide-work-panel")).to_be_hidden()
                expect(page.locator("#aide-work-panel-toggle")).to_be_focused()
                expect(page.locator("#composer-ta")).to_have_value(draft)
                page.locator("#aide-work-panel-toggle").press("Enter")
                if small:
                    page.keyboard.press("Escape")
                if page.locator("body.sidebar-hidden").count():
                    page.locator("#sidebar-toggle-btn").press("Enter")
                expect(page.locator("#aide-sidebar")).to_be_visible()
                if page.evaluate("innerWidth<=1100"):
                    expect(page.locator("#aide-work-panel")).to_be_hidden()
                expect(page.locator("#sidebar-toggle-btn")).to_have_attribute(
                    "aria-expanded", "true"
                )
                expect(page.locator("#composer-ta")).to_have_value(draft)
                if small:
                    page.locator("#aide-sidebar-close").click()
                if width == 1440 and (not zoom):
                    expect(page.locator("#aide-work-panel")).to_be_visible()
                    assert not page.locator("body.sidebar-hidden").count()
                    page.set_viewport_size({"width": 820, "height": 900})
                    page.wait_for_function(
                        "document.body.classList.contains('sidebar-hidden') && document.getElementById('composer-ta').getBoundingClientRect().width >= 300"
                    )
                    narrowed = geometry(page)
                    row["narrowed"] = narrowed
                    assert (
                        narrowed["title"]["left"] >= narrowed["header"]["left"]
                        and narrowed["title"]["right"] <= narrowed["header"]["right"]
                    ), narrowed
                    assert (
                        narrowed["title"]["top"] >= narrowed["header"]["top"]
                        and narrowed["title"]["bottom"] <= narrowed["header"]["bottom"]
                    ), narrowed
                    expect(page.locator("#aide-work-panel")).to_be_visible()
                    capture(ctx, page, out / f"{label}-resize-tools.png", 820)
                    page.locator("#sidebar-toggle-btn").press("Enter")
                    expect(page.locator("#aide-work-panel")).to_be_hidden()
                    expect(page.locator("#aide-sidebar")).to_be_visible()
                    expect(page.locator("#sidebar-toggle-btn")).to_have_attribute(
                        "aria-expanded", "true"
                    )
                    expect(page.locator("#composer-ta")).to_have_value(draft)
                    capture(ctx, page, out / f"{label}-resize-conversations.png", 820)
                    page.set_viewport_size({"width": 1440, "height": 900})
                page.reload(wait_until="networkidle")
                expect(page.locator("#aide-conversation-name")).to_have_text(name)
                expect(page.locator("#composer-ta")).to_have_value(draft)
                capture(ctx, page, out / f"{label}-retained-reload.png", width)
                saved = next(
                    (
                        x
                        for group in api.get(base + "/api/sessions").json().values()
                        for x in group
                        if x["id"] == sid
                    )
                )
                assert saved["name"] == name, saved
                assert not errors and (not console) and (not external), (errors, console, external)
                row.update(
                    status="verified",
                    saved_name=saved["name"],
                    draft=draft,
                    page_errors=errors,
                    console=console,
                    external=external,
                )
                print(label, row["status"], flush=True)
            finally:
                (out / "outcomes.json").write_text(json.dumps(rows, indent=2) + "\n")
                ctx.close()
    finally:
        browser.close()
