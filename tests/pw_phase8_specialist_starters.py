"""Rendered browser gate for the five standalone Phase 8 specialist starters."""

import sys
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8973"
OUTPUT = Path("/tmp/alles-phase8-starters")
PAGES = ("plan", "inbox", "library", "health", "finance")


def _capture_errors(page: Page, errors: list[str], label: str) -> None:
    page.on("pageerror", lambda error: errors.append(f"{label} page: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"{label} console: {message.text}") if message.type == "error" else None
        ),
    )


def _open(page: Page, name: str) -> None:
    page.goto(
        f"{BASE_URL}/docs/mockups/afterlife-specialists/{name}.html",
        wait_until="networkidle",
    )
    page.locator(".main-pane h1").wait_for(state="visible")


def _assert_no_page_overflow(page: Page) -> None:
    metrics = page.evaluate(
        """
        () => ({
          url: location.href,
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
          offenders: [...document.querySelectorAll('body *')].map(element => {
            const box = element.getBoundingClientRect();
            return { tag: element.tagName, className: element.className || '', id: element.id || '', left: box.left, right: box.right };
          }).filter(item => item.left < -1 || item.right > document.documentElement.clientWidth + 1).slice(0, 12)
        })
        """
    )
    assert metrics["scrollWidth"] <= metrics["clientWidth"] + 1, metrics


def _assert_targets(page: Page) -> None:
    undersized = page.locator(
        "button:visible, .group-link:visible, input:visible, textarea:visible"
    ).evaluate_all(
        """
        elements => elements.map(element => {
          const box = element.getBoundingClientRect();
          return { label: element.getAttribute('aria-label') || element.textContent.trim(), width: box.width, height: box.height };
        }).filter(item => item.width < 43.5 || item.height < 43.5)
        """
    )
    assert not undersized, undersized


def _assert_type_floor(page: Page) -> None:
    undersized = page.locator("body *:visible").evaluate_all(
        """
        elements => elements.map(element => {
          const directText = [...element.childNodes]
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent.trim())
            .join(' ')
            .trim();
          return {
            label: directText,
            size: parseFloat(getComputedStyle(element).fontSize),
            className: element.className || '',
          };
        }).filter(item => item.label && item.size < 11.9 && item.className !== 'state-trigger')
        """
    )
    assert not undersized, undersized


def _contrast(page: Page) -> float:
    return page.locator("body").evaluate(
        """
        element => {
          const parse = value => value.match(/[0-9.]+/g).slice(0, 3).map(Number);
          const luminance = value => {
            const rgb = parse(value).map(channel => {
              const c = channel / 255;
              return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
            });
            return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
          };
          const style = getComputedStyle(element);
          const a = luminance(style.color);
          const b = luminance(style.backgroundColor);
          return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        }
        """
    )


def _assert_structure(page: Page) -> None:
    assert page.locator(".group-link").count() == 5
    assert page.locator('.group-link[aria-current="page"]').count() == 1
    assert page.locator('.group-link[aria-current="page"]').evaluate(
        """
        element => {
          const item = element.getBoundingClientRect();
          const strip = element.closest('.group-strip').getBoundingClientRect();
          return item.left >= strip.left - 1 && item.right <= strip.right + 1;
        }
        """
    )
    assert page.locator("select").count() == 0
    assert (
        page.locator('input[type="checkbox"], input[type="radio"], input[type="file"]').count() == 0
    )
    assert page.evaluate(
        """
        [...document.querySelectorAll('[id]')].every((element, index, all) =>
          all.findIndex(other => other.id === element.id) === index)
        """
    )
    assert page.evaluate(
        """
        [...document.querySelectorAll('[aria-controls]')].every(element =>
          document.getElementById(element.getAttribute('aria-controls')))
        """
    )
    assert page.locator(".main-pane h1").evaluate(
        "element => getComputedStyle(element).opacity === '1'"
    )
    track = page.locator(".switch-track").first
    knob = page.locator(".switch-knob").first
    assert track.evaluate("element => parseFloat(getComputedStyle(element).borderRadius) >= 9")
    assert knob.evaluate(
        "element => parseFloat(getComputedStyle(element).borderRadius) >= element.getBoundingClientRect().width / 2"
    )
    _assert_no_page_overflow(page)
    _assert_targets(page)
    _assert_type_floor(page)
    assert _contrast(page) >= 7


def _exercise_common(page: Page) -> None:
    trigger = page.locator("[data-state-trigger]")
    trigger.focus()
    page.keyboard.press("ArrowDown")
    assert page.locator("#state-menu").is_visible()
    assert page.locator('#state-menu [role="option"][tabindex="0"]').count() == 1
    assert page.locator('#state-menu [role="option"][tabindex="-1"]').count() == 4
    page.keyboard.press("ArrowDown")
    assert page.locator('#state-menu [role="option"][tabindex="0"]:focus').count() == 1
    page.keyboard.press("Enter")
    assert page.locator("body").get_attribute("data-demo-state") == "loading"
    assert page.locator("#demo-state").is_visible()
    assert trigger.evaluate("element => document.activeElement === element")

    selected_tab = page.locator('.main-pane > .tabs [role="tab"][aria-selected="true"]')
    old_controls = selected_tab.get_attribute("aria-controls")
    selected_tab.focus()
    page.keyboard.press("ArrowRight")
    next_tab = page.locator('.main-pane > .tabs [role="tab"][aria-selected="true"]')
    assert next_tab.count() == 1
    assert next_tab.get_attribute("aria-controls") != old_controls
    assert page.locator(f"#{next_tab.get_attribute('aria-controls')}").is_visible()

    theme = page.locator('[role="switch"][data-switch="theme"]')
    theme.focus()
    page.keyboard.press("Space")
    assert theme.get_attribute("aria-checked") == "true"
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.wait_for_function(
        "getComputedStyle(document.body).backgroundColor === 'rgb(244, 243, 240)'"
    )
    background = page.locator("body").evaluate(
        "element => getComputedStyle(element).backgroundColor"
    )
    assert background == "rgb(244, 243, 240)", {
        "url": page.url,
        "background": background,
        "root_theme": page.locator("html").get_attribute("data-theme"),
        "switch_checked": theme.get_attribute("aria-checked"),
        "bg_value": page.locator("body").evaluate(
            "element => getComputedStyle(element).getPropertyValue('--bg')"
        ),
        "matches_light": page.locator("body").evaluate(
            "element => element.matches('[data-theme=light]')"
        ),
    }
    assert _contrast(page) >= 7

    density = page.locator('[role="switch"][data-switch="density"]')
    density.click()
    assert density.get_attribute("aria-checked") == "true"
    assert page.locator("body").get_attribute("data-density") == "compact"

    opener = page.locator("[data-open-modal]:visible").first
    opener.click()
    assert page.locator("#starter-modal").is_visible()
    assert page.locator("#starter-modal").get_attribute("role") == "presentation"
    if page.locator('#starter-modal [role="tablist"]').count():
        page.locator('#starter-modal [role="tab"][aria-selected="true"]').press("ArrowRight")
        active_tab = page.locator('#starter-modal [role="tab"][aria-selected="true"]')
        assert active_tab.get_attribute("tabindex") in (None, "0")
        active_tab.press("Shift+Tab")
        assert page.locator("#starter-modal button:focus").count() == 1
        assert page.locator("#starter-modal [hidden] :focus").count() == 0
    page.keyboard.press("Escape")
    assert page.locator("#starter-modal").is_hidden()
    assert opener.evaluate("element => document.activeElement === element")


def _desktop(browser: Browser, errors: list[str]) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(10_000)
    for name in PAGES:
        _capture_errors(page, errors, f"{name} desktop")
        _open(page, name)
        _assert_structure(page)
        _exercise_common(page)
        duration = page.locator(".switch-knob").first.evaluate(
            "element => parseFloat(getComputedStyle(element).transitionDuration)"
        )
        assert duration <= 0.001
        if name == "plan":
            page.locator("#plan-agenda-tab").click()
            choice = page.locator('[role="checkbox"]:visible').first
            choice.focus()
            before = choice.get_attribute("aria-checked")
            page.keyboard.press("Space")
            assert choice.get_attribute("aria-checked") != before
        if name == "finance":
            page.locator("[data-open-modal]:visible").first.click()
            page.locator("#starter-approve-import").click()
            assert page.locator("#import-receipt").is_visible()
            page.locator("#starter-undo-import").click()
            assert page.locator("#import-receipt").is_hidden()
        page.screenshot(path=str(OUTPUT / f"{name}-desktop.png"), full_page=True)
    context.close()


def _mobile(browser: Browser, errors: list[str]) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(10_000)
    for name in PAGES:
        _capture_errors(page, errors, f"{name} mobile")
        _open(page, name)
        _assert_structure(page)
        assert page.locator(".side-rail").evaluate(
            "element => getComputedStyle(element).overflowX === 'auto'"
        )
        page.locator("[data-state-trigger]").click()
        assert page.locator("#state-menu").is_visible()
        page.keyboard.press("Escape")
        assert page.locator("#state-menu").is_hidden()
        page.locator("[data-open-modal]:visible").first.click()
        assert page.locator("#starter-modal").is_visible()
        box = page.locator("#starter-modal .modal").bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391
        page.keyboard.press("Escape")
        page.screenshot(path=str(OUTPUT / f"{name}-mobile.png"), full_page=True)
    context.close()


def _zoom(browser: Browser, errors: list[str]) -> None:
    # Half the CSS viewport in each axis while retaining the original physical
    # pixel canvas. This exercises 200% browser-zoom reflow, not just HiDPI.
    context = browser.new_context(
        viewport={"width": 360, "height": 250},
        device_scale_factor=2,
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(10_000)
    for name in PAGES:
        _capture_errors(page, errors, f"{name} 200 percent zoom")
        _open(page, name)
        _assert_no_page_overflow(page)
        assert page.locator(".main-pane h1").is_visible()
    page.screenshot(path=str(OUTPUT / "finance-zoom-200.png"), full_page=True)
    context.close()


def run() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        _desktop(browser, errors)
        _mobile(browser, errors)
        _zoom(browser, errors)
        browser.close()
    if errors:
        raise AssertionError("browser errors:\n" + "\n".join(errors))
    print(
        "Phase 8 specialist starters passed desktop, mobile, keyboard, themes, states, "
        "custom controls, 200% zoom sizing, overflow, reduced motion, and console checks"
    )


if __name__ == "__main__":
    run()
