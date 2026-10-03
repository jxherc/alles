"""Reading navigation during local delayed, failed, and terminal writes."""

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            for case in (
                "scroll-to-top",
                "deleted-back",
                "completion-success",
                "completion-failure",
            ):
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
                response = api.post(
                    base + "/api/read/save-news",
                    data={
                        "url": f"https://example.invalid/recovery-{width}-{case}",
                        "title": f"local {case} {width}",
                        "excerpt": "synthetic saved reading",
                    },
                )
                assert response.ok, response.text()
                item = response.json()["item"]
                if case in ("scroll-to-top", "deleted-back"):
                    content = "\n\n".join(
                        f"Passage {i}. " + "Synthetic local reading text. " * 12 for i in range(60)
                    )
                    with sqlite3.connect(data / "aide.db") as db:
                        db.execute(
                            "UPDATE read_items SET text=?, read_position=0.4 WHERE id=?",
                            (content, item["id"]),
                        )
                url = base + "/api/read/" + item["id"]
                page = context.new_page()
                page.set_default_timeout(3500)
                errors, console = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                context.tracing.start(screenshots=True, snapshots=True)
                row = {"scenario_id": "library.recovery." + case, "profile": str(width)}
                try:
                    page.goto(base + "/?view=library", wait_until="networkidle")
                    page.get_by_role("tab", name="saved", exact=True).click()
                    page.locator(f'[data-open="{item["id"]}"]').click()
                    expect(page.locator(".read-article h1")).to_have_text(item["title"])
                    body = page.locator("#read-body")
                    status = page.locator("#read-position-status")
                    back = page.locator("#read-back")
                    if case == "scroll-to-top":
                        page.wait_for_function(
                            "document.getElementById('read-body').scrollTop > 100"
                        )
                        body.focus()
                        with page.expect_response(
                            lambda response: (
                                response.url == url and response.request.method == "PATCH"
                            )
                        ):
                            page.keyboard.press("PageDown")
                        expect(status).to_have_text("reading place saved")
                        assert api.get(url).json()["position"] > 0.4
                        with page.expect_response(
                            lambda response: (
                                response.url == url and response.request.method == "PATCH"
                            )
                        ):
                            page.keyboard.press("Home")
                        expect(status).to_have_text("reading place saved")
                        assert api.get(url).json()["position"] == 0
                        page.reload(wait_until="networkidle")
                        page.get_by_role("tab", name="saved", exact=True).click()
                        page.locator(f'[data-open="{item["id"]}"]').click()
                        expect(page.locator(".read-article h1")).to_have_text(item["title"])
                        assert body.evaluate("body => body.scrollTop") == 0
                    elif case == "deleted-back":
                        page.wait_for_function(
                            "document.getElementById('read-body').scrollTop > 100"
                        )
                        assert api.delete(url).ok
                        body.evaluate(
                            "body => body.scrollTop = 0.6 * (body.scrollHeight - body.clientHeight)"
                        )
                        expect(status).to_contain_text("saved text changed or was removed")
                        back.click()
                        expect(page.locator("#read-q")).to_be_visible()
                        expect(page.locator(f'[data-open="{item["id"]}"]')).to_have_count(0)
                        assert api.get(url).status == 404
                    else:
                        held = []

                        def hold(route):
                            if route.request.method == "PATCH":
                                held.append(route)
                            else:
                                route.continue_()

                        page.route(url, hold)
                        complete = page.locator("#read-complete")
                        complete.click()
                        expect(page.locator("#read-completion-status")).to_have_text(
                            "saving reading status…"
                        )
                        for _ in range(50):
                            if held:
                                break
                            page.wait_for_timeout(20)
                        assert len(held) == 1
                        blocked = back.is_disabled()
                        if not blocked:
                            back.click()
                            expect(page.locator("#read-q")).to_be_visible()
                        with page.expect_response(url):
                            if case == "completion-success":
                                reply = held[0].fetch()
                                assert reply.ok
                                held[0].fulfill(response=reply)
                            else:
                                held[0].fulfill(
                                    status=503, json={"detail": "synthetic failed completion"}
                                )
                        if case == "completion-failure":
                            expect(page.locator("#read-completion-status")).to_contain_text(
                                "could not confirm"
                            )
                            assert not api.get(url).json()["read"]
                            page.unroute(url, hold)
                            complete.click()
                            expect(page.locator("#read-completion-status")).to_have_text(
                                "marked read"
                            )
                        elif blocked:
                            expect(page.locator("#read-completion-status")).to_have_text(
                                "marked read"
                            )
                        if blocked:
                            back.click()
                        card = page.locator(f'.read-card[data-id="{item["id"]}"]')
                        expect(card.locator('[data-act="read"]')).to_have_attribute(
                            "title", "mark unread"
                        )
                        assert api.get(url).json()["read"]
                    assert not errors, errors
                    assert all("503" in message or "404" in message for message in console), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    row["status"] = "passed"
                except Exception as error:
                    row.update(status="failed", error=str(error))
                finally:
                    rows.append(row)
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                    page.screenshot(path=str(out / f"{width}-{case}.png"))
                    context.tracing.stop(path=str(out / f"{width}-{case}.zip"))
                    context.close()
        browser.close()
    assert all(row["status"] == "passed" for row in rows), rows


if __name__ == "__main__":
    run()
