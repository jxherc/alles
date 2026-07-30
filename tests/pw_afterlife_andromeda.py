"""Focused browser gate for the real Afterlife Andromeda surface."""

import base64
import json
import os
from datetime import date

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
    return {
        **common,
        "results": results,
        "has_more": len(results) < totals[category],
        "overview_seed": results if common["overview_requested"] else [],
    }


def mock_api(route: Route, requests: list[dict], overview_requests: list[dict]) -> None:
    request = route.request
    if "/api/andromeda/media" in request.url:
        route.fulfill(status=200, content_type="image/png", body=PNG)
        return
    path = request.url.split("/api/andromeda", 1)[-1].split("?", 1)[0]
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
            body=json.dumps({"status": "ready", "model": verifier_model}),
        )
        return
    if path == "/verification" and request.method == "POST":
        route.fulfill(status=200, content_type="application/json", body=json.dumps(verification))
        return
    if path == "/verification/verification-fixture" and request.method == "GET":
        route.fulfill(status=200, content_type="application/json", body=json.dumps(verification))
        return
    if path == "/saved" and request.method == "GET":
        route.fulfill(status=200, content_type="application/json", body='{"searches": []}')
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
            "accent": "#818cf8",
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

    page.locator("#andromeda-idle-settings").click()
    assert page.locator("#andromeda-settings-panel").is_visible()
    page.locator("#andromeda-provider").click()
    page.locator(".custom-dropdown-option", has_text="searxng").click()
    assert page.locator("#andromeda-provider").get_attribute("data-value") == "searxng"
    page.keyboard.press("Escape")
    assert page.locator("#andromeda-settings-panel").is_hidden()

    page.locator("#andromeda-query").fill("current search release")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_selector(".dialog-overlay [data-dialog-confirm]", state="visible")
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
    assert requests[-1]["provider"] == "searxng"
    assert page.locator("#andromeda-overview").is_visible()
    assert page.locator("#andromeda-results-title").is_visible()
    overview_box = page.locator("#andromeda-overview").bounding_box()
    web_results_box = page.locator("#andromeda-all-results").bounding_box()
    assert overview_box and web_results_box
    assert web_results_box["y"] - (overview_box["y"] + overview_box["height"]) >= 39
    assert (
        page.locator("#andromeda-all-results").evaluate(
            "element => getComputedStyle(element).borderTopStyle"
        )
        == "solid"
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
            assert page.locator(".andromeda-image-card img").first.evaluate(
                "img => img.complete && img.naturalWidth > 0"
            )
            page.locator("#andromeda-more-results").click()
            page.wait_for_function(
                "() => document.querySelectorAll('.andromeda-image-card').length === 60"
            )
            assert requests[-1]["max_results"] == 60
        elif category == "videos":
            assert page.locator(".andromeda-video-card").count() == 20
            assert page.locator(".andromeda-video-card img").first.evaluate(
                "img => img.complete && img.naturalWidth > 0"
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
    page.wait_for_selector(".andromeda-result-title", state="visible")
    assert "some sources were unavailable" in page.locator("#andromeda-status").inner_text()
    assert page.locator(".andromeda-result-title").count() > 0
    assert page.locator("#andromeda-overview").is_hidden()

    page.locator("#andromeda-query").fill("official website !ai")
    page.locator("#andromeda-form").press("Enter")
    page.wait_for_selector(".andromeda-result-title", state="visible")
    assert requests[-1]["overview"] is False
    assert page.locator("#andromeda-overview").is_hidden()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
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
