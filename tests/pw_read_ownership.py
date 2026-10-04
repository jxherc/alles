"""Reading navigation and URL receipts stay with their accepted local owner."""

import json
import os
import re
import sqlite3
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            for case in ("scope-change", "back-reopen", "back-reopen-failure"):
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
                endpoint = base + "/api/read"
                page = context.new_page()
                page.set_default_timeout(4000)
                errors, console, held = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                row = {
                    "scenario_id": "library.ownership." + case,
                    "profile": str(width),
                    "status": "failed",
                }
                rows.append(row)
                context.tracing.start(screenshots=True, snapshots=True)

                def wait_held():
                    deadline = time.monotonic() + 5
                    while not held and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert len(held) == 1, "expected one held response"

                try:
                    if case == "scope-change":
                        scope = api.get(endpoint).json()["recovery_scopes"][0]
                        other = "f" * 64
                        assert other != scope
                        accepted = [scope]

                        def listed(route):
                            response = route.fetch()
                            assert response.ok
                            if route.request.method == "POST":
                                held.append((route, response))
                            else:
                                payload = response.json()
                                payload["recovery_scopes"] = list(accepted)
                                if accepted == [other]:
                                    payload["items"] = []
                                route.fulfill(response=response, json=payload)

                        page.route(re.compile(re.escape(endpoint) + r"(?:\?.*)?$"), listed)
                        page.goto(base + "/?view=library", wait_until="networkidle")
                        page.get_by_role("tab", name="saved", exact=True).click()
                        page.locator("#read-url").fill(base + f"/owned-scope-{width}")
                        page.locator("#read-save").click()
                        wait_held()
                        key = "alles.read.pending.v1:" + scope
                        pending = page.evaluate("key=>sessionStorage.getItem(key)", key)
                        assert pending
                        accepted[:] = [other]
                        page.get_by_role("radio", name="unread", exact=True).click()
                        expect(page.locator("#read-body")).to_contain_text("nothing saved yet")
                        held[0][0].fulfill(response=held[0][1])
                        expect(page.locator("#read-body")).to_contain_text(
                            "reading storage changed"
                        )
                        assert page.evaluate("key=>sessionStorage.getItem(key)", key) == pending
                        expect(page.locator(".read-save-result")).to_have_count(0)
                        # Returning to the accepted storage can reconcile the exact receipt.
                        accepted[:] = [scope]
                        page.get_by_role("radio", name="all", exact=True).click()
                        expect(page.locator("#read-save-check")).to_be_enabled()
                        page.locator("#read-save-check").focus()
                        page.keyboard.press("Enter")
                        expect(page.locator(".read-save-result")).to_be_visible()
                        assert page.evaluate("key=>sessionStorage.getItem(key)", key) is None
                        row["old_receipt_retained_until_scope_returned"] = True
                    else:
                        response = api.post(
                            endpoint + "/save-news",
                            data={
                                "url": base + f"/owned-{width}-{case}",
                                "title": f"local reading {width} {case}",
                                "excerpt": "owned fixture",
                            },
                        )
                        assert response.ok
                        item = response.json()["item"]
                        content = "\n\n".join(
                            f"Passage {i}. " + "Synthetic local article. " * 16 for i in range(70)
                        )
                        with sqlite3.connect(data / "aide.db") as db:
                            db.execute(
                                "UPDATE read_items SET text=?, read_position=? WHERE id=?",
                                (content, 0.4, item["id"]),
                            )
                        url = endpoint + "/" + item["id"]
                        page.goto(base + "/?view=library", wait_until="networkidle")
                        page.get_by_role("tab", name="saved", exact=True).click()
                        page.locator(f'[data-open="{item["id"]}"]').click()
                        expect(page.locator(".read-article h1")).to_have_text(item["title"])
                        page.wait_for_function('document.querySelector("#read-body").scrollTop>0')
                        with sqlite3.connect(data / "aide.db") as db:
                            db.execute(
                                "UPDATE read_items SET text=?, read_position=0 WHERE id=?",
                                ("Changed source.\n\n" + content, item["id"]),
                            )
                        page.locator("#read-body").evaluate(
                            "e=>{e.scrollTop=.5*(e.scrollHeight-e.clientHeight)}"
                        )
                        expect(page.locator("#read-position-status")).to_contain_text(
                            "saved text changed"
                        )

                        def reopen(route):
                            if route.request.method == "GET" and not held:
                                response = route.fetch()
                                assert response.ok
                                held.append((route, response))
                            else:
                                route.continue_()

                        page.route(url, reopen)
                        page.locator("#read-position-retry").click()
                        wait_held()
                        page.locator("#read-back").focus()
                        page.keyboard.press("Enter")
                        expect(page.locator(".read-article")).to_have_count(0)
                        if case == "back-reopen-failure":
                            held[0][0].fulfill(
                                status=503, json={"detail": "synthetic delayed error"}
                            )
                        else:
                            held[0][0].fulfill(response=held[0][1])
                        page.wait_for_timeout(200)
                        expect(page.locator(".read-article")).to_have_count(0)
                        expect(page.locator(f'[data-open="{item["id"]}"]')).to_be_focused()
                        expect(page.get_by_text("could not open", exact=True)).to_have_count(0)
                        row["reader_after_back"] = 0
                    assert not errors, errors
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    row["status"] = "passed"
                except Exception as error:
                    row.update(error=str(error), traceback=traceback.format_exc())
                finally:
                    row.update(page_errors=errors, console_errors=console)
                    page.screenshot(path=str(out / f"{width}-{case}.png"))
                    context.tracing.stop(path=str(out / f"{width}-{case}.zip"))
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    assert all(row["status"] == "passed" for row in rows), "see scenarios.json"


if __name__ == "__main__":
    run()
