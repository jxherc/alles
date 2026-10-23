"""Synthetic response failures on the real owned feed interface."""

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
    for width in (1440, 390):
        for case in (
            "refresh-rejected",
            "refresh-partial",
            "delete-rejected",
            "list-unavailable",
            "draft-refresh",
        ):
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
            for f in api.get(base + "/api/read/feeds").json()["feeds"]:
                assert api.delete(base + "/api/read/feeds/" + f["id"]).ok
            feed = api.post(
                base + "/api/read/feeds", data={"url": "https://example.invalid/local-feed"}
            )
            assert feed.ok
            fid = feed.json()["id"]
            page = context.new_page()
            page.set_default_timeout(2500)
            page.route(
                base + "/api/read/feeds/refresh",
                lambda r: r.fulfill(
                    json={
                        "ok": True,
                        "checked": 1,
                        "failed": 0,
                        "added": 0,
                        "skipped": 0,
                        "feeds": [{"id": fid, "ok": True, "added": 0}],
                    }
                ),
            )
            try:
                page.goto(base + "/?view=read", wait_until="networkidle")
                page.locator("#read-feeds-btn").click()
                expect(page.locator("[data-feed-del]")).to_be_visible()
                if case == "refresh-rejected":
                    page.route(
                        base + "/api/read/feeds/refresh",
                        lambda r: r.fulfill(
                            status=503, json={"detail": "synthetic refresh outage"}
                        ),
                    )
                    page.locator("#feed-refresh").click()
                    expect(page.locator(".read-feeds").get_by_role("alert")).to_contain_text(
                        "synthetic refresh outage"
                    )
                elif case == "refresh-partial":
                    page.route(
                        base + "/api/read/feeds/refresh",
                        lambda r: r.fulfill(
                            json={
                                "ok": False,
                                "checked": 1,
                                "failed": 1,
                                "added": 2,
                                "skipped": 0,
                                "feeds": [
                                    {
                                        "id": fid,
                                        "ok": False,
                                        "added": 0,
                                        "error": "could not fetch this feed",
                                    },
                                    {"id": "synthetic-other", "ok": True, "added": 2},
                                ],
                            }
                        ),
                    )
                    page.locator("#feed-refresh").click()
                    expect(page.locator(".read-feeds").get_by_role("alert").first).to_contain_text(
                        "1 feed failed"
                    )
                    expect(page.locator(".read-feeds")).to_contain_text("could not fetch this feed")
                elif case == "delete-rejected":
                    page.route(
                        base + "/api/read/feeds/" + fid,
                        lambda r: r.fulfill(status=503, json={"detail": "synthetic remove outage"}),
                    )
                    page.locator("[data-feed-del]").click()
                    expect(page.locator(".read-feeds").get_by_role("alert")).to_contain_text(
                        "synthetic remove outage"
                    )
                    expect(page.locator("[data-feed-del]")).to_be_visible()
                elif case == "list-unavailable":
                    page.locator("#read-feeds-btn").click()
                    page.route(
                        base + "/api/read/feeds",
                        lambda r: r.fulfill(status=503, json={"detail": "synthetic list outage"}),
                    )
                    page.locator("#read-feeds-btn").click()
                    expect(page.locator("[data-feed-del]")).to_be_visible()
                    expect(page.locator(".read-feeds").get_by_role("alert")).to_contain_text(
                        "could not load feeds"
                    )
                else:
                    page.locator("#feed-url").fill("https://example.invalid/draft")
                    with page.expect_response(base + "/api/read/feeds/refresh"):
                        page.locator("#feed-refresh").click()
                    expect(page.locator("#feed-refresh")).to_have_text("refresh")
                    expect(page.locator("#feed-url")).to_have_value("https://example.invalid/draft")
                rows.append(
                    {
                        "scenario_id": "library.feeds." + case,
                        "profile": str(width),
                        "status": "passed",
                    }
                )
            except Exception as e:
                rows.append(
                    {
                        "scenario_id": "library.feeds." + case,
                        "profile": str(width),
                        "status": "failed",
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    }
                )
            finally:
                page.screenshot(path=str(out / f"{width}-{case}.png"))
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    browser.close()
assert all(r["status"] == "passed" for r in rows), rows
