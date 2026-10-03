"""Saved source navigation keeps the most recently selected article."""

import json
import os
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
        for late in ("success", "failure", "left"):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
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
            items = []
            for name in ("earlier", "selected"):
                result = api.post(
                    base + "/api/read/save-news",
                    data={
                        "url": f"https://example.invalid/order-{width}-{late}-{name}",
                        "title": f"{name} source {width} {late}",
                        "excerpt": f"synthetic {name} passage",
                    },
                )
                assert result.ok, result.text()
                items.append(result.json()["item"])
            page = context.new_page()
            page.set_default_timeout(6000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            held = []
            url = base + "/api/read/" + items[0]["id"]
            page.route(url, lambda route: held.append(route))
            context.tracing.start(screenshots=True, snapshots=True)
            try:
                page.goto(base + "/?view=library", wait_until="networkidle")
                page.get_by_role("tab", name="saved", exact=True).click()
                page.locator(f'[data-open="{items[0]["id"]}"]').click()
                page.wait_for_timeout(50)
                assert len(held) == 1
                if late == "left":
                    page.get_by_role("tab", name="books", exact=True).click()
                else:
                    page.locator(f'[data-open="{items[1]["id"]}"]').click()
                    expect(page.locator(".read-article h1")).to_have_text(items[1]["title"])
                with page.expect_response(url):
                    if late == "failure":
                        held[0].fulfill(status=503, json={"detail": "synthetic delayed failure"})
                    else:
                        response = held[0].fetch()
                        assert response.ok
                        held[0].fulfill(response=response)
                page.wait_for_timeout(200)
                if late == "left":
                    page.get_by_role("tab", name="saved", exact=True).click()
                    expect(page.locator("#read-q")).to_be_visible()
                title = (
                    page.locator(".read-article h1").text_content()
                    if page.locator(".read-article h1").count()
                    else None
                )
                rows.append(
                    {
                        "scenario_id": "library.source.latest-open-" + late,
                        "profile": str(width),
                        "status": "passed"
                        if title == (None if late == "left" else items[1]["title"]) and not errors
                        else "failed",
                        "expected_title": None if late == "left" else items[1]["title"],
                        "actual_title": title,
                        "page_errors": errors,
                    }
                )
                page.screenshot(path=str(out / f"{width}-{late}.png"), full_page=True)
            finally:
                context.tracing.stop(path=str(out / f"{width}-{late}.zip"))
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    browser.close()
assert all(row["status"] == "passed" for row in rows), rows
