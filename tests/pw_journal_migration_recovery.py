"""Exercise the locked Journal copy dialog against an owned, temporary Alles server."""

import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run() -> None:
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    port = os.environ["PORT"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text("utf-8").strip() == run_id
    base = f"http://docs.localhost:{port}"
    require_server_ownership(f"http://127.0.0.1:{port}/", run_id)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, day in ((1440, "2026-07-01"), (390, "2026-07-02")):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                is_mobile=width == 390,
                has_touch=width == 390,
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(15_000)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.goto(base, wait_until="domcontentloaded")
            if page.locator("#setup-wizard").is_visible():
                page.locator("#setup-skip").click()
                page.locator("#setup-wizard").wait_for(state="hidden")
            page.locator('#docs-tabs [data-group-section="journal"]').click()
            expect(page.locator("#journal-migrate")).to_be_visible()
            trigger = page.locator("#journal-migrate")
            if width == 1440:
                trigger.click()
                expect(page.locator(".jrnl-migration-layer")).to_contain_text(
                    "No Journal entries to copy yet."
                )
                expect(page.locator(".jrnl-migration-layer [data-prepare]")).to_have_count(0)
                page.keyboard.press("Escape")

            original = f"private synthetic entry {width}"
            saved = context.request.put(
                f"{base}/api/journal/{day}",
                data={"content": original, "mood": "calm", "tags": "test"},
            )
            assert saved.ok, saved.text()

            trigger.click()
            dialog = page.locator(".jrnl-migration-layer")
            expect(dialog).to_be_visible()
            expect(dialog.locator(".jrnl-migration-warning")).to_contain_text("plaintext Markdown")
            assert page.evaluate(
                "[...document.body.children].filter(x => !x.classList.contains('jrnl-migration-layer')).every(x => x.inert)"
            )
            for control in (dialog.locator("input"), dialog.locator("[data-prepare]")):
                box = control.bounding_box()
                assert box and box["height"] >= 44, box
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            dialog.locator(".jrnl-migration-head [data-close]").focus()
            page.keyboard.press("Shift+Tab")
            assert dialog.locator("[data-prepare]").evaluate(
                "element => element === document.activeElement"
            )
            page.keyboard.press("Tab")
            assert dialog.locator(".jrnl-migration-head [data-close]").evaluate(
                "element => element === document.activeElement"
            )
            page.evaluate("document.documentElement.style.zoom = '2'")
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.evaluate("document.documentElement.style.zoom = ''")

            # Escape restores focus and does not leave the Docs shell inert.
            page.keyboard.press("Escape")
            expect(dialog).to_have_count(0)
            assert trigger.evaluate("element => element === document.activeElement")
            trigger.click()
            confirmation = dialog.locator("code").inner_text()
            dialog.locator("input").fill(confirmation)
            dialog.locator("[data-prepare]").click()
            expect(dialog.locator(".jrnl-migration-status")).to_contain_text("prepared privately")
            assert dialog.locator("[data-apply]").is_visible()
            page.keyboard.press("Escape")
            page.reload(wait_until="domcontentloaded")
            page.locator('#docs-tabs [data-group-section="journal"]').click()
            page.locator("#journal-migrate").click()
            expect(dialog.locator("[data-apply]")).to_be_visible()
            expect(dialog.locator("[data-new-copy]")).to_be_hidden()
            dialog.locator("[data-apply]").click()
            expect(dialog.locator(".jrnl-migration-status")).to_contain_text("copied")
            copied = context.request.get(f"{base}/api/vault-md/file?path=Journal%2F{day}.md")
            assert copied.ok and original in copied.json()["content"]

            page.keyboard.press("Escape")
            page.reload(wait_until="domcontentloaded")
            page.locator('#docs-tabs [data-group-section="journal"]').click()
            page.locator("#journal-migrate").click()
            expect(dialog.locator("[data-rollback]")).to_be_visible()
            expect(dialog.locator("[data-new-copy]")).to_be_visible()
            dialog.locator("[data-rollback]").click()
            expect(dialog.locator(".jrnl-migration-status")).to_contain_text("rolled back")
            missing = context.request.get(f"{base}/api/vault-md/file?path=Journal%2F{day}.md")
            assert missing.ok and not missing.json()["exists"]
            source = context.request.get(f"{base}/api/journal/{day}")
            assert source.ok and source.json()["content"] == original

            if width == 1440:
                # The server can commit preparation even if this browser never sees the response.
                plan = context.request.get(f"{base}/api/journal-migration/plan")
                assert plan.ok, plan.text()
                unseen = context.request.post(
                    f"{base}/api/journal-migration/prepare",
                    data={"confirmation": plan.json()["confirmation"]},
                )
                assert unseen.ok, unseen.text()
                page.reload(wait_until="domcontentloaded")
                page.locator('#docs-tabs [data-group-section="journal"]').click()
                page.locator("#journal-migrate").click()
                expect(dialog.locator("[data-apply]")).to_be_visible()
                dialog.locator("[data-apply]").click()
                expect(dialog.locator(".jrnl-migration-status")).to_contain_text("copied")
                changed = context.request.put(
                    f"{base}/api/journal/{day}",
                    data={"content": original + " updated", "mood": "calm", "tags": "test"},
                )
                assert changed.ok, changed.text()
                page.keyboard.press("Escape")
                page.reload(wait_until="domcontentloaded")
                page.locator('#docs-tabs [data-group-section="journal"]').click()
                page.locator("#journal-migrate").click()
                expect(dialog.locator(".jrnl-migration-error")).to_contain_text("would conflict")
                expect(dialog.locator("[data-prepare]")).to_be_disabled()
                dialog.locator("[data-rollback]").click()
                expect(dialog.locator(".jrnl-migration-status")).to_contain_text("rolled back")
                expect(dialog.locator("[data-prepare]")).to_be_enabled()
            assert not errors, errors
            context.close()
        browser.close()
    print("journal copy recovery passed at desktop and phone widths")


if __name__ == "__main__":
    run()
