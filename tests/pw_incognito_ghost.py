"""Rendered check that every incognito state uses the same quiet ghost mark."""

import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8965")
BASE = f"http://127.0.0.1:{PORT}"
URL = f"http://aide.localhost:{PORT}/?app=chat"
EVIDENCE = Path(tempfile.gettempdir()) / "alles-incognito-ghost"


def _require_throwaway_data_root() -> None:
    data = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or len(run_id) < 16:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    if (data / ".alles-test-owner").read_text("utf-8").strip() != run_id:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, run_id)


def run() -> None:
    _require_throwaway_data_root()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors = []
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
        assert page.request.post(f"{BASE}/api/setup/dismiss").ok
        page.goto(URL, wait_until="networkidle")
        normal = page.locator("#incognito-btn .incognito-ghost")
        normal.wait_for(state="visible")
        normal_path = normal.locator("path").get_attribute("d")
        assert normal.evaluate("element => getComputedStyle(element).filter") == "none"
        page.screenshot(path=str(EVIDENCE / "incognito-ghost-normal.png"), full_page=False)

        page.locator("#incognito-btn").click()
        page.locator("#incognito-bar").wait_for(state="visible")
        bar = page.locator("#incognito-bar .incognito-ghost")
        hero = page.locator(".incognito-hero .incognito-ghost")
        hero.wait_for(state="visible")
        assert bar.locator("path").get_attribute("d") == normal_path
        assert hero.locator("path").get_attribute("d") == normal_path
        assert page.evaluate("getComputedStyle(document.body, '::after').content") == "none"
        assert (
            page.locator(".incognito-hero").evaluate(
                "element => getComputedStyle(element).animationName"
            )
            == "none"
        )
        page.screenshot(path=str(EVIDENCE / "incognito-ghost-active.png"), full_page=False)

        page.locator("#incognito-exit").click()
        normal.wait_for(state="visible")
        assert not errors, errors
        browser.close()

    print("PASS  normal, bar, and hero use one ghost path")
    print("PASS  enabled incognito has no glow frame or pulse")
    print("PASS  exit restores normal state with zero console errors")


if __name__ == "__main__":
    run()
