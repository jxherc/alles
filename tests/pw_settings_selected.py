"""Ordinary Settings selections use neutral state in both themes and layouts."""

from __future__ import annotations

import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def _colors(locator, pseudo: str = "") -> dict[str, str]:
    return locator.evaluate(
        """(node, pseudo) => {
          const style = getComputedStyle(node, pseudo || null);
          return {
            background: style.backgroundColor,
            border: style.borderTopColor,
            color: style.color,
          };
        }""",
        pseudo,
    )


def _token(page, name: str) -> str:
    return page.evaluate(
        """name => {
          const probe = document.createElement('span');
          probe.style.color = `var(${name})`;
          document.querySelector('#settings-modal').append(probe);
          const value = getComputedStyle(probe).color;
          probe.remove();
          return value;
        }""",
        name,
    )


def run() -> None:
    port = os.environ["PORT"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    base = f"http://127.0.0.1:{port}"
    require_server_ownership(base, run_id)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            assert context.request.post(base + "/api/setup/dismiss").ok
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.goto(base, wait_until="domcontentloaded")
            page.locator("#today-settings").click()
            expect(page.locator("#settings-modal")).to_be_visible()

            for theme in ("dark", "light"):
                page.locator('.s-nav-item[data-pane="themes"]').click()
                selected = page.locator(f'.theme-mode-btn[data-theme-mode="{theme}"]')
                selected.click()
                assert (page.locator("html").get_attribute("data-theme") or "dark") == theme
                expect(selected).to_have_class("theme-mode-btn active")
                expect(selected).to_have_attribute("aria-pressed", "true")
                expect(
                    page.locator(f'.theme-mode-btn:not([data-theme-mode="{theme}"])')
                ).to_have_attribute("aria-pressed", "false")
                expect(page.locator("#s-pane-themes > .theme-save-state")).to_have_attribute(
                    "data-state", "saved"
                )
                text = _token(page, "--k-text")
                raised = _token(page, "--k-raised")
                line = _token(page, "--k-line-strong")
                accent = _token(page, "--k-accent")
                mode = _colors(selected)
                assert mode["color"] == text and mode["background"] == raised
                assert mode["border"] == line and mode["border"] != accent
                page.screenshot(path=str(output / f"settings-appearance-{width}-{theme}.png"))

                page.locator('.s-nav-item[data-pane="general"]').click()
                switch = page.locator("#s-welcome-toggle")
                if "on" not in (switch.get_attribute("class") or "").split():
                    switch.click()
                expect(switch).to_have_attribute("aria-checked", "true")
                assert _colors(switch, "::before")["background"] == raised
                assert _colors(switch, "::after")["background"] == text
                box = switch.bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44

                page.locator('.s-nav-item[data-pane="home"]').click()
                home = page.locator('[data-home-section="today"] .home-settings-switch')
                expect(home).to_have_attribute("aria-checked", "true")
                assert _colors(home, "::before")["background"] == raised
                assert _colors(home, "::after")["background"] == text
                home.scroll_into_view_if_needed()
                page.screenshot(path=str(output / f"settings-home-{width}-{theme}.png"))

                page.locator('.s-nav-item[data-pane="notifications"]').click()
                language = page.locator('[data-locale-language="en"]')
                expect(language).to_have_attribute("aria-checked", "true")
                assert _colors(language, "::after")["background"] == text
                language.scroll_into_view_if_needed()
                language.focus()
                page.screenshot(path=str(output / f"settings-language-{width}-{theme}.png"))
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )

            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
