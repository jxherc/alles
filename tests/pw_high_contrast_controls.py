"""Verify visible switch positions and keyboard operation with forced colors."""

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                forced_colors="active",
                reduced_motion="reduce",
                service_workers="block",
            )
            assert context.request.post(base + "/api/setup/dismiss").ok
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/?view=today", wait_until="networkidle")
            page.locator("#today-settings").click()
            choose_settings_section(page, "general")

            def inspect(selector, label):
                control = page.locator(selector)
                expect(control).to_be_visible()
                control.focus()
                initial = control.get_attribute("aria-checked")
                states = []
                for expected in (initial, "false" if initial == "true" else "true"):
                    expect(control).to_have_attribute("aria-checked", expected)
                    style = control.evaluate("""e => {
                        const knob=getComputedStyle(e,'::after'), track=getComputedStyle(e,'::before');
                        const rect=e.getBoundingClientRect();
                        return {knob:knob.backgroundColor,track:track.backgroundColor,
                            adjust:knob.forcedColorAdjust,left:knob.left,
                            width:rect.width,height:rect.height};
                    }""")
                    assert style["knob"] != style["track"], style
                    assert style["adjust"] == "none", style
                    assert min(style["width"], style["height"]) >= 44, style
                    states.append(style)
                    page.screenshot(path=str(output / f"{width}-{label}-{expected}.png"))
                    control.press("Space")
                expect(control).to_have_attribute("aria-checked", initial)
                assert states[0]["left"] != states[1]["left"], states
                rows.append({"width": width, "control": label, "states": states})

            inspect("#s-welcome-toggle", "settings")
            choose_settings_section(page, "home")
            inspect('[aria-label="show schedule on Home"]', "home")
            disabled = page.locator('[aria-label="show needs you on Home"]')
            expect(disabled).to_be_disabled()
            disabled_style = disabled.evaluate("""e => ({
                knob:getComputedStyle(e,'::after').backgroundColor,
                track:getComputedStyle(e,'::before').backgroundColor
            })""")
            assert disabled_style["knob"] != disabled_style["track"], disabled_style
            page.locator("#settings-modal-close").click()
            page.evaluate("() => window._navigateTo('cookbook')")
            inspect("#cb-fitonly", "cookbook")
            assert not errors, errors
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            context.close()
        browser.close()
    (output / "controls.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"passed {len(rows)} switch keyboard and forced-color checks")


if __name__ == "__main__":
    run()
