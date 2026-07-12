"""Live browser check for the manual S3-compatible backup settings."""

import os
import sys

from playwright.sync_api import sync_playwright

PORT = os.environ.get("S3_BROWSER_PORT", os.environ.get("PORT", "8914"))
URL = f"http://aide.localhost:{PORT}/"


def _open_backup(page):
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_function("typeof window._openSettings === 'function'")
    page.evaluate("window._openSettings('backup')")
    page.wait_for_selector("#s-pane-backup.active #s3-backup-card", timeout=15_000)
    page.wait_for_function(
        "document.getElementById('s3-backup-status')?.textContent !== 'checking connection…'"
    )


def main() -> int:
    results: dict[str, bool] = {}
    console_errors: list[str] = []
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
                lambda message: (
                    console_errors.append(message.text) if message.type == "error" else None
                ),
            )
            page.on("pageerror", lambda error: console_errors.append(str(error)))
            page.on(
                "response",
                lambda response: (
                    server_errors.append(f"{response.status} {response.url}")
                    if response.status >= 500
                    else None
                ),
            )
            _open_backup(page)
            card = page.locator("#s3-backup-card")
            card.scroll_into_view_if_needed()
            results[f"{label}_card_visible"] = card.is_visible()
            results[f"{label}_reduced_motion"] = page.evaluate(
                "matchMedia('(prefers-reduced-motion: reduce)').matches"
            )
            results[f"{label}_status_real_api"] = (
                page.locator("#s3-backup-status").text_content() == "not connected"
            )
            results[f"{label}_secrets_hidden"] = page.evaluate(
                "document.getElementById('s3-backup-access-key-id').type === 'password' && "
                "document.getElementById('s3-backup-secret-access-key').type === 'password' && "
                "!document.getElementById('s3-backup-access-key-id').value && "
                "!document.getElementById('s3-backup-secret-access-key').value"
            )
            overflow = page.evaluate(
                "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) "
                "- window.innerWidth"
            )
            results[f"{label}_fits"] = overflow <= 2

            endpoint = page.locator("#s3-backup-endpoint")
            endpoint.focus()
            results[f"{label}_keyboard_focus"] = endpoint.evaluate(
                "element => document.activeElement === element"
            )

            if label == "desktop":
                chooser_button = page.locator("#s3-backup-recovery-key-btn")
                chooser_button.focus()
                with page.expect_file_chooser() as chooser_info:
                    chooser_button.press("Enter")
                chooser_info.value.set_files(
                    {
                        "name": "separate-recovery-key.txt",
                        "mimeType": "text/plain",
                        "buffer": b"browser-only-test-key",
                    }
                )
                results["desktop_keyboard_file_choice"] = (
                    page.locator("#s3-backup-recovery-key-name").text_content()
                    == "separate-recovery-key.txt"
                )

            api_status = page.evaluate("fetch('/api/backup/s3').then(r => r.json())")
            results[f"{label}_api_masked"] = (
                api_status.get("configured") is False
                and api_status.get("credentials_set") is False
                and "credentials" not in api_status
                and "access_key_id" not in api_status
                and "secret_access_key" not in api_status
            )
            page.close()
            context.close()
        browser.close()

    results["zero_console_errors"] = not console_errors
    results["zero_server_errors"] = not server_errors
    for key, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'} {key}")
    if console_errors:
        print(f"console errors: {console_errors[:10]}")
    if server_errors:
        print(f"server errors: {server_errors[:10]}")
    return 0 if results and all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
