"""Real-browser Phase 10 responsiveness budgets against throwaway Alles data."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("PHASE10_BASE", "http://127.0.0.1:8974")
LANGUAGES = ("en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar")


def _require_throwaway_data_root() -> None:
    data = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or len(run_id) < 16:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    try:
        owner = (data / ".alles-test-owner").read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, run_id)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def run() -> None:
    _require_throwaway_data_root()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.request.post(f"{BASE}/api/setup/dismiss")
        page.request.patch(f"{BASE}/api/settings", data={"language": "en"})

        boot_samples = []
        for _ in range(3):
            started = time.perf_counter()
            page.goto(BASE, wait_until="networkidle")
            expect(page.locator("#today-view")).to_be_visible()
            boot_samples.append((time.perf_counter() - started) * 1_000)

        navigation_samples = []
        for view, selector in (
            ("tasks", "#tasks-view"),
            ("calendar", "#calendar-view"),
            ("andromeda", "#andromeda-view"),
            ("today", "#today-view"),
        ) * 5:
            started = time.perf_counter()
            page.evaluate("view => window._navigateTo(view)", view)
            expect(page.locator(selector)).to_be_visible()
            navigation_samples.append((time.perf_counter() - started) * 1_000)

        localization_samples = []
        for language in LANGUAGES:
            result = page.evaluate(
                """async language => {
                  const started = performance.now();
                  const response = await fetch('/api/settings', {
                    method: 'PATCH',
                    headers: {'content-type': 'application/json'},
                    body: JSON.stringify({language}),
                  });
                  if (!response.ok) throw new Error(`locale save failed: ${response.status}`);
                  const settings = await response.json();
                  const {prepareLocalization} = await import('/static/js/i18n.js');
                  await prepareLocalization(settings);
                  return {elapsed: performance.now() - started, lang: document.documentElement.lang};
                }""",
                language,
            )
            assert result["lang"].lower().startswith(language.lower()), result
            localization_samples.append(float(result["elapsed"]))

        page.evaluate("window._navigateTo('today')")
        started = time.perf_counter()
        page.locator("#today-settings").click()
        expect(page.locator("#settings-modal")).to_be_visible()
        page.locator('.s-nav-item[data-pane="credits"]').click()
        expect(page.locator("#credits-settings-workbench")).to_have_attribute("aria-busy", "false")
        expect(page.locator("#credits-list .credits-row").first).to_be_visible()
        credits_ms = (time.perf_counter() - started) * 1_000

        metrics = {
            "coldish_boot_p95_ms": round(_p95(boot_samples), 2),
            "in_app_navigation_p95_ms": round(_p95(navigation_samples), 2),
            "locale_apply_p95_ms": round(_p95(localization_samples), 2),
            "credits_first_open_ms": round(credits_ms, 2),
        }
        budgets = {
            "coldish_boot_p95_ms": 6_000.0,
            "in_app_navigation_p95_ms": 500.0,
            "locale_apply_p95_ms": 1_000.0,
            "credits_first_open_ms": 2_000.0,
        }
        for name, budget in budgets.items():
            assert metrics[name] < budget, f"{name}: {metrics[name]} >= {budget}"
        print("Phase 10 browser performance budgets passed", json.dumps(metrics, sort_keys=True))
        context.close()
        browser.close()


if __name__ == "__main__":
    run()
