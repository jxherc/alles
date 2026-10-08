import json
import os
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
        for action in ("move", "delete", "rating", "goal", "import"):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if (urlparse(route.request.url).scheme, urlparse(route.request.url).netloc)
                    == (urlparse(base).scheme, urlparse(base).netloc)
                    else route.abort()
                ),
            )
            context.route_web_socket("**/*", lambda ws: ws.close())
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            result = api.post(
                base + "/api/books",
                data={"title": f"synthetic book {width} {action}", "status": "want"},
            )
            assert result.ok
            book = result.json()
            page = context.new_page()
            page_errors, console = [], []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            page.goto(base + "/?view=books", wait_until="networkidle")
            card = page.locator(f'.book-card[data-id="{book["id"]}"]')
            expect(card).to_be_visible()
            endpoint = base + "/api/books/" + book["id"]
            if action in ("goal", "import"):
                endpoint = base + "/api/books/" + action
            page.route(
                endpoint,
                lambda route: route.fulfill(
                    status=503, json={"detail": "synthetic book write outage"}
                ),
            )
            if action == "move":
                with page.expect_response(endpoint):
                    card.locator('[data-move="reading"]').click()
            elif action == "rating":
                with page.expect_response(endpoint):
                    card.locator('[data-rate="4"]').click()
            elif action == "goal":
                page.locator('[data-act="set-goal"]').click()
                page.get_by_role("dialog").get_by_role("textbox").fill("12")
                with page.expect_response(endpoint):
                    page.get_by_role("dialog").get_by_role("button", name="ok", exact=True).click()
            elif action == "import":
                with page.expect_file_chooser() as chooser:
                    page.locator("#books-import").click()
                with page.expect_response(endpoint):
                    chooser.value.set_files(
                        {
                            "name": "books.csv",
                            "mimeType": "text/csv",
                            "buffer": b"Title,Author,Exclusive Shelf\nSynthetic imported book,Local writer,to-read\n",
                        }
                    )
            else:
                card.locator('[data-act="del"]').click()
                with page.expect_response(endpoint):
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="remove book", exact=True
                    ).click()
            page.wait_for_timeout(100)
            success = page.locator(".toast.success").all_text_contents()
            errors = page.locator(".toast.error").all_text_contents()
            overview = api.get(base + "/api/books/overview").json()
            retained = next(b for b in overview["shelves"]["want"] if b["id"] == book["id"])
            rows.append(
                {
                    "scenario_id": "library.book.failed-" + action,
                    "profile": str(width),
                    "status": "passed"
                    if errors
                    and not success
                    and not page_errors
                    and all("503" in message for message in console)
                    else "failed",
                    "page_errors": page_errors,
                    "console": console,
                    "success_messages": success,
                    "error_messages": errors,
                    "stored_status": retained["status"],
                }
            )
            page.screenshot(path=str(out / f"{width}-{action}.png"))
            context.close()
            (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    browser.close()
assert all(r["status"] == "passed" for r in rows), rows
