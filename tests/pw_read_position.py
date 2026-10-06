"""Saved reading positions and retry using only an owned local article fixture."""

import json
import os
import sqlite3
import traceback
from pathlib import Path
from urllib.parse import urlsplit

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
            context = browser.new_context(
                viewport={"width": width, "height": 844 if width == 390 else 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if (urlsplit(route.request.url).scheme, urlsplit(route.request.url).netloc)
                    == (urlsplit(base).scheme, urlsplit(base).netloc)
                    else route.abort()
                ),
            )
            context.route_web_socket("**/*", lambda socket: socket.close())
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            item = api.post(
                base + "/api/read/save-news",
                data={
                    "url": f"https://example.invalid/position-{width}",
                    "title": f"local reading place {width}",
                    "excerpt": "local fixture",
                },
            ).json()["item"]
            content = "\n\n".join(
                f"Passage {i}. "
                + "A synthetic local paragraph keeps reading place verifiable. " * 5
                for i in range(70)
            )
            with sqlite3.connect(data / "aide.db") as db:
                db.execute(
                    "UPDATE read_items SET text=?, read_position=? WHERE id=?",
                    (content, 0.4, item["id"]),
                )
            url = base + "/api/read/" + item["id"]
            page = context.new_page()
            page.set_default_timeout(7000)
            errors, console, writes = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            page.on(
                "request",
                lambda request: (
                    writes.append(request.post_data_json)
                    if request.url == url and request.method == "PATCH"
                    else None
                ),
            )
            context.tracing.start(screenshots=True, snapshots=True)

            def record(name):
                rows.append(
                    {
                        "scenario_id": "library.position." + name,
                        "profile": str(width),
                        "status": "passed",
                    }
                )
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

            def scroll_to(position):
                page.locator("#read-body").evaluate(
                    "(body, position) => body.scrollTop = position * (body.scrollHeight - body.clientHeight)",
                    position,
                )

            def at_position(position):
                page.wait_for_function(
                    "position => { const body = document.getElementById('read-body'); return Math.abs(body.scrollTop / (body.scrollHeight - body.clientHeight) - position) < 0.015; }",
                    arg=position,
                )

            def open_item():
                page.goto(base + "/?view=library", wait_until="networkidle")
                page.get_by_role("tab", name="saved", exact=True).click()
                page.locator(f'[data-open="{item["id"]}"]').click()
                expect(page.locator(".read-article")).to_contain_text(item["title"])

            try:
                open_item()
                at_position(0.4)
                assert not writes and not api.get(url).json()["read"]
                record("open-restores-place-without-completing")
                body = page.locator("#read-body")
                body.focus()
                with page.expect_response(
                    lambda response: response.url == url and response.request.method == "PATCH"
                ) as position_response:
                    page.keyboard.press("PageDown")
                assert position_response.value.ok
                status = page.locator("#read-position-status")
                expect(status).to_have_text("reading place saved")
                saved = api.get(url).json()["position"]
                assert saved > 0.4 and not api.get(url).json()["read"]
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="saved", exact=True).click()
                page.locator(f'[data-open="{item["id"]}"]').click()
                at_position(saved)
                record("keyboard-scroll-persists-across-reload")
                page.route(
                    url,
                    lambda route: (
                        route.fulfill(status=503, json={"detail": "synthetic place failure"})
                        if route.request.method == "PATCH"
                        else route.continue_()
                    ),
                )
                before_height = body.evaluate("element => element.clientHeight")
                scroll_to(0.6)
                expect(status).to_contain_text("could not confirm")
                assert body.evaluate("element => element.clientHeight") == before_height, (
                    "reading status changed the article viewport height"
                )
                assert api.get(url).json()["position"] == saved
                at_position(0.6)
                page.unroute(url)
                page.locator("#read-position-retry").focus()
                page.keyboard.press("Enter")
                expect(status).to_have_text("reading place saved")
                assert abs(api.get(url).json()["position"] - 0.6) < 0.015
                assert body.evaluate("element => element.clientHeight") == before_height
                record("failed-write-retains-place-and-keyboard-retry")
                held = []

                def hold(route):
                    if route.request.method == "PATCH":
                        held.append((route, route.fetch()))
                    else:
                        route.continue_()

                page.route(url, hold)
                scroll_to(0.65)
                expect(status).to_have_text("saving reading place…")
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(20)
                assert len(held) == 1
                scroll_to(0.75)
                page.wait_for_timeout(700)
                assert len(held) == 1, "position writes must be serialized"
                route, response = held[0]
                route.fulfill(response=response)
                page.unroute(url, hold)
                expect(status).to_have_text("reading place saved")
                assert abs(api.get(url).json()["position"] - 0.75) < 0.015
                record("newer-scroll-follows-delayed-write")

                def lose(route):
                    if route.request.method == "PATCH":
                        assert route.fetch().ok
                        route.fulfill(status=503, json={"detail": "synthetic lost reply"})
                    else:
                        route.continue_()

                page.route(url, lose)
                scroll_to(0.8)
                expect(status).to_contain_text("could not confirm")
                assert abs(api.get(url).json()["position"] - 0.8) < 0.015
                page.unroute(url, lose)
                page.locator("#read-position-retry").click()
                expect(status).to_have_text("reading place saved")
                assert writes[-1] == writes[-2]
                record("lost-reply-retries-the-same-place")
                page.route(url, lose)
                scroll_to(0.7)
                expect(status).to_contain_text("could not confirm")
                assert abs(api.get(url).json()["position"] - 0.7) < 0.015
                page.unroute(url, lose)
                scroll_to(0.8)
                page.locator("#read-position-retry").click()
                expect(status).to_have_text("reading place saved")
                assert abs(api.get(url).json()["position"] - 0.8) < 0.015
                record("return-to-confirmed-place-reconciles-uncertain-write")
                page.set_viewport_size({"width": 820, "height": 900})
                at_position(0.8)
                page.screenshot(path=str(out / f"{width}-resumed.png"))
                assert not api.get(url).json()["read"]
                assert not errors, errors
                assert all("503" in message for message in console), console
                record("responsive-reflow-preserves-place-and-unread")
                scroll_to(0.35)
                assert page.locator("#read-back").evaluate(
                    "button => { const box = button.getBoundingClientRect(); return box.top >= 0 && box.bottom <= innerHeight; }"
                ), "back stays available without scrolling away from the reading place"
                page.locator("#read-back").click()
                expect(page.locator(f'[data-open="{item["id"]}"]')).to_be_focused()
                assert abs(api.get(url).json()["position"] - 0.35) < 0.015
                page.locator(f'[data-open="{item["id"]}"]').click()
                at_position(0.35)
                record("back-saves-latest-place-before-returning")
                profile_viewport = {"width": width, "height": 844 if width == 390 else 900}
                page.set_viewport_size(profile_viewport)
                at_position(0.35)
                assert (
                    page.evaluate("({width: innerWidth, height: innerHeight})") == profile_viewport
                )
                original_hash = api.get(url).json()["content_hash"]
                changed_place = api.patch(
                    url, data={"position": 0.25, "content_hash": original_hash}
                )
                assert changed_place.ok
                fresh_place = changed_place.json()
                assert fresh_place["content_hash"] == original_hash
                scroll_to(0.5)
                expect(status).to_contain_text("reading place changed")
                expect(page.locator("#read-position-retry")).to_have_text("reopen article")
                writes_before_reopen = len(writes)
                page.locator("#read-position-retry").focus()
                page.keyboard.press("Enter")
                at_position(0.25)
                expect(status).to_have_text("reading place saved")
                expect(page.locator("#read-position-retry")).to_be_hidden()
                expect(page.locator("#read-back")).to_be_focused()
                assert len(writes) == writes_before_reopen
                with page.expect_response(
                    lambda response: response.url == url and response.request.method == "PATCH"
                ) as resumed_response:
                    scroll_to(0.65)
                assert resumed_response.value.ok
                expect(status).to_have_text("reading place saved")
                assert writes[-1]["position_base"] == fresh_place["position_revision"]
                assert writes[-1]["content_hash"] == original_hash
                resumed = api.get(url).json()
                assert abs(resumed["position"] - 0.65) < 0.015
                assert not resumed["read"]
                assert (
                    page.evaluate("({width: innerWidth, height: innerHeight})") == profile_viewport
                )
                page.screenshot(path=str(out / f"{width}-same-text-reopen-saved.png"))
                record("same-text-position-conflict-reopens-and-resumes-saving")
                with sqlite3.connect(data / "aide.db") as db:
                    db.execute(
                        "UPDATE read_items SET text=?, read_position=0 WHERE id=?",
                        ("Changed local source.\n\n" + content, item["id"]),
                    )
                scroll_to(0.5)
                expect(status).to_contain_text("saved text changed")
                assert api.get(url).json()["position"] == 0
                expect(page.locator("#read-position-retry")).to_have_text("reopen article")
                page.locator("#read-position-retry").click()
                expect(page.locator(".read-article")).to_contain_text("Changed local source.")
                at_position(0)
                assert not api.get(url).json()["read"]
                assert not errors, errors
                assert all("503" in message or "409" in message for message in console), console
                record("changed-text-rejects-old-place-and-reopens")
                current_hash = api.get(url).json()["content_hash"]
                for source_hash, changed in ((original_hash, True), (current_hash, False)):
                    href = page.evaluate(
                        """async ({id, hash}) => {
                            const {sourcesHtml} = await import('/static/js/runs.js');
                            const holder = document.createElement('div');
                            holder.innerHTML = sourcesHtml({
                                sources: [{kind: 'read', ref: id, hash}],
                                outcomes: {}, history_complete: true
                            });
                            return holder.querySelector('a').href;
                        }""",
                        {"id": item["id"], "hash": source_hash},
                    )
                    assert "record_hash=" + source_hash in href
                    page.goto(href, wait_until="networkidle")
                    expect(page.locator(".read-article")).to_contain_text("Changed local source.")
                    expect(page.locator(".read-source-notice")).to_have_count(1 if changed else 0)
                    if changed:
                        expect(page.locator(".read-source-notice")).to_be_visible()
                        expect(page.locator(".read-source-notice")).to_contain_text(
                            "this article changed"
                        )
                    assert not api.get(url).json()["read"]
                page.goto(
                    base + "/?app=read&record_view=read&record=" + item["id"],
                    wait_until="networkidle",
                )
                expect(page.locator(".read-article")).to_contain_text("Changed local source.")
                expect(page.locator(".read-source-notice")).to_have_count(0)
                assert not errors, errors
                assert all("503" in message or "409" in message for message in console), console
                record("history-hash-notice-matching-and-live-links")
            except Exception as error:
                rows.append(
                    {
                        "scenario_id": "library.position.current",
                        "profile": str(width),
                        "status": "failed",
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    }
                )
                page.screenshot(path=str(out / f"{width}-failed.png"))
            finally:
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.tracing.stop(path=str(out / f"{width}-trace.zip"))
                context.close()
        browser.close()
    if any(row["status"] != "passed" for row in rows):
        raise AssertionError("reading place regression failed; see scenarios.json")


if __name__ == "__main__":
    run()
