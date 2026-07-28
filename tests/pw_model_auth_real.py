"""Real-server browser gate for model-provider authentication Settings."""

import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

PORT = os.environ.get("PORT", "8993")
HOME = f"http://127.0.0.1:{PORT}"
URL = f"http://aide.localhost:{PORT}/"


def _require_throwaway_data_root() -> None:
    if os.environ.get("ALLES_TEST_DATA") != "1":
        raise RuntimeError("set ALLES_TEST_DATA=1 for this isolated browser gate")
    data = Path(os.environ.get("ALLES_DATA", "")).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "")
    if not run_id or data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be an owned system-temporary child")
    if (data / ".alles-test-owner").read_text("utf-8").strip() != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match")
    require_server_ownership(HOME, run_id)


def _open_models(page) -> None:
    page.goto(URL, wait_until="networkidle")
    page.wait_for_function("typeof window._openSettings === 'function'")
    page.evaluate("window._openSettings('models')")
    expect(page.locator("#settings-modal")).to_be_visible()
    expect(page.locator("#s-pane-models")).to_be_visible()


def run() -> None:
    _require_throwaway_data_root()
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height, label in ((1366, 920, "desktop"), (390, 844, "phone")):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(8_000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            _open_models(page)

            pane = page.locator("#s-pane-models")
            warning = page.locator(".s-provider-warning").inner_text().lower()
            assert "never imports consumer chat sessions" in warning
            assert pane.locator("select:visible").count() == 0
            assert pane.locator("input[type=checkbox]:visible").count() == 0
            assert pane.locator("input[type=radio]:visible").count() == 0
            assert pane.evaluate("el => el.scrollWidth <= el.clientWidth"), label
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            ), label

            if label == "desktop":
                page.locator("#s-ep-add-details > summary").click()
                page.locator('.s-preset-btn[data-provider="kimi"]').click()
                expect(page.locator("#s-ep-url")).to_have_value("https://api.moonshot.ai/v1")
                expect(page.locator("#s-ep-provider")).to_have_attribute("data-value", "kimi")

                page.locator('.s-preset-btn[data-provider="ollama"]').click()
                expect(page.locator("#s-ep-auth")).to_have_attribute("data-value", "none")
                expect(page.locator("#s-ep-key-row")).to_be_hidden()

                page.locator('.s-preset-btn[data-provider="deepseek"]').click()
                page.locator("#s-ep-key").fill("throwaway-deepseek-key")
                page.locator("#s-ep-adapter").click()
                page.locator(".custom-dropdown-option", has_text="manual list").last.click()
                page.locator("#s-ep-manual").fill("deepseek-test-model")
                page.locator("#s-ep-add-btn").click()
                expect(page.locator(".s-ep-card", has_text="DeepSeek").first).to_be_visible()
                card = page.locator(".s-ep-card", has_text="DeepSeek").first
                assert "api key" in card.inner_text().lower()
                assert "connected" in card.inner_text().lower()
                card.locator("[data-edit-list]").click()
                note = card.locator(".s-ep-editor-note").first.inner_text().lower()
                assert "published api uses bearer api keys" in note
                assert "free chat website is not an oauth source" in note
                assert "throwaway-deepseek-key" not in card.inner_text()

                page.locator("#s-gemini-oauth-toggle").focus()
                page.keyboard.press("Enter")
                expect(page.locator("#s-gemini-oauth-panel")).to_be_visible()
                page.locator("#s-gemini-oauth-start").click()
                expect(page.locator("#toast-container .toast").last).to_contain_text("required")

                page.locator("#s-gemini-client-id").fill("owner-client.apps.googleusercontent.com")
                page.locator("#s-gemini-client-secret").fill("throwaway-client-secret")
                page.locator("#s-gemini-project-id").fill("throwaway-project")
                page.evaluate(
                    """() => {
                      window.__oauthUrl = '';
                      window.open = url => {
                        window.__oauthUrl = String(url);
                        return {closed: true};
                      };
                    }"""
                )
                page.locator("#s-gemini-oauth-start").click()
                page.wait_for_function("Boolean(window.__oauthUrl)")
                oauth_url = page.evaluate("window.__oauthUrl")
                params = parse_qs(urlsplit(oauth_url).query)
                assert urlsplit(oauth_url).hostname == "accounts.google.com"
                assert params["code_challenge_method"] == ["S256"]
                assert params["access_type"] == ["offline"]
                assert "client_secret" not in params
                assert "throwaway-client-secret" not in oauth_url

            else:
                expect(page.locator(".s-ep-card", has_text="DeepSeek").first).to_be_visible()
                page.locator("#s-gemini-oauth-toggle").click()
                expect(page.locator("#s-gemini-oauth-panel")).to_be_visible()
                grid_columns = page.locator("#s-gemini-oauth-panel .s-ep-auth-grid").evaluate(
                    "el => getComputedStyle(el).gridTemplateColumns"
                )
                assert " " not in grid_columns.strip(), grid_columns

            pane.screenshot(path=f"/tmp/alles-model-auth-{label}.png")
            page.locator("#settings-modal-close").focus()
            page.keyboard.press("Escape")
            expect(page.locator("#settings-modal")).to_be_hidden()
            context.close()
        browser.close()
    if errors:
        raise AssertionError("model auth browser errors:\n" + "\n".join(errors))
    print("Model authentication real browser gate passed")


if __name__ == "__main__":
    run()
