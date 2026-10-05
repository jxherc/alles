"""Restore book edits safely against an owned local ledger, including delayed responses."""

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
            errors, console, external, held = [], [], [], []
            mode = "normal"

            def route(r):
                u = urlparse(r.request.url)
                if u.scheme + "://" + u.netloc != base:
                    external.append(r.request.url)
                    return r.abort()
                if mode == "fail-overview" and u.path == "/api/books/overview":
                    return r.fulfill(status=503, json={"detail": "owned refresh failure"})
                if u.path == "/api/books/" + bid and r.request.method == "PATCH":
                    payload = r.request.post_data_json
                    if mode == "lose-undo" and "expected_notes" in payload:
                        response = r.fetch()
                        assert response.ok
                        return r.fulfill(
                            status=503, json={"detail": "owned response lost after restore"}
                        )
                    if mode == "invalid-note" and "notes" in payload:
                        return r.fulfill(json={"id": bid, "notes": "wrong acknowledgment"})
                    if (mode == "hold-undo" and "expected_rating" in payload) or (
                        mode == "hold-note" and "notes" in payload
                    ):
                        held.append(r)
                        return None
                return r.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda ws: ws.close())
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
            original = "  first note 中文\nkeep spacing  "
            created = api.post(
                base + "/api/books", data={"title": "Local reading " + label, "notes": original}
            )
            assert created.ok
            bid = created.json()["id"]
            second = api.post(
                base + "/api/books",
                data={"title": "Other reading " + label, "notes": "other saved"},
            )
            assert second.ok
            other_id = second.json()["id"]
            page = context.new_page()
            page.set_default_timeout(6000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            page.goto(base + "/?view=books", wait_until="networkidle")
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
            card = page.locator(f'.book-card[data-id="{bid}"]')
            other = page.locator(f'.book-card[data-id="{other_id}"]')

            def stored(book_id=bid):
                response = api.get(base + "/api/books/overview")
                assert response.ok
                return next(
                    b
                    for shelf in response.json()["shelves"].values()
                    for b in shelf
                    if b["id"] == book_id
                )

            def use(control):
                expect(control).to_be_enabled()
                if width <= 390:
                    control.tap()
                else:
                    control.press("Enter")

            def edit_note(value):
                use(card.locator('[data-act="notes"]'))
                card.locator('[data-f="notes"]').fill(value)
                use(card.locator('[data-act="save-notes"]'))

            def wait_held():
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(20)
                assert len(held) == 1

            def capture(suffix):
                card.scroll_into_view_if_needed()
                cdp = context.new_cdp_session(page)
                shot = cdp.send(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                (out / f"{label}-{suffix}.png").write_bytes(base64.b64decode(shot["data"]))
                cdp.detach()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

            use(card.locator('[data-rate="4"]'))
            expect(card.locator('[data-undo="rating"]')).to_be_visible()
            mode = "invalid-note"
            revised = "revised note 中文\nsecond line"
            edit_note(revised)
            expect(card.locator(".book-notes-edit")).to_contain_text(
                "could not confirm this change"
            )
            expect(card.locator('[data-f="notes"]')).to_have_value(revised)
            assert stored()["notes"] == original
            mode = "normal"
            use(card.locator('[data-act="save-notes"]'))
            expect(card.locator('[data-undo="notes"]')).to_be_visible()
            assert stored()["rating"] == 4 and stored()["notes"] == revised
            capture("undo-available")
            use(card.locator('[data-undo="rating"]'))
            expect(card.locator('[data-undo="rating"]')).to_have_count(0)
            assert stored()["rating"] == 0 and stored()["notes"] == revised
            use(card.locator('[data-undo="notes"]'))
            expect(card.locator('[data-undo="notes"]')).to_have_count(0)
            assert stored()["notes"] == original
            expect(card).to_be_focused()
            edit_note("changed for lost response")
            expect(card.locator('[data-undo="notes"]')).to_be_visible()
            mode = "lose-undo"
            use(card.locator('[data-undo="notes"]'))
            expect(card.locator(".book-write-error")).to_contain_text(
                "owned response lost after restore"
            )
            assert stored()["notes"] == original
            mode = "normal"
            use(card.locator('[data-undo="notes"]'))
            expect(card.locator('[data-undo="notes"]')).to_have_count(0)
            assert stored()["notes"] == original
            edit_note("before concurrent edit")
            expect(card.locator('[data-undo="notes"]')).to_be_visible()
            assert api.patch(base + "/api/books/" + bid, data={"notes": "newer saved note"}).ok
            use(card.locator('[data-undo="notes"]'))
            expect(card.locator(".book-write-error")).to_contain_text("newer values were kept")
            expect(card.locator('[data-act="notes"]')).to_have_text("newer saved note")
            expect(card.locator('[data-undo="notes"]')).to_have_count(0)
            assert stored()["notes"] == "newer saved note"
            capture("conflict-kept")
            use(card.locator('[data-rate="5"]'))
            expect(card.locator('[data-undo="rating"]')).to_be_visible()
            mode = "hold-undo"
            use(card.locator('[data-undo="rating"]'))
            wait_held()
            expect(card.locator('[data-rate="4"]')).to_be_disabled()
            use(other.locator('[data-act="notes"]'))
            draft = other.locator('[data-f="notes"]')
            draft.fill("newer unsaved draft 中文")
            draft.evaluate("e=>e.setSelectionRange(4,9)")
            mode = "normal"
            held.pop().continue_()
            expect(card.locator('[data-undo="rating"]')).to_have_count(0)
            expect(draft).to_have_value("newer unsaved draft 中文")
            expect(draft).to_be_focused()
            assert draft.evaluate("e=>[e.selectionStart,e.selectionEnd]") == [4, 9]
            assert stored()["rating"] == 0
            mode = "hold-note"
            edit_note("pending note save")
            wait_held()
            use(other.locator('[data-act="notes"]'))
            draft.fill("latest draft stays here 中文")
            draft.evaluate("e=>e.setSelectionRange(2,7)")
            mode = "normal"
            held.pop().continue_()
            expect(card.locator('[data-act="notes"]')).to_have_text("pending note save")
            expect(draft).to_be_focused()
            expect(draft).to_have_value("latest draft stays here 中文")
            assert draft.evaluate("e=>[e.selectionStart,e.selectionEnd]") == [2, 7]
            use(other.locator('[data-act="cancel-notes"]'))

            # A saved field stays current even when the following overview fails.
            mode = "fail-overview"
            use(card.locator('[data-rate="2"]'))
            expect(card.locator('[data-undo="rating"]')).to_be_visible()
            expect(card.locator('[data-rate="2"]')).to_have_attribute("aria-checked", "true")
            use(card.locator('[data-rate="5"]'))
            expect(card.locator('[data-rate="5"]')).to_have_attribute("aria-checked", "true")
            expect(card).not_to_have_attribute("aria-busy", "true")
            use(card.locator('[data-undo="rating"]'))
            expect(card.locator('[data-undo="rating"]')).to_have_count(0)
            expect(card.locator('[data-rate="2"]')).to_have_attribute("aria-checked", "true")
            assert stored()["rating"] == 2
            edit_note("first acknowledged note")
            expect(card.locator('[data-act="notes"]')).to_have_text("first acknowledged note")
            expect(card.locator('[data-undo="notes"]')).to_be_visible()
            edit_note("second acknowledged note")
            expect(card.locator('[data-act="notes"]')).to_have_text("second acknowledged note")
            expect(card.locator('[data-undo="notes"]')).to_be_enabled()
            use(card.locator('[data-undo="notes"]'))
            expect(card.locator('[data-undo="notes"]')).to_have_count(0)
            expect(card.locator('[data-act="notes"]')).to_have_text("first acknowledged note")
            assert stored()["notes"] == "first acknowledged note"
            mode = "normal"

            # Completing an older undo must keep the user's newer button focus.
            use(card.locator('[data-rate="3"]'))
            expect(card.locator('[data-undo="rating"]')).to_be_visible()
            mode = "hold-undo"
            use(card.locator('[data-undo="rating"]'))
            wait_held()
            other_button = other.locator('[data-act="notes"]')
            other_button.focus()
            mode = "normal"
            held.pop().continue_()
            expect(card.locator('[data-undo="rating"]')).to_have_count(0)
            expect(card).not_to_have_attribute("aria-busy", "true")
            expect(other_button).to_be_focused()

            page.reload(wait_until="networkidle")
            assert stored()["notes"] == "first acknowledged note"
            assert stored(other_id)["notes"] == "other saved"
            boxes = page.locator(".books-bar button").evaluate_all(
                "els=>els.map(e=>({label:e.textContent.trim(),x:e.getBoundingClientRect().x,width:e.getBoundingClientRect().width,viewport:innerWidth}))"
            )
            assert all(b["x"] >= 0 and b["x"] + b["width"] <= b["viewport"] for b in boxes), boxes
            use(page.locator("#books-add-toggle"))
            expect(page.locator("#book-title")).to_be_focused()
            use(page.locator("#book-cancel"))
            expect(page.locator("#books-add-toggle")).to_be_focused()
            page.locator(".books-bar").scroll_into_view_if_needed()
            page.screenshot(path=str(out / f"{label}-header.png"))
            assert not errors and not external, (errors, external)
            assert (
                len(console) == 8
                and sum("503" in m for m in console) == 7
                and any("409" in m for m in console)
            ), console
            rows.append(
                {
                    "profile": label,
                    "status": "passed",
                    "checks": "exact prior rating/notes, rejected invalid acknowledgment keeps draft, lost undo response/retry, newer saved edit protected, held undo and note save preserve newer other-book draft/focus/selection, saved fields and immediate prior undo survive failed overview, newer button focus preserved, header controls fit and open/close by keyboard or touch, reload readback",
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
