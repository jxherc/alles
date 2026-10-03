"""Delayed background tree reads must not replace a newer Docs navigation choice."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
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
            deleted = f"local-trash-{width}.md"
            assert api.post(
                base + "/api/vault-md/file",
                data={"path": deleted, "content": "synthetic deleted document"},
            ).ok
            assert api.delete(base + "/api/vault-md/file", params={"path": deleted}).ok
            assert api.post(
                base + "/api/vault-md/file",
                data={"path": f"local-kept-{width}.md", "content": "synthetic kept document"},
            ).ok
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            held = []
            page.route(
                base + "/api/vault-md/tree", lambda route: held.append((route, route.fetch()))
            )
            context.tracing.start(screenshots=True, snapshots=True)
            try:
                page.goto(base + "/?view=wiki", wait_until="domcontentloaded")
                expect(page.locator("#wiki-empty-state")).to_be_visible()
                if width == 390:
                    page.locator("#wiki-tree-toggle").click()
                page.locator("#wiki-trash-btn").click()
                restore = page.get_by_role("button", name=f"restore {deleted}", exact=True)
                expect(restore).to_be_visible()
                assert held, "expected initial or watch tree refresh to be in flight"
                for route, response in held:
                    route.fulfill(response=response)
                page.unroute(base + "/api/vault-md/tree")
                page.wait_for_load_state("networkidle")
                expect(restore).to_be_visible()
                assert not errors, errors
                restore.click()
                expect(page.locator("#wiki-path")).to_have_text(deleted)
                expect(page.locator("#wiki-preview")).to_have_text("synthetic deleted document")
                rows.append(
                    {
                        "scenario_id": "docs.trash-survives-late-tree-and-restores",
                        "profile": str(width),
                        "status": "passed",
                    }
                )
                if width == 390:
                    page.locator("#wiki-tree-toggle").click()
                held_search = []

                def hold_search(route):
                    if "q=synthetic" in route.request.url:
                        held_search.append((route, route.fetch()))
                    else:
                        route.continue_()

                page.route(base + "/api/vault-md/grep?*", hold_search)
                page.locator("#wiki-search").fill("synthetic")
                for _ in range(100):
                    if held_search:
                        break
                    page.wait_for_timeout(20)
                assert held_search
                page.locator("#wiki-search").fill("unmatched local phrase")
                expect(page.locator("#wiki-tree")).to_have_text("no matches")
                for route, response in held_search:
                    route.fulfill(response=response)
                page.unroute(base + "/api/vault-md/grep?*")
                page.wait_for_load_state("networkidle")
                expect(page.locator("#wiki-tree")).to_have_text("no matches")
                page.get_by_role("button", name="all documents", exact=True).click()
                expect(page.locator("#wiki-search")).to_have_value("")
                if width == 390:
                    page.locator("#wiki-tree-toggle").click()
                expect(
                    page.locator(f'#wiki-tree [data-file="local-kept-{width}.md"]')
                ).to_be_visible()
                rows.append(
                    {
                        "scenario_id": "docs.search-keeps-newest-result-and-returns-to-all",
                        "profile": str(width),
                        "status": "passed",
                    }
                )

            except Exception as error:
                rows.append(
                    {
                        "scenario_id": "docs.trash-survives-late-tree-and-restores",
                        "profile": str(width),
                        "status": "failed",
                        "error": str(error),
                    }
                )
            finally:
                page.screenshot(path=str(out / f"{width}-trash.png"), full_page=True)
                context.tracing.stop(path=str(out / f"{width}-trash.zip"))
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    assert all(row["status"] == "passed" for row in rows), rows


if __name__ == "__main__":
    run()
