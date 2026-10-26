"""Rendered gate: the andromeda answer model is one stored value, editable in two sections."""

import json
import os

from playwright.sync_api import expect, sync_playwright

PORT = os.environ.get("PORT", "8030")
BASE = f"http://127.0.0.1:{PORT}"
ENDPOINTS = [
    {"id": "ep-a", "name": "alpha", "models": ["alpha-fast", "alpha-big"]},
    {"id": "ep-b", "name": "beta", "models": ["beta-fast", "beta-big"]},
]


def run() -> None:
    errors: list[str] = []
    patches: list[dict] = []
    stored = {
        "aide_chat": {},
        "andromeda_answer": {"endpoint_id": "ep-a", "model": "alpha-fast"},
        "andromeda_verifier": {},
        "jarvis": {},
        "coding": {},
    }

    def settings(route):
        if route.request.method == "PATCH":
            body = route.request.post_data_json
            patches.append(body)
            if "model_roles" in body:
                stored.update(body["model_roles"])
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"context_limit": 57, "language": "en", "model_roles": stored}),
        )

    def models(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(ENDPOINTS))

    def wait_for(page, ready):
        for _ in range(50):
            if ready():
                return
            page.wait_for_timeout(100)
        raise AssertionError("the save never reached the settings route")

    def pick(page, selector, text):
        page.locator(selector).click()
        page.locator(".custom-dropdown-option", has_text=text).last.click()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1440, 1000), (390, 844)):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(5_000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/settings", settings)
            page.route("**/api/models", models)
            page.goto(BASE, wait_until="networkidle")
            page.evaluate("window._navigateTo('andromeda')")
            page.wait_for_selector("#andromeda-view:visible")
            page.locator("#andromeda-idle-settings").click()
            page.wait_for_selector("#s-pane-andromeda.active", state="visible")

            answer = page.locator("#s-andromeda-answer-model")
            expect(answer).to_contain_text("alpha · alpha-fast")

            # andromeda section -> stored value -> models section
            patches.clear()
            pick(page, "#s-andromeda-answer-model", "beta · beta-big")
            wait_for(page, lambda: patches)
            assert patches[-1]["model_roles"]["andromeda_answer"]["model"] == "beta-big"
            assert patches[-1]["model_roles"]["andromeda_answer"]["endpoint_id"] == "ep-b"
            page.evaluate("window._openSettings('models')")
            role = page.locator('[data-role-select="andromeda_answer"]')
            expect(role).to_contain_text("beta · beta-big")

            # models section -> stored value -> andromeda section, other roles untouched
            patches.clear()
            pick(page, '[data-role-select="aide_chat"]', "alpha · alpha-big")
            pick(page, '[data-role-select="andromeda_answer"]', "alpha · alpha-fast")
            wait_for(page, lambda: patches)
            assert patches[-1]["model_roles"]["andromeda_answer"]["model"] == "alpha-fast"
            # an unsaved edit of another role is not written by the shared role's save
            assert patches[-1]["model_roles"]["aide_chat"] == {}
            page.evaluate("window._openSettings('andromeda')")
            expect(page.locator("#s-andromeda-answer-model")).to_contain_text("alpha · alpha-fast")
            # the models section kept its unsaved draft
            page.evaluate("window._openSettings('models')")
            expect(page.locator('[data-role-select="aide_chat"]')).to_contain_text(
                "alpha · alpha-big"
            )
            context.close()
        browser.close()

    if errors:
        raise AssertionError("browser errors:\n" + "\n".join(errors))
    print("andromeda answer model stays in sync between settings sections")


if __name__ == "__main__":
    run()
