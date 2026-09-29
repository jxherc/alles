"""Library local persistence and recovery. External provider success is not certified.

Run only against the owned isolated browser runner. HTTP 503 and network failures
are explicit simulations. Successful URL save uses a private URL rejected by the
extractor, proving local record persistence with no readable page text.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for profile in ("desktop", "phone"):
            context = browser.new_context(
                viewport={"width": 1440 if profile == "desktop" else 390, "height": 900},
                service_workers="block",
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
                reduced_motion="reduce",
            )
            assert context.request.post(base + "/api/setup/dismiss").ok
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(15000)
            events = {"console": [], "page_errors": [], "failed_requests": [], "http_errors": []}
            allowed_http = []
            allowed_failed = []
            page.on(
                "console",
                lambda msg: events["console"].append({"type": msg.type, "text": msg.text}),
            )
            page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
            page.on(
                "requestfailed",
                lambda req: events["failed_requests"].append(
                    {"url": req.url, "failure": req.failure}
                ),
            )
            page.on(
                "response",
                lambda res: (
                    events["http_errors"].append({"url": res.url, "status": res.status})
                    if res.status >= 400
                    else None
                ),
            )
            current = None

            def begin(name):
                nonlocal current
                current = {
                    "scenario_id": name,
                    "feature_id": "library.reading-and-news",
                    "profile": profile,
                    "status": "failed",
                }
                records.append(current)

            def passed():
                current.update(
                    status="passed", detail="real local saved state, reload and visible controls"
                )

            def books():
                return [
                    book
                    for shelf in context.request.get(base + "/api/books/overview")
                    .json()["shelves"]
                    .values()
                    for book in shelf
                ]

            def keyboard_reach(selector):
                page.locator("#app-drawer-btn").focus()
                for _ in range(100):
                    page.keyboard.press("Tab")
                    if page.locator(selector).evaluate("(e) => e === document.activeElement"):
                        return
                raise AssertionError(f"control absent from keyboard order: {selector}")

            def shot(name):
                page.screenshot(path=str(output / f"{profile}-{name}.png"), full_page=True)

            try:
                page.goto(base + "/?view=today", wait_until="networkidle")
                if profile == "phone":
                    page.locator("#today-settings").click()
                    page.locator('.s-nav-item[data-pane="themes"]').click()
                    page.wait_for_function(
                        'document.querySelector(\'[data-theme-mode="light"]\')?.dataset.bound === "1"'
                    )
                    with page.expect_response(
                        lambda r: r.url.endswith("/api/appearance") and r.request.method == "PUT"
                    ):
                        page.locator('[data-theme-mode="light"]').click()
                    page.locator("#settings-modal-close").click()
                    expect(page.locator("html")).to_have_attribute("data-theme", "light")
                page.goto(base + "/?view=library", wait_until="networkidle")
                if profile == "phone":
                    expect(page.locator("html")).to_have_attribute("data-theme", "light")
                page.get_by_role("tab", name="books", exact=True).click()
                begin("library.book-note-recovery")
                title = f"{profile} 城市与记忆 — a synthetic long book title with several words and important notes"
                page.get_by_role("button", name="book", exact=True).click()
                page.locator("#book-title").fill(title)
                page.locator("#book-author").fill("Example Writer / 仮名")
                page.get_by_role("button", name="add", exact=True).click()
                expect(page.locator("#book-create")).to_have_count(0)
                book = next(b for b in books() if b["title"] == title)
                bid = book["id"]
                card = page.locator(f'.book-card[data-id="{bid}"]')
                card.get_by_role("button", name="+ note", exact=True).click()
                draft = f"{profile} retained library note 中文"
                card.locator("textarea").fill(draft)
                url = base + "/api/books/" + bid
                allowed_http.append({"url": url, "status": 503})
                page.route(
                    url,
                    lambda route: (
                        route.fulfill(status=503, json={"detail": "simulated storage outage"})
                        if route.request.method == "PATCH"
                        else route.continue_()
                    ),
                )
                card.get_by_role("button", name="save", exact=True).click()
                expect(card.locator("[role=alert]")).to_have_text("simulated storage outage")
                expect(card.locator("textarea")).to_have_value(draft)
                assert next(b for b in books() if b["id"] == bid)["notes"] == ""
                shot("note-http-error")
                page.unroute(url)
                # The pending editor cannot accept text that would be discarded at completion.
                held = []
                page.route(
                    url,
                    lambda route: (
                        held.append(route) if route.request.method == "PATCH" else route.continue_()
                    ),
                )
                card.get_by_role("button", name="save", exact=True).click()
                expect(card.locator("textarea")).to_be_disabled()
                expect(card.get_by_role("button", name="save", exact=True)).to_be_disabled()
                assert len(held) == 1
                held[0].continue_()
                expect(card.locator("textarea")).to_have_count(0)
                page.unroute(url)
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="books", exact=True).click()
                expect(card.locator(".book-notes")).to_have_text(draft)
                assert next(b for b in books() if b["id"] == bid)["notes"] == draft
                keyboard_reach(f'.book-card[data-id="{bid}"] .book-notes')
                page.keyboard.press("Enter")
                expect(card.locator("textarea")).to_be_focused()
                card.locator("textarea").fill(draft + " after network failure")
                allowed_failed.append(url)
                page.route(
                    url,
                    lambda route: (
                        route.abort("failed")
                        if route.request.method == "PATCH"
                        else route.continue_()
                    ),
                )
                card.get_by_role("button", name="save", exact=True).click()
                expect(card.locator("[role=alert]")).to_be_visible()
                expect(card.locator("textarea")).to_have_value(draft + " after network failure")
                page.unroute(url)
                card.get_by_role("button", name="save", exact=True).click()
                expect(card.locator("textarea")).to_have_count(0)
                assert next(b for b in books() if b["id"] == bid)["notes"].endswith(
                    "after network failure"
                )
                passed()
                begin("library.book-controls")
                goal = page.locator('[data-act="set-goal"]')
                goal.click()
                page.get_by_role("dialog").get_by_role("textbox").fill("12")
                page.get_by_role("dialog").get_by_role("button", name="ok", exact=True).click()
                expect(page.locator(".books-goal")).to_be_visible()
                keyboard_reach(".books-goal")
                page.keyboard.press("Enter")
                expect(page.get_by_role("dialog")).to_be_visible()
                page.get_by_role("dialog").get_by_role("button", name="cancel", exact=True).click()
                overlap = card.locator(".book-title").evaluate("""e => {
                    const n=e.firstChild, hit=[];
                    for(let i=0;i<n.length;i++) {
                        const range=document.createRange(); range.setStart(n,i); range.setEnd(n,i+1);
                        const r=range.getBoundingClientRect();
                        if(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.closest('.book-del')) hit.push(i);
                    }
                    return hit;
                }""")
                assert not overlap, overlap
                for control in (
                    card.locator(".book-notes"),
                    page.locator(".books-goal"),
                    card.locator(".book-del"),
                ):
                    box = control.bounding_box()
                    assert box and box["height"] >= 44 and box["width"] >= 44, box
                shot("book-controls")
                passed()
                begin("library.goodreads-import")
                imported_title = f"Quartzferret Import {profile}"
                csv = (
                    "Title,Author,My Rating,Exclusive Shelf,Date Read,ISBN13,Year Published\n"
                    f"{imported_title},Author,4,read,2020/01/02,,2020\n"
                )
                with page.expect_file_chooser() as chooser:
                    page.locator("#books-import").click()
                with page.expect_response(
                    lambda response: (
                        response.url.endswith("/api/books/import")
                        and response.request.method == "POST"
                    )
                ) as import_response:
                    chooser.value.set_files(
                        {"name": "books.csv", "mimeType": "text/csv", "buffer": csv.encode()}
                    )
                assert import_response.value.ok
                imported_book = next(b for b in books() if b["title"] == imported_title)
                imported_card = page.locator(f'.book-card[data-id="{imported_book["id"]}"]')
                expect(imported_card).to_be_visible()
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="books", exact=True).click()
                expect(imported_card).to_be_visible()
                shot("goodreads-import")
                passed()
                begin("library.url-loading-draft")
                loading = []
                page.route(base + "/api/read?*", lambda route: loading.append(route))
                page.route(base + "/api/read/stats", lambda route: loading.append(route))
                page.get_by_role("tab", name="saved", exact=True).click()
                expect(page.locator(".legacy-load-note")).to_contain_text("loading")
                field = page.locator("#read-url")
                prefix = "http://127.0.0.1:1/draft-"
                field.click()
                field.press_sequentially(prefix)
                expect(field).to_be_focused()
                assert len(loading) == 2
                for route in loading:
                    route.continue_()
                expect(page.locator(".legacy-load-note")).to_have_count(0)
                expect(field).to_be_focused()
                page.keyboard.type("tail")
                expect(field).to_have_value(prefix + "tail")
                page.unroute(base + "/api/read?*")
                page.unroute(base + "/api/read/stats")

                # A pending search must not reclaim focus after the user moves to URL capture.
                loading.clear()
                page.route(base + "/api/read?*", lambda route: loading.append(route))
                page.route(base + "/api/read/stats", lambda route: loading.append(route))
                page.locator("#read-q").fill("pending search")
                expect(page.locator(".legacy-load-note")).to_contain_text("loading")
                field.click()
                field.press("End")
                expect(field).to_be_focused()
                assert len(loading) == 2
                for route in loading:
                    route.continue_()
                expect(page.locator(".legacy-load-note")).to_have_count(0)
                expect(field).to_be_focused()
                page.keyboard.type("-after-search")
                expect(field).to_have_value(prefix + "tail-after-search")
                expect(page.locator("#read-q")).to_have_value("pending search")
                shot("url-loading-draft")
                page.unroute(base + "/api/read?*")
                page.unroute(base + "/api/read/stats")
                with page.expect_response(lambda response: "/api/read?" in response.url):
                    page.locator("#read-q").fill("")
                expect(page.locator(".legacy-load-note")).to_have_count(0)
                passed()
                begin("library.read-selection")
                filters = page.locator('.read-filter-choices [role="radio"]')
                feeds = page.locator("#read-feeds-btn")
                expect(filters.first).to_have_attribute("aria-checked", "true")
                filters.nth(3).click()
                expect(filters.nth(3)).to_have_attribute("aria-checked", "true")
                feeds.click()
                expect(feeds).to_have_attribute("aria-pressed", "true")
                expect(filters.nth(3)).to_have_attribute("aria-checked", "true")
                visual = page.evaluate("""() => {
                    const radio = document.querySelector('.read-filter-choices [role="radio"][aria-checked="true"]');
                    const feeds = document.querySelector('#read-feeds-btn');
                    const token = name => {
                        const probe = document.createElement('span');
                        probe.style.color = `var(${name})`;
                        radio.parentElement.append(probe);
                        const color = getComputedStyle(probe).color;
                        probe.remove();
                        return color;
                    };
                    const style = node => {
                        const value = getComputedStyle(node);
                        return {color: value.color, background: value.backgroundColor,
                                border: value.borderTopColor};
                    };
                    return {radio: style(radio), feeds: style(feeds),
                            text: token('--k-text'), raised: token('--k-raised'),
                            line: token('--k-line-strong'), accent: token('--k-accent')};
                }""")
                for name in ("radio", "feeds"):
                    assert visual[name]["color"] == visual["text"], visual
                    assert visual[name]["background"] == visual["raised"], visual
                    assert visual[name]["border"] == visual["line"], visual
                    assert visual[name]["border"] != visual["accent"], visual
                for control in (filters.nth(3), feeds):
                    box = control.bounding_box()
                    assert box and box["width"] >= 44 and box["height"] >= 44, box
                shot("read-feeds-selected")
                feeds.focus()
                feeds.press("Enter")
                expect(feeds).to_have_attribute("aria-pressed", "false")
                expect(filters.nth(3)).to_have_attribute("aria-checked", "true")
                if profile == "desktop":
                    page.evaluate("document.documentElement.style.zoom = '2'")
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                    )
                    expect(filters.nth(3)).to_be_visible()
                    expect(feeds).to_be_visible()
                    page.evaluate("document.documentElement.style.zoom = ''")
                filters.first.click()
                expect(filters.first).to_have_attribute("aria-checked", "true")
                shot("read-selection")
                passed()
                begin("library.saved-url-recovery")
                save_url = f"http://127.0.0.1:1/library-{profile}"
                page.locator("#read-url").fill(save_url)
                url = base + "/api/read"
                allowed_http.append({"url": url, "status": 503})
                page.route(
                    url,
                    lambda route: (
                        route.fulfill(status=503, json={"detail": "simulated save outage"})
                        if route.request.method == "POST"
                        else route.continue_()
                    ),
                )
                page.get_by_role("button", name="save", exact=True).click()
                expect(page.locator("#read-save-error")).to_have_text("simulated save outage")
                expect(page.locator("#read-url")).to_have_value(save_url)
                expect(page.locator("#read-save")).to_be_enabled()
                shot("url-http-error")
                page.unroute(url)
                allowed_failed.append(url)
                page.route(
                    url,
                    lambda route: (
                        route.abort("failed")
                        if route.request.method == "POST"
                        else route.continue_()
                    ),
                )
                page.get_by_role("button", name="save", exact=True).click()
                expect(page.locator("#read-save-error")).to_contain_text("Check your connection")
                expect(page.locator("#read-url")).to_have_value(save_url)
                expect(page.locator("#read-save")).to_be_enabled()
                page.unroute(url)

                def acknowledge(body):
                    return lambda route: (
                        route.fulfill(status=200, content_type="application/json", body=body)
                        if route.request.method == "POST"
                        else route.continue_()
                    )

                for acknowledgment in ("{broken", "null", "{}", "[]", '{"id":"incomplete"}'):
                    page.route(url, acknowledge(acknowledgment))
                    page.get_by_role("button", name="save", exact=True).click()
                    expect(page.locator("#read-save-error")).to_contain_text(
                        "Check saved items before retrying"
                    )
                    expect(page.locator("#read-url")).to_have_value(save_url)
                    expect(page.locator("#read-save")).to_be_enabled()
                    expect(
                        page.locator("#toast-container .toast.success").filter(
                            has_text=re.compile(r"^saved ·")
                        )
                    ).to_have_count(0)
                    assert not [
                        item
                        for item in context.request.get(base + "/api/read").json()["items"]
                        if item["url"] == save_url
                    ]
                    page.unroute(url)
                held = []
                page.route(
                    url,
                    lambda route: (
                        held.append(route) if route.request.method == "POST" else route.continue_()
                    ),
                )
                page.locator("#read-url").press("Enter")
                expect(page.locator("#read-url")).to_be_disabled()
                page.keyboard.press("Enter")
                assert len(held) == 1
                held[0].continue_()
                expect(page.locator("#read-save")).to_be_enabled()
                expect(page.locator("#read-url")).to_have_value("")
                page.unroute(url)
                saved = [
                    r
                    for r in context.request.get(base + "/api/read").json()["items"]
                    if r["url"] == save_url
                ]
                assert len(saved) == 1
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="saved", exact=True).click()
                expect(page.locator(f'.read-card[data-id="{saved[0]["id"]}"]')).to_be_visible()
                passed()
                item = context.request.post(
                    base + "/api/read/save-news",
                    data={
                        "url": f"https://example.invalid/library-{profile}",
                        "title": f"{profile} saved reading 学習",
                        "excerpt": "A synthetic local excerpt with quartzneedle for search.",
                        "publisher": "Fixture",
                    },
                ).json()["item"]
                begin("library.saved-news-source-label")
                listed = {
                    row["id"]: row
                    for row in context.request.get(base + "/api/read").json()["items"]
                }
                assert listed[item["id"]]["source_kind"] == "saved_news"
                assert listed[saved[0]["id"]]["source_kind"] == "read_later"
                page.goto(base + "/?view=library", wait_until="networkidle")
                expect(
                    page.get_by_role("button", name=f"open saved news: {item['title']}")
                ).to_be_visible()
                expect(
                    page.get_by_role(
                        "button", name=f"open saved reading: {saved[0]['title']}"
                    ).first
                ).to_be_visible()
                shot("saved-news-source-label")
                passed()
                begin("library.read-tag-selection")
                page.get_by_role("tab", name="saved", exact=True).click()
                page.locator(f'.read-card[data-id="{item["id"]}"] .read-tag').first.click()
                active_tag = page.locator(".read-tagfilter .read-tag.active")
                expect(active_tag).to_be_visible()
                assert active_tag.evaluate(
                    "node => getComputedStyle(node).color"
                ) == active_tag.evaluate(
                    """node => {
                        const probe = document.createElement('span');
                        probe.style.color = 'var(--k-text)';
                        node.parentElement.append(probe);
                        const color = getComputedStyle(probe).color;
                        probe.remove();
                        return color;
                    }"""
                )
                shot("read-tag-selected")
                page.locator("#read-tag-clear").click()
                expect(active_tag).to_have_count(0)
                page.get_by_role("tab", name="overview", exact=True).click()
                passed()
                begin("library.overview-opens-book")
                keyboard_reach(f'.specialist-library-row[aria-label="open book: {title}"]')
                page.keyboard.press("Enter")
                expect(card).to_be_visible()
                expect(card).to_be_focused()
                shot("overview-open-book")
                passed()
                page.goto(base + "/?view=library", wait_until="networkidle")
                begin("library.overview-opens-saved-reading")
                keyboard_reach(
                    f'.specialist-library-row[aria-label="open saved news: {item["title"]}"]'
                )
                page.keyboard.press("Enter")
                expect(page.locator(".read-article h1")).to_have_text(item["title"])
                expect(page.locator("#read-back")).to_be_focused()
                shot("overview-open-saved-reading")
                page.locator("#read-back").click()
                expect(page.locator(f'[data-open="{item["id"]}"]')).to_be_focused()
                page.go_back(wait_until="networkidle")
                expect(page.locator("#library-view")).to_have_attribute("data-section", "overview")
                page.get_by_role("tab", name="saved", exact=True).click()
                expect(page.locator("#read-q")).to_be_visible()
                expect(page.locator(".read-article")).to_have_count(0)
                passed()
                begin("library.overview-open-recovery")
                page.goto(base + "/?view=library", wait_until="networkidle")
                bad_item_url = base + "/api/read/" + item["id"]
                page.route(
                    bad_item_url,
                    lambda route: route.fulfill(status=200, body="invalid item response"),
                )
                page.get_by_role("button", name=f"open saved news: {item['title']}").click()
                expect(page.locator("#read-q")).to_be_focused()
                expect(page.locator(".read-article")).to_have_count(0)
                expect(page.locator(".toast.error")).to_have_text("could not open")
                page.unroute(bad_item_url)
                passed()
                page.goto(base + "/?view=library", wait_until="networkidle")
                begin("library.saved-keyboard-reading")
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="saved", exact=True).click()
                page.locator("#read-q").fill(profile + " saved reading")
                expect(page.locator(".read-card")).to_have_count(1)
                expect(page.locator(f'[data-open="{item["id"]}"]')).to_be_visible()
                keyboard_reach(f'[data-open="{item["id"]}"]')
                page.keyboard.press("Enter")
                expect(page.locator(".read-article")).to_contain_text("quartzneedle")
                expect(page.locator("#read-back")).to_be_focused()
                shot("reader")
                page.keyboard.press("Enter")
                expect(page.locator(f'[data-open="{item["id"]}"]')).to_be_focused()
                if profile == "phone":
                    page.locator(f'[data-open="{item["id"]}"]').tap()
                    expect(page.locator(".read-article")).to_be_visible()
                    page.locator("#read-back").tap()
                assert context.request.get(base + "/api/read/" + item["id"]).json()["read"]
                assert not events["page_errors"], events["page_errors"]
                assert all(e in allowed_http for e in events["http_errors"]), events["http_errors"]
                assert all(e["url"] in allowed_failed for e in events["failed_requests"]), events[
                    "failed_requests"
                ]
                console_errors = [e["text"] for e in events["console"] if e["type"] == "error"]
                expected_console = [
                    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
                    "Failed to load resource: net::ERR_FAILED",
                ] * 2
                assert sorted(console_errors) == sorted(expected_console), console_errors
                assert len(events["http_errors"]) == 2
                assert len(events["failed_requests"]) == 2
                passed()
            except Exception as error:
                if current:
                    current["detail"] = str(error)
                shot("failure")
                raise
            finally:
                (output / f"{profile}-events.json").write_text(json.dumps(events, indent=2))
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.tracing.stop(path=str(output / f"{profile}.zip"))
                context.close()
        browser.close()


if __name__ == "__main__":
    run()
