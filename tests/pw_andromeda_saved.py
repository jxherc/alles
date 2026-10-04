"""Search save/reopen and uncertain-write recovery against an owned local store."""

import json
import os
import traceback
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

CASES = (
    "pending-recovery-load",
    "scope-change-open",
    "reload-focus",
    "confirmed-deleted-open",
    "larger-save-reopen",
    "category-save",
    "lost-reply-reload-check",
    "retry-one-snapshot",
    "missing-check-retry",
    "deleted-discard",
    "blocked-storage",
    "corrupt-storage",
    "new-query-during-save",
    "late-open",
    "recovery-load-failure",
    "malformed-save-reply",
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
                page.set_default_timeout(5000)
                errors, console, posts = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                endpoint = base + "/api/andromeda/saved"
                page.on(
                    "request",
                    lambda request: (
                        posts.append(request.post_data_json)
                        if request.url == endpoint and request.method == "POST"
                        else None
                    ),
                )
                context.tracing.start(screenshots=True, snapshots=True)

                def routes(route):
                    url = urlparse(route.request.url)
                    if url.netloc != urlparse(base).netloc:
                        route.abort()
                        return
                    if url.path == "/api/andromeda/providers":
                        route.fulfill(
                            json={
                                "selected": "fixture",
                                "providers": [
                                    {
                                        "value": "fixture",
                                        "label": "owned local fixture",
                                        "available": True,
                                    }
                                ],
                            }
                        )
                        return
                    if url.path == "/api/andromeda/search":
                        body = route.request.post_data_json
                        kind = body.get("category", "all")
                        count = min(13 if kind == "all" else 30, int(body.get("max_results") or 8))
                        route.fulfill(
                            json={
                                "query": body["query"],
                                "used_no_ai": True,
                                "overview_requested": False,
                                "normal_results_enabled": True,
                                "category": kind,
                                "provider": "fixture",
                                "status": "ready",
                                "elapsed_ms": 1,
                                "has_more": count < 13,
                                "results": [
                                    {
                                        "title": f"owned result {i}",
                                        "url": base + f"/owned/{i}",
                                        "snippet": "synthetic local excerpt",
                                        "publisher": "owned local source",
                                    }
                                    for i in range(count)
                                ],
                            }
                        )
                        return
                    if url.path.startswith("/api/andromeda/") and not url.path.startswith(
                        "/api/andromeda/saved"
                    ):
                        route.fulfill(
                            status=400, json={"detail": "fixture refuses external operations"}
                        )
                        return
                    route.continue_()

                context.route("**/*", routes)
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                query = f"owned {width} {case} !ai"

                def search(value=query):
                    page.locator("#andromeda-query").fill(value)
                    page.locator("#andromeda-query").press("Enter")
                    expect(page.locator(".andromeda-result")).to_have_count(8)

                def pending():
                    return page.evaluate(
                        "() => Object.keys(sessionStorage).filter(k=>k.startsWith('alles.andromeda.pending.v1:')).map(k=>JSON.parse(sessionStorage.getItem(k)))"
                    )

                def copies():
                    response = api.get(endpoint)
                    assert response.ok
                    return [item for item in response.json()["searches"] if item["query"] == query]

                def lose(route):
                    assert route.fetch().ok
                    route.fulfill(status=503, json={"detail": "synthetic lost save reply"})

                def fail_save(commit=True):
                    page.route(
                        endpoint,
                        lose
                        if commit
                        else lambda r: r.fulfill(status=503, json={"detail": "synthetic outage"}),
                    )
                    page.locator("#andromeda-save").click()
                    expect(page.locator("#andromeda-save-message")).to_contain_text("synthetic")
                    page.unroute(endpoint)
                    assert len(pending()) == 1

                def confirmed():
                    expect(page.locator("#andromeda-save-message")).to_have_text("search saved")
                    expect(page.locator("#andromeda-save-open")).to_be_visible()
                    assert not pending()
                    assert len(copies()) == 1

                def hold_response(url, method="GET"):
                    page.evaluate(
                        """({url,method}) => {
                        const fetch = window.fetch.bind(window);
                        window.fetch = async (target, options = {}) => {
                            const response = await fetch(target, options);
                            if (target === url && (options.method || 'GET') === method && !window.heldResponseReady) {
                                window.heldResponseReady = true;
                                await new Promise(resolve => { window.releaseHeldResponse = resolve; });
                            }
                            return response;
                        };
                    }""",
                        {"url": url, "method": method},
                    )

                def wait_held():
                    page.wait_for_function("window.heldResponseReady === true")

                def release_response():
                    page.evaluate("() => { window.releaseHeldResponse(); }")

                try:
                    page.goto(base + "/?app=andromeda", wait_until="networkidle")
                    expect(page.locator("#andromeda-save")).to_have_attribute(
                        "aria-disabled", "false"
                    )
                    search()
                    if case == "pending-recovery-load":
                        fail_save(False)
                        page.route(
                            endpoint,
                            lambda route: route.fulfill(
                                status=503, json={"detail": "synthetic pending-list outage"}
                            ),
                        )
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#andromeda-save-message")).to_contain_text(
                            "synthetic pending-list outage"
                        )
                        page.unroute(endpoint)
                        page.locator("#andromeda-save-reload").focus()
                        page.locator("#andromeda-save-reload").press("Enter")
                        expect(page.locator("#andromeda-save-message")).to_have_text(
                            "this search save still needs confirmation"
                        )
                        expect(page.locator("#andromeda-save-check")).to_be_focused()
                        page.locator("#andromeda-save-retry").click()
                        confirmed()
                    elif case in ("scope-change-open", "reload-focus"):

                        def list_outage(route):
                            if route.request.method == "GET":
                                route.fulfill(status=503, json={"detail": "synthetic list outage"})
                            else:
                                route.continue_()

                        page.route(endpoint, list_outage)
                        page.locator("#andromeda-save").click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text(
                            "synthetic list outage"
                        )
                        page.unroute(endpoint)
                        if case == "scope-change-open":
                            search("current query after scope change !ai")
                            hold_response("/api/andromeda/saved/" + copies()[0]["id"])
                            page.locator("#andromeda-save-open").click()
                            wait_held()
                            listing = api.get(endpoint).json()
                            listing["recovery_scopes"] = ["a" * 64]
                            page.route(endpoint, lambda route: route.fulfill(json=listing))
                            page.locator("#andromeda-save-reload").click()
                            expect(page.locator("#andromeda-save-reload")).to_be_hidden()
                            release_response()
                            page.wait_for_timeout(100)
                            expect(page.locator("#andromeda-query")).to_have_value(
                                "current query after scope change !ai"
                            )
                        else:
                            page.locator("#andromeda-save-reload").focus()
                            page.locator("#andromeda-save-reload").press("Enter")
                            expect(page.locator("#andromeda-save-reload")).to_be_hidden()
                            expect(page.locator("#andromeda-save-open")).to_be_focused()
                            expect(page.locator("#andromeda-save-message")).to_have_text(
                                "search saved"
                            )
                    elif case == "confirmed-deleted-open":
                        page.locator("#andromeda-save").click()
                        confirmed()
                        assert api.delete(endpoint + "/" + copies()[0]["id"]).ok
                        page.locator("#andromeda-save-open").click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text("not found")
                        page.locator("#andromeda-save").click()
                        expect(page.locator("#andromeda-save-message")).to_have_text("search saved")
                        assert len(posts) == 2 and len(copies()) == 1
                    elif case == "larger-save-reopen":
                        page.locator("#andromeda-more-results").click()
                        expect(page.locator(".andromeda-result")).to_have_count(13)
                        page.locator("#andromeda-save").click()
                        confirmed()
                        page.locator("#andromeda-save").click()
                        assert len(posts) == 1
                        search("another local query !ai")
                        page.locator("#andromeda-save-open").click()
                        expect(page.locator("#andromeda-query")).to_have_value(query)
                        expect(page.locator(".andromeda-result")).to_have_count(13)
                        expect(page.locator("#andromeda-query")).to_be_focused()
                        assert (
                            len(api.get(endpoint + "/" + copies()[0]["id"]).json()["results"]) == 13
                        )
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#andromeda-query")).to_have_value(query)
                        expect(page.locator(".andromeda-result")).to_have_count(13)
                        page.locator("#andromeda-save").press("Enter")
                        expect(page.locator("#andromeda-save-message")).to_have_text(
                            "this search is already saved"
                        )
                        assert len(posts) == 1 and len(copies()) == 1
                        changed_query = f"changed local query {width} !ai"
                        search(changed_query)
                        page.locator("#andromeda-save").click()
                        expect(page.locator("#andromeda-save-message")).to_have_text("search saved")
                        assert len(posts) == 2
                        assert posts[-1]["query"] == changed_query
                    elif case == "category-save":
                        page.locator("[data-andromeda-category=news]").click()
                        expect(page.locator(".andromeda-news-card")).to_have_count(20)
                        page.locator("#andromeda-save").click()
                        confirmed()
                        assert (
                            len(api.get(endpoint + "/" + copies()[0]["id"]).json()["results"]) == 20
                        )
                    elif case == "lost-reply-reload-check":
                        fail_save()
                        identity = pending()[0]["request_id"]
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#andromeda-save-query")).to_have_text(query)
                        assert pending()[0]["request_id"] == identity
                        page.locator("#andromeda-save-check").focus()
                        page.locator("#andromeda-save-check").press("Enter")
                        confirmed()
                        expect(page.locator("#andromeda-save-open")).to_be_focused()
                        assert len(posts) == 1
                        expect(page.locator("#andromeda-actions")).to_be_hidden()
                        expect(page.locator("#andromeda-result-tools")).to_be_hidden()
                    elif case == "retry-one-snapshot":
                        fail_save()
                        page.locator("#andromeda-save-retry").click()
                        confirmed()
                        assert len(posts) == 2 and posts[0] == posts[1]
                    elif case == "missing-check-retry":
                        fail_save(False)
                        page.locator("#andromeda-save-check").click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text("not found")
                        assert not copies()
                        page.locator("#andromeda-save-retry").click()
                        confirmed()
                        assert posts[0] == posts[1]
                    elif case == "deleted-discard":
                        fail_save()
                        assert api.delete(endpoint + "/" + copies()[0]["id"]).ok
                        page.locator("#andromeda-save-check").click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text("deleted")
                        page.locator("#andromeda-save-retry").click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text("deleted")
                        assert not copies()
                        page.locator("#andromeda-save-discard").click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text("discarded")
                        assert not pending()
                    elif case == "blocked-storage":
                        page.evaluate(
                            "() => {window.originalStorageSet=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.startsWith('alles.andromeda.pending.v1:'))throw new Error('synthetic storage blocked');return window.originalStorageSet.call(this,k,v)}}"
                        )
                        page.locator("#andromeda-save").click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text(
                            "allow browser storage"
                        )
                        assert not posts and not copies()
                        page.evaluate(
                            "() => { Storage.prototype.setItem=window.originalStorageSet; }"
                        )
                        page.locator("#andromeda-save").click()
                        confirmed()
                    elif case == "corrupt-storage":
                        scope = api.get(endpoint).json()["recovery_scopes"][0]
                        page.evaluate(
                            "key=>sessionStorage.setItem(key,'{broken')",
                            "alles.andromeda.pending.v1:" + scope,
                        )
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#andromeda-save-message")).to_contain_text(
                            "could not read"
                        )
                        page.locator("#andromeda-save-discard").click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text("discarded")
                        search()
                        page.locator("#andromeda-save").click()
                        confirmed()
                    elif case == "new-query-during-save":
                        hold_response("/api/andromeda/saved", "POST")
                        page.locator("#andromeda-save").focus()
                        page.locator("#andromeda-save").press("Enter")
                        wait_held()
                        page.locator("#andromeda-save").press("Enter")
                        assert len(posts) == 1
                        search("new query while saving !ai")
                        release_response()
                        confirmed()
                        expect(page.locator("#andromeda-query")).to_have_value(
                            "new query while saving !ai"
                        )
                        expect(page.locator("#andromeda-save-query")).to_have_text(query)
                    elif case == "late-open":
                        page.locator("#andromeda-save").click()
                        confirmed()
                        hold_response("/api/andromeda/saved/" + copies()[0]["id"])
                        page.locator("#andromeda-save-open").click()
                        wait_held()
                        search("new query while opening !ai")
                        release_response()
                        page.wait_for_timeout(100)
                        expect(page.locator("#andromeda-query")).to_have_value(
                            "new query while opening !ai"
                        )
                    elif case == "recovery-load-failure":
                        page.route(
                            endpoint,
                            lambda route: route.fulfill(
                                status=503, json={"detail": "synthetic list outage"}
                            ),
                        )
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#andromeda-save-message")).to_contain_text(
                            "synthetic list outage"
                        )
                        assert not posts
                        page.locator("#andromeda-save-reload").focus()
                        with page.expect_response(
                            lambda response: (
                                response.url == endpoint and response.request.method == "GET"
                            )
                        ):
                            page.locator("#andromeda-save-reload").press("Enter")
                        expect(page.locator("#andromeda-save-message")).to_contain_text(
                            "synthetic list outage"
                        )
                        expect(page.locator("#andromeda-save-reload")).to_be_focused()
                        page.unroute(endpoint)
                        page.locator("#andromeda-save-reload").click()
                        expect(page.locator("#andromeda-save")).to_have_attribute(
                            "aria-disabled", "false"
                        )
                        expect(page.locator("#andromeda-save-recovery")).to_be_hidden()
                        expect(page.locator("#andromeda-query")).to_be_focused()
                        search()
                        page.locator("#andromeda-save").click()
                        confirmed()
                    elif case == "malformed-save-reply":

                        def malformed(route):
                            assert route.fetch().ok
                            route.fulfill(json={"id": "unrelated", "query": "wrong"})

                        page.route(endpoint, malformed)
                        page.locator("#andromeda-save").click()
                        expect(page.locator("#andromeda-save-message")).to_contain_text(
                            "incomplete"
                        )
                        page.unroute(endpoint)
                        assert len(pending()) == 1
                        page.locator("#andromeda-save-check").click()
                        confirmed()
                    if page.locator("#andromeda-save-recovery").is_visible():
                        page.locator("#andromeda-save-recovery").scroll_into_view_if_needed()
                    for button in page.locator("#andromeda-save-recovery button:visible").all():
                        assert button.bounding_box()["height"] >= 44
                    rendered = page.evaluate(
                        "() => ({width:innerWidth,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth+1,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches})"
                    )
                    assert not errors, errors
                    assert not rendered["overflow"] and rendered["reduced"], rendered
                    assert not [
                        line
                        for line in console
                        if "Failed to load resource" not in line and "net::ERR_FAILED" not in line
                    ], console
                    rows.append(
                        {
                            "profile": str(width),
                            "case": case,
                            "status": "passed",
                            "rendered": rendered,
                            "console": console,
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "profile": str(width),
                            "case": case,
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
    print(json.dumps(rows, indent=2))
    if any(row["status"] != "passed" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
