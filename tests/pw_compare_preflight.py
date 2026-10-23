"""Compare draft recovery with synthetic responses on an owned local application."""

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
profiles += [(1440, t, True) for t in ["dark", "light"]]

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
            state = {"models": [], "mode": "fail", "catalog_fail": False, "catalog_hold": False}
            posts, held, catalogs, errors, console = [], [], [], [], []

            def route(request):
                url = request.request.url
                if urlparse(url).netloc != urlparse(base).netloc:
                    return request.abort()
                path = urlparse(url).path
                if path == "/api/models":
                    if state["catalog_hold"]:
                        state["catalog_hold"] = False
                        catalogs.append(request)
                        return None
                    return request.fulfill(
                        status=503 if state["catalog_fail"] else 200,
                        json={"detail": "owned interruption"}
                        if state["catalog_fail"]
                        else state["models"],
                    )
                if path == "/api/compare" and request.request.method == "POST":
                    posts.append(request.request.post_data_json)
                    if state["mode"] == "hold":
                        held.append(request)
                        return None
                    return request.fulfill(
                        status=503 if state["mode"] == "fail" else 200,
                        json={"compare_id": "owned", "count": 2},
                    )
                if path.startswith("/api/compare/owned/stream/"):
                    body = f"data: {json.dumps({'delta': 'synthetic answer ' + path.rsplit('/', 1)[-1]})}\n\ndata: [DONE]\n\n"
                    return request.fulfill(content_type="text/event-stream", body=body)
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
            row = {
                "scenario_id": "compare.preflight-recovery",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                page.goto(base + "/?view=compare", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    actual = worker.evaluate("""async () => {
                        const tab = (await chrome.tabs.query({})).find(t => t.url.startsWith('http://127.0.0.1:'));
                        await chrome.tabs.setZoom(tab.id, 2); return chrome.tabs.getZoom(tab.id);
                    }""")
                    assert actual == 2
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                expect(page.locator("#compare-model-status")).to_contain_text("no models available")
                field = page.locator("#compare-input")
                draft = "  compare these local notes\nwithout losing whitespace  "
                field.fill(draft)
                page.locator("#compare-send-btn").click()
                expect(field).to_have_value(draft)
                expect(field).to_be_focused()
                assert not posts
                page.screenshot(path=str(out / f"{label}-no-model.png"))
                setup = page.locator("#compare-model-setup")
                setup.focus()
                page.keyboard.press("Enter")
                expect(page.locator("#s-pane-models")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator("#settings-modal")).to_be_hidden()
                expect(setup).to_be_focused()
                expect(field).to_have_value(draft)
                state["models"] = [
                    {
                        "id": "owned",
                        "name": "local fixture",
                        "enabled": True,
                        "models": ["synthetic alpha", "synthetic beta"],
                    }
                ]
                page.locator("#compare-model-refresh").click()
                alpha = page.get_by_role("checkbox", name="synthetic alpha", exact=True)
                beta = page.get_by_role("checkbox", name="synthetic beta", exact=True)
                expect(alpha).to_be_visible()
                page.locator("#compare-send-btn").click()
                expect(field).to_have_value(draft)
                assert not posts
                alpha.focus()
                page.keyboard.press("Space")
                expect(alpha).to_have_attribute("aria-checked", "true")
                beta.focus()
                page.keyboard.press("Enter")
                expect(beta).to_have_attribute("aria-checked", "true")
                page.locator("#compare-send-btn").click()
                expect(page.locator(".toast").last).to_contain_text("could not start comparison")
                expect(field).to_have_value(draft)
                expect(field).to_be_focused()
                assert len(posts) == 1
                page.screenshot(path=str(out / f"{label}-failed.png"))
                state["mode"] = "hold"
                page.locator("#compare-send-btn").focus()
                page.keyboard.press("Enter")
                expect(page.locator("#compare-send-btn")).to_be_disabled()
                expect(field).to_have_value(draft)
                page.wait_for_timeout(50)
                assert len(held) == 1 and len(posts) == 2
                field.fill("next draft stays here")
                held.pop().fulfill(json={"compare_id": "owned", "count": 2})
                expect(page.locator("#compare-grid")).to_contain_text("synthetic answer 1")
                expect(field).to_have_value("next draft stays here")
                state["mode"] = "success"
                page.locator("#compare-send-btn").click()
                expect(field).to_have_value("")
                expect(page.locator("#compare-grid")).to_contain_text("synthetic answer 0")
                assert len(posts) == 3
                assert posts[0]["message"] == draft.strip()
                assert posts[2]["message"] == "next draft stays here"
                field.fill("preserved during catalog retry")
                # Late failures must leave the user's newer keyboard or modal focus alone.
                state["mode"] = "hold"
                for newer in ["checkbox", "settings"]:
                    page.locator("#compare-send-btn").press("Enter")
                    for _ in range(100):
                        if held:
                            break
                        page.wait_for_timeout(10)
                    assert len(held) == 1
                    if newer == "settings":
                        setup.press("Enter")
                        page.wait_for_function(
                            "document.querySelector('#settings-modal').contains(document.activeElement)"
                        )
                    else:
                        alpha.focus()
                    held.pop().fulfill(status=503, json={"detail": "synthetic unavailable"})
                    expect(page.locator("#compare-send-btn")).to_be_enabled()
                    expect(field).to_have_value("preserved during catalog retry")
                    if newer == "settings":
                        assert page.evaluate(
                            "document.querySelector('#settings-modal').contains(document.activeElement)"
                        )
                        page.keyboard.press("Escape")
                        expect(setup).to_be_focused()
                    else:
                        expect(alpha).to_be_focused()
                refresh = page.locator("#compare-model-refresh")
                for newer in ["checkbox", "prompt", "settings", "removed"]:
                    state["catalog_hold"] = True
                    refresh.press("Enter")
                    for _ in range(100):
                        if catalogs:
                            break
                        page.wait_for_timeout(10)
                    assert len(catalogs) == 1
                    if newer == "settings":
                        setup.press("Enter")
                        page.wait_for_function(
                            "document.querySelector('#settings-modal').contains(document.activeElement)"
                        )
                    elif newer == "prompt":
                        field.focus()
                    else:
                        alpha.focus()
                    catalogs.pop().fulfill(json=[] if newer == "removed" else state["models"])
                    expect(refresh).to_be_enabled()
                    if newer == "settings":
                        assert page.evaluate(
                            "document.querySelector('#settings-modal').contains(document.activeElement)"
                        )
                        page.keyboard.press("Escape")
                        expect(setup).to_be_focused()
                    elif newer == "prompt":
                        expect(field).to_be_focused()
                    elif newer == "removed":
                        expect(alpha).to_have_count(0)
                        expect(refresh).to_be_focused()
                    else:
                        expect(alpha).to_be_focused()
                        expect(alpha).to_have_attribute("aria-checked", "true")
                state["catalog_hold"] = False
                refresh.press("Enter")
                expect(alpha).to_be_visible()
                alpha.press("Space")
                beta.press("Space")
                state["catalog_fail"] = True
                page.locator("#compare-model-refresh").click()
                expect(page.locator("#compare-model-status")).to_contain_text(
                    "could not load models"
                )
                expect(alpha).to_have_attribute("aria-checked", "true")
                expect(field).to_have_value("preserved during catalog retry")
                state["catalog_fail"] = False
                page.locator("#compare-model-refresh").click()
                expect(page.locator("#compare-model-status")).to_contain_text("select models")
                expect(alpha).to_have_attribute("aria-checked", "true")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                # The desktop result rail is 300px including its 32px gutters.
                assert field.bounding_box()["width"] >= (260 if width > 820 and not zoom else 280)
                for control in [
                    alpha,
                    beta,
                    setup,
                    page.locator("#compare-model-refresh"),
                    page.locator("#compare-send-btn"),
                ]:
                    box = control.bounding_box()
                    assert box["width"] >= 43.9 and box["height"] >= 43.9, box
                expect(page.locator(".toast")).to_have_count(0, timeout=10000)
                page.locator("#compare-body-1").scroll_into_view_if_needed()
                box = page.locator("#compare-body-1").bounding_box()
                assert box["y"] < page.evaluate("innerHeight") and box["y"] + box["height"] > 0
                page.screenshot(path=str(out / f"{label}-results.png"))
                assert not errors, errors
                assert len(console) == 4 and all("503" in item for item in console), console
                row.update(status="passed", posts=len(posts), native_zoom=zoom)
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
