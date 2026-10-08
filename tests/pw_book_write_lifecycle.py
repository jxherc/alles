"""Reproduce book refresh guard and newer goal draft loss on owned localhost."""

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
        for case in ("book-guard", "goal-draft", "delete-after-refresh"):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            context.route(
                "**/*",
                lambda r: (
                    r.continue_()
                    if (urlparse(r.request.url).scheme, urlparse(r.request.url).netloc)
                    == (urlparse(base).scheme, urlparse(base).netloc)
                    else r.abort()
                ),
            )
            context.route_web_socket("**/*", lambda ws: ws.close())
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            assert api.put(base + "/api/books/goal", data={"goal": 3}).ok
            created = api.post(
                base + "/api/books", data={"title": f"Local race {width} {case}", "status": "want"}
            )
            assert created.ok
            bid = created.json()["id"]
            page = context.new_page()
            page.set_default_timeout(2500)
            errors = []
            console = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            try:
                page.goto(base + "/?view=books", wait_until="networkidle")
                card = page.locator(f'.book-card[data-id="{bid}"]')
                expect(card).to_be_visible()
                held = []
                if case == "book-guard":
                    page.route(base + "/api/books/overview", lambda r: held.append((r, r.fetch())))
                    with page.expect_request(base + "/api/books/overview"):
                        card.locator('[data-move="reading"]').click()
                    page.locator("#books-add-toggle").click()
                    expect(card.locator('[data-rate="4"]')).to_be_disabled()
                    held[0][0].fulfill(response=held[0][1])
                    expect(card.locator('[data-move="want"]')).to_be_enabled()
                    page.unroute(base + "/api/books/overview")
                    card.locator('[data-rate="4"]').focus()
                    page.keyboard.press("Enter")
                    expect(card.locator('[data-rate="4"]')).to_be_enabled()
                    stored = api.get(base + "/api/books/overview").json()["shelves"]["reading"]
                    assert next(b for b in stored if b["id"] == bid)["rating"] == 4
                elif case == "goal-draft":

                    def goal(route):
                        if route.request.post_data_json["goal"] == 12:
                            held.append((route, route.fetch()))
                        else:
                            route.fulfill(
                                status=503, json={"detail": "synthetic rejected newer goal"}
                            )

                    page.route(base + "/api/books/goal", goal)

                    def submit(value):
                        page.locator('[data-act="set-goal"]').click()
                        page.get_by_role("dialog").get_by_role("textbox").fill(value)
                        with page.expect_request(base + "/api/books/goal"):
                            page.get_by_role("dialog").get_by_role(
                                "button", name="ok", exact=True
                            ).click()

                    submit("12")
                    submit("15")
                    expect(page.locator(".toast.error")).to_contain_text(
                        "synthetic rejected newer goal"
                    )
                    with page.expect_response(base + "/api/books/overview"):
                        held[0][0].fulfill(response=held[0][1])
                    expect(page.locator(".books-goal")).to_contain_text("/ 12")
                    page.locator('[data-act="set-goal"]').click()
                    expect(page.get_by_role("dialog").get_by_role("textbox")).to_have_value("15")
                    page.unroute(base + "/api/books/goal")
                    page.get_by_role("dialog").get_by_role("button", name="ok", exact=True).click()
                    expect(page.locator(".books-goal")).to_contain_text("/ 15")
                    assert api.get(base + "/api/books/overview").json()["goal"] == 15
                else:
                    other = api.post(
                        base + "/api/books", data={"title": "Local second book", "status": "want"}
                    ).json()["id"]
                    page.reload(wait_until="networkidle")
                    page.route(
                        base + "/api/books/overview",
                        lambda route: held.append((route, route.fetch())),
                    )
                    with page.expect_request(base + "/api/books/overview"):
                        page.locator(f'.book-card[data-id="{other}"] [data-move="reading"]').click()
                    card.locator('[data-act="del"]').click()
                    expect(page.get_by_role("alertdialog")).to_be_visible()
                    held[0][0].fulfill(response=held[0][1])
                    expect(
                        page.locator(f'.book-card[data-id="{other}"] [data-move="want"]')
                    ).to_be_enabled()
                    deletes = []
                    page.route(base + "/api/books/" + bid, lambda route: deletes.append(route))
                    with page.expect_request(base + "/api/books/" + bid):
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="remove book", exact=True
                        ).click()
                    expect(card.locator('[data-rate="4"]')).to_be_disabled()
                    expect(card.locator('[data-act="notes"]')).to_be_disabled()
                    page.unroute(base + "/api/books/overview")
                    deletes[0].fulfill(response=deletes[0].fetch())
                    expect(card).to_have_count(0)
                    assert all(
                        b["id"] != bid
                        for shelf in api.get(base + "/api/books/overview")
                        .json()["shelves"]
                        .values()
                        for b in shelf
                    )
                assert not errors, errors
                assert all("503" in m for m in console), console
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                rows.append(
                    {
                        "scenario_id": "library.book." + case,
                        "profile": str(width),
                        "status": "passed",
                    }
                )
            except Exception as e:
                rows.append(
                    {
                        "scenario_id": "library.book." + case,
                        "profile": str(width),
                        "status": "failed",
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    }
                )
            finally:
                page.screenshot(path=str(out / f"{width}-{case}.png"))
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    browser.close()
assert all(r["status"] == "passed" for r in rows), rows
