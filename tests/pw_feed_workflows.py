"""Real feed writes/refresh/rendering against synthetic HTTP fixtures."""

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
    for width in (1440, 820, 390):
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            service_workers="block",
            reduced_motion="reduce",
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
        for feed in api.get(base + "/api/read/feeds").json()["feeds"]:
            assert api.delete(base + "/api/read/feeds/" + feed["id"]).ok
        page = context.new_page()
        page.set_default_timeout(5000)
        errors = []
        console = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        context.tracing.start(screenshots=True, snapshots=True)

        def record(name):
            rows.append(
                {"scenario_id": "library.feeds." + name, "profile": str(width), "status": "passed"}
            )
            (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

        try:
            page.goto(base + "/?view=read", wait_until="networkidle")
            page.locator("#read-feeds-btn").click()
            expect(page.locator("#feed-url")).to_be_enabled()
            good = f"https://feeds.example.invalid/good-{width}"
            bad = f"https://feeds.example.invalid/bad-{width}"

            def add(url):
                page.locator("#feed-url").fill(url)
                page.locator("#feed-url").press("Enter")

            page.route(
                base + "/api/read/feeds",
                lambda r: (
                    r.fulfill(status=503, json={"detail": "synthetic add outage"})
                    if r.request.method == "POST"
                    else r.continue_()
                ),
            )
            add(good)
            expect(page.locator(".read-feeds").get_by_role("alert")).to_contain_text(
                "synthetic add outage"
            )
            expect(page.locator("#feed-url")).to_have_value(good)
            page.unroute(base + "/api/read/feeds")

            def lose_add(route):
                if route.request.method != "POST":
                    route.continue_()
                    return
                response = route.fetch()
                assert response.ok
                route.fulfill(status=503, json={"detail": "synthetic lost add reply"})

            page.route(base + "/api/read/feeds", lose_add)
            page.locator("#feed-add").click()
            expect(page.locator(".read-feeds").get_by_role("alert")).to_contain_text(
                "synthetic lost add reply"
            )
            assert (
                sum(
                    feed["url"] == good
                    for feed in api.get(base + "/api/read/feeds").json()["feeds"]
                )
                == 1
            )
            page.unroute(base + "/api/read/feeds")
            page.locator("#feed-add").click()
            expect(page.locator("[data-feed-del]")).to_have_count(1)
            expect(page.locator("#feed-url")).to_have_value("")
            add(bad)
            expect(page.locator("[data-feed-del]")).to_have_count(2)
            record("add-failure-keeps-draft-and-real-retry-saves")
            page.locator("#feed-refresh").focus()
            page.keyboard.press("Enter")
            expect(page.locator(".read-feeds").get_by_role("alert")).to_contain_text(
                "1 feed checked; 2 new items saved; 1 feed failed"
            )
            expect(page.locator(".read-feeds")).to_contain_text(
                "feed returned an unsuccessful response"
            )
            expect(
                page.get_by_role("button", name=f"open Local post 1 good-{width}", exact=True)
            ).to_be_visible()
            saved = api.get(base + "/api/read").json()["items"]
            assert sum(f"/good-{width}/" in i["url"] for i in saved) == 2
            record("partial-refresh-saves-real-articles-and-identifies-failure")
            page.screenshot(path=str(out / f"{width}-partial.png"))
            page.locator("#read-feeds-btn").click()
            page.route(
                base + "/api/read/feeds",
                lambda r: r.fulfill(status=503, json={"detail": "synthetic list outage"}),
            )
            page.locator("#read-feeds-btn").click()
            expect(page.locator("[data-feed-del]")).to_have_count(2)
            expect(page.locator("#feed-retry")).to_be_visible()
            page.unroute(base + "/api/read/feeds")
            page.locator("#feed-retry").click()
            expect(page.locator("#feed-retry")).to_have_count(0)
            expect(page.locator("#feed-url")).to_be_focused()
            record("failed-list-retains-known-feeds-and-keyboard-retry")
            badid = next(
                f["id"]
                for f in api.get(base + "/api/read/feeds").json()["feeds"]
                if f["url"] == bad
            )

            def lose_delete(route):
                response = route.fetch()
                assert response.ok
                route.fulfill(status=503, json={"detail": "synthetic lost delete reply"})

            page.route(base + "/api/read/feeds/" + badid, lose_delete)
            page.locator(f'[data-feed-del="{badid}"]').click()
            expect(page.locator(".read-feeds").get_by_role("alert")).to_contain_text(
                "synthetic lost delete reply"
            )
            expect(page.locator(f'[data-feed-del="{badid}"]')).to_be_enabled()
            page.unroute(base + "/api/read/feeds/" + badid)
            page.locator(f'[data-feed-del="{badid}"]').click()
            expect(page.locator("[data-feed-del]")).to_have_count(1)
            record("lost-delete-retry-confirms-absence-and-keeps-articles")
            page.locator("#feed-url").fill("https://feeds.example.invalid/unfinished")
            page.locator("#feed-refresh").click()
            expect(page.locator(".read-feeds").get_by_role("status")).to_contain_text(
                "1 feed checked; 0 new items saved"
            )
            expect(page.locator("#feed-url")).to_have_value(
                "https://feeds.example.invalid/unfinished"
            )
            assert (
                sum(
                    f"/good-{width}/" in i["url"]
                    for i in api.get(base + "/api/read").json()["items"]
                )
                == 2
            )
            record("repeat-refresh-keeps-draft-and-saves-no-duplicates")
            page.locator("[data-feed-del]").click()
            expect(page.locator("[data-feed-del]")).to_have_count(0)
            page.locator("#feed-refresh").click()
            expect(page.locator(".read-feeds").get_by_role("status")).to_contain_text(
                "no feeds to refresh"
            )
            assert (
                sum(
                    f"/good-{width}/" in i["url"]
                    for i in api.get(base + "/api/read").json()["items"]
                )
                == 2
            )
            record("removal-keeps-saved-reading-and-empty-refresh-is-honest")
            assert not errors, errors
            assert all("503" in m or "404" in m or "400" in m for m in console), console
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
        except Exception as e:
            rows.append(
                {
                    "scenario_id": "library.feeds.current",
                    "profile": str(width),
                    "status": "failed",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
        finally:
            page.screenshot(path=str(out / f"{width}-final.png"))
            context.tracing.stop(path=str(out / f"{width}-trace.zip"))
            context.close()
            (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    browser.close()
assert all(r["status"] == "passed" for r in rows), rows
