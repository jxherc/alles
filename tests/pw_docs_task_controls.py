"""Verify accessible visual-editor task controls and exact Markdown saves."""

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
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in [
            (w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")
        ] + [(1440, t, True) for t in ("light", "dark")]:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            ctx = owned_context(pw, browser, width, zoom, label)
            errors = []
            console = []
            external = []

            def guard(route):
                u = urlsplit(route.request.url)
                if (u.scheme, u.netloc) != (origin.scheme, origin.netloc):
                    external.append(route.request.url)
                    return route.abort()
                return route.continue_()

            ctx.route("**/*", guard)
            ctx.route_web_socket("**/*", lambda ws: (external.append(ws.url), ws.close()))
            page = ctx.new_page()
            page.set_default_timeout(8000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            row = {
                "profile": label,
                "native_zoom": zoom,
                "status": "failed",
                "scope": "owned plain checklist; control accessibility only, no security test",
            }
            rows.append(row)
            try:
                api = ctx.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                name = "owned-accessible-checklist-" + label + ".md"
                content = "# owned checklist\n\n- [ ] bring the blue cup 草稿\n- [x] keep the saved note\n"
                assert api.post(
                    base + "/api/vault-md/file", data={"path": name, "content": content}
                ).ok
                page.goto(base + "/?view=wiki", wait_until="networkidle")
                if zoom:
                    native_zoom(ctx, page, base)
                file = page.locator('#wiki-tree [data-file="' + name + '"]')
                if not file.is_visible():
                    page.locator("#wiki-tree-toggle").click()
                file.click()
                page.locator("#wiki-edit-btn").click()
                controls = page.locator(".cm-task-checkbox")
                expect(controls).to_have_count(2)
                metrics = controls.evaluate_all(
                    "els=>els.map(e=>({tag:e.tagName,type:e.type,appearance:getComputedStyle(e).appearance,rect:e.getBoundingClientRect().toJSON(),aria:e.getAttribute('aria-label'),labels:[...e.labels||[]].map(l=>l.textContent),checked:e.getAttribute('aria-checked'),outer:e.outerHTML}))"
                )
                assert all(
                    m["tag"] == "BUTTON"
                    and m["type"] == "button"
                    and m["appearance"] == "none"
                    and m["rect"]["width"] >= 44
                    and m["rect"]["height"] >= 44
                    and m["aria"]
                    for m in metrics
                ), metrics
                assert [m["aria"] for m in metrics] == [
                    "bring the blue cup 草稿",
                    "keep the saved note",
                ]
                assert [m["checked"] for m in metrics] == ["false", "true"]
                controls.first.scroll_into_view_if_needed()
                capture(ctx, page, out / f"{label}-custom-checkbox.png", width)
                task = page.get_by_role("checkbox", name="bring the blue cup 草稿", exact=True)
                task.press("Space")
                expect(task).to_have_attribute("aria-checked", "true")
                expect(task).to_be_focused()
                task.press("Enter")
                expect(task).to_have_attribute("aria-checked", "false")
                expect(task).to_be_focused()
                task.press("Space")
                expect(task).to_have_attribute("aria-checked", "true")
                expect(task).to_be_focused()
                expect(page.locator("#wiki-save-btn")).to_be_enabled()
                page.locator("#wiki-save-btn").press("Enter")
                expect(page.locator("#wiki-save-state")).to_have_text("saved")
                saved = api.get(base + "/api/vault-md/file", params={"path": name}).json()
                assert saved["content"] == content.replace("- [ ] bring", "- [x] bring"), saved
                page.locator("#wiki-source-btn").click()
                updated = saved["content"].replace(
                    "bring the blue cup 草稿", "bring the red cup 草稿"
                )
                page.locator("#wiki-source").fill(updated)
                page.locator("#wiki-visual-btn").click()
                expect(
                    page.get_by_role("checkbox", name="bring the red cup 草稿", exact=True)
                ).to_have_attribute("aria-checked", "true")
                expect(
                    page.get_by_role("checkbox", name="bring the blue cup 草稿", exact=True)
                ).to_have_count(0)
                page.locator("#wiki-save-btn").press("Enter")
                expect(page.locator("#wiki-save-state")).to_have_text("saved")
                final = api.get(base + "/api/vault-md/file", params={"path": name}).json()
                assert final["content"] == updated, final
                page.reload(wait_until="networkidle")
                expect(page.locator("#wiki-preview")).to_contain_text("bring the red cup 草稿")
                capture(ctx, page, out / f"{label}-saved-reloaded.png", width)
                more = page.locator("#wiki-more-btn")
                more.focus()
                more.press("Enter")
                expect(page.locator("#wiki-rename-btn")).to_be_focused()
                page.keyboard.press("Escape")
                expect(page.locator("#wiki-more-menu")).to_be_hidden()
                expect(more).to_be_focused()
                expect(more).to_have_attribute("aria-expanded", "false")
                capture(ctx, page, out / f"{label}-menu-escape-focus.png", width)
                more.press("Enter")
                page.locator("#wiki-edit-btn").click()
                expect(page.locator("#wiki-more-menu")).to_be_hidden()
                expect(more).not_to_be_focused()
                assert not errors and not console and not external, (errors, console, external)
                row.update(
                    status="verified",
                    metrics=metrics,
                    original_content=content,
                    saved=saved,
                    final=final,
                    page_errors=errors,
                    console=console,
                    external=external,
                )
                print(
                    theme,
                    "custom labelled44px checkbox Space/Enter/focus/exactsave/renamedlabel/reload verified",
                    flush=True,
                )
            finally:
                (out / "outcomes.json").write_text(json.dumps(rows, indent=2) + "\n")
                ctx.close()
    finally:
        browser.close()
