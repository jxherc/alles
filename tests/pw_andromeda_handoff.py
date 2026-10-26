"""Owned search result -> saved excerpt -> source-linked document workflow."""

import json
import os
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

CASES = (
    "web-note",
    "news-open",
    "lost-reply",
    "malformed-reply",
    "reload-resave",
    "newer-search",
    "open-retry",
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
                page = context.new_page()
                page.set_default_timeout(4000)
                errors, console, fetches, saves = [], [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console", lambda msg: console.append(msg.text) if msg.type == "error" else None
                )
                context.tracing.start(screenshots=True, snapshots=True)
                query = f"owned handoff {width} {case} !ai"
                title = f"local source {width} {case}"
                url = base + f"/owned/handoff/{width}/{case}"
                excerpt = "A synthetic source excerpt for a local reading note."
                endpoint = base + (
                    "/api/read/save-news" if case == "news-open" else "/api/read/save-result"
                )

                # a case's temporary answers for one url. they live in this one handler: a
                # second page-level route raced it under load and answered a request twice
                overrides = {}

                def routes(route):
                    parsed = urlparse(route.request.url)
                    if parsed.netloc != urlparse(base).netloc:
                        route.abort()
                    elif route.request.url in overrides:
                        overrides[route.request.url](route)
                    elif parsed.path.startswith("/owned/") or parsed.path.endswith("/fetch-text"):
                        fetches.append(route.request.url)
                        route.abort()
                    elif parsed.path == "/api/andromeda/providers":
                        route.fulfill(
                            json={
                                "selected": "fixture",
                                "providers": [
                                    {
                                        "value": "fixture",
                                        "label": "owned fixture",
                                        "available": True,
                                    }
                                ],
                            }
                        )
                    elif parsed.path == "/api/andromeda/search":
                        body = route.request.post_data_json
                        route.fulfill(
                            json={
                                "query": body["query"],
                                "used_no_ai": True,
                                "overview_requested": False,
                                "normal_results_enabled": True,
                                "category": body.get("category", "all"),
                                "provider": "fixture",
                                "status": "ready",
                                "elapsed_ms": 1,
                                "has_more": False,
                                "results": [
                                    {
                                        "title": title
                                        if body["query"] == query
                                        else "newer local result",
                                        "url": url if body["query"] == query else url + "/newer",
                                        "snippet": excerpt,
                                        "publisher": "owned local source",
                                    }
                                ],
                            }
                        )
                    elif parsed.path.startswith("/api/andromeda/") and not parsed.path.startswith(
                        "/api/andromeda/saved"
                    ):
                        route.fulfill(status=400, json={"detail": "fixture refuses providers"})
                    else:
                        route.continue_()

                context.route("**/*", routes)
                page.on(
                    "request",
                    lambda request: (
                        saves.append(request.post_data_json)
                        if request.url == endpoint and request.method == "POST"
                        else None
                    ),
                )
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok

                def search(value=query):
                    page.locator("#andromeda-query").fill(value)
                    page.locator("#andromeda-query").press("Enter")
                    expect(page.locator(".andromeda-result-title")).to_have_text(
                        title if value == query else "newer local result"
                    )

                def copies():
                    response = api.get(base + "/api/read")
                    assert response.ok
                    return [item for item in response.json()["items"] if item["url"] == url]

                def library_button(label, result_title=title):
                    if case != "news-open":
                        trigger = page.get_by_role(
                            "button", name="actions for " + result_title, exact=True
                        )
                        if trigger.get_attribute("aria-expanded") != "true":
                            trigger.click()
                        button = page.get_by_role("menuitem", name=label, exact=True)
                    else:
                        button = page.get_by_role("button", name=label, exact=True)
                    expect(button).to_be_visible()
                    return button

                def library_status():
                    selector = (
                        ".andromeda-result-receipt"
                        if case != "news-open"
                        else ".andromeda-library-status"
                    )
                    return page.locator(selector)

                def open_saved():
                    button = library_button("open in Library: " + title)
                    expect(button).to_be_enabled()
                    if case == "open-retry":
                        identity = copies()[0]["id"]
                        failed_url = base + "/api/read/" + identity
                        overrides[failed_url] = lambda r: r.fulfill(
                            status=503, json={"detail": "synthetic read outage"}
                        )
                        button.click()
                        expect(page.locator("#read-q")).to_be_visible()
                        assert parse_qs(urlparse(page.url).query)["record"] == [identity]
                        overrides.pop(failed_url)
                        page.reload(wait_until="networkidle")
                    else:
                        button.focus()
                        page.keyboard.press("Enter")
                    expect(page.locator(".read-article h1")).to_have_text(title)
                    expect(page.locator(".read-article")).to_contain_text(excerpt)
                    item = copies()[0]
                    assert parse_qs(urlparse(page.url).query)["record"] == [item["id"]]
                    assert not item["read"]
                    expect(page.locator("#read-back")).to_be_focused()
                    return item

                try:
                    page.goto(base + "/?view=andromeda", wait_until="networkidle")
                    search()
                    if case == "news-open":
                        page.locator("[data-andromeda-category=news]").click()
                        expect(page.locator(".andromeda-news-title")).to_have_text(title)
                    assert not copies(), "merely searching must not save a result"
                    save = library_button("save to Library: " + title)
                    assert save.bounding_box()["height"] >= 44
                    if case in {"lost-reply", "malformed-reply"}:

                        def uncertain(route):
                            assert route.fetch().ok
                            if case == "lost-reply":
                                route.fulfill(status=503, json={"detail": "synthetic lost reply"})
                            else:
                                route.fulfill(json={"item": {"id": "wrong", "url": url + "/wrong"}})

                        overrides[endpoint] = uncertain
                        save.focus()
                        page.keyboard.press("Enter")
                        expect(library_status()).to_contain_text("retry")
                        assert len(copies()) == 1
                        overrides.pop(endpoint)
                        save = library_button("save to Library: " + title)
                    if case == "newer-search":
                        page.evaluate(
                            """endpoint => {
                            const fetch = window.fetch.bind(window);
                            window.fetch = async (url, options) => {
                                const response = await fetch(url, options);
                                if (url === endpoint) { window.held = true; await new Promise(r => window.releaseSave = r); }
                                return response;
                            };
                        }""",
                            endpoint.removeprefix(base),
                        )
                    save.focus()
                    page.keyboard.press("Enter")
                    if case == "newer-search":
                        page.wait_for_function("window.held")
                        search("different owned query !ai")
                        page.evaluate("window.releaseSave()")
                        expect(
                            library_button(
                                "save to Library: newer local result", "newer local result"
                            )
                        ).to_be_visible()
                        assert len(copies()) == 1
                        assert library_status().inner_text() == ""
                    else:
                        opened = library_button("open in Library: " + title)
                        assert len(copies()) == 1
                        page.screenshot(path=str(out / f"{width}-{case}-saved.png"))
                        if case == "reload-resave":
                            page.reload(wait_until="networkidle")
                            search()
                            opened = library_button("open in Library: " + title)
                            expect(opened).to_be_visible()
                            assert len(copies()) == 1
                        item = open_saved()
                        assert item["source_kind"] == (
                            "saved_news" if case == "news-open" else "saved_search"
                        )
                        if case == "web-note":
                            page.locator("#read-note").click()
                            dialog = page.get_by_role(
                                "dialog", name="note from " + title, exact=True
                            )
                            expect(dialog.get_by_label("note name", exact=True)).to_be_focused()
                            name = f"search-handoff-{width}.md"
                            dialog.get_by_label("note name", exact=True).fill(name)
                            dialog.get_by_label("note", exact=True).fill("my own local observation")
                            dialog.get_by_role("button", name="save", exact=True).click()
                            open_note = page.locator("#read-note-recovery .note-saved-open")
                            expect(open_note).to_be_focused()
                            open_note.click()
                            preview = page.locator("#wiki-preview")
                            expect(preview).to_contain_text("my own local observation")
                            source = preview.get_by_role("link", name=title, exact=True)
                            target = parse_qs(urlparse(source.get_attribute("href")).query)
                            assert target["record"] == [item["id"]]
                            with page.expect_popup() as popup:
                                source.click()
                            reader = popup.value
                            expect(reader.locator(".read-article h1")).to_have_text(title)
                            expect(reader.locator(".read-article")).to_contain_text(excerpt)
                            reader.close()
                    rendered = page.evaluate(
                        "() => ({width:innerWidth,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth+1,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches})"
                    )
                    assert not errors and not fetches, (errors, fetches)
                    assert not rendered["overflow"] and rendered["reduced"], rendered
                    assert not [
                        line
                        for line in console
                        if "Failed to load resource" not in line and "net::ERR_FAILED" not in line
                    ], console
                    rows.append(
                        {
                            "scenario_id": "andromeda.handoff." + case,
                            "profile": str(width),
                            "status": "passed",
                            "rendered": rendered,
                            "console": console,
                            "save_count": len(saves),
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "scenario_id": "andromeda.handoff." + case,
                            "profile": str(width),
                            "status": "failed",
                            "error": str(error),
                            "traceback": traceback.format_exc(),
                        }
                    )
                finally:
                    page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                    context.tracing.stop(path=str(out / f"{width}-{case}.zip"))
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    print(json.dumps(rows))
    if any(row["status"] != "passed" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
