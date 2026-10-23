"""Real pointer/keyboard acceptance for switch tracks inside 44px targets."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pw_v5_literal_resting_controls import BASE, PORT, _require_owned_data

GEOMETRY = """el => {
  const track = getComputedStyle(el, '::before');
  const thumb = el.matches('.andromeda-switch') ? getComputedStyle(el.querySelector('span')) : getComputedStyle(el, '::after');
  const box = el.getBoundingClientRect();
  const shift = thumb.transform === 'none' ? 0 : new DOMMatrix(thumb.transform).m41;
  return {width: box.width, height: box.height, background: getComputedStyle(el).backgroundColor,
    track: [parseFloat(track.left), parseFloat(track.top), parseFloat(track.width), parseFloat(track.height)],
    thumb: [parseFloat(thumb.left)+shift, parseFloat(thumb.top), parseFloat(thumb.width), parseFloat(thumb.height)],
    trackSizing: track.boxSizing, thumbMotion: thumb.transitionDuration,
    checked: el.getAttribute('aria-checked') === 'true'};
}"""


def check_geometry(control) -> None:
    geometry = control.evaluate(GEOMETRY)
    assert geometry["width"] >= 44 and geometry["height"] >= 44, geometry
    assert geometry["background"] == "rgba(0, 0, 0, 0)", geometry
    assert geometry["trackSizing"] == "border-box", geometry
    x, y, width, height = geometry["track"]
    tx, ty, tw, th = geometry["thumb"]
    assert width > height and tw == th, geometry
    assert 0 <= x and x + width <= geometry["width"], geometry
    assert abs(y + height / 2 - (ty + th / 2)) < 0.5, geometry
    assert x < tx and tx + tw < x + width, geometry
    assert (tx + tw / 2 > x + width / 2) == geometry["checked"], geometry
    assert all(
        float(value.strip().removesuffix("s")) <= 0.001
        for value in geometry["thumbMotion"].split(",")
    ), geometry


def exercise(control) -> None:
    expect(control).to_be_visible()
    check_geometry(control)
    initial = control.get_attribute("aria-checked")
    control.click()
    expect(control).to_have_attribute("aria-checked", str(initial != "true").lower())
    expect(control).not_to_have_attribute("aria-busy", "true")
    check_geometry(control)
    control.press("Space")
    expect(control).to_have_attribute("aria-checked", initial)
    expect(control).not_to_have_attribute("aria-busy", "true")
    check_geometry(control)
    assert control.evaluate("el => el === document.activeElement")
    assert control.evaluate("el => parseFloat(getComputedStyle(el).outlineWidth) >= 2")


def run() -> None:
    _require_owned_data()
    output = Path(os.environ.get("ALLES_SWITCH_OUTPUT", "/tmp/alles-switch-proof"))
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            assert page.request.post(f"{BASE}/api/setup/dismiss").ok
            page.goto(BASE, wait_until="networkidle")
            page.locator("#today-settings").click()
            page.locator('#settings-modal [data-pane="general"]').click()
            exercise(page.locator("#s-welcome-toggle"))
            page.screenshot(path=str(output / f"settings-{width}.png"))
            page.keyboard.press("Escape")
            page.goto(f"http://andromeda.localhost:{PORT}/", wait_until="networkidle")
            page.locator(
                "#andromeda-idle-settings:visible, #andromeda-settings-button:visible"
            ).click()
            exercise(page.locator("#andromeda-overview-toggle"))
            page.screenshot(path=str(output / f"andromeda-{width}.png"))
            context.close()
        browser.close()
    assert not errors, errors
    print(
        "shared switch geometry passed: pointer, Space, state, focus, reduced motion, desktop and phone"
    )


if __name__ == "__main__":
    run()
