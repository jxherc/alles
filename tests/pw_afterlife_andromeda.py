"""Focused browser gate for the real Afterlife Andromeda surface."""

import base64
import json
import os
from datetime import date
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Route, sync_playwright

PORT = os.environ.get("PORT", "6769")
URL = f"http://andromeda.localhost:{PORT}/"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def search_payload(body: dict) -> dict:
    category = body.get("category", "all")
    requested = int(body.get("max_results") or 10)
    query = body.get("query", "")
    no_ai = any(part.casefold() == "!ai" for part in query.split())
    clean = " ".join(part for part in query.split() if part.casefold() != "!ai")
    common = {
        "query": clean,
        "used_no_ai": no_ai,
        "normal_results_enabled": True,
        "overview_requested": category == "all" and not no_ai,
        "category": category,
        "provider": body.get("provider") or "fixture",
        "elapsed_ms": 18,
        "status": "partial" if "partial provider" in clean else "ready",
        "error": "fallback timed out" if "partial provider" in clean else "",
        # the chosen engine said no and a backup answered
        "backup_for": "exa" if "refused words" in clean else "",
        "backup_reason": "refused" if "refused words" in clean else "",
        "period": body.get("period", "") if category in ("all", "news") else "",
        "can_filter_period": True,
    }
    if category == "images":
        results = [
            {
                "title": f"search result layout {index + 1}",
                "url": f"https://images.example.test/layout/{index + 1}",
                "snippet": "result layout",
                "publisher": "images.example.test",
                "thumbnail_url": f"https://images.example.test/layout-{index + 1}.png",
                "image_url": f"https://images.example.test/layout-{index + 1}.png",
                "width": 1200 if index % 2 else 800,
                "height": 800 if index % 2 else 1200,
                "source_kind": "community",
                "source_quality": 5,
            }
            for index in range(min(requested, 65))
        ]
    elif category == "news":
        results = [
            {
                "title": f"search project release {index + 1}",
                "url": f"https://news.example.test/release/{index + 1}",
                "snippet": "" if index % 4 == 0 else "The release improves first-result latency.",
                "publisher": "news.example.test",
                "published": "" if index % 3 == 0 else "2026-07-13T12:10:18+00:00",
                "thumbnail_url": "" if index % 2 else f"https://news.example.test/{index + 1}.png",
                "source_kind": "release notes",
                "source_quality": 2,
            }
            for index in range(min(requested, 45))
        ]
    elif category == "videos":
        results = [
            {
                "title": f"how grounded search works {index + 1}",
                "url": f"https://video.example.test/watch/{index + 1}",
                "snippet": "A short system walkthrough.",
                "publisher": "video.example.test",
                "thumbnail_url": f"https://video.example.test/thumb-{index + 1}.png",
                "duration": "6:24",
                "source_kind": "community",
                "source_quality": 5,
            }
            for index in range(min(requested, 21))
        ]
    else:
        seed = [
            {
                "title": "official search release notes",
                "url": "https://docs.example.test/releases/4.0",
                "snippet": "Version 4.0 is the current supported release.",
                "publisher": "docs.example.test",
                "source_kind": "release notes",
                "source_quality": 2,
            },
            {
                "title": "search source repository",
                "url": "https://code.example.test/project",
                "snippet": "Source and issue history.",
                "publisher": "code.example.test",
                "source_kind": "source repository",
                "source_quality": 3,
            },
        ]
        results = [
            {
                **seed[index % len(seed)],
                "title": f"{seed[index % len(seed)]['title']} {index + 1}",
                "url": f"{seed[index % len(seed)]['url']}/{index + 1}",
            }
            for index in range(min(requested, 12))
        ]
    totals = {"all": 12, "images": 65, "news": 45, "videos": 21}
    strips = {}
    if category == "all" and "strip rows" in clean:
        # a search that asks for news and pictures: the server sends a few of each with the results
        strips = {
            "news": [
                {
                    "title": f"strip story {index + 1} with a title long enough to need its dots at the end",
                    "url": f"https://news.example.test/strip/{index + 1}",
                    "publisher": "news.example.test",
                    "published": "2026-07-13T12:10:18+00:00",
                }
                for index in range(3)
            ],
            "images": [
                {
                    "title": f"strip picture {index + 1}",
                    "url": f"https://images.example.test/strip/{index + 1}",
                    "publisher": "images.example.test",
                    "thumbnail_url": f"https://images.example.test/strip-{index + 1}.png",
                    "image_url": f"https://images.example.test/strip-{index + 1}.png",
                    "width": 1200 if index % 2 else 800,
                    "height": 800 if index % 2 else 1200,
                }
                for index in range(8)
            ],
        }
    return {
        **common,
        "results": results,
        "has_more": len(results) < totals[category],
        "overview_seed": results if common["overview_requested"] else [],
        "strips": strips,
    }


def knowledge_panel(typed: str) -> dict | None:
    """wikipedia's summary, in the shape the server sends, for the one search that names a page."""
    if typed.replace("!ai", "").strip() != "toronto":
        return None
    return {
        "title": "Toronto",
        "description": "Most populous city in Canada",
        "extract": "Toronto is the most populous city in Canada and the capital city of the "
        "Canadian province of Ontario. It is located on a harbour at the northwestern shore of "
        "Lake Ontario.",
        "url": "https://en.wikipedia.org/wiki/Toronto",
        "language": "en",
        "source": "wikipedia",
        "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8b/toronto.jpg/500px-t.jpg",
        "image_width": 500,
        "image_height": 300,
    }


def check_knowledge(page, viewport: dict, requests: list[dict]) -> None:
    """the panel that says what the searched thing is: beside the results where the section is
    wide enough, one block over them otherwise, and never a late push on the results."""
    panel = page.locator("#andromeda-knowledge")
    page.locator("#andromeda-query").fill("toronto !ai")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_selector("#andromeda-knowledge:not([hidden]) .andromeda-knowledge-title")
    page.wait_for_selector(".andromeda-knowledge-media img")
    link = page.locator(".andromeda-knowledge-title")
    assert link.inner_text() == "Toronto"
    assert link.get_attribute("href") == "https://en.wikipedia.org/wiki/Toronto"
    assert link.get_attribute("target") == "_blank"
    assert "noopener" in link.get_attribute("rel")
    assert page.locator(".andromeda-knowledge-source").inner_text() == "en.wikipedia.org"
    assert panel.get_attribute("aria-labelledby") == "andromeda-knowledge-title"
    assert page.locator("#andromeda-knowledge-title").count() == 1
    box = panel.bounding_box()
    results = page.locator("#andromeda-results").bounding_box()
    first = page.locator("#andromeda-results .andromeda-result").first.bounding_box()
    title = link.bounding_box()
    assert box and results and first and title
    assert title["height"] >= 44
    beside = viewport["width"] >= 1440
    if beside:
        # its own column: the results keep their place and their width
        assert box["x"] >= results["x"] + results["width"] + 32, (box, results)
        assert abs(box["y"] - first["y"]) <= 2, (box, first)
    else:
        assert box["y"] + box["height"] <= first["y"], (box, first)
    assert box["x"] + box["width"] <= viewport["width"]
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    # keyboard: the title is a link like any result title, with a visible focus state
    link.focus()
    assert page.evaluate("document.activeElement.className") == "andromeda-knowledge-title"

    # a search that names no page takes the panel away
    page.locator("#andromeda-query").fill("different !ai")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_function(
        "() => document.getElementById('andromeda-result-meta').textContent.trim() !== ''"
        " && document.getElementById('andromeda-knowledge').hidden"
    )
    assert panel.locator("*").count() == 0

    # wikipedia answering after the results: beside them it still shows, over them it would
    # push the results down under the reader, so there it stays away
    held = []
    page.route("**/api/andromeda/knowledge*", lambda route: held.append(route))
    sent = len(requests)
    page.locator("#andromeda-query").fill("toronto !ai")
    page.locator("#andromeda-form").press("Enter")
    for _ in range(100):
        if held and len(requests) > sent:
            break
        page.wait_for_timeout(50)
    assert held, "the panel was never asked for"
    assert len(requests) > sent, "the search never left"
    # the results wait 150 ms for the panel, then show without it
    page.wait_for_timeout(600)
    assert panel.is_hidden()
    before = page.locator("#andromeda-results .andromeda-result").first.bounding_box()
    held[0].fallback()
    if beside:
        page.wait_for_selector("#andromeda-knowledge:not([hidden])")
    else:
        page.wait_for_timeout(400)
        assert panel.is_hidden()
    after = page.locator("#andromeda-results .andromeda-result").first.bounding_box()
    assert before == after, (before, after)
    page.unroute("**/api/andromeda/knowledge*")

    # a picture that is gone leaves no empty frame behind
    page.route(
        "**/api/andromeda/media*",
        lambda route: route.fulfill(
            status=200,
            content_type="image/svg+xml",
            headers={"x-andromeda-media-state": "unavailable"},
            body="<svg xmlns='http://www.w3.org/2000/svg'/>",
        ),
    )
    sent = len(requests)
    page.locator("#andromeda-query").fill("toronto !ai")
    page.locator("#andromeda-form").press("Enter")
    for _ in range(100):
        if len(requests) > sent:
            break
        page.wait_for_timeout(50)
    page.wait_for_selector("#andromeda-knowledge:not([hidden]) .andromeda-knowledge-title")
    page.wait_for_function("() => !document.querySelector('.andromeda-knowledge-media')")
    assert page.locator(".andromeda-knowledge-text").is_visible()
    page.unroute("**/api/andromeda/media*")


def check_period_and_related(page, viewport: dict, requests: list[dict]) -> None:
    """the date filter by the tabs and the related searches under the results."""
    sent = len(requests)
    page.locator("#andromeda-query").fill("toronto !ai")
    page.locator("#andromeda-form").press("Enter")
    # the search before this one keeps its rows up until this one is sent (the spelling check
    # comes first): measured in that gap, a row disappears between two readings
    for _ in range(200):
        if len(requests) > sent:
            break
        page.wait_for_timeout(50)
    assert len(requests) > sent, "the search was never sent"
    page.wait_for_selector("#andromeda-related:not([hidden]) .andromeda-related-item")
    period = page.locator("#andromeda-period")
    assert period.is_visible()
    assert requests[-1]["period"] == ""
    tabs = page.locator(".andromeda-tabs").bounding_box()
    box = period.bounding_box()
    first = page.locator("#andromeda-results .andromeda-result").first.bounding_box()
    assert tabs and box and first, (tabs, box, first)
    assert box["height"] >= 44
    assert box["x"] + box["width"] <= viewport["width"]
    # beside the tabs with a gap, or on its own row under them: never touching, never over them
    beside = box["y"] < tabs["y"] + tabs["height"]
    assert (
        (box["x"] >= tabs["x"] + tabs["width"] + 8)
        if beside
        else (box["y"] >= tabs["y"] + tabs["height"] + 8)
    ), (tabs, box)
    # opening it moves nothing (a real pointer: a scripted click scrolls the page first)
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_selector('[role="option"]:has-text("past week")', state="visible")
    assert page.locator(".andromeda-tabs").bounding_box() == tabs
    assert period.bounding_box() == box
    assert page.locator("#andromeda-results .andromeda-result").first.bounding_box() == first
    options = page.locator('[role="option"]:visible').all_inner_texts()
    assert [text.strip() for text in options][-5:] == [
        "any time",
        "past 24 hours",
        "past week",
        "past month",
        "past year",
    ], options
    sent = len(requests)
    page.get_by_role("option", name="past week").click()
    for _ in range(100):
        if len(requests) > sent:
            break
        page.wait_for_timeout(50)
    assert requests[-1]["period"] == "week", requests[-1]
    assert "t=week" in page.url
    assert period.get_attribute("data-value") == "week"
    # a picture has no date: the filter leaves with the tab and is not sent
    page.locator('[data-andromeda-category="images"]').click()
    page.wait_for_function("() => document.getElementById('andromeda-period').hidden")
    assert requests[-1]["period"] == ""
    page.locator('[data-andromeda-category="all"]').click()
    page.wait_for_selector("#andromeda-related:not([hidden]) .andromeda-related-item")
    assert requests[-1]["period"] == "week"
    # related searches: plain rows a finger can hit, and one tap searches it
    rows = page.locator(".andromeda-related-item")
    assert rows.count() >= 2
    for index in range(rows.count()):
        row = rows.nth(index).bounding_box()
        assert row and row["height"] >= 44 and row["x"] + row["width"] <= viewport["width"], row
    wanted = rows.first.inner_text().strip()
    sent = len(requests)
    rows.first.click()
    for _ in range(100):
        if len(requests) > sent:
            break
        page.wait_for_timeout(50)
    assert requests[-1]["query"] == wanted, (requests[-1]["query"], wanted)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    # back to any time, so the checks after this one search as before
    box = period.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    sent = len(requests)
    page.get_by_role("option", name="any time").click()
    for _ in range(100):
        if len(requests) > sent:
            break
        page.wait_for_timeout(50)
    assert requests[-1]["period"] == ""
    assert "t=" not in page.url.split("?", 1)[-1]


def check_strips(page, viewport: dict, requests: list[dict]) -> None:
    """news rows above the results and pictures after the third, sent with the results."""
    sent = len(requests)
    page.locator("#andromeda-query").fill("strip rows !ai")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_selector("#andromeda-results > .andromeda-strip")
    # they came in the search's own reply: no second request, so nothing arrives late
    assert len(requests) == sent + 1, requests[sent:]
    order = page.evaluate(
        "[...document.querySelectorAll('#andromeda-results > *')]"
        ".map(node => node.dataset.strip || 'result')"
    )
    assert order[:5] == ["news", "result", "result", "result", "images"], order
    assert order.count("news") == 1 and order.count("images") == 1, order
    fourth = page.locator("#andromeda-results .andromeda-result").nth(3)
    before = fourth.bounding_box()
    page.wait_for_function(
        "() => document.querySelectorAll('.andromeda-strip-image img.loaded').length >= 4"
    )
    assert fourth.bounding_box() == before, "a picture that loaded moved the results under it"
    stories = page.locator(".andromeda-strip-story")
    assert stories.count() == 3
    heights = set()
    for index in range(3):
        row = stories.nth(index).bounding_box()
        assert row and row["x"] + row["width"] <= viewport["width"], row
        heights.add(round(row["height"]))
        title = stories.nth(index).locator(".andromeda-strip-story-title")
        assert title.get_attribute("href").startswith("https://news.example.test/strip/")
        # a long title ends in dots on its one line instead of making its row taller
        assert title.evaluate("node => node.scrollWidth > node.clientWidth") or (
            viewport["width"] > 1000
        )
    assert len(heights) == 1, heights
    # the pictures fill whole rows inside their box; one that fits no row is cut off whole
    shown = page.evaluate(
        """() => { const list = document.querySelector('.andromeda-strip-images .andromeda-strip-list');
          const box = list.getBoundingClientRect();
          return [...list.children].map(tile => tile.getBoundingClientRect())
            .filter(tile => tile.top < box.bottom - 1)
            .map(tile => [tile.left >= box.left - 1, tile.right <= box.right + 1, tile.bottom <= box.bottom + 1, Math.round(tile.height)]); }"""
    )
    assert len(shown) >= 4, shown
    assert all(left and right and bottom for left, right, bottom, _ in shown), shown
    assert len({height for *_, height in shown}) == 1, shown
    for kind in ("news", "images"):
        more = page.locator(f".andromeda-strip-{kind} .andromeda-strip-more").bounding_box()
        assert more and more["height"] >= 44, more
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    # more results draws the list again: the rows stay where they were, once each
    more_results = page.locator("#andromeda-more-results")
    if more_results.is_visible():
        more_results.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#andromeda-results .andromeda-result').length > 10"
        )
        order = page.evaluate(
            "[...document.querySelectorAll('#andromeda-results > *')]"
            ".map(node => node.dataset.strip || 'result')"
        )
        assert order[:5] == ["news", "result", "result", "result", "images"], order
        assert order.count("news") == 1 and order.count("images") == 1, order
    # a picture opens large in place, stepping through the strip's own pictures
    page.locator(".andromeda-strip-image").first.click()
    page.wait_for_selector(".andromeda-preview .dialog-title", state="visible")
    assert page.locator(".andromeda-preview .dialog-title").inner_text() == "strip picture 1"
    page.keyboard.press("ArrowRight")
    page.wait_for_function(
        "() => document.querySelector('.andromeda-preview .dialog-title')?.textContent"
        " === 'strip picture 2'"
    )
    page.keyboard.press("Escape")
    page.wait_for_selector(".andromeda-preview", state="detached")
    # the heading opens that tab for the same search
    sent = len(requests)
    page.locator(".andromeda-strip-news .andromeda-strip-more").click()
    for _ in range(100):
        if len(requests) > sent:
            break
        page.wait_for_timeout(50)
    assert requests[-1]["category"] == "news", requests[-1]
    page.wait_for_selector("#andromeda-news .andromeda-news-card")
    # a search that asks for neither shows neither
    page.locator('[data-andromeda-category="all"]').click()
    page.locator("#andromeda-query").fill("toronto !ai")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_selector("#andromeda-results .andromeda-result")
    page.wait_for_function("() => !document.querySelector('#andromeda-results > .andromeda-strip')")


def mock_api(route: Route, requests: list[dict], overview_requests: list[dict]) -> None:
    request = route.request
    if "/api/andromeda/media" in request.url:
        route.fulfill(status=200, content_type="image/png", body=PNG)
        return
    path = request.url.split("/api/andromeda", 1)[-1].split("?", 1)[0]
    if path == "/suggest":
        typed = parse_qs(urlsplit(request.url).query).get("q", [""])[0]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"query": typed, "suggestions": [f"{typed} release notes", f"{typed}ent events"]}
            ),
        )
        return
    if path == "/knowledge":
        typed = parse_qs(urlsplit(request.url).query).get("q", [""])[0]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"query": typed, "panel": knowledge_panel(typed)}),
        )
        return
    if path == "/providers":
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "selected": "searxng",
                    "providers": [
                        {"value": "searxng", "label": "searxng", "available": True},
                        {"value": "brave", "label": "brave", "available": False},
                        {"value": "duckduckgo", "label": "duckduckgo", "available": True},
                    ],
                }
            ),
        )
        return
    if path == "/search":
        body = request.post_data_json
        requests.append(body)
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(search_payload(body))
        )
        return
    if path == "/overview/preview":
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "endpoint_id": "fixture-remote",
                    "endpoint": "remote fixture",
                    "model": "fixture-model",
                    "privacy_class": "remote",
                    "confirm_each_search": True,
                }
            ),
        )
        return
    if path == "/overview":
        overview_requests.append(request.post_data_json)
        quote = "Version 4.0 is the current supported release."
        claim = {
            "text": "Version 4.0 is the current supported release.",
            "citations": [
                {
                    "source_id": "s1",
                    "quote": quote,
                    "url": "https://docs.example.test/releases/4.0",
                    "title": "official search release notes",
                    "source_kind": "release notes",
                    "source_quality": 2,
                }
            ],
        }
        evidence = {
            "id": "s1",
            "title": "official search release notes",
            "url": "https://docs.example.test/releases/4.0",
            "source_kind": "release notes",
            "source_quality": 2,
            "passages": [quote],
        }
        overview = {
            "status": "ready",
            "key_answer": {
                **claim,
                "text": "Version 4.0 is the current supported release.",
                "focus": "4.0",
            },
            "claims": [claim],
            "freshness": {"checked_on": "2026-07-13", "newest_version_seen": "4.0"},
        }
        stream = "".join(
            [
                f"data: {json.dumps({'type': 'evidence', 'sources': [evidence]})}\n\n",
                f"data: {json.dumps({'type': 'claim', 'claim': claim})}\n\n",
                f"data: {json.dumps({'type': 'overview', 'overview': overview})}\n\n",
                "data: [DONE]\n\n",
            ]
        )
        route.fulfill(status=200, content_type="text/event-stream", body=stream)
        return
    verifier_model = {
        "endpoint_id": "fixture-verifier",
        "endpoint": "local verifier fixture",
        "model": "fixture-verifier-model",
        "privacy_class": "local",
    }
    verification = {
        "id": "verification-fixture",
        "status": "checked",
        "model": verifier_model,
        "result": {
            "status": "checked",
            "checked_on": date.today().isoformat(),
            "counts": {"verified": 2, "corrected": 0, "conflicting": 0, "insufficient": 0},
            "changes": [],
        },
    }
    if path == "/verification/preview":
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"status": "ready", "model": verifier_model, "confirm_each_search": True}
            ),
        )
        return
    if path == "/verification" and request.method == "POST":
        route.fulfill(status=200, content_type="application/json", body=json.dumps(verification))
        return
    if path == "/verification/verification-fixture" and request.method == "GET":
        route.fulfill(status=200, content_type="application/json", body=json.dumps(verification))
        return
    if path == "/saved" and request.method == "GET":
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"searches": [], "recovery_scopes": ["a" * 64]}),
        )
        return
    if path == "/saved" and request.method == "POST":
        route.fulfill(status=200, content_type="application/json", body='{"id": "saved-fixture"}')
        return
    route.continue_()


def run_case(browser, *, viewport: dict, mobile: bool, theme: str, screenshot: str) -> None:
    context = browser.new_context(
        viewport=viewport,
        is_mobile=mobile,
        reduced_motion="reduce",
        service_workers="block",
    )
    colors = (
        {
            "bg": "#f5f4f1",
            "text": "#111111",
            "panel": "#efede9",
            "faint": "#666666",
            "accent": "#686fd8",
        }
        if theme == "light"
        else {
            "bg": "#090909",
            "text": "#f0f0f0",
            "panel": "#121212",
            "faint": "#777777",
            "accent": "#9298ff",
        }
    )
    appearance = {
        "_stored": True,
        "preset": theme,
        "colors": colors,
        "font": "sans",
        "density": "comfortable",
        "bgPattern": "none",
        "frosted": False,
    }
    context.add_init_script(
        "localStorage.setItem('alles-appearance', " + json.dumps(json.dumps(appearance)) + ");"
    )
    page = context.new_page()
    errors: list[str] = []
    server_errors: list[str] = []
    requests: list[dict] = []
    overview_requests: list[dict] = []
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "response",
        lambda response: (
            server_errors.append(f"{response.status} {response.url}")
            if response.status >= 500
            else None
        ),
    )
    page.route(
        "**/api/andromeda/**",
        lambda route: mock_api(route, requests, overview_requests),
    )
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("#andromeda-view", state="visible")
    assert page.locator("#andromeda-view").get_attribute("data-state") == "idle"
    assert page.locator("#andromeda-idle-home").count() == 0
    assert page.locator("#app-drawer-btn").is_visible()
    assert page.locator("#andromeda-view select:visible").count() == 0
    assert page.locator('#andromeda-view input[type="checkbox"]:visible').count() == 0
    assert page.locator('#andromeda-view input[type="radio"]:visible').count() == 0

    # settings are the one settings screen, opened on its andromeda section
    page.locator("#andromeda-idle-settings").click()
    page.wait_for_selector("#settings-modal #s-pane-andromeda.active", state="visible")
    assert page.locator("#andromeda-settings-panel").count() == 0
    page.keyboard.press("Escape")
    assert page.locator("#settings-modal").is_hidden()
    assert (
        page.locator("#andromeda-provider, #andromeda-exact-model, #andromeda-saved").count() == 0
    )

    # completions show under the box while typing, and the keyboard picks one
    page.locator("#andromeda-query").click()
    page.keyboard.type("curr")
    # an earlier case's search may sit above them as a recent one: wait for the completions
    page.wait_for_function(
        "() => [...document.querySelectorAll('#andromeda-history [data-history-index]')]"
        ".some(row => row.textContent.includes('curr release notes'))"
    )
    options = page.locator("#andromeda-history [data-history-index]")
    assert [text.strip() for text in options.all_inner_texts()][-2:] == [
        "curr release notes",
        "current events",
    ], options.all_inner_texts()
    assert "suggestions" in page.locator("#andromeda-history").inner_text()
    panel_box = page.locator("#andromeda-history").bounding_box()
    assert panel_box and panel_box["x"] >= 0
    assert panel_box["x"] + panel_box["width"] <= viewport["width"]
    assert all(box["height"] >= 44 for box in (option.bounding_box() for option in options.all()))
    page.keyboard.press("ArrowDown")
    assert (
        page.locator("#andromeda-query").get_attribute("aria-activedescendant")
        == "andromeda-history-0"
    )
    page.keyboard.press("Escape")
    assert page.locator("#andromeda-history").is_hidden()
    assert page.locator("#andromeda-view").get_attribute("data-state") == "idle"

    page.locator("#andromeda-query").fill("current search release")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_selector(".dialog-overlay [data-dialog-confirm]", state="visible")
    # the reply for the text just searched must not open the list again over the results
    assert page.locator("#andromeda-history").is_hidden()
    assert "selected web evidence" in page.locator(".dialog-msg").inner_text()
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    page.wait_for_selector(".andromeda-marker", state="visible")
    assert (
        page.locator(".andromeda-app-head").evaluate("el => getComputedStyle(el).borderBottomWidth")
        == "0px"
    )
    assert page.locator("#andromeda-go-home").count() == 0
    assert page.locator(".andromeda-brand").count() == 0
    search_box = page.locator("#andromeda-form").bounding_box()
    result_box = page.locator(".andromeda-result-column").bounding_box()
    assert search_box and result_box
    assert abs(search_box["x"] - result_box["x"]) <= 1
    assert abs(search_box["width"] - result_box["width"]) <= 1
    assert requests[-1]["category"] == "all"
    assert "provider" not in requests[-1]
    assert page.locator("#andromeda-overview").is_visible()
    assert page.locator("#andromeda-results-title").is_visible()
    overview_box = page.locator("#andromeda-overview").bounding_box()
    web_results_box = page.locator("#andromeda-all-results").bounding_box()
    assert overview_box and web_results_box
    # one section gap (2rem) under the overview rule
    assert web_results_box["y"] - (overview_box["y"] + overview_box["height"]) >= 31
    # the overview reads apart from the web results as its own tinted surface, not a ruled block
    assert page.locator("#andromeda-overview").evaluate(
        """element => {
            const style = getComputedStyle(element);
            return style.borderBottomWidth === '0px'
                && style.backgroundColor !== 'rgba(0, 0, 0, 0)'
                && style.backgroundColor !== 'transparent';
        }"""
    )
    assert (
        page.locator("#andromeda-key-answer-text")
        .inner_text()
        .startswith("Version 4.0 is the current supported release.")
    )
    assert page.locator("#andromeda-key-answer-text mark").inner_text() == "4.0"
    page.wait_for_function(
        "() => document.querySelector('#andromeda-verification-state')?.textContent.includes('2 claims verified')"
    )
    assert "checked today" in page.locator("#andromeda-verification-state").inner_text()
    page.screenshot(path=screenshot.replace(".png", "-answer.png"), full_page=True)
    assert overview_requests[-1]["confirmed_endpoint_id"] == "fixture-remote"
    assert overview_requests[-1]["confirmed_model"] == "fixture-model"
    assert requests[-1]["max_results"] == 8
    assert page.locator(".andromeda-result-title").count() == 8
    assert page.locator(".andromeda-result").evaluate_all(
        "nodes => nodes.every(node => getComputedStyle(node).borderBottomWidth === '0px')"
    )
    assert page.locator(".andromeda-source-mark").count() == 8
    assert page.locator(".andromeda-source-mark img").count() == 0
    assert page.locator(".andromeda-source-mark > span").all_inner_texts() == [
        "de",
        "ce",
        "de",
        "ce",
        "de",
        "ce",
        "de",
        "ce",
    ]
    assert page.locator(".andromeda-result-select").count() == 0
    assert page.get_by_text("ranked links", exact=True).count() == 0
    assert page.locator("#andromeda-more-results").is_visible()
    assert (
        float(
            page.locator(".andromeda-result-column").evaluate(
                "el => parseFloat(getComputedStyle(el).paddingBottom)"
            )
        )
        >= 96
    )
    page.locator("#andromeda-more-results").click()
    page.wait_for_function(
        "() => document.querySelector('#andromeda-more-results').disabled === false"
    )
    assert requests[-1]["max_results"] == 16
    assert page.locator(".andromeda-result-title").count() == 12
    assert page.locator("#andromeda-more-results").is_hidden()
    assert (
        float(
            page.locator(".andromeda-result-title").first.evaluate(
                "el => parseFloat(getComputedStyle(el).fontSize)"
            )
        )
        >= 17
    )

    for category, selector in (
        ("images", ".andromeda-image-card"),
        ("news", ".andromeda-news-card"),
        ("videos", ".andromeda-video-card"),
    ):
        page.locator(f'[data-andromeda-category="{category}"]').click()
        page.wait_for_selector(selector, state="visible")
        assert requests[-1]["category"] == category
        assert page.locator("#andromeda-overview").is_hidden()
        assert page.locator(f'[data-andromeda-view="{category}"]').is_visible()
        if category == "news":
            assert page.locator(".andromeda-news-card").count() == 20
            assert page.locator(".andromeda-news-card.no-media").count() > 0
            assert (
                page.locator(".andromeda-news-source").first.evaluate(
                    "el => getComputedStyle(el).display"
                )
                == "block"
            )
            assert "T12:10:18" not in page.locator(".andromeda-news-date").first.inner_text()
        elif category == "images":
            assert page.locator(".andromeda-image-card").count() == 30
            assert (
                page.locator(".andromeda-image-card img").first.get_attribute("loading") == "lazy"
            )
            # lazy thumbnails finish decoding a moment after the grid renders
            page.wait_for_function(
                "() => { const img = document.querySelector('.andromeda-image-card img'); return !!img && img.complete && img.naturalWidth > 0; }"
            )
            # a click previews the picture in place; it used to leave for the source site
            cards = page.locator(".andromeda-image-card")
            first_title = cards.nth(0).locator(".andromeda-media-title").inner_text()
            second_title = cards.nth(1).locator(".andromeda-media-title").inner_text()
            pages_before = len(page.context.pages)
            cards.nth(0).click()
            preview = page.locator(".dialog-card.andromeda-preview")
            preview.wait_for(state="visible")
            assert len(page.context.pages) == pages_before
            assert preview.locator(".dialog-title").inner_text() == first_title
            assert preview.locator(".andromeda-preview-step").nth(0).is_disabled()
            stage = preview.locator(".andromeda-preview-stage").bounding_box()
            page.keyboard.press("ArrowRight")
            page.wait_for_function(
                "title => document.querySelector('.andromeda-preview .dialog-title')?.textContent === title",
                arg=second_title,
            )
            # stepping moves nothing: the stage keeps its box
            assert preview.locator(".andromeda-preview-stage").bounding_box() == stage
            assert preview.locator("a.btn.primary").get_attribute("href") == cards.nth(
                1
            ).get_attribute("href")
            assert preview.locator("a.btn.primary").get_attribute("target") == "_blank"
            preview.locator(".andromeda-preview-step").nth(0).click()
            assert preview.locator(".dialog-title").inner_text() == first_title
            assert preview.evaluate("card => card.contains(document.activeElement)")
            page.keyboard.press("Escape")
            preview.wait_for(state="detached")
            assert page.locator("#andromeda-images-results .andromeda-view-head span").count() == 0
            page.locator("#andromeda-more-results").click()
            page.wait_for_function(
                "() => document.querySelectorAll('.andromeda-image-card').length === 60"
            )
            assert requests[-1]["max_results"] == 60
        elif category == "videos":
            assert page.locator(".andromeda-video-card").count() == 20
            page.wait_for_function(
                "() => { const img = document.querySelector('.andromeda-video-card img'); return !!img && img.complete && img.naturalWidth > 0; }"
            )
            assert (
                page.locator(".andromeda-video-card")
                .first.get_attribute("href")
                .startswith("https://video.example.test/watch/")
            )

    page.locator('[data-andromeda-category="all"]').click()
    page.wait_for_selector(".dialog-overlay [data-dialog-cancel]", state="visible")
    page.locator(".dialog-overlay [data-dialog-cancel]").click()
    assert (
        "cancelled before anything was sent"
        in page.locator("#andromeda-overview-state").inner_text()
    )
    page.locator("#andromeda-query").fill("partial provider !ai")
    page.locator("#andromeda-form").press("Enter")
    # the old results stay up for the spelling check, so wait for this search's own status
    page.wait_for_function(
        "() => document.getElementById('andromeda-status').textContent.includes('some sources were unavailable')"
    )
    page.wait_for_selector(".andromeda-result-title", state="visible")
    assert page.locator(".andromeda-result-title").count() > 0
    assert page.locator("#andromeda-overview").is_hidden()

    sent = len(requests)
    page.locator("#andromeda-query").fill("official website !ai")
    page.locator("#andromeda-form").press("Enter")
    for _ in range(100):
        if len(requests) > sent:
            break
        page.wait_for_timeout(50)
    page.wait_for_selector(".andromeda-result-title", state="visible")
    assert requests[-1]["overview"] is False
    assert page.locator("#andromeda-overview").is_hidden()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    check_knowledge(page, viewport, requests)
    check_period_and_related(page, viewport, requests)
    check_strips(page, viewport, requests)
    # worse results get their reason: one quiet line under the tabs, gone with the next search
    page.locator("#andromeda-query").fill("refused words !ai")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_function(
        "() => document.getElementById('andromeda-status').textContent.includes('exa refused')"
    )
    notice = page.locator("#andromeda-status")
    assert notice.inner_text() == (
        "exa refused this search. these results are from the backup engines."
    )
    notice_box = notice.bounding_box()
    first_result = page.locator("#andromeda-results .andromeda-result").first.bounding_box()
    assert notice_box and first_result
    assert notice_box["y"] + notice_box["height"] <= first_result["y"]
    assert notice_box["x"] + notice_box["width"] <= viewport["width"]
    assert float(notice.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")) >= 13
    page.locator("#andromeda-query").fill("different !ai")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_function(
        "() => !document.getElementById('andromeda-status').textContent.includes('refused')"
        " && document.getElementById('andromeda-result-meta').textContent.trim() !== ''"
    )
    # a search still on its way must not write over the next one being typed
    held = []
    page.route("**/api/andromeda/search", lambda route: held.append(route))
    page.locator("#andromeda-query").fill("slow search !ai")
    page.locator("#andromeda-form").press("Enter")
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "the search request never left"
    page.locator("#andromeda-query").fill("typed meanwhile")
    sent = len(requests)
    held[0].fallback()
    for _ in range(100):
        if len(requests) > sent:
            break
        page.wait_for_timeout(50)
    page.wait_for_function(
        "() => document.getElementById('andromeda-result-meta').textContent.trim() !== ''"
    )
    assert page.locator("#andromeda-query").input_value() == "typed meanwhile"
    page.unroute("**/api/andromeda/search")
    page.keyboard.press("Escape")
    assert not errors, errors
    assert not server_errors, server_errors
    page.screenshot(path=screenshot, full_page=True)
    page.locator("#app-drawer-btn").click()
    page.locator('.app-drawer-item[data-view="today"]').click()
    page.wait_for_url(f"http://localhost:{PORT}/")
    context.close()


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        run_case(
            browser,
            viewport={"width": 1440, "height": 1000},
            mobile=False,
            theme="dark",
            screenshot="/tmp/alles-andromeda-desktop-dark.png",
        )
        run_case(
            browser,
            viewport={"width": 1440, "height": 1000},
            mobile=False,
            theme="light",
            screenshot="/tmp/alles-andromeda-desktop-light.png",
        )
        run_case(
            browser,
            viewport={"width": 390, "height": 844},
            mobile=True,
            theme="dark",
            screenshot="/tmp/alles-andromeda-mobile-dark.png",
        )
        run_case(
            browser,
            viewport={"width": 390, "height": 844},
            mobile=True,
            theme="light",
            screenshot="/tmp/alles-andromeda-mobile-light.png",
        )
        browser.close()
    print("andromeda browser gate passed")


if __name__ == "__main__":
    main()
