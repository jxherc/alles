"""Gallery action discovery, keyboard ownership and local outcomes, including native zoom."""

import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        browser = pw.chromium.launch()
        try:
            for width, zoom in ((1440, 1), (390, 1), (1440, 2)):
                for theme in ("light", "dark"):
                    label = f"{width}-{theme}-zoom{zoom}"
                    options = dict(
                        viewport={"width": width, "height": 900},
                        reduced_motion="reduce",
                        service_workers="block",
                    )
                    if zoom == 2:
                        profile = Path(os.environ["ALLES_DATA"]) / label
                        ext = profile / "extension"
                        ext.mkdir(parents=True)
                        (ext / "manifest.json").write_text(
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
                        (ext / "zoom.js").write_text(
                            "chrome.runtime.onInstalled.addListener(() => {});"
                        )
                        context = pw.chromium.launch_persistent_context(
                            profile / "browser",
                            channel="chromium",
                            headless=True,
                            args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"],
                            **options,
                        )
                    else:
                        context = browser.new_context(**options)
                    errors, console, external = [], [], []
                    page = context.new_page()
                    page.set_default_timeout(5000)
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "console", lambda m: console.append(m.text) if m.type == "error" else None
                    )

                    def local_only(route):
                        target = urlsplit(route.request.url)
                        if (target.scheme, target.netloc) != ("http", urlsplit(base).netloc):
                            external.append(route.request.url)
                            return route.abort()
                        route.continue_()

                    context.route("**/*", local_only)
                    context.route_web_socket("**/*", lambda socket: socket.close())
                    assert api.put("/api/appearance", data=from_legacy(theme, None)).ok

                    def capture(state):
                        if zoom == 2:
                            shot = context.new_cdp_session(page).send(
                                "Page.captureScreenshot",
                                {"format": "png", "captureBeyondViewport": False},
                            )
                            (out / (label + "-" + state + ".png")).write_bytes(
                                base64.b64decode(shot["data"])
                            )
                        else:
                            page.screenshot(path=str(out / (label + "-" + state + ".png")))

                    record = {"profile": label, "status": "failed"}
                    records.append(record)
                    try:
                        page.goto(base + "/?view=scheduled", wait_until="networkidle")
                        if zoom == 2:
                            worker = (
                                context.service_workers[0]
                                if context.service_workers
                                else context.wait_for_event("serviceworker")
                            )
                            assert (
                                worker.evaluate(
                                    "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                                    base,
                                )
                                == 2
                            )
                            page.wait_for_function("innerWidth===720 && devicePixelRatio===2")
                        page.evaluate(
                            "() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))"
                        )
                        geometry = page.locator("#aide-scheduled-new").evaluate(
                            "e=>{const r=e.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(e);const t=range.getBoundingClientRect();return {buttonRight:r.right,textRight:t.right,fits:t.left>=r.left&&t.right<=r.right}}"
                        )
                        assert geometry["fits"], geometry
                        page.locator("#aide-scheduled-new").press("Enter")
                        expect(page.locator("#aide-schedule-form")).to_be_visible()
                        page.locator("#aide-schedule-cancel").press("Enter")
                        expect(page.locator("#aide-schedule-form")).to_be_hidden()
                        record["scheduled_geometry"] = geometry
                        capture("scheduled")
                        # Only synthetic job status: never start an import or inspect Apple Photos.
                        job_state = {"failed": False}
                        status_route = base + "/api/photos/sync/macos/status"
                        job_route = base + "/api/photos/sync/macos/jobs/owned-menu-job"

                        def mac_status(route):
                            route.fulfill(
                                status=200,
                                content_type="application/json",
                                body=json.dumps(
                                    {
                                        "platform": "darwin",
                                        "available": True,
                                        "authorization": "authorized",
                                        "job": None
                                        if job_state["failed"]
                                        else {
                                            "id": "owned-menu-job",
                                            "state": "running",
                                            "processed": 0,
                                            "total": 1,
                                        },
                                    }
                                ),
                            )

                        def mac_job(route):
                            route.fulfill(
                                status=200,
                                content_type="application/json",
                                body=json.dumps(
                                    {
                                        "id": "owned-menu-job",
                                        "state": "failed" if job_state["failed"] else "running",
                                        "processed": 0,
                                        "total": 1,
                                        "message": "synthetic local job failure",
                                    }
                                ),
                            )

                        context.route(status_route, mac_status)
                        context.route(job_route, mac_job)
                        page.goto(base + "/?view=files", wait_until="networkidle")
                        page.get_by_role("tab", name="gallery", exact=True).press("Enter")
                        expect(page.locator("#photos-view")).to_be_visible()
                        mac = page.locator("#photos-macos-btn")
                        expect(mac).to_be_disabled()
                        page.locator("#photos-more-btn").press("Enter")
                        expect(mac).to_have_attribute("aria-disabled", "true")
                        job_state["failed"] = True
                        page.wait_for_function(
                            "!document.querySelector('#photos-macos-btn').disabled"
                        )
                        expect(page.locator("#photos-more-menu")).to_be_visible()
                        expect(mac).to_have_attribute("aria-disabled", "false")
                        page.keyboard.press("Home")
                        cycle = []
                        for _ in range(7):
                            cycle.append(page.evaluate("document.activeElement.id"))
                            page.keyboard.press("ArrowDown")
                        assert "photos-macos-btn" in cycle, cycle
                        capture("job-failure-menu")
                        record["job_menu_recovery"] = {
                            "keyboard_cycle": cycle,
                            "reachable_without_reopen": True,
                            "fixture": "synthetic local status only; no native import or library access",
                        }
                        bounds = page.locator("#photos-more-menu").evaluate(
                            "e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:innerWidth,height:innerHeight}}"
                        )
                        record["job_menu_geometry"] = bounds
                        assert 0 <= bounds["left"] and bounds["right"] <= bounds["width"], bounds
                        if width == 390:
                            reopened = []
                            for resized_width in (1440, 390):
                                page.set_viewport_size({"width": resized_width, "height": 900})
                                expect(page.locator("#photos-more-menu")).to_be_hidden()
                                page.locator("#photos-more-btn").press("Enter")
                                bounds = page.locator("#photos-more-menu").evaluate(
                                    "e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,width:innerWidth}}"
                                )
                                assert 0 <= bounds["left"] and bounds["right"] <= bounds["width"], (
                                    bounds
                                )
                                reopened.append(bounds)
                            record["resize_reopen_geometry"] = reopened
                        page.locator("#photos-more-menu").get_by_role(
                            "menuitem", name="gallery settings", exact=True
                        ).click()
                        expect(page.locator("#photos-more-menu")).to_be_hidden()
                        expect(
                            page.locator('.app-settings-pop input[data-k="photos_dir"]')
                        ).to_be_focused()
                        record["pointer_menu_settings"] = True
                        page.locator("#photos-search").click()
                        expect(page.locator(".app-settings-pop")).to_have_count(0)
                        context.unroute(status_route, mac_status)
                        context.unroute(job_route, mac_job)
                        page.goto(base + "/?view=files", wait_until="networkidle")
                        page.get_by_role("tab", name="gallery", exact=True).press("Enter")
                        expect(page.locator("#photos-view")).to_be_visible()
                        assert (
                            page.locator(".photos-head").evaluate(
                                "e=>getComputedStyle(e,'::after').content"
                            )
                            == "none"
                        )
                        capture("header")
                        header = page.locator("#photos-more-btn")
                        menu = page.locator("#photos-more-menu")
                        header.press("ArrowDown")
                        expect(menu).to_be_visible()
                        expect(menu.get_by_role("menuitem").first).to_be_focused()
                        page.keyboard.press("End")
                        expect(page.locator("#photos-settings-btn")).to_be_focused()
                        page.keyboard.press("Escape")
                        expect(menu).to_be_hidden()
                        expect(header).to_be_focused()
                        header.press("Enter")
                        page.locator("#photos-settings-btn").press("Enter")
                        expect(menu).to_be_hidden()
                        expect(
                            page.locator('.app-settings-pop input[data-k="photos_dir"]')
                        ).to_be_focused()
                        page.locator("#photos-search").click()
                        expect(page.locator(".app-settings-pop")).to_have_count(0)
                        header.press("Enter")
                        page.locator("#photos-rescan-btn").press("Enter")
                        expect(menu).to_be_hidden()
                        expect(header).to_be_focused()
                        page.wait_for_load_state("networkidle")
                        fixture = out / (label + "-fixture.png")
                        Image.new("RGB", (120, 80), (60, 120, 180)).save(fixture)
                        with page.expect_file_chooser() as chooser:
                            page.locator("#photos-upload-btn").press("Enter")
                        chooser.value.set_files(str(fixture))
                        opener = page.get_by_role("button", name="open " + fixture.name, exact=True)
                        expect(opener).to_be_visible()
                        opener.press("Enter")
                        expect(page.locator("#photos-close-btn")).to_be_focused()
                        contrast = page.locator("#photos-lightbox").evaluate(
                            "e=>{const rgb=s=>s.match(/[\\d.]+/g).slice(0,3).map(Number),lum=s=>rgb(s).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0),bg=getComputedStyle(e).backgroundColor,b=lum(bg);return [...e.querySelectorAll('.photos-lb-top button')].filter(x=>x.getClientRects().length).map(x=>{const fg=getComputedStyle(x).color,f=lum(fg);return {id:x.id,fg,bg,ratio:(Math.max(f,b)+.05)/(Math.min(f,b)+.05)}})}"
                        )
                        assert all(item["ratio"] >= 4.5 for item in contrast), contrast
                        record["viewer_text_contrast"] = contrast
                        more = page.locator("#photos-viewer-more-btn")
                        viewer_menu = page.locator("#photos-viewer-more-menu")
                        controls = page.locator(".photos-lb-top").evaluate(
                            "e=>[...e.querySelectorAll('button,a')].filter(b=>b.getClientRects().length).map(b=>({id:b.id,top:b.getBoundingClientRect().top,right:b.getBoundingClientRect().right}))"
                        )
                        assert len(controls) == 4 and len({x["top"] for x in controls}) == 1, (
                            controls
                        )
                        assert all(x["right"] <= page.evaluate("innerWidth") for x in controls)
                        more.press("Enter")
                        expect(page.locator("#photos-archive-btn")).to_be_focused()
                        bounds = viewer_menu.evaluate(
                            "e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,width:innerWidth}}"
                        )
                        assert 0 <= bounds["left"] and bounds["right"] <= bounds["width"], bounds
                        record["viewer_menu_geometry"] = bounds
                        capture("viewer-menu")
                        page.keyboard.press("End")
                        expect(page.locator("#photos-del-btn")).to_be_focused()
                        page.keyboard.press("Home")
                        expect(page.locator("#photos-archive-btn")).to_be_focused()
                        page.keyboard.press("ArrowDown")
                        expect(page.locator("#photos-hide-btn")).to_be_focused()
                        page.keyboard.press("Escape")
                        expect(viewer_menu).to_be_hidden()
                        expect(page.locator("#photos-lightbox")).to_be_visible()
                        expect(more).to_be_focused()
                        more.press("Enter")
                        page.keyboard.press("Tab")
                        expect(viewer_menu).to_be_hidden()
                        expect(page.locator("#photos-lightbox")).to_be_visible()
                        assert page.locator("#photos-lightbox").evaluate(
                            "e=>e.contains(document.activeElement)"
                        )
                        more.press("Enter")
                        page.locator("#photos-del-btn").press(" ")
                        confirmation = page.get_by_role("alertdialog", name="delete this image?")
                        expect(confirmation).to_be_visible()
                        assert confirmation.evaluate("e=>e.contains(document.activeElement)")
                        confirmation.get_by_role("button", name="cancel", exact=True).press("Enter")
                        expect(confirmation).to_be_hidden()
                        expect(more).to_be_focused()
                        more.press("Enter")
                        with page.expect_download() as downloaded:
                            page.locator("#photos-dl-btn").press(" ")
                        downloaded.value.save_as(out / (label + "-download.png"))
                        assert (
                            hashlib.sha256((out / (label + "-download.png")).read_bytes()).digest()
                            == hashlib.sha256(fixture.read_bytes()).digest()
                        )
                        more.press("Enter")
                        page.locator("#photos-edit-btn").press("Enter")
                        expect(page.locator("#imgeditor-modal")).to_be_visible()
                        page.locator('#imgeditor-modal [data-act="close"]').press("Enter")
                        expect(page.locator("#imgeditor-modal")).to_be_hidden()
                        opener.press("Enter")
                        more.press("Enter")
                        page.locator("#photos-archive-btn").press("Enter")
                        expect(page.locator("#photos-lightbox")).to_be_hidden()
                        expect(opener).to_have_count(0)
                        page.get_by_role("button", name="archive", exact=True).press("Enter")
                        expect(opener).to_be_visible()
                        opener.press("Enter")
                        more.press("Enter")
                        page.locator("#photos-archive-btn").press("Enter")
                        expect(page.locator("#photos-lightbox")).to_be_hidden()
                        page.get_by_role("button", name="photos", exact=True).press("Enter")
                        expect(opener).to_be_visible()
                        page.reload(wait_until="networkidle")
                        opener.press("Enter")
                        more.press("Enter")
                        viewer_menu.get_by_role("menuitem", name="delete", exact=True).press(
                            "Enter"
                        )
                        page.get_by_role("button", name="confirm", exact=True).press("Enter")
                        expect(page.locator("#photos-lightbox")).to_be_hidden()
                        expect(opener).to_have_count(0)
                        assert not errors and not console and not external
                        record.update(
                            status="passed",
                            viewer_controls=controls,
                            native_zoom=zoom,
                            keyboard_menu_escape_tab=True,
                            download_bytes=True,
                            editor_reentry=True,
                            archive_unarchive_reload=True,
                            confirmed_delete=True,
                        )
                    except Exception as error:
                        record["error"] = str(error)
                    finally:
                        record.update(page_errors=errors, console_errors=console, external=external)
                        if zoom == 2:
                            shot = context.new_cdp_session(page).send(
                                "Page.captureScreenshot",
                                {"format": "png", "captureBeyondViewport": False},
                            )
                            (out / (label + ".png")).write_bytes(base64.b64decode(shot["data"]))
                        else:
                            page.screenshot(path=str(out / (label + "-final.png")))
                        (out / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
                        context.close()
        finally:
            api.dispose()
            browser.close()
    assert all(r["status"] == "passed" for r in records), records


if __name__ == "__main__":
    run()
