"""Saved article retrieval through the real app and synthetic local HTTP responses."""

import json
import os
import sqlite3
import traceback
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

CASES = (
    "explicit-fetch-and-note",
    "http-failure-retry",
    "empty-failure",
    "lost-reply-check",
    "lost-reply-reload",
    "legacy-confirmation",
    "empty-feed",
    "late-response-navigation",
    "reopen-during-fetch",
    "changed-source",
    "reading-place-failure",
    "completion-reopen",
    "removed-link-focus",
)
HTML = (
    "<html><head><title>Publisher title</title></head><body><article>"
    + "".join(
        f"<p>Local article passage {i}. "
        + "A synthetic saved article remains readable without contacting a publisher. " * 6
        + "</p>"
        for i in range(30)
    )
    + "</article></body></html>"
)


def run(context_factory=None):
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == os.environ["ALLES_TEST_RUN_ID"]
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
                    lambda r: (
                        r.continue_()
                        if urlparse(r.request.url).netloc == urlparse(base).netloc
                        else r.abort()
                    ),
                )
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                url = f"https://articles.example.invalid/{width}-{case}"

                def fixture(status=200, html=HTML):
                    (data / "article-fixtures.json").write_text(
                        json.dumps({url: {"status": status, "html": html}})
                    )

                def calls():
                    log = data / "article-requests.jsonl"
                    return (
                        sum(json.loads(line)["url"] == url for line in log.read_text().splitlines())
                        if log.exists()
                        else 0
                    )

                fixture()
                if case == "empty-feed":
                    for feed in api.get(base + "/api/read/feeds").json()["feeds"]:
                        assert api.delete(base + "/api/read/feeds/" + feed["id"]).ok
                    assert api.post(
                        base + "/api/read/feeds",
                        data={"url": f"https://feeds.example.invalid/{width}-{case}"},
                    ).ok
                    assert api.post(base + "/api/read/feeds/refresh").ok
                    item = next(
                        i for i in api.get(base + "/api/read").json()["items"] if i["url"] == url
                    )
                else:
                    item = api.post(
                        base + "/api/read/save-news",
                        data={
                            "url": url,
                            "title": f"Local {case} {width}",
                            "excerpt": ""
                            if case == "removed-link-focus"
                            else "Original local excerpt.",
                        },
                    ).json()["item"]
                endpoint = base + "/api/read/" + item["id"]
                fetch_url = endpoint + "/fetch-text"
                if case == "legacy-confirmation":
                    with sqlite3.connect(data / "aide.db") as db:
                        db.execute(
                            "UPDATE read_items SET text_state='unknown' WHERE id=?", (item["id"],)
                        )
                if case == "reading-place-failure":
                    with sqlite3.connect(data / "aide.db") as db:
                        db.execute(
                            "UPDATE read_items SET text=? WHERE id=?",
                            ("\n\n".join(["Original local excerpt. " * 30] * 30), item["id"]),
                        )
                before = api.get(endpoint).json()
                assert calls() == 0
                page = context.new_page()
                page.set_default_timeout(5000)
                errors, console, posts, held = [], [], [], []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                page.on(
                    "request",
                    lambda r: (
                        posts.append(r.post_data_json)
                        if r.method == "POST" and r.url == fetch_url
                        else None
                    ),
                )
                context.tracing.start(screenshots=True, snapshots=True)

                def open_item():
                    page.goto(base + "/?view=read", wait_until="networkidle")
                    page.locator(f'[data-open="{item["id"]}"]').click()
                    expect(page.locator(".read-article h1")).to_have_text(item["title"])

                def fetch_text():
                    page.locator("#read-fetch-text").focus()
                    page.keyboard.press("Enter")

                def saved():
                    expect(page.locator("#read-fetch-text")).to_be_hidden()
                    expect(page.locator("#read-text-status")).to_contain_text("article text saved")
                    expect(page.locator(".read-article")).to_contain_text("Local article passage")
                    assert api.get(endpoint).json()["text_state"] == "extracted"

                def lose(route):
                    response = route.fetch()
                    assert response.ok
                    route.fulfill(
                        status=503, json={"detail": "synthetic lost reply; check saved text"}
                    )

                try:
                    open_item()
                    assert calls() == 0
                    if case == "legacy-confirmation":
                        expect(page.locator("#read-text-status")).to_contain_text("unknown")
                        fetch_text()
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_contain_text("reading place restarts")
                        page.keyboard.press("Escape")
                        expect(page.locator("#read-fetch-text")).to_be_focused()
                        assert not posts and calls() == 0
                        fetch_text()
                        dialog.get_by_role("button", name="confirm", exact=True).click()
                        saved()
                        assert posts[0]["replace_saved_text"] is True
                    elif case in {"http-failure-retry", "empty-failure"}:
                        page.locator("#read-fetch-text").focus()
                        page.wait_for_timeout(800)
                        expect(page.locator("#read-position-status")).to_have_text(
                            "reading place saved"
                        )
                        saved_before_fetch = []

                        def capture_saved_text(route):
                            saved_before_fetch.append(api.get(endpoint).json())
                            route.continue_()

                        page.route(fetch_url, capture_saved_text)
                        fixture(
                            403 if case == "http-failure-retry" else 200,
                            "<html><body>Forbidden</body></html>"
                            if case == "http-failure-retry"
                            else "",
                        )
                        fetch_text()
                        expect(page.locator("#read-text-error")).to_contain_text(
                            "saved text is unchanged"
                        )
                        expect(page.locator(".read-article")).to_contain_text(
                            "Original local excerpt."
                        )
                        page.wait_for_timeout(1200)
                        expect(page.locator("#read-position-status")).to_have_text(
                            "reading place saved"
                        )
                        assert api.get(endpoint).json() == saved_before_fetch[-1], (
                            api.get(endpoint).json()["position"],
                            saved_before_fetch[-1]["position"],
                        )
                        page.screenshot(path=str(out / f"{width}-{case}.png"))
                        fixture()
                        fetch_text()
                        saved()
                        assert calls() == 2
                    elif case in {"lost-reply-check", "lost-reply-reload"}:
                        page.route(fetch_url, lose)
                        fetch_text()
                        expect(page.locator("#read-text-error")).to_contain_text(
                            "synthetic lost reply"
                        )
                        assert api.get(endpoint).json()["text_state"] == "extracted"
                        expect(page.locator(".read-article")).to_contain_text(
                            "Original local excerpt."
                        )
                        page.unroute(fetch_url)
                        if case == "lost-reply-check":
                            page.locator("#read-check-text").click()
                        else:
                            open_item()
                        saved()
                        assert calls() == 1 and len(posts) == 1
                    elif case in {"late-response-navigation", "reopen-during-fetch"}:
                        page.route(fetch_url, lambda r: held.append(r))
                        fetch_text()
                        expect(page.locator("#read-fetch-text")).to_be_disabled()
                        page.wait_for_timeout(100)
                        assert len(held) == 1
                        page.locator("#read-back").click()
                        expect(page.locator(f'[data-open="{item["id"]}"]')).to_be_focused()
                        if case == "reopen-during-fetch":
                            page.locator(f'[data-open="{item["id"]}"]').click()
                            expect(page.locator("#read-fetch-text")).to_be_disabled()
                        else:
                            page.locator("#read-q").fill("current query")
                        held.pop().continue_()
                        page.unroute(fetch_url)
                        if case == "reopen-during-fetch":
                            saved()
                            expect(page.locator("#read-back")).to_be_focused()
                        else:
                            page.wait_for_timeout(500)
                            expect(page.locator("#read-q")).to_be_focused()
                            expect(page.locator("#read-q")).to_have_value("current query")
                            expect(page.locator(".read-article")).to_have_count(0)
                            assert api.get(endpoint).json()["text_state"] == "extracted"
                            open_item()
                            saved()
                    elif case == "changed-source":
                        page.locator("#read-fetch-text").focus()
                        page.wait_for_timeout(800)
                        expect(page.locator("#read-position-status")).to_have_text(
                            "reading place saved"
                        )
                        with sqlite3.connect(data / "aide.db") as db:
                            db.execute(
                                "UPDATE read_items SET text='Newer saved version' WHERE id=?",
                                (item["id"],),
                            )
                        fetch_text()
                        expect(page.locator("#read-text-error")).to_contain_text(
                            "saved text changed"
                        )
                        assert calls() == 0
                        page.locator("#read-check-text").click()
                        expect(page.locator(".read-article")).to_contain_text("Newer saved version")
                        fetch_text()
                        saved()
                    elif case == "completion-reopen":
                        page.route(
                            endpoint,
                            lambda r: (
                                held.append(r) if r.request.method == "PATCH" else r.continue_()
                            ),
                        )
                        page.locator("#read-complete").click()
                        expect(page.locator("#read-complete")).to_be_disabled()
                        page.wait_for_timeout(100)
                        assert len(held) == 1
                        page.get_by_role("tab", name="overview", exact=True).click()
                        with page.expect_response(
                            lambda r: r.url == endpoint and r.request.method == "GET"
                        ):
                            page.get_by_role(
                                "button", name="open saved news: " + item["title"], exact=True
                            ).click()
                        expect(page.locator("#read-back")).to_be_focused()
                        expect(page.locator(".read-article h1")).to_have_text(item["title"])
                        held.pop().continue_()
                        page.unroute(endpoint)
                        expect(page.locator("#read-complete")).to_be_enabled()
                        expect(page.locator("#read-fetch-text")).to_be_enabled()
                        expect(page.locator("#read-complete")).to_have_text("mark unread")
                        assert api.get(endpoint).json()["read"]
                    elif case == "removed-link-focus":
                        page.route(fetch_url, lambda r: held.append(r))
                        fetch_text()
                        expect(page.locator("#read-fetch-text")).to_be_disabled()
                        page.locator(".read-empty a").focus()
                        expect(page.locator(".read-empty a")).to_be_focused()
                        assert len(held) == 1
                        held.pop().continue_()
                        page.unroute(fetch_url)
                        saved()
                        expect(page.locator("#read-text-status")).to_be_focused()
                    elif case == "reading-place-failure":
                        page.route(
                            endpoint,
                            lambda r: (
                                r.fulfill(status=503, json={"detail": "local position failure"})
                                if r.request.method == "PATCH"
                                else r.continue_()
                            ),
                        )
                        page.locator("#read-body").evaluate(
                            "body => body.scrollTop = (body.scrollHeight - body.clientHeight) * 0.5"
                        )
                        expect(page.locator("#read-position-status")).to_contain_text(
                            "could not confirm"
                        )
                        fetch_text()
                        expect(page.locator("#read-text-error")).to_contain_text(
                            "save your reading place"
                        )
                        assert calls() == 0
                        page.unroute(endpoint)
                        page.locator("#read-position-retry").click()
                        expect(page.locator("#read-position-status")).to_have_text(
                            "reading place saved"
                        )
                        fetch_text()
                        saved()
                        assert api.get(endpoint).json()["position"] == 0
                    else:
                        expected_label = (
                            "no article text" if case == "empty-feed" else "saved excerpt"
                        )
                        expect(page.locator("#read-text-status")).to_contain_text(expected_label)
                        fetch_text()
                        saved()
                        assert calls() == 1
                        after = api.get(endpoint).json()
                        assert all(
                            after[key] == before[key]
                            for key in (
                                "id",
                                "title",
                                "url",
                                "tags",
                                "read",
                                "fav",
                                "archived",
                                "source_kind",
                            )
                        )
                        expect(page.locator("#read-text-status")).to_be_focused()
                        if case == "explicit-fetch-and-note":
                            page.locator("#read-note").click()
                            dialog = page.get_by_role(
                                "dialog", name="note from " + item["title"], exact=True
                            )
                            name = f"fetched-article-{width}.md"
                            dialog.get_by_label("note name", exact=True).fill(name)
                            dialog.get_by_label("note", exact=True).fill(
                                "A local observation on the fetched text."
                            )
                            dialog.get_by_role("button", name="save", exact=True).click()
                            expect(
                                page.locator("#read-note-recovery .note-saved-open")
                            ).to_be_visible()
                            content = api.get(
                                base + "/api/vault-md/file", params={"path": name}
                            ).json()["content"]
                            assert item["id"] in content and after["content_hash"] in content
                            assert before["content_hash"] not in content
                            page.locator("#read-complete").click()
                            expect(page.locator("#read-complete")).to_have_text("mark unread")
                            assert api.get(endpoint).json()["read"]
                    assert not errors, errors
                    assert all(
                        any(str(status) in line for status in (403, 409, 502, 503))
                        for line in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(out / f"{width}-{case}-final.png"))
                    rows.append(
                        {
                            "scenario_id": "library.text." + case,
                            "profile": str(width),
                            "status": "passed",
                            "rendered": page.evaluate(
                                "({width:innerWidth,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme})"
                            ),
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "scenario_id": "library.text." + case,
                            "profile": str(width),
                            "status": "failed",
                            "error": str(error),
                        }
                    )
                    traceback.print_exc()
                    page.screenshot(path=str(out / f"{width}-{case}-failure.png"))
                finally:
                    for route in held:
                        route.abort()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                    context.tracing.stop(path=str(out / f"{width}-{case}.zip"))
                    context.close()
        browser.close()
    raise SystemExit(1 if any(row["status"] != "passed" for row in rows) else 0)


if __name__ == "__main__":
    run()
