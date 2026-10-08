"""Malformed local policy proposals retain their text and explain how to repair it."""

import json
import os
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

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
                        has_touch=width == 390,
                    )
                    errors, console, external, responses = [], [], [], []

                    def route(request):
                        if urlparse(request.request.url).netloc != urlparse(base).netloc:
                            external.append(request.request.url)
                            return request.abort()
                        return request.continue_()

                    context.route("**/*", route)
                    context.route_web_socket("**/*", lambda socket: socket.close())
                    page = context.new_page()
                    page.set_default_timeout(5000)
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "console", lambda m: console.append(m.text) if m.type == "error" else None
                    )
                    row = {
                        "scenario_id": "server.policy-validation",
                        "profile": label,
                        "status": "failed",
                    }
                    rows.append(row)
                    try:
                        api = context.request
                        assert api.post(base + "/api/setup/dismiss").ok
                        assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                        before = api.get(base + "/api/system/policy").json()
                        page.goto(base + "/?view=server", wait_until="networkidle")
                        root = page.locator("#server-workbench-view")
                        root.locator('[data-group-section="policy"]').press("Enter")
                        card = root.locator(".server-workbench-card").filter(
                            has=page.get_by_role("heading", name="server access policy", exact=True)
                        )
                        editor = card.locator("textarea")
                        expect(editor).to_be_visible()
                        original = editor.input_value()
                        message = card.locator(".server-workbench-status").first
                        validate = card.get_by_role(
                            "button", name="validate and show diff", exact=True
                        )
                        for proposal in ("{", "", '{\n  "control_mode":\n}'):
                            editor.fill(proposal)
                            with page.expect_response(base + "/api/system/policy/diff") as response:
                                validate.press("Enter")
                            responses.append(response.value.json())
                            expect(message).not_to_have_text("[object Object]")
                            expect(message).to_contain_text("policy is not valid JSON")
                            expect(message).to_contain_text(re.compile(r"line \d+, column \d+"))
                            expect(editor).to_have_value(proposal)
                            expect(validate).to_be_enabled()
                            expect(validate).to_be_focused()
                            assert api.get(base + "/api/system/policy").json() == before
                        page.screenshot(path=str(output / f"{label}-invalid.png"))
                        editor.fill(" " * 32769)
                        validate.press("Enter")
                        expect(message).to_contain_text("at most 32768 characters")
                        expect(message).not_to_contain_text("[object Object]")
                        expect(editor).to_have_value(" " * 32769)
                        assert api.get(base + "/api/system/policy").json() == before
                        editor.fill(original)
                        validate.press("Enter")
                        expect(message).to_have_text("policy is valid")
                        expect(message).not_to_have_class(re.compile("is-error"))
                        assert api.get(base + "/api/system/policy").json() == before
                        assert editor.input_value() == original
                        page.screenshot(path=str(output / f"{label}-recovered.png"))
                        assert not errors, errors
                        assert not external, external
                        assert all(
                            "409 (Conflict)" in text or "422 (Unprocessable Entity)" in text
                            for text in console
                        ), console
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        row.update(
                            status="passed",
                            checks="syntax guidance, location, exact proposal retained, no policy mutation, corrected validation, keyboard focus, both themes",
                        )
                    except Exception:
                        row["error"] = traceback.format_exc()
                        page.screenshot(path=str(output / f"{label}-failed.png"))
                    finally:
                        row.update(
                            page_errors=errors,
                            console_errors=console,
                            blocked_external=external,
                            validation_responses=responses,
                        )
                        context.close()
                        (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
        finally:
            browser.close()
    assert all(row["status"] == "passed" for row in rows), rows


if __name__ == "__main__":
    run()
