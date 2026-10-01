"""Ordinary Settings selections use neutral state in both themes and layouts."""

from __future__ import annotations

import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section


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
                choose_settings_section(page, "themes")
                browse = page.locator('#theme-editor-inline [data-theme-section="presets"]')
                if browse.get_attribute("open") is None:
                    browse.locator("summary").click()
                page.locator('#theme-editor-inline [data-preset="default"]').click()
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

                if (
                    page.locator(
                        '#theme-editor-inline [data-theme-section="presets"]'
                    ).get_attribute("open")
                    is None
                ):
                    page.locator(
                        '#theme-editor-inline [data-theme-section="presets"] > summary'
                    ).click()
                presets = page.locator("#theme-editor-inline .te-presets")
                expect(presets).to_have_attribute("role", "radiogroup")
                tile_count = presets.locator('[role="radio"]').count()
                assert tile_count >= 50
                search = page.locator("#te-preset-filter")
                search.fill("forest")
                visible = presets.locator('[role="radio"]:visible')
                assert visible.count() == 2
                visible.first.focus()
                visible.first.press("End")
                expect(presets.locator('[data-preset="everforest"]')).to_be_focused()
                search.fill("no such theme")
                expect(page.locator("#te-preset-results")).to_have_text("no matching themes")
                search.fill("")
                assert presets.locator('[role="radio"]:visible').count() == tile_count
                presets.locator('[data-preset="default"]').click()
                selected.click()
                if (
                    page.locator(
                        '#theme-editor-inline [data-theme-section="presets"]'
                    ).get_attribute("open")
                    is None
                ):
                    page.locator(
                        '#theme-editor-inline [data-theme-section="presets"] > summary'
                    ).click()
                default = presets.locator('[data-preset="default"]')
                expect(default).to_have_attribute("aria-checked", "true")
                assert _colors(default)["background"] == raised
                assert _colors(default)["border"] == line
                assert _colors(default)["border"] != accent

                if page.locator("#s-accent-details").get_attribute("open") is None:
                    page.locator("#s-accent-details > summary").click()
                page.locator('#s-accent-swatches .accent-swatch[data-hex="#a78bfa"]').click()
                expect(
                    page.locator('#theme-editor-inline input[data-color="accent"]')
                ).to_have_value("#a78bfa")

                presets.locator('[data-preset="midnight"]').click()
                if page.locator("#s-accent-details").get_attribute("open") is None:
                    page.locator("#s-accent-details > summary").click()
                swatch = page.locator('#s-accent-swatches .accent-swatch[data-hex="#a78bfa"]')
                swatch.focus()
                swatch.press("Enter")
                selected.focus()
                selected.press("Enter")
                assert (
                    page.evaluate(
                        "JSON.parse(localStorage.getItem('alles-appearance')).accentCustom"
                    )
                    is True
                )
                expect(
                    page.locator('#theme-editor-inline input[data-color="accent"]')
                ).to_have_value("#a78bfa")

                if (
                    page.locator(
                        '#theme-editor-inline [data-theme-section="advanced"]'
                    ).get_attribute("open")
                    is None
                ):
                    page.locator(
                        '#theme-editor-inline [data-theme-section="advanced"] > summary'
                    ).click()
                font = page.locator('#theme-editor-inline [data-seg="font"]')
                expect(font).to_have_attribute("role", "radiogroup")
                sans = font.locator('[data-val="sans"]')
                mono = font.locator('[data-val="mono"]')
                sans.focus()
                sans.press("ArrowRight")
                expect(mono).to_be_focused()
                expect(mono).to_have_attribute("aria-checked", "true")
                assert (page.locator("html").get_attribute("data-theme") or "dark") == theme
                assert (
                    page.evaluate(
                        "JSON.parse(localStorage.getItem('alles-appearance')).colors.accent"
                    )
                    == "#a78bfa"
                )
                assert _colors(mono)["background"] == raised, (
                    theme,
                    _colors(mono),
                    raised,
                    mono.get_attribute("class"),
                    mono.get_attribute("data-kokuen-state"),
                )
                assert _colors(mono)["color"] == text
                mono.press("Home")
                expect(sans).to_be_focused()
                expect(sans).to_have_attribute("aria-checked", "true")

                harmony = page.locator('#theme-editor-inline [data-seg="harmony-type"]')
                expect(harmony).to_have_attribute("role", "radiogroup")
                harmony.locator('[data-val="complementary"]').focus()
                harmony.locator('[data-val="complementary"]').press("ArrowRight")
                expect(harmony.locator('[data-val="analogous"]')).to_have_attribute(
                    "aria-checked", "true"
                )

                sample = presets.locator(
                    '[data-preset="sakura"]' if theme == "light" else '[data-preset="graphite"]'
                )
                sample.click()
                expect(sample).to_be_focused()
                expect(sample).to_have_attribute("aria-checked", "true")
                assert _colors(sample)["background"] == _token(page, "--raised")
                assert _colors(sample)["border"] == _token(page, "--line-strong")
                assert _colors(sample)["border"] != _token(page, "--accent")
                page.locator('#theme-editor-inline input[data-color="bg"]').evaluate(
                    "el => { el.value = '#123456'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                expect(presets.locator('[aria-checked="true"]')).to_have_count(0)
                default.click()
                expect(default).to_have_attribute("aria-checked", "true")
                selected.click()
                expect(page.locator("#s-pane-themes > .theme-save-state")).to_have_attribute(
                    "data-state", "saved"
                )
                page.screenshot(path=str(output / f"settings-appearance-{width}-{theme}.png"))

                if width == 1440:
                    page.evaluate("document.body.style.zoom = '200%'")
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                    )
                    page.evaluate("document.body.style.zoom = ''")
                font.scroll_into_view_if_needed()
                page.screenshot(path=str(output / f"settings-editor-options-{width}-{theme}.png"))

                choose_settings_section(page, "general")
                switch = page.locator("#s-welcome-toggle")
                if "on" not in (switch.get_attribute("class") or "").split():
                    switch.click()
                expect(switch).to_have_attribute("aria-checked", "true")
                assert _colors(switch, "::before")["background"] == raised
                assert _colors(switch, "::after")["background"] == text
                box = switch.bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44

                choose_settings_section(page, "home")
                home = page.locator('[data-home-section="today"] .home-settings-switch')
                expect(home).to_have_attribute("aria-checked", "true")
                assert _colors(home, "::before")["background"] == raised
                assert _colors(home, "::after")["background"] == text
                home.scroll_into_view_if_needed()
                page.screenshot(path=str(output / f"settings-home-{width}-{theme}.png"))

                choose_settings_section(page, "notifications")
                language = page.locator('[data-locale-language="en"]')
                expect(language).to_have_attribute("aria-checked", "true")
                assert _colors(language, "::after")["background"] == text
                language.scroll_into_view_if_needed()
                language.focus()
                page.screenshot(path=str(output / f"settings-language-{width}-{theme}.png"))
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )

            # A chosen accent can be pale on light surfaces; permission wording
            # must remain readable without changing that saved owner choice.
            page.goto(f"http://aide.localhost:{port}", wait_until="networkidle")
            permission = page.locator("#perm-mode-btn")
            expect(permission).to_be_visible()
            assert _colors(permission)["color"] == _token(page, "--k-text")
            page.screenshot(path=str(output / f"settings-custom-accent-aide-{width}.png"))
            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
