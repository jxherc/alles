"""Literal resting-control and universal-shell gate for every KOKUEN space.

This complements feature journeys. It measures every currently visible control
instead of asserting a few representative selectors, then opens and closes the
one universal shell by pointer and keyboard from every product space.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Page, sync_playwright

PORT = os.environ.get("PORT", "8146")
DATA = Path(os.environ["ALLES_DATA"]).resolve()
RUN_ID = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
REPEATS = int(os.environ.get("ALLES_CONTROL_REPEAT", "2"))
SPACE_FILTER = {
    item.strip() for item in os.environ.get("ALLES_CONTROL_SPACES", "").split(",") if item.strip()
}
BASE = f"http://127.0.0.1:{PORT}"

SPACES = (
    ("home", f"{BASE}/"),
    ("aide", f"http://aide.localhost:{PORT}/"),
    ("andromeda", f"http://andromeda.localhost:{PORT}/"),
    ("plan", f"http://plan.localhost:{PORT}/"),
    ("inbox", f"http://inbox.localhost:{PORT}/"),
    ("docs", f"http://docs.localhost:{PORT}/"),
    ("files", f"http://files.localhost:{PORT}/"),
    ("library", f"http://library.localhost:{PORT}/"),
    ("health", f"http://health.localhost:{PORT}/"),
    ("finance", f"http://finance.localhost:{PORT}/"),
    ("vault", f"http://passwords.localhost:{PORT}/"),
    ("server", f"http://server.localhost:{PORT}/"),
)

EXPECTED_DESTINATION_NAMES = (
    "home",
    "aide",
    "andromeda",
    "plan",
    "inbox",
    "docs",
    "files",
    "library",
    "health",
    "finance",
    "vault",
    "server",
)
EXPECTED_DESTINATION_VIEWS = (
    "today",
    "chat",
    "andromeda",
    "plan",
    "inbox",
    "wiki",
    "files",
    "library",
    "health",
    "finance",
    "vault",
    "system",
)

CONTROL_AUDIT = r"""
() => {
  const selector = [
    'button', 'a[href]', 'input:not([type="hidden"]):not([type="file"])',
    'textarea', 'summary', '.custom-select', '.s-switch',
    '[role="button"]', '[role="checkbox"]', '[role="combobox"]',
    '[role^="menuitem"]', '[role="option"]', '[role="radio"]',
    '[role="switch"]', '[role="tab"]', '[contenteditable="true"]',
  ].join(',');
  const visible = element => {
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return !element.hidden && element.getAttribute('aria-hidden') !== 'true'
      && box.width > 0 && box.height > 0
      && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const text = element => String(element?.textContent || '').replace(/\s+/g, ' ').trim();
  const name = element => {
    const labelled = String(element.getAttribute('aria-labelledby') || '')
      .split(/\s+/).filter(Boolean).map(id => text(document.getElementById(id))).join(' ').trim();
    return String(element.getAttribute('aria-label') || '').trim()
      || labelled
      || [...(element.labels || [])].map(text).join(' ').trim()
      || String(element.getAttribute('title') || '').trim()
      || text(element)
      || String(element.getAttribute('value') || '').trim()
      || String(element.getAttribute('placeholder') || '').trim();
  };
  const rows = [...new Set(document.querySelectorAll(selector))].filter(visible).map(element => {
    const box = element.getBoundingClientRect();
    return {
      id: element.id || '',
      tag: element.tagName.toLowerCase(),
      role: element.getAttribute('role') || '',
      primitive: element.dataset.kokuenPrimitive || '',
      name: name(element),
      width: Math.round(box.width * 10) / 10,
      height: Math.round(box.height * 10) / 10,
    };
  });
  return {
    count: rows.length,
    unnamed: rows.filter(row => !row.name),
    undersized: rows.filter(row => row.width < 43.5 || row.height < 43.5),
    undecorated: rows.filter(row => !row.primitive),
    nativeChoices: [...document.querySelectorAll('select,input[type="checkbox"],input[type="radio"]')]
      .filter(visible).map(element => element.id || element.outerHTML.slice(0, 100)),
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  };
}
"""


def _require_owned_data() -> None:
    if os.environ.get("ALLES_TEST_DATA", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the literal control gate")
    temp_root = Path(tempfile.gettempdir()).resolve()
    if DATA == temp_root or temp_root not in DATA.parents:
        raise RuntimeError("ALLES_DATA must be an owned child of the system temp directory")
    if len(RUN_ID) < 16 or (DATA / ".alles-test-owner").read_text("utf-8").strip() != RUN_ID:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this run")
    require_server_ownership(BASE, RUN_ID)


def _dismiss_setup(page: Page) -> None:
    response = page.request.post(f"{BASE}/api/setup/dismiss")
    assert response.ok, response.text()


def _assert_controls(page: Page, label: str) -> int:
    audit = page.evaluate(CONTROL_AUDIT)
    assert not audit["overflow"], f"{label}: horizontal overflow"
    assert not audit["nativeChoices"], f"{label}: native choices {audit['nativeChoices']}"
    assert not audit["undecorated"], f"{label}: undecorated controls {audit['undecorated']}"
    assert not audit["unnamed"], f"{label}: unnamed controls {audit['unnamed']}"
    assert not audit["undersized"], f"{label}: undersized controls {audit['undersized']}"
    return audit["count"]


def _assert_shell_cycle(page: Page, label: str, *, keyboard: bool) -> None:
    trigger = page.locator("#app-drawer-btn")
    assert trigger.count() == 1 and trigger.is_visible(), (
        f"{label}: missing universal shell at {page.url}; "
        f"body={(page.locator('body').inner_text() or '')[:240]!r}"
    )
    trigger.focus()
    if keyboard:
        trigger.press("Enter")
    else:
        trigger.click()
    drawer = page.locator("#app-drawer")
    drawer.wait_for(state="visible")
    destinations = drawer.locator(".app-drawer-item")
    assert destinations.count() == len(EXPECTED_DESTINATION_NAMES), label
    actual = destinations.evaluate_all("nodes => nodes.map(node => node.dataset.view || '')")
    names = destinations.locator("b").all_inner_texts()
    assert tuple(actual) == EXPECTED_DESTINATION_VIEWS, (label, actual)
    assert tuple(names) == EXPECTED_DESTINATION_NAMES, (label, names)
    assert _assert_controls(page, f"{label} shell") >= len(EXPECTED_DESTINATION_NAMES)
    page.keyboard.press("Escape")
    drawer.wait_for(state="hidden")
    assert trigger.evaluate("node => document.activeElement === node"), (
        f"{label}: focus not returned"
    )


def _audit_visible_tabs(page: Page, label: str, counts: dict[str, int]) -> None:
    """Open every visible application tab and audit the populated panel it owns."""
    tabs = page.locator("main [role='tab']:visible")
    tab_names = tabs.evaluate_all(
        "nodes => nodes.map(node => (node.getAttribute('aria-label') || node.textContent || '').trim())"
    )
    for index, tab_name in enumerate(tab_names):
        current = page.locator("main [role='tab']:visible").nth(index)
        current.click()
        page.wait_for_load_state("domcontentloaded")
        page.locator("#app-drawer-btn").wait_for(state="visible")
        page.wait_for_timeout(350)
        tab_label = f"{label} tab {tab_name or index + 1}"
        counts[tab_label] = _assert_controls(page, tab_label)


def run() -> None:
    _require_owned_data()
    errors: list[str] = []
    counts: dict[str, int] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height, viewport in ((1440, 1000, "desktop"), (390, 844, "phone")):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(10_000)
            page.on("pageerror", lambda error: errors.append(f"{page.url}: {error}"))
            page.on(
                "console",
                lambda message: (
                    errors.append(f"{page.url}: {message.text}")
                    if message.type == "error"
                    else None
                ),
            )
            _dismiss_setup(page)
            for space, url in SPACES:
                if SPACE_FILTER and space not in SPACE_FILTER:
                    continue
                page.goto(url, wait_until="domcontentloaded")
                page.locator("#app-drawer-btn").wait_for(state="visible")
                label = f"{viewport} {space}"
                counts[label] = _assert_controls(page, label)
                _audit_visible_tabs(page, label, counts)
                for repeat in range(REPEATS):
                    _assert_shell_cycle(page, f"{label} pointer {repeat + 1}", keyboard=False)
                    _assert_shell_cycle(page, f"{label} keyboard {repeat + 1}", keyboard=True)
            context.close()
        browser.close()
    if errors:
        raise AssertionError("literal resting-control browser errors:\n" + "\n".join(errors))
    print(
        f"literal resting-control gate passed: {len(counts)} surfaces, {sum(counts.values())} visible controls"
    )


if __name__ == "__main__":
    run()
