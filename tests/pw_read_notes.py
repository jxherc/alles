"""Owned saved article -> recoverable note -> exact article return workflow."""

import json
import os
import sqlite3
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == os.environ["ALLES_TEST_RUN_ID"]
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
            response = api.post(
                base + "/api/read/save-news",
                data={
                    "url": f"https://example.invalid/reading-note-{width}",
                    "title": f"source [one] {width}",
                    "excerpt": f"original local passage {width}",
                },
            )
            assert response.ok
            item = response.json()["item"]
            item_url = base + "/api/read/" + item["id"]
            item = api.get(item_url).json()
            page = context.new_page()
            page.set_default_timeout(7000)
            errors, console, writes = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )

            def observe_popup(popup):
                popup.on("pageerror", lambda error: errors.append(str(error)))
                popup.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )

            context.on("page", observe_popup)
            note_url = base + "/api/vault-md/file"
            page.on(
                "request",
                lambda request: (
                    writes.append(request.post_data_json)
                    if request.url == note_url and request.method == "POST"
                    else None
                ),
            )
            context.tracing.start(screenshots=True, snapshots=True)

            def record(name):
                rows.append(
                    {
                        "scenario_id": "library.note." + name,
                        "profile": str(width),
                        "status": "passed",
                    }
                )
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

            def open_item():
                page.goto(base + "/?view=read", wait_until="networkidle")
                page.locator(f'[data-open="{item["id"]}"]').click()
                expect(page.locator(".read-article h1")).to_have_text(item["title"])

            def dialog():
                return page.get_by_role("dialog", name="note from " + item["title"], exact=True)

            try:
                page.route(
                    base + "/api/vault-md/create-scope",
                    lambda route: route.fulfill(
                        status=503, json={"detail": "synthetic unavailable note recovery"}
                    ),
                )
                open_item()
                recovery = page.locator("#read-note-recovery .note-recovery-error button")
                expect(recovery).to_be_visible()
                page.unroute(base + "/api/vault-md/create-scope")
                recovery.click()
                expect(page.locator("#read-note")).to_be_focused()
                assert not writes
                record("unavailable-recovery-retries-without-losing-article")
                page.locator("#read-note").focus()
                page.keyboard.press("Enter")
                expect(dialog().get_by_label("note name", exact=True)).to_be_focused()
                dialog().get_by_label("note", exact=True).fill("cancelled note")
                page.keyboard.press("Escape")
                expect(page.locator("#read-note")).to_be_focused()
                assert not writes
                record("keyboard-cancel-no-write")

                page.locator("#read-note").click()
                dialog().get_by_role("button", name="save", exact=True).click()
                expect(dialog().get_by_role("alert")).to_contain_text("write a note")
                assert not writes
                note = f"    exact reading note {width}\n\n**my own observation**  "
                name = f"reading-{width}.md"
                dialog().get_by_label("note name", exact=True).fill(name)
                dialog().get_by_label("note", exact=True).fill(note)
                page.route(
                    note_url,
                    lambda route: (
                        route.fulfill(status=503, json={"detail": "synthetic failed note"})
                        if route.request.method == "POST"
                        else route.continue_()
                    ),
                )
                dialog().get_by_role("button", name="save", exact=True).click()
                expect(dialog().get_by_role("alert")).to_contain_text("synthetic failed note")
                expect(dialog().get_by_label("note", exact=True)).to_have_value(note)
                assert len(writes) == 1
                page.screenshot(path=str(out / f"{width}-retained-note.png"))
                page.unroute(note_url)
                dialog().get_by_role("button", name="save", exact=True).click()
                open_note = page.locator("#read-note-recovery .note-saved-open")
                expect(open_note).to_be_focused()
                assert writes[0] == writes[1]
                saved = api.get(note_url, params={"path": name}).json()["content"]
                assert saved == writes[1]["content"] and saved.startswith(note + "\n\nsource: ")
                assert not api.get(item_url).json()["read"]
                record("failed-save-retains-exact-note-and-retries-once")

                open_note.click()
                preview = page.locator("#wiki-preview")
                expect(preview).to_contain_text("my own observation")
                source = preview.get_by_role("link", name=item["title"], exact=True)
                target = parse_qs(urlparse(source.get_attribute("href")).query)
                assert target["record"] == [item["id"]]
                assert target["record_hash"] == [item["content_hash"]]
                with page.expect_popup() as opened:
                    source.click()
                reader = opened.value
                expect(reader.locator(".read-article h1")).to_have_text(item["title"])
                expect(reader.locator(".read-source-notice")).to_have_count(0)
                assert not api.get(item_url).json()["read"]
                reader.locator("#read-back").click()
                expect(reader.locator("#read-q")).to_be_visible()
                assert "record=" not in reader.url and "record_hash=" not in reader.url
                reader.close()
                record("saved-document-link-opens-exact-article-without-completing")

                open_item()
                page.locator("#read-note").click()
                fenced_note = "```js\nconst unfinished = true;"
                fenced_name = f"fenced-reading-{width}.md"
                dialog().get_by_label("note name", exact=True).fill(fenced_name)
                dialog().get_by_label("note", exact=True).fill(fenced_note)
                dialog().get_by_role("button", name="save", exact=True).click()
                expect(open_note).to_be_focused()
                open_note.click()
                expect(preview).to_contain_text("const unfinished = true;")
                expect(source).to_be_visible()
                with page.expect_popup() as fenced_source:
                    source.click()
                reader = fenced_source.value
                expect(reader.locator(".read-article h1")).to_have_text(item["title"])
                reader.close()
                assert (
                    fenced_note in api.get(note_url, params={"path": fenced_name}).json()["content"]
                )
                record("unfinished-markdown-keeps-source-link-clickable")

                with sqlite3.connect(data / "aide.db") as db:
                    db.execute(
                        "UPDATE read_items SET text=?, read_position=0.5 WHERE id=?",
                        (
                            "\n\n".join(
                                f"changed local passage {width}. " + "synthetic text " * 30
                                for _ in range(45)
                            ),
                            item["id"],
                        ),
                    )
                with page.expect_popup() as changed:
                    source.click()
                reader = changed.value
                expect(reader.locator(".read-source-notice")).to_contain_text(
                    "changed since the note"
                )
                expect(reader.locator(".read-article")).to_contain_text(
                    f"changed local passage {width}"
                )
                reader.wait_for_function("document.getElementById('read-body').scrollTop > 100")
                assert reader.locator(".read-source-notice").evaluate(
                    "notice => { const box = notice.getBoundingClientRect(); return box.top >= 0 && box.bottom <= innerHeight; }"
                ), "changed-source warning stays visible at the restored reading position"
                reader.close()
                assert api.get(note_url, params={"path": name}).json()["content"] == saved
                record("changed-article-is-labelled-and-saved-note-stays-intact")

                open_item()
                page.locator("#read-note").click()
                dialog().get_by_label("note name", exact=True).fill(name)
                uncertain = f"retained uncertain note {width}"
                dialog().get_by_label("note", exact=True).fill(uncertain)
                replies = []

                def lose(route):
                    if route.request.method != "POST":
                        route.continue_()
                        return
                    reply = route.fetch()
                    assert reply.ok, reply.text()
                    replies.append(reply.json())
                    route.fulfill(status=503, json={"detail": "synthetic lost note reply"})

                page.route(note_url, lose)
                dialog().get_by_role("button", name="save", exact=True).click()
                expect(dialog().get_by_role("alert")).to_contain_text("synthetic lost note reply")
                assert len(replies) == 1 and replies[0]["path"] != name
                original_request = writes[-1]
                dialog().get_by_label("note", exact=True).fill("different later draft")
                dialog().get_by_role("button", name="save", exact=True).click()
                expect(dialog().get_by_role("alert")).to_contain_text("finish the pending note")
                assert len(replies) == 1
                dialog().get_by_role("button", name="cancel", exact=True).click()
                expect(page.locator("#read-note-recovery .note-retry")).to_be_visible()
                page.unroute(note_url, lose)
                page.reload(wait_until="networkidle")
                retry = page.locator("#read-note-recovery .note-retry")
                expect(retry).to_be_visible()
                retry.focus()
                page.keyboard.press("Enter")
                expect(open_note).to_be_focused()
                assert writes[-1] == original_request
                assert (
                    api.get(note_url, params={"path": replies[0]["path"]}).json()["content"]
                    == original_request["content"]
                )
                assert api.get(note_url, params={"path": name}).json()["content"] == saved
                assert (
                    len(
                        api.get(base + "/api/vault-md/grep", params={"q": uncertain}).json()[
                            "results"
                        ]
                    )
                    == 1
                )
                record("collision-lost-reply-edit-rejection-reload-exact-recovery")

                open_note.click()
                expect(preview).to_contain_text(uncertain)
                page.screenshot(path=str(out / f"{width}-saved-note.png"))
                assert api.delete(item_url).ok
                with page.expect_popup() as removed:
                    preview.get_by_role("link", name=item["title"], exact=True).click()
                reader = removed.value
                expect(reader.locator("#read-q")).to_be_visible()
                expect(reader.locator(".read-article")).to_have_count(0)
                expect(reader.locator(".toast.error").last).to_contain_text("could not open")
                reader.close()
                assert (
                    api.get(note_url, params={"path": replies[0]["path"]}).json()["content"]
                    == original_request["content"]
                )
                record("deleted-source-keeps-note-and-shows-no-replacement")
                assert not errors, errors
                assert all("503" in message or "404" in message for message in console), console
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                record("saved-result-keyboard-console-and-bounds")
            except Exception as error:
                rows.append(
                    {
                        "scenario_id": "library.note.current",
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
    assert all(row["status"] == "passed" for row in rows), "see scenarios.json"


if __name__ == "__main__":
    run()
