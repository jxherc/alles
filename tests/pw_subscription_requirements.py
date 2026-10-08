"""Required subscription inputs, actual date selection and safe uncertain-save retries."""

import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path.cwd()))
from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 820, 390, 320] for t in ["light", "dark"]] + [
    (1440, t, True) for t in ["light", "dark"]
]
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 844},
                service_workers="block",
                reduced_motion="reduce" if theme == "dark" else "no-preference",
                has_touch=width <= 390,
            )
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned zoom",
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
            errors, console, external, held, writes = [], [], [], [], []
            mode = "normal"
            name = "Local renewal " + label
            held_name = "Delayed renewal " + label
            detected_name = "Detected renewal " + label

            def route(r):
                u = urlparse(r.request.url)
                if u.scheme + "://" + u.netloc != base:
                    external.append(r.request.url)
                    return r.abort()
                if u.path == "/api/subscriptions/detect":
                    return r.fulfill(
                        json={
                            "candidates": [
                                {"payee": detected_name, "amount": -9, "cycle": "monthly"}
                            ]
                        }
                    )
                if u.path == "/api/subscriptions" and r.request.method == "POST":
                    writes.append(r.request.post_data_json)
                    if mode == "reject":
                        return r.fulfill(
                            status=422, json={"detail": "owned refusal; revise and retry"}
                        )
                    if mode == "lose":
                        response = r.fetch()
                        assert response.ok, response.text()
                        return r.fulfill(status=503, json={"detail": "owned saved response lost"})
                    if mode == "hold":
                        held.append(r)
                        return None
                return r.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda ws: ws.close())
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
            page = context.new_page()
            page.set_default_timeout(6000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            page.goto(base + "/?view=subs", wait_until="networkidle")
            if zoom:
                worker = (
                    context.service_workers[0]
                    if context.service_workers
                    else context.wait_for_event("serviceworker")
                )
                assert (
                    worker.evaluate(
                        "async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,2);return chrome.tabs.getZoom(t.id)}",
                        base,
                    )
                    == 2
                )
                page.wait_for_function(
                    "innerWidth===720 && innerHeight===422 && devicePixelRatio===2"
                )
            add = page.locator("#sub-add-btn")
            field = page.locator("#sub-name")
            due = page.locator("#sub-due")
            hint = page.locator("#sub-required")

            def use(control):
                expect(control).to_be_enabled()
                if width <= 390:
                    control.tap()
                else:
                    control.press("Enter")

            def select_date():
                use(due)
                use(page.locator(".dp-now"))
                assert due.evaluate("e=>e.value")

            def stored():
                response = api.get(base + "/api/subscriptions?advance=false")
                assert response.ok
                return [
                    s
                    for s in response.json()["subscriptions"]
                    if s["name"] in [name, held_name, detected_name]
                ]

            def capture(suffix):
                cdp = context.new_cdp_session(page)
                shot = cdp.send(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                (out / f"{label}-{suffix}.png").write_bytes(base64.b64decode(shot["data"]))
                cdp.detach()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

            expect(add).to_be_disabled()
            expect(hint).to_have_text("enter a name and choose the next billing date.")
            expect(hint).to_have_attribute("aria-live", "polite")
            expect(add).to_have_attribute("aria-describedby", "sub-required")
            field.fill("   ")
            expect(add).to_be_disabled()
            field.fill(name)
            expect(hint).to_have_text("choose the next billing date to continue.")
            expect(add).to_be_disabled()
            capture("date-needed")
            select_date()
            expect(add).to_be_enabled()
            due.evaluate(
                "e=>{window.clearChanges=0;e.addEventListener('change',()=>window.clearChanges++)}"
            )
            use(due)
            use(page.locator(".dp-clear"))
            assert due.evaluate("e=>e.value") == ""
            assert page.evaluate("window.clearChanges") == 1
            expect(add).to_be_disabled()
            expect(hint).to_have_text("choose the next billing date to continue.")
            expect(due).to_be_focused()
            assert writes == [] and stored() == []
            select_date()
            page.locator("#sub-price").fill("5")
            mode = "reject"
            use(add)
            expect(page.locator("#sub-create-status")).to_contain_text("owned refusal")
            expect(field).to_have_value(name)
            expect(field).to_be_enabled()
            expect(add).to_be_enabled()
            assert stored() == []
            field.fill(" ")
            expect(add).to_be_disabled()
            expect(hint).to_have_text("enter a name to continue.")
            field.fill(name)
            mode = "lose"
            use(add)
            expect(page.locator("#sub-create-status")).to_contain_text("could not confirm")
            expect(field).to_be_disabled()
            expect(add).to_be_enabled()
            expect(add).to_have_text("retry add")
            expect(hint).to_have_text("retry uses the original name and billing date.")
            assert len(stored()) == 1 and stored()[0]["price"] == 5
            capture("retry-ready")
            mode = "normal"
            use(add)
            expect(field).to_have_value("")
            expect(add).to_be_disabled()
            expect(hint).to_have_text("enter a name to continue.")
            assert len(stored()) == 1
            assert len(writes) == 3 and writes[1] == writes[2]
            assert writes[0]["request_id"] != writes[1]["request_id"]
            field.fill(held_name)
            mode = "hold"
            use(add)
            for _ in range(100):
                if held:
                    break
                page.wait_for_timeout(20)
            assert len(held) == 1
            expect(add).to_be_disabled()
            expect(field).to_be_disabled()
            mode = "normal"
            held.pop().continue_()
            expect(field).to_have_value("")
            expect(field).to_be_enabled()
            expect(add).to_be_disabled()
            assert len(stored()) == 2
            # Reviewing a detected candidate fills both requirements without saving.
            use(page.locator("[data-adopt]").first)
            expect(field).to_have_value(detected_name)
            expect(add).to_be_enabled()
            assert len(stored()) == 2 and len(writes) == 4
            use(add)
            expect(field).to_have_value("")
            expect(add).to_be_disabled()
            assert len(stored()) == 3
            page.reload(wait_until="networkidle")
            expect(add).to_be_disabled()
            expect(hint).to_have_text("enter a name and choose the next billing date.")
            assert len(stored()) == 3
            capture("saved-reloaded")
            assert not errors and not external, (errors, external)
            assert (
                len(console) == 2
                and any("422" in m for m in console)
                and any("503" in m for m in console)
            ), console
            rows.append(
                {
                    "profile": label,
                    "status": "passed",
                    "checks": "empty/whitespace/name/date requirements and hints, actual date select/clear emits change and restores focus, rejected create editable, committed create lost response/retry same request no duplicate, busy add disabled, detected prefill requires review, actual saved reload",
                    "viewport": page.evaluate(
                        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"
                    ),
                    "console": console,
                }
            )
            (out / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")
            context.close()
    finally:
        browser.close()
