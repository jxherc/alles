"""Persistent book/habit labels and exact saved values through recovery, including native zoom."""

import base64
import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

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
                        "console",
                        lambda m: (
                            console.append({"text": m.text, "url": m.location.get("url", "")})
                            if m.type == "error"
                            else None
                        ),
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

                    page.goto(base + "/?view=books", wait_until="networkidle")
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
                    for surface in ("books", "habits"):
                        record = {"profile": label, "surface": surface, "status": "failed"}
                        records.append(record)
                        try:
                            page.goto(base + "/?view=" + surface, wait_until="networkidle")

                            def labelled(field, text):
                                labels = field.evaluate(
                                    "e=>[...(e.labels||[])].map(l=>({text:l.textContent.trim(),visible:!!l.getClientRects().length}))"
                                )
                                assert any(
                                    text in item["text"] and item["visible"] for item in labels
                                ), labels

                            if surface == "books":
                                page.locator("#books-add-toggle").press("Enter")
                                title = "reading & notes " + label
                                author = 'writer "synthetic"'
                                page.locator("#book-title").fill(title)
                                page.locator("#book-author").fill(author)
                                labelled(page.locator("#book-title"), "book title")
                                labelled(page.locator("#book-author"), "book author")
                                capture("books-filled")
                                page.locator("#book-cancel").press("Enter")
                                expect(page.locator("#books-add-toggle")).to_be_focused()
                                page.locator("#books-add-toggle").press("Enter")
                                expect(page.locator("#book-title")).to_have_value(title)
                                expect(page.locator("#book-author")).to_have_value(author)

                                def fail_book(route):
                                    route.fulfill(
                                        status=503, json={"detail": "synthetic local save outage"}
                                    )

                                page.route(base + "/api/books", fail_book)
                                page.locator("#book-create").press("Enter")
                                expect(page.locator("#book-create-error")).to_contain_text(
                                    "synthetic"
                                )
                                expect(page.locator("#book-title")).to_have_value(title)
                                expect(page.locator("#book-author")).to_have_value(author)
                                labelled(page.locator("#book-title"), "book title")
                                labelled(page.locator("#book-author"), "book author")
                                capture("books-retry")
                                page.unroute(base + "/api/books", fail_book)
                                page.locator("#book-create").press("Enter")
                                expect(page.locator("#book-create-open")).to_be_visible()
                                book_rows = [
                                    b
                                    for shelf in api.get(base + "/api/books/overview")
                                    .json()["shelves"]
                                    .values()
                                    for b in shelf
                                    if b["title"] == title
                                ]
                                assert len(book_rows) == 1 and book_rows[0]["author"] == author
                                page.locator("#book-create-open").press("Enter")
                                card = page.locator(
                                    '.book-card[data-id="' + book_rows[0]["id"] + '"]'
                                )
                                expect(card).to_be_focused()
                                page.reload(wait_until="networkidle")
                                expect(card).to_contain_text(title)
                                expect(card).to_contain_text(author)
                                record["saved_record"] = book_rows[0]["id"]
                                assert api.delete(base + "/api/books/" + book_rows[0]["id"]).ok
                            else:
                                page.locator("#habits-add-toggle").press("Enter")
                                form = page.locator(".habit-add")
                                name = "read & rest " + label
                                form.locator('[data-f="name"]').fill(name)
                                labelled(form.locator('[data-f="name"]'), "habit name")
                                labelled(form.locator('[data-f="icon"]'), "icon")
                                cadence = form.locator('[data-f="cadence"]')
                                label_id = cadence.get_attribute("aria-labelledby")
                                assert label_id and page.locator("#" + label_id).is_visible()
                                expect(page.locator("#" + label_id)).to_have_text("frequency")
                                expect(form.locator(".habit-target-field")).to_be_hidden()
                                expect(form.locator(".habit-cadence-help")).to_contain_text(
                                    "each day"
                                )
                                capture("habit-daily")
                                cadence.press("End")
                                cadence.press("Enter")
                                expect(cadence).to_have_attribute("data-value", "weekly")
                                target = form.locator('[data-f="target"]')
                                expect(target).to_be_visible()
                                labelled(target, "days per week")
                                target.fill("4")
                                cadence.press("Home")
                                cadence.press("Enter")
                                expect(target).to_be_hidden()
                                cadence.press("End")
                                cadence.press("Enter")
                                expect(target).to_have_value("4")
                                expect(form.locator(".habit-cadence-help")).to_contain_text(
                                    "each week"
                                )
                                field_geometry = form.evaluate(
                                    "e=>{const label=e.querySelector('[data-f=cadence] .custom-select-label'),icon=e.querySelector('[data-f=icon]'),cadence=e.querySelector('[data-f=cadence]');return {labelWidth:label.clientWidth,labelScroll:label.scrollWidth,iconHeight:icon.getBoundingClientRect().height,cadenceHeight:cadence.getBoundingClientRect().height}}"
                                )
                                record["weekly_field_geometry"] = field_geometry
                                assert (
                                    field_geometry["labelScroll"] <= field_geometry["labelWidth"]
                                    and abs(
                                        field_geometry["iconHeight"]
                                        - field_geometry["cadenceHeight"]
                                    )
                                    <= 1
                                ), field_geometry
                                capture("habit-weekly")

                                def fail_habit(route):
                                    route.fulfill(
                                        status=503, json={"detail": "synthetic local save outage"}
                                    )

                                page.route(base + "/api/habits", fail_habit)
                                form.locator('[data-act="create"]').press("Enter")
                                expect(form.locator(".habit-create-error")).to_contain_text(
                                    "input is kept"
                                )
                                expect(form.locator('[data-f="name"]')).to_have_value(name)
                                expect(form.locator('[data-f="target"]')).to_have_value("4")
                                labelled(form.locator('[data-f="name"]'), "habit name")
                                labelled(form.locator('[data-f="target"]'), "days per week")
                                capture("habit-retry")
                                page.unroute(base + "/api/habits", fail_habit)
                                form.locator('[data-act="create"]').press("Enter")
                                expect(form).to_have_count(0)
                                habit_rows = [
                                    h
                                    for h in api.get(base + "/api/habits/overview").json()["habits"]
                                    if h["name"] == name
                                ]
                                assert (
                                    len(habit_rows) == 1
                                    and habit_rows[0]["cadence"] == "weekly"
                                    and habit_rows[0]["target"] == 4
                                )
                                hid = habit_rows[0]["id"]
                                page.reload(wait_until="networkidle")
                                card = page.locator('.habit-card[data-id="' + hid + '"]')
                                expect(card).to_contain_text(name)
                                card.locator('[data-act="edit"]').press("Enter")
                                labelled(card.locator('[data-f="name"]'), "habit name")
                                labelled(card.locator('[data-f="target"]'), "days per week")
                                expect(card.locator('[data-f="target"]')).to_have_value("4")
                                capture("habit-edit")
                                card.locator('[data-f="name"]').fill(name + " cancelled")
                                card.locator('[data-act="cancel"]').press("Enter")
                                expect(card).to_contain_text(name)
                                assert (
                                    next(
                                        h
                                        for h in api.get(base + "/api/habits/overview").json()[
                                            "habits"
                                        ]
                                        if h["id"] == hid
                                    )["name"]
                                    == name
                                )
                                record["saved_record"] = hid
                                assert api.delete(base + "/api/habits/" + hid).ok
                            unexpected_console = [
                                m
                                for m in console
                                if m["text"]
                                != "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
                                or m["url"] not in (base + "/api/books", base + "/api/habits")
                            ]
                            assert not errors and not external and not unexpected_console, (
                                errors,
                                external,
                                unexpected_console,
                            )
                            record["expected_synthetic_outages"] = list(console)
                            geometry = page.evaluate(
                                "({width:innerWidth,scroll:document.documentElement.scrollWidth,zoom:devicePixelRatio})"
                            )
                            assert geometry["scroll"] <= geometry["width"]
                            record.update(
                                status="passed",
                                filled_labels=True,
                                retry_keeps_exact_values=True,
                                one_saved_record=True,
                                reload=True,
                                cancel=True,
                                geometry=geometry,
                            )
                        except Exception:
                            record["failure"] = traceback.format_exc()
                            capture(surface + "-failure")
                        finally:
                            record.update(
                                page_errors=list(errors),
                                console_errors=list(console),
                                external=list(external),
                            )
                            (out / "scenarios.json").write_text(
                                json.dumps(records, indent=2) + "\n"
                            )
                    context.close()
        finally:
            browser.close()
    assert len(records) == 12 and all(row["status"] == "passed" for row in records), records


if __name__ == "__main__":
    run()
