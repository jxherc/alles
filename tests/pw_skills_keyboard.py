"""Keyboard create, save, reopen, delete and drawer recovery on owned local data."""

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

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 820, 390] for t in ["dark", "light"]]
profiles += [(1280, t, True) for t in ["dark", "light"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "service_workers": "block",
                "reduced_motion": "reduce",
            }
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
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
            context.route(
                "**/*",
                lambda request: (
                    request.continue_()
                    if urlparse(request.request.url).netloc == urlparse(base).netloc
                    else request.abort()
                ),
            )
            page = context.new_page()
            page.set_default_timeout(5000)
            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {
                "scenario_id": "aide.skills-keyboard",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                page.goto(base + "/?view=skills", wait_until="networkidle")
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
                    page.wait_for_function("innerWidth === 640 && devicePixelRatio === 2")

                name = "owned keyboard workflow " + label
                new = page.locator("#skl-new")
                new.press("Enter")
                drawer = page.get_by_role("dialog", name="new skill", exact=True)
                expect(drawer).to_be_visible()
                expect(page.locator("#skl-drawer").get_by_label("name", exact=True)).to_be_focused()
                close = page.locator("#skl-d-close")
                close.focus()
                page.keyboard.press("Shift+Tab")
                expect(page.locator("#skl-d-save")).to_be_focused()
                page.keyboard.press("Tab")
                expect(close).to_be_focused()
                page.locator("#skl-drawer").get_by_label("name", exact=True).fill(name)
                page.locator("#skl-drawer").get_by_label("description", exact=True).fill(
                    "a local daily checklist"
                )
                page.locator("#skl-drawer").get_by_label("when to use", exact=True).fill(
                    "before shopping"
                )
                body_field = page.locator("#skl-drawer").get_by_label(
                    "procedure (markdown)", exact=True
                )
                body_field.fill("read the list, then mark each purchased item")

                def fail(route):
                    route.fulfill(status=503, json={"detail": "synthetic save interruption"})

                page.route(base + "/api/skills", fail)
                page.locator("#skl-d-save").press("Enter")
                expect(page.locator(".toast.error").last).to_contain_text("save failed")
                expect(body_field).to_have_value("read the list, then mark each purchased item")
                page.unroute(base + "/api/skills", fail)
                page.locator("#skl-d-save").press("Enter")
                expect(page.locator("#skl-d-heading")).to_have_text("edit skill")
                expect(page.get_by_role("button", name="open " + name, exact=True)).to_have_count(1)
                page.keyboard.press("Escape")
                expect(new).to_be_focused()
                expect(page.locator("#skl-drawer")).to_be_hidden()
                assert page.locator("#skl-drawer").evaluate("node=>node.inert")
                page.keyboard.press("Tab")
                assert not page.locator("#skl-drawer").evaluate(
                    "node=>node.contains(document.activeElement)"
                )
                search = page.locator("#skl-search")
                search.fill(name)
                expect(page.locator("#skl-grid .skl-card")).to_have_count(1)
                opener = page.get_by_role("button", name="open " + name, exact=True)
                slug = opener.locator("..").locator("..").get_attribute("data-slug")
                held = []

                def hold(route):
                    held.append(route)

                page.route(base + "/api/skills/" + slug, hold)
                opener.press("Enter")
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(10)
                assert len(held) == 1
                search.focus()
                response = held[0].fetch()
                assert response.ok
                held.pop().fulfill(response=response)
                page.unroute(base + "/api/skills/" + slug, hold)
                expect(search).to_be_focused()
                expect(page.locator("#skl-drawer")).to_be_hidden()
                opener.press("Enter")
                expect(page.get_by_role("dialog", name="edit skill", exact=True)).to_be_visible()
                expect(body_field).to_have_value("read the list, then mark each purchased item")
                body_field.fill("keep the receipt with the completed list")
                page.locator("#skl-d-save").press("Enter")
                expect(page.locator("#skl-d-status")).to_have_text("saved")
                expect(page.locator("#skl-grid .skl-card")).to_have_count(1)
                page.keyboard.press("Escape")
                expect(opener).to_be_focused()
                page.screenshot(path=str(out / f"{label}-saved-focus.png"))
                page.reload(wait_until="networkidle")
                search.fill(name)
                expect(page.locator("#skl-grid .skl-card")).to_have_count(1)
                opener.press("Space")
                expect(body_field).to_have_value("keep the receipt with the completed list")
                page.locator("#skl-d-del").press("Enter")
                confirmation = page.get_by_role("alertdialog")
                confirmation.get_by_role("button", name="cancel", exact=True).press("Enter")
                expect(page.locator("#skl-d-del")).to_be_focused()
                page.locator("#skl-d-del").press("Enter")
                confirmation.get_by_role("button", name="confirm", exact=True).press("Enter")
                expect(page.locator("#skl-grid .skl-card")).to_have_count(0)
                expect(new).to_be_focused()
                page.locator('.skl-rail-act[data-act="library"]').press("Enter")
                library_open = page.locator("#skl-grid .skl-card-name").first
                expect(library_open).to_be_visible()
                library_open.press("Enter")
                expect(page.get_by_role("dialog")).to_be_visible()
                expect(close).to_be_focused()
                page.keyboard.press("Escape")
                expect(library_open).to_be_focused()
                match = page.locator("#skl-match")
                match.press("Enter")
                expect(page.locator("#skl-match-q")).to_be_focused()
                page.keyboard.press("Escape")
                expect(match).to_be_focused()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                for control in [new, match, library_open]:
                    bounds = control.bounding_box()
                    assert bounds["width"] >= 43.9 and bounds["height"] >= 43.9, bounds
                assert not errors, errors
                assert len(console) == 1 and "503" in console[0], console
                row.update(status="passed", native_zoom=zoom)
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                page.screenshot(path=str(out / f"{label}-final.png"))
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()

raise SystemExit(any(row["status"] != "passed" for row in rows))
