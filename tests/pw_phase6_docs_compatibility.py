"""Rendered browser proof for legacy Docs, Notes, and Journal links.

Run against an isolated Alles server, for example:

    PORT=8966 ALLES_DATA=/tmp/alles-phase6-compat python app.py
    PORT=8966 python tests/pw_phase6_docs_compatibility.py
"""

import os
import re

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8966")


def _url(host: str, suffix: str = "/") -> str:
    return f"http://{host}.localhost:{PORT}{suffix}"


def run() -> None:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )

        page.goto(
            _url("notes", "/?mode=edit&keep=1#Folder%2FNote.md"),
            wait_until="domcontentloaded",
        )
        page.wait_for_url(re.compile(rf"^http://docs\.localhost:{PORT}/"))
        page.wait_for_selector("#wiki-view:visible")
        page.wait_for_selector("#wiki-notes:visible")
        assert page.url == _url("docs", "/?mode=edit&keep=1#Folder%2FNote.md")
        assert page.locator("body").get_attribute("data-app") == "docs"

        page.goto(
            _url("journal", "/?d=2026-07-01&keep=1#daily"),
            wait_until="domcontentloaded",
        )
        page.wait_for_url(re.compile(rf"^http://docs\.localhost:{PORT}/"))
        page.wait_for_selector("#wiki-view:visible")
        page.wait_for_selector("#docs-journal-section:visible")
        assert page.url == _url("docs", "/?d=2026-07-01&keep=1#daily")
        assert page.locator("body").get_attribute("data-app") == "docs"

        page.goto(
            _url("wiki", "/?keep=1#Folder%2FDoc.md"),
            wait_until="domcontentloaded",
        )
        page.wait_for_url(re.compile(rf"^http://docs\.localhost:{PORT}/"))
        page.wait_for_selector("#wiki-view:visible")
        assert page.url == _url("docs", "/?keep=1#Folder%2FDoc.md")
        assert page.locator("#wiki-notes").is_hidden()

        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        context.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("phase 6 docs compatibility browser gate passed")


if __name__ == "__main__":
    run()
