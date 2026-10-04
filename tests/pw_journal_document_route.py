"""Journal reload and browser history must not reopen a previous Docs fragment."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (1440, 390):
                for theme in ("light", "dark"):
                    label = f"{width}-{theme}"
                    context = browser.new_context(
                        viewport={"width": width, "height": 900},
                        service_workers="block",
                        reduced_motion="reduce",
                        has_touch=width <= 390,
                    )
                    external, errors, console = [], [], []

                    def route(request):
                        if urlparse(request.request.url).netloc != urlparse(base).netloc:
                            external.append(request.request.url)
                            return request.abort()
                        return request.continue_()

                    context.route("**/*", route)
                    context.route_web_socket("**/*", lambda socket: socket.close())
                    page = context.new_page()
                    page.set_default_timeout(5000)
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console", lambda m: console.append(m.text) if m.type == "error" else None
                    )
                    row = {
                        "scenario_id": "journal.document-route",
                        "profile": label,
                        "status": "failed",
                    }
                    rows.append(row)
                    try:
                        api = context.request
                        assert api.post(base + "/api/setup/dismiss").ok
                        assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                        name = f"synthetic agenda {label}.md"
                        original = "the original synthetic document"
                        assert api.post(
                            base + "/api/vault-md/file", data={"path": name, "content": original}
                        ).ok
                        day = "2026-10-04"
                        entry = f"saved journal entry {label}"
                        page.goto(
                            base + "/?view=wiki&d=" + day + "&doc=" + quote(name),
                            wait_until="networkidle",
                        )
                        expect(page.locator("#wiki-preview")).to_have_text(original)
                        journal = page.locator(
                            '#docs-workbench-view [data-group-section="journal"]'
                        )
                        journal.press("Enter")
                        editor = page.locator("#jrnl-text")
                        expect(editor).to_be_visible()
                        editor.fill(entry)
                        page.locator("#jrnl-save").click()
                        expect(page.locator("#jrnl-saved")).to_contain_text("saved ")
                        assert api.get(base + "/api/journal/" + day).json()["content"] == entry
                        before_reload = page.url
                        page.screenshot(path=str(output / f"{label}-before-reload.png"))
                        page.reload(wait_until="networkidle")
                        expect(journal).to_have_attribute("aria-selected", "true")
                        expect(editor).to_be_visible()
                        expect(editor).to_have_value(entry)
                        expect(page.locator("#docs-reader-main")).to_be_hidden()
                        assert page.url == before_reload
                        assert parse_qs(urlparse(page.url).query)["d"] == [day]
                        page.screenshot(path=str(output / f"{label}-reloaded.png"))
                        page.go_back(wait_until="networkidle")
                        expect(page.locator("#wiki-preview")).to_be_visible()
                        expect(page.locator("#wiki-preview")).to_have_text(original)
                        expect(page.locator("#wiki-path")).to_have_text(name)
                        page.go_forward(wait_until="networkidle")
                        expect(editor).to_be_visible()
                        expect(editor).to_have_value(entry)
                        # Old links may carry either legacy document selector alongside Journal.
                        for selector in ("#" + quote(name[:-3]), "&doc=" + quote(name)):
                            page.goto(
                                base + "/?view=journal&d=" + day + selector,
                                wait_until="networkidle",
                            )
                            expect(editor).to_be_visible()
                            expect(editor).to_have_value(entry)
                            expect(page.locator("#docs-reader-main")).to_be_hidden()
                        assert not external, external
                        assert not errors, errors
                        assert not console, console
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        row.update(
                            status="passed",
                            checks="saved entry, reload, exact date, legacy fragment/query isolation, back to original document, forward to Journal, keyboard, console",
                        )
                    except Exception:
                        row["error"] = traceback.format_exc()
                        page.screenshot(path=str(output / f"{label}-failed.png"))
                    finally:
                        row.update(
                            page_errors=errors, console_errors=console, blocked_external=external
                        )
                        context.close()
                        (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
        finally:
            browser.close()
    assert all(row["status"] == "passed" for row in rows), rows


if __name__ == "__main__":
    run()
