"""Aide context choices remain reachable and preserve the exact composer draft."""

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
profiles = [(w, t, False) for w in [1440, 768, 390, 320] for t in ["dark", "light"]]
profiles += [(1440, t, True) for t in ["dark", "light"]]
choices = {
    "plan": "plan",
    "inbox": "inbox",
    "library": "library",
    "health": "health",
    "finance": "finance",
    "wiki": "docs · @wiki",
    "files": "files",
    "photos": "files · gallery",
    "vault": "vault",
    "days": "plan · days",
    "journal": "docs · journal",
    "activity": "server · activity",
}
rows = []


def visible_geometry(page, target=None, focus=False):
    result = page.locator("#_more_tools_menu").evaluate("""menu => ({
      box: menu.getBoundingClientRect().toJSON(), width: innerWidth, height: innerHeight,
      visible: {left: visualViewport.offsetLeft, top: visualViewport.offsetTop,
        width: visualViewport.width, height: visualViewport.height, scale: visualViewport.scale},
      pageWidth: document.documentElement.scrollWidth,
      clientWidth: menu.clientWidth, scrollWidth: menu.scrollWidth,
      clientHeight: menu.clientHeight, scrollHeight: menu.scrollHeight,
    })""")
    box = result["box"]
    viewport = result["visible"]
    assert (
        box["left"] >= viewport["left"] + 8
        and box["right"] <= viewport["left"] + viewport["width"] - 8
    ), result
    assert (
        box["top"] >= viewport["top"] + 8
        and box["bottom"] <= viewport["top"] + viewport["height"] - 8
    ), result
    assert result["scrollWidth"] <= result["clientWidth"] + 1, result
    assert result["pageWidth"] <= result["width"] + 1, result
    if target is not None:
        control = target.evaluate("""e => {
          const r=e.getBoundingClientRect(), s=getComputedStyle(e);
          return {box:r.toJSON(), font:parseFloat(s.fontSize),
            hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),
            focus:e===document.activeElement,
            ring:parseFloat(s.outlineWidth)>0 && s.outlineStyle!=='none' || s.boxShadow!=='none'};
        }""")
        r = control["box"]
        assert r["width"] >= 44 and r["height"] >= 44, control
        assert r["top"] >= box["top"] and r["bottom"] <= box["bottom"], control
        assert control["font"] >= 13 and control["hit"], control
        if focus:
            assert control["focus"] and control["ring"], control
    return result


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            height = 1000 if width == 1440 else 1024 if width == 768 else 844
            options = {
                "viewport": {"width": width, "height": height},
                "service_workers": "block",
                "reduced_motion": "reduce" if theme == "dark" else "no-preference",
                "has_touch": width <= 390,
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
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"scenario_id": "aide.app-context", "profile": label, "status": "failed"}
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                page.goto(base + "/?view=chat", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate("""async () => {
                      const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));
                      await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id);
                    }""")
                        == 2
                    )
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                    row["zoom"] = page.evaluate(
                        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"
                    )
                field = page.locator("#composer-ta")
                trigger = page.locator("#more-tools-btn")
                menu = page.locator("#_more_tools_menu")
                draft = "before selected after"
                field.fill(draft)
                trigger.focus()
                page.keyboard.press("Enter")
                expect(menu.get_by_role("menuitem", name="upload file")).to_be_focused()
                page.keyboard.press("ArrowDown")
                expect(menu.get_by_role("menuitem", name="link an app", exact=True)).to_be_focused()
                page.keyboard.press("Enter")
                expect(page.locator("[data-app-link]")).to_have_count(12)
                actual = page.locator("[data-app-link]").evaluate_all(
                    "es=>Object.fromEntries(es.map(e=>[e.dataset.appLink,e.textContent]))"
                )
                assert actual == choices, actual
                assert menu.get_by_role("group").count() == 3
                if not zoom:
                    # Pinch scaling shrinks the visual viewport without moving
                    # the composer in the layout viewport. Native zoom is separate.
                    cdp = context.new_cdp_session(page)
                    cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2})
                    page.wait_for_function("visualViewport.scale === 2")
                    page.wait_for_timeout(100)
                    assert trigger.evaluate(
                        "e => e.getBoundingClientRect().top > visualViewport.offsetTop + visualViewport.height"
                    )
                    row["pinch_offscreen_trigger"] = visible_geometry(page)
                    page.keyboard.press("End")
                    visible_geometry(page, page.locator(":focus"), focus=True)
                    page.screenshot(path=str(out / f"{label}-pinch.png"))
                    cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
                    page.wait_for_function("visualViewport.scale === 1")
                    page.keyboard.press("Home")
                    cdp.detach()
                visited = []
                for _ in range(13):
                    target = page.locator(":focus")
                    visible_geometry(page, target, focus=True)
                    visited.append(target.text_content())
                    page.keyboard.press("ArrowDown")
                assert len(set(visited)) == 13, visited
                page.keyboard.press("End")
                expect(
                    menu.get_by_role("menuitem", name="server · activity", exact=True)
                ).to_be_focused()
                row["scrolled_menu"] = visible_geometry(page, page.locator(":focus"), focus=True)
                page.screenshot(path=str(out / f"{label}-last-choice.png"))
                page.keyboard.press("Home")
                expect(menu.get_by_role("menuitem", name="back to add context")).to_be_focused()
                page.keyboard.press("ArrowUp")
                expect(
                    menu.get_by_role("menuitem", name="server · activity", exact=True)
                ).to_be_focused()
                page.keyboard.press("ArrowLeft")
                expect(menu.get_by_role("menuitem", name="link an app", exact=True)).to_be_focused()
                page.keyboard.press("Enter")
                page.keyboard.press("Escape")
                expect(menu).to_have_count(0)
                expect(trigger).to_be_focused()
                expect(field).to_have_value(draft)

                # Every existing token stays selectable by a real pointer/tap.
                for token, name in choices.items():
                    field.fill(draft)
                    field.evaluate("e=>e.setSelectionRange(7,15)")
                    if width <= 390:
                        trigger.tap()
                    else:
                        trigger.click()
                    menu.get_by_role("menuitem", name="link an app", exact=True).click()
                    target = menu.get_by_role("menuitem", name=name, exact=True)
                    target.scroll_into_view_if_needed()
                    visible_geometry(page, target)
                    if width <= 390:
                        target.tap()
                    else:
                        target.click()
                    expect(menu).to_have_count(0)
                    expect(field).to_be_focused()
                    expect(field).to_have_value(f"before @{token}  after")
                    if token == "wiki":
                        expect(page.locator(".toast").last).to_contain_text(
                            "docs context added as @wiki"
                        )
                        page.reload(wait_until="networkidle")
                        expect(field).to_have_value("before @wiki  after")
                page.reload(wait_until="networkidle")
                expect(field).to_have_value("before @activity  after")
                trigger.click()
                menu.get_by_role("menuitem", name="link an app", exact=True).click()
                page.keyboard.press("End")
                page.set_viewport_size({"width": 640 if zoom else 320, "height": 700})
                page.wait_for_timeout(100)
                visible_geometry(page, page.locator(":focus"), focus=True)
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(100)
                visible_geometry(page, page.locator(":focus"), focus=True)
                page.screenshot(path=str(out / f"{label}-resized.png"))
                page.keyboard.press("Escape")
                expect(trigger).to_be_focused()

                trigger.click()
                menu.get_by_role("menuitem", name="link an app", exact=True).click()
                menu.get_by_role("menuitem", name="back to add context").click()
                expect(menu.get_by_role("menuitem", name="link an app", exact=True)).to_be_focused()
                trigger.click()
                expect(menu).to_have_count(0)
                expect(trigger).to_be_focused()
                trigger.click()
                page.keyboard.press("Tab")
                expect(menu).to_have_count(0)
                assert page.evaluate(
                    "document.activeElement!==document.body && document.activeElement.getBoundingClientRect().width>0"
                )
                trigger.click()
                field_box = field.bounding_box()
                field.click(position={"x": field_box["width"] - 8, "y": field_box["height"] / 2})
                expect(menu).to_have_count(0)
                expect(field).to_be_focused()
                trigger.click()
                with page.expect_file_chooser() as chooser:
                    page.keyboard.press("Enter")
                chooser.value.set_files([])
                expect(menu).to_have_count(0)
                expect(trigger).to_be_focused()
                expect(field).to_have_value("before @activity  after")
                assert not errors and not console and not external, (errors, console, external)
                row.update(
                    status="passed",
                    selected_tokens=list(choices),
                    keyboard_items=visited,
                    page_errors=errors,
                    console_errors=console,
                    external_attempts=external,
                )
            except Exception as error:
                row.update(
                    error=str(error),
                    traceback=traceback.format_exc(),
                    page_errors=errors,
                    console_errors=console,
                    external_attempts=external,
                )
                page.screenshot(path=str(out / f"{label}-failed.png"))
            finally:
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    finally:
        browser.close()
assert all(row["status"] == "passed" for row in rows), "see scenarios.json"
