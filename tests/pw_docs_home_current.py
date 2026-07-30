"""The universal shell moves from Docs to the current Today surface."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8968")
BASE = f"http://127.0.0.1:{PORT}"
DATA = Path(os.environ["ALLES_DATA"]).resolve()
OUTPUT = Path(tempfile.gettempdir()) / "alles-docs-home-current.png"


def _require_throwaway_data_root() -> None:
    if os.environ.get("ALLES_TEST_DATA", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the isolated Docs navigation gate")
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        relative = DATA.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError("ALLES_DATA must be inside the system temporary directory") from exc
    if not relative.parts:
        raise RuntimeError("ALLES_DATA cannot be the system temporary directory itself")
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if len(run_id) < 16:
        raise RuntimeError("set a unique ALLES_TEST_RUN_ID for this browser run")
    try:
        owner = (DATA / ".alles-test-owner").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this browser run")
    require_server_ownership(BASE, run_id)


def run() -> None:
    _require_throwaway_data_root()
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(f"page: {error}"))
        page.on(
            "console",
            lambda message: (
                errors.append(f"console: {message.text}") if message.type == "error" else None
            ),
        )

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_function("typeof window._navigateTo === 'function'")
        if page.locator("#setup-wizard").is_visible():
            page.locator("#setup-skip").click()
            page.locator("#setup-wizard").wait_for(state="hidden")
        page.locator('.today-shortcut[data-view="wiki"]').click()
        page.locator("#wiki-view").wait_for(state="visible")
        assert not page.locator("#today-view").is_visible()
        assert not page.locator("#home-view").is_visible()

        page.locator("#app-drawer-btn").click()
        page.locator('.app-drawer-item[data-view="today"]').click()
        page.locator("#today-view").wait_for(state="visible")
        assert not page.locator("#home-view").is_visible()
        assert not page.locator("#wiki-view").is_visible()
        OUTPUT.unlink(missing_ok=True)
        page.screenshot(path=str(OUTPUT), full_page=True)

        context.close()
        browser.close()

    if errors:
        raise AssertionError("browser errors:\n" + "\n".join(errors))
    print(f"Docs Home current-route gate passed; capture: {OUTPUT}")


if __name__ == "__main__":
    run()
