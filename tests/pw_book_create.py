"""Book creation through the owned app; every lookup and failure is synthetic."""

import json
import os
import traceback
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

CASES = (
    "lost-reply-reload-check",
    "retry-no-duplicate",
    "unknown-check-retry",
    "deleted-confirm-discard",
    "blocked-storage",
    "corrupt-storage",
    "closed-pending-refresh",
    "draft-refresh-close",
    "lookup-retry-autofill",
    "late-lookup",
    "closed-lookup",
    "stale-overview-after-save",
    "ime-search",
)


def run(context_factory=None):
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 820, 390):
            for case in CASES:
                context = (
                    context_factory(pw, width)
                    if context_factory
                    else browser.new_context(
                        viewport={"width": width, "height": 900},
                        service_workers="block",
                        reduced_motion="reduce",
                    )
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
                endpoint = base + "/api/books"
                other = api.post(endpoint, data={"title": "Local other book", "status": "want"})
                assert other.ok
                other_id = other.json()["id"]
                page = context.new_page()
                page.set_default_timeout(4000)
                errors, console, posts, held = [], [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                page.on(
                    "request",
                    lambda request: (
                        posts.append(request.post_data_json)
                        if request.method == "POST" and request.url == endpoint
                        else None
                    ),
                )
                context.tracing.start(screenshots=True, snapshots=True)
                title = f"Local creation {width} {case}"

                def copies():
                    response = api.get(endpoint + "/overview")
                    assert response.ok
                    return [
                        book
                        for shelf in response.json()["shelves"].values()
                        for book in shelf
                        if book["title"] == title
                    ]

                def pending():
                    return page.evaluate(
                        "() => Object.keys(sessionStorage).filter(k=>k.startsWith('alles.books.pending.v1:')).map(k=>sessionStorage.getItem(k))"
                    )

                def lose(route):
                    response = route.fetch()
                    assert response.ok
                    route.fulfill(status=503, json={"detail": "synthetic lost create reply"})

                def fail_save(commit=True):
                    page.route(
                        endpoint,
                        lose
                        if commit
                        else lambda r: r.fulfill(
                            status=503, json={"detail": "synthetic save outage"}
                        ),
                    )
                    page.locator("#book-create").click()
                    expect(page.locator("#book-create-error")).to_contain_text("synthetic")
                    expect(page.locator("#book-create")).to_be_enabled()
                    page.unroute(endpoint)
                    assert len(posts) == 1 and len(pending()) == 1

                def confirm_dialog():
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).click()

                def wait_held():
                    for _ in range(100):
                        if held:
                            return
                        page.wait_for_timeout(20)
                    raise AssertionError("expected a held local response")

                try:
                    page.goto(base + "/?view=books", wait_until="networkidle")
                    page.locator("#books-add-toggle").click()
                    page.locator("#book-title").fill(title)
                    page.locator("#book-author").fill("Local writer")
                    other_card = page.locator(f'.book-card[data-id="{other_id}"]')
                    if case == "ime-search":
                        searches = []

                        def lookup(route):
                            searches.append(route.request.url)
                            route.fulfill(json={"results": []})

                        page.route("**/api/books/lookup?*", lookup)
                        field = page.locator("#book-q")
                        field.focus()
                        page.evaluate(
                            "() => { window.composingBookInput=document.querySelector('#book-q'); }"
                        )
                        session = context.new_cdp_session(page)
                        session.send(
                            "Input.imeSetComposition",
                            {"text": "中", "selectionStart": 1, "selectionEnd": 1},
                        )
                        assert page.evaluate("window.composingBookInput.isConnected"), (
                            "search field removed during IME composition"
                        )
                        field.dispatch_event("keydown", {"key": "Enter", "isComposing": True})
                        page.wait_for_timeout(50)
                        assert not searches, "composition confirmation started a search"
                        session.send("Input.insertText", {"text": "中文"})
                        session.detach()
                        expect(field).to_have_value("中文")
                        expect(field).to_be_focused()
                        field.press("Enter")
                        expect(page.locator('.book-add [role="status"]')).to_contain_text(
                            "no books found"
                        )
                        assert len(searches) == 1
                    elif case == "lost-reply-reload-check":
                        fail_save()
                        saved = copies()[0]
                        assert api.patch(
                            endpoint + "/" + saved["id"],
                            data={
                                "title": title + " edited",
                                "notes": "later notes",
                                "status": "done",
                            },
                        ).ok
                        page.reload(wait_until="networkidle")
                        assert len(posts) == 1
                        expect(page.locator("#book-title")).to_have_value(title)
                        expect(page.locator("#book-title")).to_be_disabled()
                        page.locator("#book-create-check").click()
                        expect(page.locator(".book-create-result")).to_contain_text(
                            title + " edited"
                        )
                        page.locator("#book-create-open").click()
                        card = page.locator(f'.book-card[data-id="{saved["id"]}"]')
                        expect(card).to_be_focused()
                        expect(card).to_contain_text("later notes")
                        assert len(posts) == 1 and not pending()
                    elif case in ("retry-no-duplicate", "unknown-check-retry"):
                        fail_save(commit=case == "retry-no-duplicate")
                        if case == "unknown-check-retry":
                            page.locator("#book-create-check").click()
                            expect(page.locator("#book-create-error")).to_contain_text("not found")
                            assert len(posts) == 1 and not copies()
                        page.locator("#book-create").click()
                        expect(page.locator("#book-create-open")).to_be_visible()
                        assert len(copies()) == 1 and len(posts) == 2
                        assert posts[0] == posts[1] and not pending()
                    elif case == "deleted-confirm-discard":
                        fail_save()
                        assert api.delete(endpoint + "/" + copies()[0]["id"]).ok
                        page.locator("#book-create-check").click()
                        expect(page.locator("#book-create-error")).to_contain_text("deleted")
                        page.locator("#book-create-discard").click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="cancel", exact=True
                        ).click()
                        assert len(pending()) == 1
                        page.locator("#book-create-discard").click()
                        confirm_dialog()
                        expect(page.locator("#book-title")).to_be_enabled()
                        assert not pending() and not copies() and len(posts) == 1
                    elif case == "blocked-storage":
                        page.evaluate(
                            "() => {const original=Storage.prototype.setItem; window.restoreBookStorage=()=>Storage.prototype.setItem=original; Storage.prototype.setItem=function(k,v){if(k.startsWith('alles.books.pending.v1:'))throw new Error('synthetic blocked storage'); return original.call(this,k,v);};}"
                        )
                        page.locator("#book-create").click()
                        expect(page.locator("#book-create-error")).to_be_visible()
                        expect(page.locator("#book-title")).to_have_value(title)
                        assert not posts and not copies()
                        page.evaluate("() => window.restoreBookStorage()")
                        page.locator("#book-create").click()
                        expect(page.locator("#book-create-open")).to_be_visible()
                        assert len(copies()) == 1
                    elif case == "corrupt-storage":
                        scope = api.get(endpoint + "/overview").json()["recovery_scopes"][0]
                        page.evaluate(
                            "scope=>sessionStorage.setItem('alles.books.pending.v1:'+scope,'{broken')",
                            scope,
                        )
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#book-create-error")).to_contain_text("could not read")
                        page.locator("#books-add-toggle").click()
                        expect(page.locator("#book-create")).to_be_disabled()
                        assert not posts
                        page.locator("#book-create-discard").click()
                        confirm_dialog()
                        expect(page.locator("#book-create")).to_be_enabled()
                        assert not pending()
                    elif case == "closed-pending-refresh":
                        fail_save()
                        page.locator("#book-cancel").click()
                        expect(page.locator("#book-title")).to_have_count(0)
                        other_card.locator('[data-rate="4"]').click()
                        expect(other_card.locator('[data-rate="4"]')).to_be_enabled()
                        expect(page.locator("#book-title")).to_have_count(0)
                        expect(page.locator("#book-create-check")).to_be_visible()
                        assert len(posts) == 1 and len(pending()) == 1
                    elif case == "draft-refresh-close":
                        shelf = page.get_by_role("radiogroup", name="book shelf")
                        shelf.get_by_role("radio", name="want", exact=True).focus()
                        page.keyboard.press("Enter")
                        other_card.locator('[data-rate="4"]').click()
                        expect(other_card.locator('[data-rate="4"]')).to_be_enabled()
                        expect(page.locator("#book-title")).to_have_value(title)
                        expect(page.locator("#book-author")).to_have_value("Local writer")
                        page.locator("#book-cancel").click()
                        expect(page.locator("#books-add-toggle")).to_be_focused()
                        page.locator("#books-add-toggle").click()
                        expect(page.locator("#book-title")).to_have_value(title)
                        expect(
                            shelf.get_by_role("radio", name="want", exact=True)
                        ).to_have_attribute("aria-checked", "true")
                        page.locator("#book-create").click()
                        expect(page.locator("#book-create-open")).to_be_visible()
                        assert copies()[0]["status"] == "want"
                    elif case == "lookup-retry-autofill":
                        lookup = "**/api/books/lookup?*"
                        page.route(
                            lookup,
                            lambda r: r.fulfill(
                                status=503, json={"detail": "synthetic lookup outage"}
                            ),
                        )
                        page.locator("#book-q").fill("Local search")
                        page.locator("#book-q").press("Enter")
                        expect(page.locator('.book-add [role="alert"]')).to_contain_text(
                            "could not"
                        )
                        expect(page.locator("#book-title")).to_have_value(title)
                        page.unroute(lookup)
                        page.route(lookup, lambda r: r.fulfill(json={"results": []}))
                        page.locator("#book-search").click()
                        expect(page.locator('.book-add [role="status"]')).to_contain_text(
                            "no books found"
                        )
                        page.unroute(lookup)
                        page.route(
                            lookup,
                            lambda r: r.fulfill(
                                json={
                                    "results": [
                                        {
                                            "title": title,
                                            "author": "Lookup writer",
                                            "cover": "",
                                            "isbn": "local-isbn",
                                            "year": 2020,
                                        }
                                    ]
                                }
                            ),
                        )
                        page.locator("#book-search").click()
                        page.locator(".book-lookup-item").click()
                        expect(page.locator("#book-title")).to_be_focused()
                        expect(page.locator("#book-author")).to_have_value("Lookup writer")
                        page.locator("#book-create").click()
                        expect(page.locator("#book-create-open")).to_be_visible()
                        book = copies()[0]
                        assert (book["author"], book["isbn"], book["year"]) == (
                            "Lookup writer",
                            "local-isbn",
                            2020,
                        )
                    elif case in ("late-lookup", "closed-lookup"):
                        page.route("**/api/books/lookup?*", lambda r: held.append(r))
                        page.locator("#book-q").fill("Old query")
                        page.locator("#book-search").click()
                        wait_held()
                        if case == "late-lookup":
                            page.locator("#book-q").fill("New query")
                        else:
                            page.locator("#book-cancel").click()
                        held.pop().fulfill(
                            json={"results": [{"title": "Old answer", "author": "Old writer"}]}
                        )
                        page.wait_for_load_state("networkidle")
                        expect(page.locator(".book-lookup-item")).to_have_count(0)
                        if case == "closed-lookup":
                            expect(page.locator("#book-title")).to_have_count(0)
                            expect(page.locator("#books-add-toggle")).to_be_focused()
                        else:
                            expect(page.locator("#book-q")).to_have_value("New query")
                            expect(page.locator("#book-q")).to_be_focused()
                    elif case == "stale-overview-after-save":

                        def overview(route):
                            response = route.fetch()
                            if not held:
                                held.append((route, response))
                            else:
                                route.fulfill(response=response)

                        page.route(endpoint + "/overview", overview)
                        other_card.locator('[data-rate="4"]').click()
                        wait_held()
                        page.locator("#book-create").click()
                        expect(page.locator("#book-create-open")).to_be_visible()
                        saved = copies()[0]
                        card = page.locator(f'.book-card[data-id="{saved["id"]}"]')
                        expect(card).to_be_visible()
                        route, response = held[0]
                        route.fulfill(response=response)
                        page.wait_for_load_state("networkidle")
                        expect(card).to_be_visible()
                        page.locator("#book-create-open").click()
                        expect(card).to_be_focused()
                    assert not errors, errors
                    assert all(
                        any(code in message for code in ("503", "404", "410"))
                        for message in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    rows.append(
                        {
                            "scenario_id": "library.book-create." + case,
                            "profile": str(width),
                            "rendered": page.evaluate(
                                "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme})"
                            ),
                            "status": "passed",
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "scenario_id": "library.book-create." + case,
                            "profile": str(width),
                            "rendered": page.evaluate(
                                "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme})"
                            ),
                            "status": "failed",
                            "error": str(error),
                            "traceback": traceback.format_exc(),
                        }
                    )
                finally:
                    page.screenshot(path=str(out / f"{width}-{case}.png"))
                    context.tracing.stop(path=str(out / f"{width}-{case}.zip"))
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    assert all(row["status"] == "passed" for row in rows), "see scenarios.json"


if __name__ == "__main__":
    run()
