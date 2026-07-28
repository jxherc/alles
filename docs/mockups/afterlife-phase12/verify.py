#!/usr/bin/env python3
"""Rendered behavior checks for the isolated Phase 12 approval starters."""

from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8769"
APPS = [
    "plan",
    "inbox",
    "docs",
    "files",
    "library",
    "health",
    "finance",
    "vault",
    "server",
]


def no_horizontal_page_overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def click_each_button(page, url, selector="button:visible"):
    """Use a real pointer on every button visible in the requested starting view."""
    page.goto(url)
    page.reload()
    count = page.locator(selector).count()
    for index in range(count):
        page.goto(url)
        page.reload()
        buttons = page.locator(selector)
        assert buttons.count() == count, (url, index, count, buttons.count())
        button = buttons.nth(index)
        button.evaluate("element => element.scrollIntoView({block: 'center'})")
        button.click()


def run() -> None:
    errors = []
    with TemporaryDirectory(prefix="alles-phase12-") as shots, sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.on(
            "console",
            lambda message: (
                errors.append(f"console: {message.text}") if message.type == "error" else None
            ),
        )
        page.on("pageerror", lambda error: errors.append(f"page: {error}"))

        page.goto(f"{BASE}/workbenches.html#apps")
        assert page.locator("[data-open-app]").count() == len(APPS)
        assert page.locator("[data-open-app] .app-entry-name").all_inner_texts() == APPS
        assert page.locator("select, input[type=checkbox], input[type=radio]").count() == 0
        home_links = page.locator(".home-action")
        assert home_links.count() == len(APPS) + 1
        assert all(
            home_links.nth(index).get_attribute("href") == "../afterlife-navigation/home.html"
            for index in range(home_links.count())
        )
        for app in APPS:
            page.goto(f"{BASE}/workbenches.html#{app}")
            assert page.locator(f'[data-workbench="{app}"]').is_visible()
            assert page.locator(f'[data-workbench="{app}"] .app-name').inner_text() == app
            assert no_horizontal_page_overflow(page)

        page.goto(f"{BASE}/workbenches.html#apps")
        page.locator('[data-open-app="plan"]').click()
        assert page.url.endswith("#plan")
        page.go_back()
        assert page.url.endswith("#apps")
        page.locator("[data-theme-toggle]").click()
        assert page.locator("html").get_attribute("data-theme") == "light"

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{BASE}/workbenches.html#files")
        page.locator('[data-workbench="files"] .photo').first.click()
        assert (
            page.locator('[data-workbench="files"] .workbench-body').get_attribute(
                "data-mobile-pane"
            )
            == "detail"
        )
        assert page.locator('[data-workbench="files"] .detail-pane .mobile-back').is_visible()
        page.locator('[data-workbench="files"] .detail-pane .mobile-back').click()
        assert (
            page.locator('[data-workbench="files"] .workbench-body').get_attribute(
                "data-mobile-pane"
            )
            == "main"
        )
        page.locator('[data-workbench="files"] .photo').first.click()
        page.go_back()
        assert (
            page.locator('[data-workbench="files"] .workbench-body').get_attribute(
                "data-mobile-pane"
            )
            == "main"
        )
        assert no_horizontal_page_overflow(page)
        page.screenshot(path=str(Path(shots) / "files-phone.png"), full_page=True)

        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{BASE}/andromeda.html#idle")
        visible_searches = page.locator('form[role="search"]:visible').count()
        assert visible_searches == 1
        page.locator("#idle-query").fill("latest sqlite stable release")
        page.locator(".idle-form button[type=submit]").click()
        assert page.url.endswith("#results")
        assert page.locator(".result").count() == 4
        assert page.locator(".answer-block").is_visible()
        assert page.locator(".search-shell .app-name").count() == 0
        search_box = page.locator(".identity-context .andromeda-form").bounding_box()
        results_box = page.locator(".search-main").bounding_box()
        assert search_box and results_box
        assert abs(search_box["x"] - results_box["x"]) <= 1
        assert abs(search_box["width"] - results_box["width"]) <= 1
        home_box = page.locator(".search-shell .home-action").bounding_box()
        assert home_box
        assert 20 <= 1280 - home_box["x"] - home_box["width"] <= 28
        page.locator('[data-verification="corrected"]').click()
        assert (
            page.locator("[data-verification-state]").get_attribute("data-verdict") == "corrected"
        )
        page.locator('[data-demo-state="partial"]').click()
        assert page.locator('[data-state-only="partial"]').is_visible()
        assert page.locator(".answer-block").is_visible()
        assert page.locator(".answer-highlight").inner_text() == "3.50.4"
        assert page.locator("#web-results-title").is_visible()
        assert page.locator(".results").is_visible()
        assert page.locator(".result").evaluate_all(
            "nodes => nodes.every(node => getComputedStyle(node).borderBottomWidth === '0px')"
        )
        answer_box = page.locator(".answer-block").bounding_box()
        web_results_box = page.locator(".web-results-region").bounding_box()
        assert answer_box and web_results_box
        assert web_results_box["y"] - (answer_box["y"] + answer_box["height"]) >= 39
        assert (
            page.locator(".web-results-region").evaluate(
                "element => getComputedStyle(element).borderTopStyle"
            )
            == "solid"
        )
        page.locator('[data-demo-state="loading"]').click()
        assert page.locator('[data-state-only="loading"]').is_visible()
        assert page.locator(".results").is_visible()
        page.locator('[data-demo-state="long"]').click()
        assert page.locator('[data-state-only="long"]').is_visible()
        assert no_horizontal_page_overflow(page)
        page.screenshot(path=str(Path(shots) / "andromeda-results.png"), full_page=True)

        page.goto(f"{BASE}/server.html#overview")
        assert page.locator(".server-neofetch").is_visible()
        assert "KMMMMMMMMMMNWMMMMMMMMMM0" in page.locator(".server-neofetch-mark").inner_text()
        assert (
            page.locator(".server-terminal-monitor").get_attribute("data-runtime-renderer")
            == "static/js/system.js"
        )
        assert page.locator(".server-btop").is_visible()
        assert page.locator(".server-monitor-box").count() == 4
        process_box = page.locator(".server-monitor-processes").bounding_box()
        btop_box = page.locator(".server-btop").bounding_box()
        assert process_box and btop_box
        assert abs(process_box["width"] - btop_box["width"]) <= 1
        assert page.locator(".server-monitor-processes .monitor-process-row").count() >= 6
        assert page.locator(".server-monitor-processes .monitor-process-row").first.locator(
            "span"
        ).all_inner_texts() == ["pid", "program", "thr", "user", "mem", "cpu%"]
        page.locator('.local-panel [data-open-server-page="search-models"]').click()
        selected_mode = page.locator('[aria-label="Verification mode"] [aria-checked="true"]')
        selected_mode.press("ArrowDown")
        assert (
            page.locator('[aria-label="Verification mode"] [aria-checked="true"]').get_attribute(
                "data-value"
            )
            == "always"
        )
        verifier_switch = page.locator('[role="switch"][aria-label="Background fact-check"]')
        verifier_switch.click()
        assert verifier_switch.get_attribute("aria-checked") == "false"

        page.locator('.local-panel [data-open-server-page="access-policy"]').click()
        page.locator('[data-demo-state="permission"]').click()
        assert page.locator('[data-state-only="permission"]').is_visible()
        page.locator('[aria-label="Server control mode"] [data-value="allowlisted_host"]').click()
        assert (
            '"control_mode": "allowlisted_host"'
            in page.locator("[data-policy-editor]").input_value()
        )
        page.locator("[data-validate-policy]").click()
        assert "1 exact host service" in page.locator("[data-policy-status]").inner_text()
        page.locator("[data-save-policy]").click()
        assert page.locator("[data-policy-dialog]").is_visible()
        page.locator("[data-confirm-field]").fill("allow services")
        page.locator("[data-confirm-policy]").click()
        assert page.locator("[data-confirm-error]").is_visible()
        page.locator("[data-confirm-field]").fill("allow host services")
        page.locator("[data-confirm-policy]").click()
        assert page.locator("[data-policy-dialog]").is_hidden()
        assert page.locator("[data-save-policy]").evaluate("el => el === document.activeElement")
        assert "audit recorded" in page.locator("[data-policy-status]").inner_text()
        assert "audit recorded" in page.locator("[data-live]").inner_text()
        page.locator("[data-save-policy]").click()
        page.locator("[data-close-dialog]").click()
        assert page.locator("[data-policy-dialog]").is_hidden()
        page.locator('.local-panel [data-open-server-page="logs"]').click()
        page.locator('[data-demo-state="long"]').click()
        assert page.locator('[data-state-only="long"]').is_visible()
        assert no_horizontal_page_overflow(page)
        page.screenshot(path=str(Path(shots) / "server-policy.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{BASE}/server.html#overview")
        page.locator(".server-page:visible [data-server-nav]").click()
        assert page.locator(".server-body").get_attribute("data-mobile-pane") == "nav"
        page.locator('.local-panel [data-open-server-page="search-models"]').click()
        assert page.locator(".server-body").get_attribute("data-mobile-pane") == "main"
        assert no_horizontal_page_overflow(page)

        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{BASE}/andromeda.html#results")
        page.evaluate("document.documentElement.style.zoom = '2'")
        assert no_horizontal_page_overflow(page)

        reduced = browser.new_context(
            viewport={"width": 760, "height": 800}, reduced_motion="reduce"
        )
        reduced_page = reduced.new_page()
        reduced_page.goto(f"{BASE}/workbenches.html#apps")
        reduced_page.locator('[data-open-app="docs"]').click()
        assert reduced_page.url.endswith("#docs")
        assert reduced_page.evaluate("document.getAnimations().length") == 0
        assert no_horizontal_page_overflow(reduced_page)
        reduced.close()

        page.set_viewport_size({"width": 1280, "height": 720})
        click_each_button(page, f"{BASE}/workbenches.html#apps")
        for app in APPS:
            click_each_button(
                page,
                f"{BASE}/workbenches.html#{app}",
                f'[data-workbench="{app}"] button:visible, .preview-tools button:visible',
            )
        click_each_button(page, f"{BASE}/andromeda.html#idle")
        click_each_button(page, f"{BASE}/andromeda.html#results")
        for server_page in [
            "overview",
            "services",
            "search-models",
            "backups",
            "updates",
            "logs",
            "access-policy",
        ]:
            click_each_button(
                page,
                f"{BASE}/server.html#{server_page}",
                ".identity-actions button:visible, .local-panel button:visible, "
                ".server-page:visible button:visible, .preview-tools button:visible",
            )

        context.close()
        browser.close()

    assert not errors, "\n".join(errors)
    print("phase 12 starters: rendered behavior checks passed")
    print("desktop 1280x720, compact 760x800, phone 390x844, 200% zoom, reduced motion")


if __name__ == "__main__":
    run()
