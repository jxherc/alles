"""Browser check for the Phase 1 API-token scope controls."""

import os
import sys

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PHASE1_PORT", os.environ.get("PORT", "8912"))
URL = f"http://aide.localhost:{PORT}/"


def _open_developer(page):
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_function("typeof window._openSettings === 'function'")
    page.evaluate("window._openSettings('developer')")
    page.wait_for_selector("#s-pane-developer.active #token-scopes", timeout=15_000)


def main() -> int:
    results: dict[str, bool] = {}
    errors: list[str] = []
    server_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for label, viewport, mobile in (
            ("desktop", {"width": 1280, "height": 800}, False),
            ("mobile", {"width": 390, "height": 844}, True),
        ):
            context = browser.new_context(
                viewport=viewport,
                is_mobile=mobile,
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "response",
                lambda response: (
                    server_errors.append(f"{response.status} {response.url}")
                    if response.status >= 500
                    else None
                ),
            )
            _open_developer(page)
            results[f"{label}_reduced_motion"] = page.evaluate(
                "matchMedia('(prefers-reduced-motion: reduce)').matches"
            )
            results[f"{label}_all_scopes_visible"] = (
                page.locator("[data-token-scope]:visible").count() == 7
            )
            results[f"{label}_read_only_default"] = page.evaluate(
                "[...document.querySelectorAll('[data-token-scope].active')]"
                ".map(x => x.dataset.tokenScope).join(',') === 'read'"
            )
            overflow = page.evaluate(
                "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) "
                "- window.innerWidth"
            )
            results[f"{label}_fits"] = overflow <= 2

            read = page.locator('[data-token-scope="read"]')
            read.focus()
            results[f"{label}_keyboard_focus"] = read.evaluate(
                "element => document.activeElement === element"
            )

            if label == "desktop":
                page.locator('[data-token-scope="write"]').press("Space")
                page.fill("#token-name", "phase one browser check")
                page.click("#token-add-btn")
                page.wait_for_selector("#token-reveal:visible")
                page.wait_for_function(
                    "document.querySelector('#token-list')?.textContent.includes('read, write')"
                )
                results["desktop_generate_scoped_token"] = True
            page.close()
            context.close()
        browser.close()

    results["zero_console_errors"] = not errors
    results["zero_server_errors"] = not server_errors
    for key, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'} {key}")
    if errors:
        print(f"console errors: {errors[:10]}")
    if server_errors:
        print(f"server errors: {server_errors[:10]}")
    return 0 if results and all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
