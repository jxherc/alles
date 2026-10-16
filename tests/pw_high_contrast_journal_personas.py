"""Visible Journal cells and Persona settings in forced colors on owned test data."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section


def appearance(locator, pseudo=None):
    return locator.evaluate(
        """(el, pseudo) => {
            const s = getComputedStyle(el, pseudo);
            return {background: s.backgroundColor, color: s.color,
                border: s.borderTopWidth, borderStyle: s.borderTopStyle,
                borderColor: s.borderTopColor, outline: s.outlineWidth,
                content: s.content, decoration: s.textDecorationLine};
        }""",
        pseudo,
    )


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            for scheme in ("light", "dark"):
                label = f"{width}-{scheme}"
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    forced_colors="active",
                    color_scheme=scheme,
                    reduced_motion="reduce",
                    service_workers="block",
                )
                external, errors = [], []

                def route(request):
                    if urlparse(request.request.url).netloc != urlparse(base).netloc:
                        external.append(request.request.url)
                        return request.abort()
                    return request.continue_()

                context.route("**/*", route)
                context.route_web_socket("**/*", lambda socket: socket.close())
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                day = "2026-10-12"
                assert api.put(
                    base + "/api/journal/" + day,
                    data={"content": "synthetic forced colors journal entry"},
                ).ok
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base + "/?view=journal&d=" + day, wait_until="networkidle")
                populated = page.locator(f'.jrnl-hc[data-d="{day}"]')
                expect(populated).to_be_visible()
                populated.scroll_into_view_if_needed()
                empty = page.locator(".jrnl-hc.l0:not(.off)").first
                empty_style, filled_style = appearance(empty), appearance(populated)
                assert empty_style["border"] == "1px", empty_style
                assert empty_style["borderColor"] != empty_style["background"], empty_style
                assert filled_style["background"] != empty_style["background"], filled_style
                page.screenshot(path=str(output / f"{label}-journal.png"))
                rows.append(
                    {
                        "profile": label,
                        "check": "journal",
                        "empty": empty_style,
                        "populated": filled_style,
                    }
                )

                page.goto(base + "/?view=today", wait_until="networkidle")
                page.locator("#today-settings").click()
                choose_settings_section(page, "personas")
                slider = page.get_by_role("slider", name="temperature", exact=True)
                slider.scroll_into_view_if_needed()
                slider.focus()
                for key, value, count in (
                    ("Home", "0.0", 0),
                    ("ArrowRight", "0.1", 1),
                    ("End", "2.0", 20),
                    ("ArrowLeft", "1.9", 19),
                ):
                    slider.press(key)
                    expect(slider).to_have_attribute("aria-valuenow", value)
                    expect(slider.locator(".tc.f")).to_have_count(count)
                filled, unfilled = (
                    appearance(slider.locator(".tc.f").first),
                    appearance(slider.locator(".tc:not(.f)").first),
                )
                assert filled["background"] != unfilled["background"], (filled, unfilled)
                assert unfilled["borderColor"] != unfilled["background"], unfilled
                assert float(appearance(slider)["outline"].rstrip("px")) >= 2
                page.screenshot(path=str(output / f"{label}-temperature.png"))
                rows.append(
                    {
                        "profile": label,
                        "check": "temperature-keyboard",
                        "filled": filled,
                        "unfilled": unfilled,
                    }
                )

                mode = page.locator('#persona-mode [data-val="chat"]')
                mode.focus()
                mode.press("Space")
                expect(mode).to_have_class("seg-opt active")
                selected_mode = appearance(mode)
                other_mode = appearance(page.locator('#persona-mode [data-val="agent"]'))
                assert selected_mode["background"] != other_mode["background"]
                assert "underline" in selected_mode["decoration"]

                swatch = page.get_by_role("button", name="indigo", exact=True)
                swatch.focus()
                swatch.press("Space")
                expect(swatch).to_have_class("pa-swatch active")
                selected = appearance(swatch)
                other = appearance(page.get_by_role("button", name="violet", exact=True))
                assert selected["background"] != other["background"]
                assert selected["background"] != selected["color"]
                assert appearance(swatch, "::after")["content"] == '"indigo"'
                assert "underline" in selected["decoration"]
                page.screenshot(path=str(output / f"{label}-selections.png"))
                rows.append(
                    {
                        "profile": label,
                        "check": "selection-keyboard",
                        "mode": selected_mode,
                        "accent": selected,
                    }
                )

                page.emulate_media(forced_colors="none")
                assert appearance(swatch, "::after")["content"] == "none"
                assert appearance(swatch)["background"] != other["background"]
                page.screenshot(path=str(output / f"{label}-normal-theme.png"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                assert not external, external
                context.close()
        browser.close()
    (output / "journal-personas.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"passed {len(rows)} Journal/Persona visual and keyboard checks")


if __name__ == "__main__":
    run()
