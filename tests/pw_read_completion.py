"""Explicit reading completion and uncertain-response recovery using local fixtures."""

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
        for width in (1440, 820, 390):
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
            result = api.post(
                base + "/api/read/save-news",
                data={
                    "url": f"https://example.invalid/local-completion-{width}",
                    "title": f"local reading {width}",
                    "excerpt": "An owned synthetic source to inspect and finish.",
                },
            )
            assert result.ok, result.text()
            item = result.json()["item"]
            url = base + "/api/read/" + item["id"]
            page = context.new_page()
            errors, console, writes = [], [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            page.on(
                "request",
                lambda r: (
                    writes.append(r.post_data_json)
                    if r.url == url and r.method == "PATCH"
                    else None
                ),
            )
            page.set_default_timeout(6000)
            context.tracing.start(screenshots=True, snapshots=True)

            def record(name):
                rows.append(
                    {
                        "scenario_id": "library.read." + name,
                        "profile": str(width),
                        "status": "passed",
                    }
                )

            try:
                page.goto(base + "/?view=library", wait_until="networkidle")
                page.get_by_role("tab", name="saved", exact=True).click()
                entry = page.locator(f'[data-open="{item["id"]}"]')
                entry.focus()
                page.keyboard.press("Enter")
                expect(page.locator("#read-back")).to_be_focused()
                expect(page.locator(".read-article")).to_contain_text(item["title"])
                assert not api.get(url).json()["read"]
                assert not writes
                record("opening-keeps-unread")
                complete = page.locator("#read-complete")
                status = page.locator("#read-completion-status")
                page.route(
                    url,
                    lambda r: (
                        r.fulfill(status=503, json={"detail": "synthetic storage failure"})
                        if r.request.method == "PATCH"
                        else r.continue_()
                    ),
                )
                complete.focus()
                page.keyboard.press("Enter")
                expect(status).to_contain_text("could not confirm")
                expect(complete).to_have_text("mark read")
                assert not api.get(url).json()["read"]
                record("failed-completion-keeps-state")
                page.unroute(url)
                replies = []

                def lose_reply(route):
                    if route.request.method != "PATCH":
                        route.continue_()
                        return
                    reply = route.fetch()
                    assert reply.ok, reply.text()
                    replies.append(reply.json())
                    route.fulfill(status=503, json={"detail": "synthetic lost acknowledgment"})

                page.route(url, lose_reply)
                complete.click()
                expect(status).to_contain_text("could not confirm")
                assert replies and api.get(url).json()["read"]
                expect(complete).to_have_text("mark read")
                page.unroute(url)
                complete.focus()
                page.keyboard.press("Enter")
                expect(status).to_have_text("marked read")
                expect(complete).to_have_text("mark unread")
                page.screenshot(path=str(out / f"{width}-confirmed-read.png"), full_page=True)
                assert api.get(url).json()["read_at"] == replies[0]["read_at"]
                assert writes == [{"read": True}] * 3
                record("lost-reply-retries-same-desired-state")
                complete.click()
                expect(status).to_have_text("marked unread")
                assert not api.get(url).json()["read"]
                page.locator("#read-back").click()
                expect(entry).to_be_focused()
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="saved", exact=True).click()
                entry.click()
                expect(complete).to_have_text("mark read")
                assert not api.get(url).json()["read"]
                record("undo-reload-reopen-keeps-unread")
                page.locator("#read-back").click()
                card = page.locator(f'.read-card[data-id="{item["id"]}"]')

                def fail_change(route):
                    method = route.request.method
                    if method not in ("PATCH", "POST", "DELETE"):
                        route.continue_()
                        return
                    key = (
                        next(iter(route.request.post_data_json or {}), "")
                        if method == "PATCH"
                        else ""
                    )
                    action = {"archived": "archive", "fav": "fav", "read": "read"}.get(
                        key, "del" if method == "DELETE" else "read"
                    )
                    route.fulfill(status=503, json={"detail": f"synthetic failed {action}"})

                page.route(url + "**", fail_change)
                for action in ("archive", "fav", "read", "del"):
                    card.locator(f'[data-act="{action}"]').click()
                    if action == "del":
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                    expect(page.locator(".toast.error").last).to_have_text(
                        f"synthetic failed {action}"
                    )
                    expect(page.locator(".toast.success")).to_have_count(0)
                    expect(card).to_be_visible()
                    persisted = api.get(url).json()
                    assert (
                        not persisted["read"] and not persisted["archived"] and not persisted["fav"]
                    )
                page.unroute(url + "**")
                record("failed-card-writes-retain-item-without-false-success")
                entry.click()

                assert complete.bounding_box()["height"] >= 44
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                assert not errors, errors
                assert all("503" in message for message in console), console
                page.screenshot(path=str(out / f"{width}-reader.png"), full_page=True)
                record("keyboard-reduced-motion-bounds-console")
                page.locator("#read-back").click()
                card.locator('[data-act="fav"]').click()
                expect(card.locator('[data-act="fav"]')).to_have_attribute("title", "unstar")
                assert api.get(url).json()["fav"]
                card.locator('[data-act="read"]').click()
                expect(card.locator('[data-act="read"]')).to_have_attribute("title", "mark unread")
                assert api.get(url).json()["read"]
                record("card-star-and-explicit-read-confirm-persisted-state")
                page.route(url, lose_reply)
                card.locator('[data-act="archive"]').click()
                expect(page.locator(".toast.error").last).to_have_text(
                    "synthetic lost acknowledgment"
                )
                expect(card).to_be_visible()
                assert api.get(url).json()["archived"]
                page.unroute(url)
                card.locator('[data-act="archive"]').click()
                expect(card).to_have_count(0)
                page.get_by_role("radio", name="archive", exact=True).click()
                expect(card).to_be_visible()
                card.locator('[data-act="archive"]').click()
                expect(card).to_have_count(0)
                assert not api.get(url).json()["archived"]
                page.get_by_role("radio", name="all", exact=True).click()
                expect(card).to_be_visible()
                record("lost-archive-reply-retry-and-unarchive")

                def lose_delete(route):
                    if route.request.method != "DELETE":
                        route.continue_()
                        return
                    response = route.fetch()
                    assert response.ok, response.text()
                    route.fulfill(
                        status=503, json={"detail": "synthetic lost delete acknowledgment"}
                    )

                page.route(url, lose_delete)
                card.locator('[data-act="del"]').click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(page.locator(".toast.error").last).to_have_text(
                    "synthetic lost delete acknowledgment"
                )
                expect(card).to_be_visible()
                assert api.get(url).status == 404
                page.unroute(url)
                card.locator('[data-act="del"]').click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(card).to_have_count(0)
                expect(page.locator("#read-q")).to_be_focused()
                assert not errors, errors
                assert all("503" in message or "404" in message for message in console), console
                record("lost-delete-reply-reconciles-already-absent-item")

            except Exception as error:
                rows.append(
                    {
                        "scenario_id": "library.read.current",
                        "profile": str(width),
                        "status": "failed",
                        "error": str(error),
                    }
                )
                page.screenshot(path=str(out / f"{width}-failed.png"), full_page=True)
                raise
            finally:
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.tracing.stop(path=str(out / f"{width}-reader.zip"))
                context.close()
        browser.close()


if __name__ == "__main__":
    run()
