"""Real Books controls reject stale forward edits and safely retry lost acknowledgments."""

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

data = Path(os.environ["ALLES_DATA"]).resolve()
run_id = os.environ["ALLES_TEST_RUN_ID"]
assert Path(tempfile.gettempdir()).resolve() in data.parents
assert os.environ["ALLES_TEST_DATA"] == "1" and os.environ["PYTHON_DOTENV_DISABLED"] == "1"
assert (data / ".alles-test-owner").read_text().strip() == run_id
assert data in Path(os.environ["ALLES_DB"]).resolve().parents
base = "http://127.0.0.1:" + str(int(os.environ["PORT"]))
require_server_ownership(base, run_id)
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
out.mkdir(parents=True, exist_ok=True)

records = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 844 if width == 390 else 900},
                service_workers="block",
                reduced_motion="reduce",
                has_touch=width == 390,
            )
            api = context.request
            checks, errors, consoles, blocked, writes, responses, held = [], [], [], [], [], [], []
            mode = "normal"
            row = {"width": width, "status": "failed", "checks": checks}
            records.append(row)

            ids, pages = set(), []
            try:
                assert api.post(base + "/api/setup/dismiss", max_redirects=0).ok
                assert api.patch(
                    base + "/api/settings", data={"language": "en"}, max_redirects=0
                ).ok

                def create(title, rating, notes):
                    response = api.post(
                        base + "/api/books",
                        data={
                            "title": title,
                            "status": "reading",
                            "rating": rating,
                            "notes": notes,
                        },
                        max_redirects=0,
                    )
                    assert response.ok, response.text()
                    book_id = response.json()["id"]
                    ids.add(book_id)
                    return book_id

                bid = create(f"synthetic stale book {width}", 1, "  note 1 中文\nfirst  ")
                other_id = create(f"synthetic normal book {width}", 0, "")

                def guard(route):
                    global mode
                    request = route.request
                    url = urlsplit(request.url)
                    if (url.scheme, url.netloc) != ("http", urlsplit(base).netloc):
                        blocked.append(request.url)
                        return route.abort()
                    if request.method == "GET" and url.path == "/api/books/overview":
                        return route.continue_()
                    if request.method == "PATCH" and url.path in {
                        f"/api/books/{item}" for item in ids
                    }:
                        payload = request.post_data_json
                        writes.append({"url": url.path, "body": payload})
                        if (
                            mode == "hold-note"
                            and url.path == f"/api/books/{bid}"
                            and "notes" in payload
                        ):
                            held.append(route)
                            return None
                        if mode == "lose-next-patch":
                            mode = "normal"
                            response = route.fetch(max_redirects=0)
                            assert response.ok, response.text()
                            return route.fulfill(
                                status=503, json={"detail": "synthetic response lost after commit"}
                            )
                        return route.continue_()
                    return route.continue_()

                context.route("**/*", guard)
                context.route_web_socket("**/*", lambda socket: socket.close())
                pages = [context.new_page(), context.new_page()]

                def response_record(response):
                    if "/api/books/" in response.url:
                        responses.append(
                            {
                                "path": urlsplit(response.url).path,
                                "method": response.request.method,
                                "status": response.status,
                            }
                        )

                for page in pages:
                    page.set_default_timeout(6000)
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            consoles.append(message.text) if message.type == "error" else None
                        ),
                    )
                    page.on("response", response_record)
                    page.goto(base + "/?view=books", wait_until="networkidle")
                    expect(page.locator(f'.book-card[data-id="{bid}"]')).to_be_visible()
                first, second = pages

                def card(page=first, book=bid):
                    return page.locator(f'.book-card[data-id="{book}"]')

                def stored(book=bid):
                    response = api.get(base + "/api/books/overview", max_redirects=0)
                    assert response.ok
                    return next(
                        item
                        for shelf in response.json()["shelves"].values()
                        for item in shelf
                        if item["id"] == book
                    )

                def use(control):
                    expect(control).to_be_enabled()
                    control.tap() if width == 390 else control.press("Enter")

                def rate(value, page=first, book=bid):
                    use(card(page, book).locator(f'[data-rate="{value}"]'))

                def idle(page=first, book=bid):
                    expect(card(page, book)).not_to_have_attribute("aria-busy", "true")
                    expect(card(page, book).locator('[data-rate="1"]')).to_be_enabled()

                def edit_note(value, page=first, book=bid):
                    current = card(page, book)
                    use(current.locator('[data-act="notes"]'))
                    current.locator('[data-f="notes"]').fill(value)
                    use(current.locator('[data-act="save-notes"]'))

                def undo(field, page=first, book=bid):
                    use(card(page, book).locator(f'[data-undo="{field}"]'))
                    expect(card(page, book).locator(f'[data-undo="{field}"]')).to_have_count(0)
                    idle(page, book)

                # Both tabs saw 1; tab two saves 2; stale tab one attempts 3.
                rate(2, second)
                expect(card(second).locator('[data-undo="rating"]')).to_be_visible()
                idle(second)
                assert stored()["rating"] == 2
                rate(3)
                expect(card().locator(".book-write-error")).to_contain_text(
                    "newer values were kept"
                )
                idle()
                assert stored()["rating"] == 2
                expect(card().locator('[data-rate="2"]')).to_have_attribute("aria-checked", "true")
                expect(card().locator('[data-undo="rating"]')).to_have_count(0)
                rejected = writes[-1]["body"]
                assert rejected["rating"] == 3 and rejected["expected_rating"] == 1
                assert re.fullmatch("[0-9a-f]{64}", rejected["recovery_scope"])
                rate(3)
                expect(card().locator('[data-undo="rating"]')).to_be_visible()
                idle()
                assert stored()["rating"] == 3
                assert writes[-1]["body"]["expected_rating"] == 2
                undo("rating")
                assert stored()["rating"] == 2
                checks.append(
                    "two-tab rating 1 -> 2; stale 3 refused; refreshed retry 3 and undo restores 2"
                )

                prior = "  note 1 中文\nfirst  "
                newer = "  note 2 中文\nsecond  "
                draft = "  note 3 草稿\nkeep exact spacing  "
                edit_note(newer, second)
                expect(card(second).locator('[data-undo="notes"]')).to_be_visible()
                idle(second)
                edit_note(draft)
                expect(card().locator(".book-notes-error")).to_contain_text(
                    "newer values were kept"
                )
                expect(card().locator('[data-act="save-notes"]')).to_be_enabled()
                expect(card().locator('[data-f="notes"]')).to_have_value(draft)
                assert stored()["notes"] == newer
                assert writes[-1]["body"]["expected_notes"] == prior
                expect(card().locator('[data-undo="notes"]')).to_have_count(0)
                use(card().locator('[data-act="save-notes"]'))
                expect(card().locator('[data-undo="notes"]')).to_be_visible()
                idle()
                assert stored()["notes"] == draft
                assert writes[-1]["body"]["expected_notes"] == newer
                undo("notes")
                assert stored()["notes"] == newer and stored()["rating"] == 2
                checks.append(
                    "two-tab notes conflict retains exact draft; retry and undo restore actual prior text"
                )

                # Ordinary saves still undo zero/empty values and preserve the other field.
                rate(4, book=other_id)
                expect(card(book=other_id).locator('[data-undo="rating"]')).to_be_visible()
                idle(book=other_id)
                assert stored(other_id)["rating"] == 4
                undo("rating", book=other_id)
                assert stored(other_id)["rating"] == 0
                normal = "  normal note 中文\nexact  "
                edit_note(normal, book=other_id)
                expect(card(book=other_id).locator('[data-undo="notes"]')).to_be_visible()
                idle(book=other_id)
                assert stored(other_id)["notes"] == normal
                undo("notes", book=other_id)
                assert stored(other_id)["notes"] == "" and stored(other_id)["rating"] == 0
                checks.append(
                    "normal rating and notes save/undo, including zero and empty previous values"
                )

                # A lost forward response must allow the identical retry to confirm the write.
                mode = "lose-next-patch"
                rate(5, book=other_id)
                expect(card(book=other_id).locator(".book-write-error")).to_contain_text(
                    "response lost"
                )
                idle(book=other_id)
                first_body = writes[-1]["body"]
                assert stored(other_id)["rating"] == 5
                rate(5, book=other_id)
                expect(card(book=other_id).locator('[data-undo="rating"]')).to_be_visible()
                idle(book=other_id)
                assert writes[-1]["body"] == first_body
                undo("rating", book=other_id)
                assert stored(other_id)["rating"] == 0
                mode = "lose-next-patch"
                edit_note(normal, book=other_id)
                expect(card(book=other_id).locator(".book-notes-error")).to_contain_text(
                    "response lost"
                )
                expect(card(book=other_id).locator('[data-act="save-notes"]')).to_be_enabled()
                expect(card(book=other_id).locator('[data-f="notes"]')).to_have_value(normal)
                first_body = writes[-1]["body"]
                assert stored(other_id)["notes"] == normal
                use(card(book=other_id).locator('[data-act="save-notes"]'))
                expect(card(book=other_id).locator('[data-undo="notes"]')).to_be_visible()
                idle(book=other_id)
                assert writes[-1]["body"] == first_body
                mode = "lose-next-patch"
                use(card(book=other_id).locator('[data-undo="notes"]'))
                expect(card(book=other_id).locator(".book-write-error")).to_contain_text(
                    "response lost"
                )
                idle(book=other_id)
                first_body = writes[-1]["body"]
                assert stored(other_id)["notes"] == ""
                undo("notes", book=other_id)
                assert writes[-1]["body"] == first_body and stored(other_id)["notes"] == ""
                checks.append(
                    "lost forward rating/notes response and lost undo response retain identical safe retries"
                )

                mode = "hold-note"
                edit_note("pending saved note")
                for _ in range(100):
                    if held:
                        break
                    first.wait_for_timeout(20)
                assert len(held) == 1
                use(card(book=other_id).locator('[data-act="notes"]'))
                field = card(book=other_id).locator('[data-f="notes"]')
                exact = "newer unsaved 草稿\n untouched  "
                field.fill(exact)
                field.evaluate("el => el.setSelectionRange(2, 8)")
                mode = "normal"
                held.pop().continue_()
                expect(card().locator('[data-act="notes"]')).to_have_text("pending saved note")
                idle()
                expect(field).to_have_value(exact)
                expect(field).to_be_focused()
                assert field.evaluate("el => [el.selectionStart, el.selectionEnd]") == [2, 8]
                assert stored(other_id)["notes"] == ""
                checks.append(
                    "delayed save preserves the other book exact newer draft, focus and selection"
                )

                second.reload(wait_until="networkidle")
                expect(card(second).locator('[data-act="notes"]')).to_have_text(
                    "pending saved note"
                )
                assert stored()["rating"] == 2 and stored()["notes"] == "pending saved note"
                assert stored(other_id)["rating"] == 0 and stored(other_id)["notes"] == ""
                assert not errors and not blocked, (errors, blocked)
                assert all("409" in message or "503" in message for message in consoles), consoles
                assert sum(item["status"] == 409 for item in responses) == 2, responses
                assert sum(item["status"] == 503 for item in responses) == 3, responses
                row["status"] = "passed"
            except Exception as error:
                row["error"] = repr(error)
            finally:
                row.update(
                    page_errors=errors,
                    console_errors=consoles,
                    blocked_requests=blocked,
                    writes=writes,
                    responses=responses,
                )
                try:
                    for index, page in enumerate(pages):
                        page.screenshot(
                            path=str(out / f"books-{width}-tab-{index}.png"), full_page=True
                        )
                except Exception as error:
                    row.update(status="failed", screenshot_error=repr(error))
                try:
                    for route in held:
                        route.abort()
                    for book_id in ids:
                        assert api.delete(base + "/api/books/" + book_id, max_redirects=0).ok
                except Exception as error:
                    row.update(status="failed", cleanup_error=repr(error))
                finally:
                    context.close()
                (out / "book-undo-results.json").write_text(json.dumps(records, indent=2) + "\n")
    finally:
        browser.close()

raise SystemExit(any(record["status"] != "passed" for record in records))
