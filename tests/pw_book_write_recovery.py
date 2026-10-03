"""Owned local book writes, real saved state and synthetic rejected/lost responses."""

import json
import os
import traceback
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

base = f"http://127.0.0.1:{os.environ['PORT']}"
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 390):
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            service_workers="block",
            reduced_motion="reduce",
        )
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if urlparse(route.request.url).netloc == urlparse(base).netloc
                else route.abort()
            ),
        )
        api = context.request
        assert api.post(base + "/api/setup/dismiss").ok
        assert api.put(base + "/api/books/goal", data={"goal": 3}).ok
        created = api.post(
            base + "/api/books", data={"title": f"synthetic full book {width}", "status": "want"}
        )
        assert created.ok
        book = created.json()
        bid = book["id"]
        url = base + "/api/books/" + bid

        def current():
            return next(
                (
                    b
                    for shelf in api.get(base + "/api/books/overview").json()["shelves"].values()
                    for b in shelf
                    if b["id"] == bid
                ),
                None,
            )

        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        console = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console",
            lambda message: console.append(message.text) if message.type == "error" else None,
        )
        context.tracing.start(screenshots=True, snapshots=True)

        def record(name):
            rows.append(
                {"scenario_id": "library.book." + name, "profile": str(width), "status": "passed"}
            )
            (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

        try:
            page.goto(base + "/?view=books", wait_until="networkidle")
            card = page.locator(f'.book-card[data-id="{bid}"]')
            expect(card).to_be_visible()
            page.route(
                url,
                lambda route: route.fulfill(status=503, json={"detail": "synthetic book outage"}),
            )
            card.locator('[data-move="reading"]').click()
            expect(card.get_by_role("alert")).to_contain_text("synthetic book outage")
            assert current()["status"] == "want"
            page.unroute(url)
            card.locator('[data-move="reading"]').click()
            expect(card.locator('[data-move="want"]')).to_be_enabled()
            assert current()["status"] == "reading"
            record("failed-move-retry-persists-and-unlocks-card")
            star = card.locator('[data-rate="4"]')
            star.focus()
            page.keyboard.press("Enter")
            expect(card.locator('[data-rate="4"]')).to_have_attribute("aria-checked", "true")
            expect(card.locator('[data-rate="4"]')).to_be_enabled()
            assert current()["rating"] == 4
            card.locator('[data-act="notes"]').click()
            card.locator("textarea").fill("Exact local notes.\n\nSecond paragraph.")
            card.locator('[data-act="save-notes"]').click()
            expect(card.locator(".book-notes")).to_have_text(
                "Exact local notes.\n\nSecond paragraph."
            )
            assert current()["notes"] == "Exact local notes.\n\nSecond paragraph."
            record("rating-keyboard-and-note-save-remain-usable")
            goal = base + "/api/books/goal"
            page.route(
                goal,
                lambda route: route.fulfill(status=503, json={"detail": "synthetic goal outage"}),
            )
            page.locator('[data-act="set-goal"]').click()
            page.get_by_role("dialog").get_by_role("textbox").fill("12")
            page.get_by_role("dialog").get_by_role("button", name="ok", exact=True).click()
            expect(page.locator(".toast.error").filter(has_text="synthetic goal")).to_be_visible()
            page.unroute(goal)
            page.locator('[data-act="set-goal"]').click()
            expect(page.get_by_role("dialog").get_by_role("textbox")).to_have_value("12")
            page.get_by_role("dialog").get_by_role("button", name="ok", exact=True).click()
            expect(page.locator(".books-goal")).to_contain_text("/ 12")
            assert api.get(base + "/api/books/overview").json()["goal"] == 12
            record("failed-goal-retains-number-for-real-retry")
            imports = base + "/api/books/import"
            csv = f"Title,Author,Exclusive Shelf\nSynthetic import {width},Local writer,to-read\n".encode()

            def choose():
                with page.expect_file_chooser() as chooser:
                    page.locator("#books-import").click()
                chooser.value.set_files(
                    {"name": "books.csv", "mimeType": "text/csv", "buffer": csv}
                )

            page.route(
                imports,
                lambda route: route.fulfill(status=503, json={"detail": "synthetic import outage"}),
            )
            choose()
            expect(page.locator(".toast.error").filter(has_text="synthetic import")).to_be_visible()
            page.unroute(imports)
            choose()
            expect(
                page.locator(".book-title").filter(has_text=f"Synthetic import {width}")
            ).to_be_visible()
            choose()
            expect(
                page.locator(".toast.success").filter(has_text="imported 0 books")
            ).to_be_visible()
            assert (
                page.locator(".book-title").filter(has_text=f"Synthetic import {width}").count()
                == 1
            )
            record("failed-import-retry-and-repeat-preserve-one-copy")

            def lose(route):
                response = route.fetch()
                assert response.ok
                route.fulfill(status=503, json={"detail": "synthetic lost delete reply"})

            page.route(url, lose)
            card.locator('[data-act="del"]').click()
            page.get_by_role("alertdialog").get_by_role(
                "button", name="confirm", exact=True
            ).click()
            expect(card.get_by_role("alert")).to_contain_text("synthetic lost delete")
            assert current() is None
            page.unroute(url)
            card.locator('[data-act="del"]').click()
            page.get_by_role("alertdialog").get_by_role(
                "button", name="confirm", exact=True
            ).click()
            expect(card).to_have_count(0)
            assert current() is None
            record("lost-delete-retry-confirms-absence")
            assert not errors, errors
            assert all("503" in message or "404" in message for message in console), console
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
        except Exception as error:
            rows.append(
                {
                    "scenario_id": "library.book.current",
                    "profile": str(width),
                    "status": "failed",
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                }
            )
        finally:
            page.screenshot(path=str(out / f"{width}-books.png"))
            context.tracing.stop(path=str(out / f"{width}-trace.zip"))
            context.close()
            (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    browser.close()
assert all(row["status"] == "passed" for row in rows), "see scenarios.json"
