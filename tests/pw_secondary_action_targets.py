"""Gallery and Andromeda action geometry on an owned local application."""

import json
import os
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 820, 390, 320] for t in ["dark", "light"]]
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
                "has_touch": width in (320, 390),
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
            errors, console = [], []

            def route(request):
                url = urlparse(request.request.url)
                if url.netloc != urlparse(base).netloc:
                    return request.abort()
                if url.path == "/owned-result":
                    return request.fulfill(
                        content_type="text/html", body="<h1>owned synthetic destination</h1>"
                    )
                if url.path == "/api/andromeda/providers":
                    return request.fulfill(
                        json={
                            "selected": "fixture",
                            "providers": [
                                {
                                    "value": "fixture",
                                    "label": "owned local fixture",
                                    "available": True,
                                }
                            ],
                        }
                    )
                if url.path == "/api/andromeda/search":
                    payload = request.request.post_data_json
                    return request.fulfill(
                        json={
                            "query": payload["query"],
                            "used_no_ai": True,
                            "overview_requested": False,
                            "normal_results_enabled": True,
                            "category": "all",
                            "provider": "fixture",
                            "status": "ready",
                            "elapsed_ms": 1,
                            "has_more": False,
                            "results": [
                                {
                                    "title": (
                                        "long local result " * 12
                                        if "long" in payload["query"]
                                        else "local result"
                                    ),
                                    "url": base + "/owned-result",
                                    "snippet": "synthetic local excerpt",
                                    "publisher": "owned local source",
                                }
                            ],
                        }
                    )
                return request.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(7000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"profile": label, "status": "failed"}
            rows.append(row)
            try:
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                image_path = Path(os.environ["ALLES_DATA"]) / (label + ".png")
                Image.new("RGB", (160, 120), "#2479bb").save(image_path)
                assert api.post(
                    base + "/api/photos/upload",
                    multipart={
                        "file": {
                            "name": image_path.name,
                            "mimeType": "image/png",
                            "buffer": image_path.read_bytes(),
                        }
                    },
                ).ok
                page.goto(base + "/?view=files", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async()=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 640 && devicePixelRatio === 2")
                page.get_by_role("tab", name="gallery", exact=True).click()
                page.get_by_role("button", name="open " + image_path.name, exact=True).click()
                expect(page.locator("#photos-lightbox")).to_be_visible()
                row["gallery"] = page.locator(".photos-lb-top .btn").evaluate_all(
                    "els=>els.map(el=>{const b=el.getBoundingClientRect();const range=document.createRange();range.selectNodeContents(el);const t=range.getBoundingClientRect();return {id:el.id,width:b.width,height:b.height,textLeft:t.left-b.left,textRight:b.right-t.right}})"
                )
                page.screenshot(path=str(out / (label + "-gallery.png")))
                close = page.locator("#photos-close-btn")
                expect(close).to_be_focused()
                page.keyboard.press("Tab")
                page.keyboard.press("Shift+Tab")
                expect(close).to_be_focused()
                assert close.evaluate(
                    "el=>el.matches(':focus-visible') && (getComputedStyle(el).outlineStyle !== 'none' || getComputedStyle(el).boxShadow !== 'none')"
                )
                page.locator("#photos-info-btn").focus()
                page.keyboard.press("Enter")
                expect(page.locator("#photos-lightbox")).to_have_class(re.compile("drawer-open"))
                page.locator("#photos-info-btn").click()
                page.locator("#photos-edit-btn").focus()
                page.keyboard.press("Enter")
                expect(page.locator("#imgeditor-modal")).to_be_visible()
                expect(page.locator("#photos-lightbox")).to_be_hidden()
                page.locator('#imgeditor-modal [data-act="close"]').click()
                expect(page.locator("#imgeditor-modal")).to_be_hidden()
                opener = page.get_by_role("button", name="open " + image_path.name, exact=True)
                opener.click()
                expect(close).to_be_focused()
                if width in (320, 390):
                    close.tap()
                else:
                    page.keyboard.press("Enter")
                expect(page.locator("#photos-lightbox")).to_be_hidden()
                expect(opener).to_be_focused()
                page.goto(base + "/?app=andromeda", wait_until="networkidle")
                page.locator("#andromeda-query").fill("synthetic local query !ai")
                page.locator("#andromeda-query").press("Enter")
                title = page.locator(".andromeda-result-title").first
                expect(title).to_be_visible()
                title.focus()
                row["search"] = title.evaluate(
                    "el=>{const b=el.getBoundingClientRect();return {width:b.width,height:b.height,topHit:document.elementFromPoint(b.left+b.width/2,b.top+1)?.closest('a')===el,bottomHit:document.elementFromPoint(b.left+b.width/2,b.bottom-1)?.closest('a')===el}}"
                )
                page.screenshot(path=str(out / (label + "-search.png")))
                assert row["search"]["topHit"] and row["search"]["bottomHit"]
                page.keyboard.press("Tab")
                page.keyboard.press("Shift+Tab")
                expect(title).to_be_focused()
                assert title.evaluate(
                    "el=>el.matches(':focus-visible') && (getComputedStyle(el).outlineStyle !== 'none' || getComputedStyle(el).boxShadow !== 'none')"
                )
                with page.expect_popup() as popup:
                    page.keyboard.press("Enter")
                expect(popup.value.get_by_role("heading")).to_have_text(
                    "owned synthetic destination"
                )
                popup.value.close()
                save = page.locator(".andromeda-news-save").first
                box = save.bounding_box()
                linkbox = title.bounding_box()
                assert box["y"] >= linkbox["y"] + linkbox["height"]
                if width in (320, 390):
                    save.tap()
                else:
                    save.click()
                expect(save).to_have_text("open in Library")
                save.click()
                expect(page.locator(".read-article h1")).to_have_text("local result")
                page.goto(base + "/?app=andromeda", wait_until="networkidle")
                page.locator("#andromeda-query").fill("long synthetic local query !ai")
                page.locator("#andromeda-query").press("Enter")
                expect(title).to_have_text("long local result " * 12)
                assert title.bounding_box()["height"] >= 44
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                page.screenshot(path=str(out / (label + "-search-long.png")))
                row["page_errors"] = errors
                row["console_errors"] = console
                assert not console, console
                row["failures"] = [
                    r["id"] + " label escapes"
                    for r in row["gallery"]
                    if r["textLeft"] < -0.5 or r["textRight"] < -0.5
                ]
                if row["search"]["height"] < 44:
                    row["failures"].append("search title below44")
                assert not errors, errors
                assert not row["failures"], row["failures"]
                row["status"] = "passed"
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    finally:
        browser.close()
assert all(row["status"] == "passed" for row in rows), "see scenarios.json"
