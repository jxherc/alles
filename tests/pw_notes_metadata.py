"""Keep document metadata out of quick notes, including a real offline queued save."""

import json
import os
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme in [(1440, "dark"), (390, "light")]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="allow",
                reduced_motion="reduce",
                has_touch=width == 390,
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(10000)
            errors, console, external = [], [], []
            row = {"profile": f"{width}-{theme}", "status": "failed"}
            rows.append(row)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )

            def boundary(route):
                if urlsplit(route.request.url).netloc != urlsplit(base).netloc:
                    external.append(route.request.url)
                    route.abort("blockedbyclient")
                else:
                    route.continue_()

            context.route("**/*", boundary)
            context.route_web_socket("**/*", lambda socket: socket.close())
            api = context.request

            def click(target):
                target.tap() if width == 390 else target.click()

            def section(name):
                target = page.locator(f'.docs-sec-btn[data-section="{name}"]')
                if not target.is_visible():
                    click(page.locator("#wiki-tree-toggle"))
                click(target)

            try:
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.patch(base + "/api/settings", data={"theme": theme, "language": "en"}).ok
                name = f"saved-metadata-{width}.md"
                assert api.post(
                    base + "/api/vault-md/file",
                    data={"path": name, "content": "one two three four five six seven"},
                ).ok
                note_response = api.post(
                    base + "/api/notes",
                    data={"title": f"metadata note {width}", "content": "original note"},
                )
                assert note_response.ok
                note = note_response.json()
                page.goto(base + "/?view=wiki", wait_until="networkidle")
                page.wait_for_function("navigator.serviceWorker.controller !== null")
                target = page.locator(f'#wiki-tree [data-file="{name}"]')
                if not target.is_visible():
                    click(page.locator("#wiki-tree-toggle"))
                click(target)
                expect(page.locator("#wiki-stats")).to_have_text("7 words · 1 min")
                expect(page.locator("#wiki-save-state")).to_have_text("saved")
                if width > 1050:
                    expect(page.locator("#wiki-stats")).to_be_visible()
                expect(page.locator("#wiki-save-state")).to_be_visible()
                section("notes")
                click(page.locator(f'.note-card[data-id="{note["id"]}"] .note-title'))
                expect(page.locator("#wiki-stats")).to_be_hidden()
                expect(page.locator("#wiki-save-state")).to_be_hidden()
                draft = "offline quick note 草稿 exact"
                page.locator("#note-edit-body").fill(draft)
                context.set_offline(True)
                click(page.locator("#note-save-btn"))
                expect(page.locator(".toast.error").last).to_contain_text("save was not confirmed")
                expect(page.locator("#sync-indicator")).to_contain_text("1 pending")
                expect(page.locator("#note-edit-body")).to_have_value(draft)
                expect(page.locator("#wiki-stats")).to_be_hidden()
                expect(page.locator("#wiki-save-state")).to_be_hidden()
                page.screenshot(path=str(output / f"{width}-offline-note.png"))
                context.set_offline(False)
                page.wait_for_function(
                    """async ({id, content}) => {
                  const response = await fetch('/api/notes');
                  return response.ok && (await response.json()).some(note => note.id === id && note.content === content);
                }""",
                    arg={"id": note["id"], "content": draft},
                    timeout=20000,
                )
                expect(page.locator("#note-edit-body")).to_have_value(draft)
                expect(page.locator("#wiki-save-state")).to_be_hidden()
                page.screenshot(path=str(output / f"{width}-replayed-note.png"))
                section("docs")
                if not target.is_visible():
                    click(page.locator("#wiki-tree-toggle"))
                click(target)
                if width > 1050:
                    expect(page.locator("#wiki-stats")).to_be_visible()
                expect(page.locator("#wiki-stats")).to_have_text("7 words · 1 min")
                expect(page.locator("#wiki-save-state")).to_be_visible()
                expect(page.locator("#wiki-save-state")).to_have_text("saved")
                expect(page.locator("#wiki-current")).to_have_text(name.removesuffix(".md"))
                page.screenshot(path=str(output / f"{width}-document-return.png"))
                assert not errors and not external, (errors, external)
                unexpected = [
                    message for message in console if "ERR_INTERNET_DISCONNECTED" not in message
                ]
                assert not unexpected, unexpected
                row.update(
                    status="passed",
                    checks=[
                        "saved document shows its own count/status",
                        "quick notes hides document metadata",
                        "offline note save remains unconfirmed with one queued write",
                        "reconnection replays exact draft",
                        "returning to document restores its correct count/status",
                    ],
                )
            except Exception:
                row["error"] = traceback.format_exc()
                page.screenshot(path=str(output / f"{width}-failure.png"))
            finally:
                context.set_offline(False)
                row.update(errors=errors, console=console, external=external)
                (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.tracing.stop(path=str(output / f"notes-metadata-{width}-trace.zip"))
                context.close()
        browser.close()
    print(json.dumps(rows, indent=2))
    assert all(row["status"] == "passed" for row in rows)


if __name__ == "__main__":
    run()
