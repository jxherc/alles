"""Browser gate for every finished surface using the shared KOKUEN runtime.

Run against an isolated server, for example:

    test_root="$(python3 -c 'import tempfile; print(tempfile.mkdtemp(prefix="alles-kokuen-"))')"
    test_run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    printf '%s\n' "$test_run_id" > "$test_root/.alles-test-owner"
    ALLES_DATA="$test_root" ALLES_TEST_DATA=1 ALLES_TEST_RUN_ID="$test_run_id" \
      PORT=8137 AUTH_ENABLED=false python3 app.py
    ALLES_DATA="$test_root" ALLES_TEST_DATA=1 ALLES_TEST_RUN_ID="$test_run_id" \
      PORT=8137 python3 tests/pw_kokuen_finished_surfaces.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

PORT = os.environ.get("PORT", "8137")
DATA = Path(os.environ["ALLES_DATA"]).resolve()
OUTPUT = Path(os.environ.get("KOKUEN_SCREENSHOTS", "/tmp/alles-kokuen-finished"))
LIGHT_APPEARANCE = """
localStorage.setItem('alles-appearance', JSON.stringify({
  preset: 'light',
  colors: {
    bg: '#f5f4f1', text: '#111111', panel: '#efede9',
    faint: '#d4d2ce', accent: '#737bd9'
  },
  font: 'sans', density: 'comfortable', bgPattern: 'none', frosted: false
}));
"""


def _require_throwaway_data_root() -> None:
    sentinel = os.environ.get("ALLES_TEST_DATA", "").strip().lower()
    if sentinel not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the isolated KOKUEN browser gate")
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        relative = DATA.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError("ALLES_DATA must be inside the system temporary directory") from exc
    if not relative.parts:
        raise RuntimeError("ALLES_DATA cannot be the system temporary directory itself")
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if len(run_id) < 16:
        raise RuntimeError("set a unique ALLES_TEST_RUN_ID for this browser run")
    owner_file = DATA / ".alles-test-owner"
    try:
        owner = owner_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this browser run")
    require_server_ownership(f"http://127.0.0.1:{PORT}/", run_id)


def _assert_no_overflow(page: Page) -> None:
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def _record_errors(page: Page, errors: list[str], label: str) -> None:
    page.on("pageerror", lambda error: errors.append(f"{label} page: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"{label} console: {message.text}") if message.type == "error" else None
        ),
    )


def _dismiss_setup_if_needed(page: Page) -> None:
    setup = page.evaluate(
        "fetch('/api/setup/status').then(response => response.json()).then(data => data.setup)"
    )
    if setup.get("completed") or setup.get("dismissed"):
        return
    page.locator("#setup-wizard").wait_for(state="visible")
    page.locator("#setup-skip").click()
    page.locator("#setup-wizard").wait_for(state="hidden")
    page.wait_for_function(
        "fetch('/api/setup/status').then(response => response.json()).then(data => data.setup.dismissed)"
    )


def _new_context(
    browser: Browser,
    width: int,
    height: int,
    *,
    light: bool = False,
    reduced_motion: str = "no-preference",
) -> BrowserContext:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        reduced_motion=reduced_motion,
        service_workers="block",
    )
    if light:
        context.add_init_script(LIGHT_APPEARANCE)
    return context


def _open_files(page: Page) -> None:
    page.goto(f"http://files.localhost:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_selector("#files-view:visible")
    page.wait_for_selector(
        '#files-list .file-row[data-path="project notes.txt"] .file-name-button',
        state="attached",
    )
    page.wait_for_function("document.querySelectorAll('#files-list .file-row').length >= 2")
    assert page.locator("body").get_attribute("data-app") == "files"


def _files_desktop(browser: Browser, errors: list[str]) -> None:
    context = _new_context(browser, 1440, 1000)
    page = context.new_page()
    page.set_default_timeout(8_000)
    _record_errors(page, errors, "files desktop")
    _open_files(page)

    assert page.locator("#files-view select:visible").count() == 0
    assert (
        page.locator(
            '#files-view input[type="checkbox"]:visible, #files-view input[type="radio"]:visible'
        ).count()
        == 0
    )
    assert (
        page.locator("#files-search").evaluate(
            "el => Math.round(el.getBoundingClientRect().height)"
        )
        == 36
    )
    assert page.locator(".main > .topbar").evaluate("el => getComputedStyle(el).display === 'none'")
    assert (
        page.locator("#files-app-header").evaluate(
            "el => Math.round(el.getBoundingClientRect().height)"
        )
        >= 52
    )
    assert page.locator("#files-list .file-row").first.evaluate(
        "el => el.getBoundingClientRect().height >= 44"
    )
    assert page.locator("body").evaluate(
        "el => getComputedStyle(el).fontFamily.includes('-apple-system')"
    )

    search = page.locator("#files-search")
    search.focus()
    assert search.evaluate(
        "el => getComputedStyle(el).borderColor !== getComputedStyle(document.body).getPropertyValue('--faint').trim()"
    )
    row = page.locator("#files-list .file-row").first
    resting = row.evaluate("el => getComputedStyle(el).backgroundColor")
    row.hover()
    page.wait_for_timeout(160)
    assert row.evaluate("el => getComputedStyle(el).backgroundColor") != resting
    page.mouse.move(0, 0)
    action = row.locator(".file-name-button")
    action.focus()
    assert action.evaluate(
        "el => document.activeElement === el && getComputedStyle(el).outlineStyle !== 'none'"
    )
    _assert_no_overflow(page)
    page.screenshot(path=str(OUTPUT / "files-desktop.png"), full_page=True)
    context.close()


def _files_light(browser: Browser, errors: list[str]) -> None:
    context = _new_context(browser, 1280, 900, light=True)
    page = context.new_page()
    page.set_default_timeout(8_000)
    _record_errors(page, errors, "files light")
    _open_files(page)
    assert page.locator("html").get_attribute("data-theme") == "light"
    assert page.locator("body").evaluate(
        "el => getComputedStyle(el).backgroundColor !== 'rgb(9, 9, 9)'"
    )
    assert page.locator("#files-view .file-name-button").first.evaluate(
        "el => getComputedStyle(el).color !== getComputedStyle(document.body).backgroundColor"
    )
    _assert_no_overflow(page)
    page.screenshot(path=str(OUTPUT / "files-light.png"), full_page=True)
    context.close()


def _files_mobile(browser: Browser, errors: list[str]) -> None:
    context = _new_context(browser, 390, 844)
    page = context.new_page()
    page.set_default_timeout(8_000)
    _record_errors(page, errors, "files mobile")
    _open_files(page)
    search_height = page.locator("#files-search").evaluate(
        "el => el.getBoundingClientRect().height"
    )
    assert search_height >= 43.5, search_height
    assert page.locator("#files-search").evaluate("el => el.getBoundingClientRect().width >= 120")
    assert page.locator("#files-view .files-phase7-actions .files-text-button").first.evaluate(
        "el => el.getBoundingClientRect().height >= 44"
    )
    assert page.locator("#files-list .file-row").first.evaluate(
        "el => el.getBoundingClientRect().height >= 44"
    )
    check = page.locator("#files-list .file-row [data-file-select]").first
    assert check.evaluate(
        "el => el.getBoundingClientRect().width >= 44 && el.getBoundingClientRect().height >= 44"
    )
    assert check.get_attribute("role") == "checkbox"
    assert check.get_attribute("aria-checked") == "false"
    file_name = page.locator(
        '#files-list .file-row[data-path="project notes.txt"] .file-name-button'
    )
    name_box = file_name.bounding_box()
    assert file_name.is_visible() and name_box and name_box["width"] >= 60, {
        "visible": file_name.is_visible(),
        "box": name_box,
        "text": file_name.text_content(),
    }
    _assert_no_overflow(page)
    page.screenshot(path=str(OUTPUT / "files-mobile.png"), full_page=True)
    context.close()


def _files_reduced_motion(browser: Browser, errors: list[str]) -> None:
    context = _new_context(browser, 1024, 768, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(8_000)
    _record_errors(page, errors, "files reduced motion")
    _open_files(page)
    duration = page.locator("#files-list .file-row").first.evaluate(
        "el => parseFloat(getComputedStyle(el).transitionDuration)"
    )
    assert duration <= 0.001
    context.close()


def _aide_smoke(browser: Browser, errors: list[str]) -> None:
    context = _new_context(browser, 1440, 1000)
    page = context.new_page()
    page.set_default_timeout(10_000)
    _record_errors(page, errors, "aide")
    page.goto(f"http://aide.localhost:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_selector("#composer-ta:visible")
    assert page.locator("body").get_attribute("data-space") == "aide"
    assert page.locator("body").evaluate(
        "el => getComputedStyle(el).getPropertyValue('--k-page').trim().length > 0"
    )
    assert page.locator(".sidebar-brand").evaluate(
        "el => getComputedStyle(el).fontWeight === '400'"
    )
    assert page.locator(".composer-box").evaluate("el => getComputedStyle(el).boxShadow === 'none'")
    page.locator("#perm-mode-btn").click()
    page.locator('#perm-menu [data-v="full_access"]').click()
    permission_style = page.locator("#perm-mode-btn").evaluate(
        """el => {
          const probe = document.createElement('span');
          probe.style.color = 'var(--k-permission)';
          el.appendChild(probe);
          const value = {
            color: getComputedStyle(el).color,
            expected: getComputedStyle(probe).color,
            className: el.className,
            label: el.textContent.trim()
          };
          probe.remove();
          return value;
        }"""
    )
    assert permission_style["label"] == "full access", permission_style
    assert "perm-full" in permission_style["className"], permission_style
    assert permission_style["color"] == permission_style["expected"], permission_style
    tools = page.locator(".aide-tools-link")
    if tools.is_visible():
        tools.click()
        page.wait_for_selector(".aide-sidebar-menu:not([hidden])")
        assert page.locator(".aide-sidebar-menu").evaluate(
            "el => getComputedStyle(el).boxShadow === 'none'"
        )
    _assert_no_overflow(page)
    page.screenshot(path=str(OUTPUT / "aide-desktop.png"), full_page=True)

    tool_headers = []
    for view, root_id, state_root_id in (
        ("scheduled", "aide-scheduled-view", "aide-scheduled-view"),
        ("brain", "brain-view", "brain-view"),
        ("skills", "skills-view", "skills-view"),
        ("aide-reminders", "reminders-view", "reminders-view"),
    ):
        page.evaluate("view => window._navigateTo(view)", view)
        root = page.locator(f"#{root_id}")
        root.wait_for(state="visible")
        try:
            page.wait_for_function(
                "rootId => document.getElementById(rootId)?.getAttribute('aria-busy') === 'false'",
                arg=state_root_id,
                timeout=10_000,
            )
        except PlaywrightTimeoutError as exc:
            state = page.locator(f"#{state_root_id}").evaluate(
                "el => ({ busy: el.getAttribute('aria-busy'), run: el.dataset.specialistRun, state: el.querySelector(':scope > .specialist-state')?.dataset.state })"
            )
            raise AssertionError((view, root_id, state_root_id, state, errors)) from exc
        assert root.get_attribute("data-kokuen-surface") == "aide-tool"
        header = root.locator(":scope > .aide-tool-head")
        metrics = header.evaluate(
            """el => ({
              x: Math.round(el.getBoundingClientRect().x),
              width: Math.round(el.getBoundingClientRect().width),
              paddingTop: Math.round(parseFloat(getComputedStyle(el).paddingTop)),
              paddingBottom: Math.round(parseFloat(getComputedStyle(el).paddingBottom)),
            })"""
        )
        assert metrics["paddingTop"] == 48, (view, metrics)
        assert metrics["paddingBottom"] == 32, (view, metrics)
        title = header.locator(".page-view-title, h1").first
        title_weight = title.evaluate("el => getComputedStyle(el).fontWeight")
        assert title_weight == "500", (view, title_weight)
        # Reminders is owned and laid out by the Stage 8 Plan workbench. The
        # other three remain direct Aide tools and share one outer header grid.
        if view != "aide-reminders":
            tool_headers.append((view, metrics))
        _assert_no_overflow(page)
        page.screenshot(path=str(OUTPUT / f"aide-{view}.png"), full_page=True)

    assert (
        max(item[1]["x"] for item in tool_headers) - min(item[1]["x"] for item in tool_headers) <= 1
    ), tool_headers
    assert (
        max(item[1]["width"] for item in tool_headers)
        - min(item[1]["width"] for item in tool_headers)
        <= 1
    ), tool_headers
    context.close()


def _aide_mobile(browser: Browser, errors: list[str]) -> None:
    context = _new_context(browser, 390, 844, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(10_000)
    _record_errors(page, errors, "aide mobile")
    page.goto(f"http://aide.localhost:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_selector("#composer-ta:visible")
    assert page.locator("body").evaluate("el => el.classList.contains('sidebar-hidden')")
    assert page.locator(".sidebar").is_hidden()
    composer = page.locator(".composer-box")
    composer_box = composer.bounding_box()
    assert composer_box and composer_box["x"] >= 0
    assert composer_box["x"] + composer_box["width"] <= 390.5
    assert page.locator("#composer-ta").evaluate(
        "el => parseFloat(getComputedStyle(el).fontSize) >= 16"
    )
    page.locator("#sidebar-toggle-btn").click()
    assert page.locator(".sidebar").is_visible()
    assert page.locator("#nav-backdrop").is_visible()
    page.locator("#nav-backdrop").click(position={"x": 370, "y": 400})
    assert page.locator(".sidebar").is_hidden()
    _assert_no_overflow(page)
    page.screenshot(path=str(OUTPUT / "aide-mobile.png"), full_page=True)

    for view, root_id, state_root_id in (
        ("scheduled", "aide-scheduled-view", "aide-scheduled-view"),
        ("brain", "brain-view", "brain-view"),
        ("skills", "skills-view", "skills-view"),
        ("aide-reminders", "reminders-view", "reminders-view"),
    ):
        page.evaluate("view => window._navigateTo(view)", view)
        root = page.locator(f"#{root_id}")
        root.wait_for(state="visible")
        page.wait_for_function(
            "rootId => document.getElementById(rootId)?.getAttribute('aria-busy') === 'false'",
            arg=state_root_id,
            timeout=10_000,
        )
        assert root.get_attribute("data-kokuen-surface") == "aide-tool"
        if view == "aide-reminders":
            form = root.locator(".reminder-add-form")
            text_field = root.locator("#reminder-text")
            time_field = root.locator("#reminder-time")
            kind_field = root.locator("#reminder-type-select")
            set_button = root.locator("#reminder-add-btn")
            form_box = form.bounding_box()
            text_box = text_field.bounding_box()
            time_box = time_field.bounding_box()
            kind_box = kind_field.bounding_box()
            set_box = set_button.bounding_box()
            assert all((form_box, text_box, time_box, kind_box, set_box))
            layout = {
                "form": form_box,
                "text": text_box,
                "time": time_box,
                "kind": kind_box,
                "set": set_box,
            }
            assert text_box["width"] >= form_box["width"] - 1, layout
            assert time_box["width"] >= form_box["width"] - 1, layout
            assert kind_box["x"] + kind_box["width"] <= set_box["x"] + 0.5, layout
        _assert_no_overflow(page)
        page.screenshot(path=str(OUTPUT / f"aide-{view}-mobile.png"), full_page=True)
    context.close()


def _home_and_apps(browser: Browser, errors: list[str]) -> None:
    for width, height, label in ((1440, 1000, "desktop"), (390, 844, "mobile")):
        context = _new_context(browser, width, height, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(10_000)
        _record_errors(page, errors, f"home/apps {label}")
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
        page.wait_for_selector("#today-view:visible")
        _dismiss_setup_if_needed(page)
        home = page.locator("#today-view")
        assert home.get_attribute("data-kokuen-surface") == "home"
        assert (
            page.locator(".today-topbar").evaluate(
                "el => Math.round(el.getBoundingClientRect().height)"
            )
            == 52
        )
        assert page.locator("#today-settings").inner_text().strip() == "settings"
        assert page.locator("#today-view select:visible").count() == 0
        _assert_no_overflow(page)
        page.screenshot(path=str(OUTPUT / f"home-{label}.png"), full_page=True)

        shell_trigger = page.locator("#app-drawer-btn")
        assert shell_trigger.is_visible()
        assert shell_trigger.get_attribute("aria-expanded") == "false"
        shell_trigger.click()
        drawer = page.locator("#app-drawer")
        drawer.wait_for(state="visible")
        assert drawer.get_attribute("data-kokuen-surface") == "apps"
        assert shell_trigger.get_attribute("aria-expanded") == "true"
        assert page.locator("#app-drawer-close").evaluate("el => document.activeElement === el")
        assert page.locator(".main").get_attribute("inert") is not None
        assert page.locator("#app-drawer-close").evaluate(
            "el => el.getBoundingClientRect().height >= 44"
        )
        assert page.locator(".app-drawer-item").first.evaluate(
            "el => el.getBoundingClientRect().height >= 44"
        )
        assert page.locator(".app-drawer-group").count() == 4
        assert page.locator(".app-drawer-item").count() == 12
        assert page.locator(".app-drawer-group").first.locator(".app-drawer-item").count() == 3
        assert page.locator("#app-drawer select:visible").count() == 0
        _assert_no_overflow(page)
        page.screenshot(path=str(OUTPUT / f"apps-{label}.png"), full_page=True)
        page.locator("#app-drawer-close").click()
        assert drawer.is_hidden()
        assert shell_trigger.evaluate("el => document.activeElement === el")
        assert page.locator(".main").get_attribute("inert") is None
        context.close()


def _universal_command(browser: Browser, errors: list[str]) -> None:
    def search_fixture(route) -> None:
        if "q=offline" in route.request.url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body="",
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"notes":[{"name":"project plan.md","path":"project plan.md",'
                '"snippet":"release checklist"}],"tasks":[{"title":"plan review",'
                '"done":false}]}'
            ),
        )

    context = _new_context(browser, 1440, 1000, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(10_000)
    _record_errors(page, errors, "universal command desktop")
    page.route("**/api/search?*", search_fixture)
    page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_selector("#today-view:visible")
    _dismiss_setup_if_needed(page)

    opener = page.locator("#today-settings")
    opener.focus()
    page.keyboard.press("Control+K")
    modal = page.locator("#search-modal")
    search = page.locator("#search-input")
    results = page.locator("#search-results")
    modal.wait_for(state="visible")
    assert modal.get_attribute("role") == "dialog"
    assert modal.get_attribute("aria-modal") == "true"
    assert modal.get_attribute("aria-labelledby") == "search-dialog-title"
    assert search.get_attribute("role") == "combobox"
    assert search.get_attribute("aria-controls") == "search-results"
    assert results.get_attribute("role") == "listbox"
    assert search.evaluate("el => document.activeElement === el")
    assert modal.evaluate(
        "el => getComputedStyle(el).getPropertyValue('--ui-space-8').trim() === '64px'"
    )
    assert modal.evaluate("el => getComputedStyle(el).animationName === 'none'")
    assert modal.locator("select:visible").count() == 0
    assert (
        modal.locator(
            'input[type="checkbox"]:visible, input[type="radio"]:visible'
        ).count()
        == 0
    )

    search.fill("plan")
    page.wait_for_function(
        "document.querySelectorAll('#search-results [role=\"option\"]').length >= 4"
    )
    options = results.locator('[role="option"]')
    assert options.count() >= 4
    assert results.locator('[role="option"][aria-selected="true"]').count() == 1
    initial_id = search.get_attribute("aria-activedescendant")
    assert initial_id == options.first.get_attribute("id")
    options.nth(1).hover()
    assert search.get_attribute("aria-activedescendant") == options.nth(1).get_attribute("id")
    page.keyboard.press("Home")
    page.keyboard.press("ArrowDown")
    assert search.get_attribute("aria-activedescendant") != initial_id
    page.keyboard.press("End")
    assert search.get_attribute("aria-activedescendant") == options.last.get_attribute("id")
    page.keyboard.press("Home")
    assert search.get_attribute("aria-activedescendant") == options.first.get_attribute("id")
    page.screenshot(path=str(OUTPUT / "universal-command-desktop.png"), full_page=True)

    page.keyboard.press("Shift+Tab")
    assert page.locator("#search-close").evaluate("el => document.activeElement === el")
    page.keyboard.press("Tab")
    assert search.evaluate("el => document.activeElement === el")
    page.keyboard.press("Escape")
    modal.wait_for(state="hidden")
    focus_state = page.evaluate(
        "() => ({ active: document.activeElement?.id, openerVisible: !!document.querySelector('#today-settings')?.offsetParent })"
    )
    assert focus_state["active"] == "today-settings", focus_state

    page.keyboard.press("Control+K")
    search.fill("offline")
    page.wait_for_selector("#search-results .search-state--error")
    assert "failed" in results.locator(".search-state--error").inner_text()
    assert results.locator('[role="option"]').count() == 2
    page.locator("#search-close").click()
    focus_state = page.evaluate(
        "() => ({ active: document.activeElement?.id, openerVisible: !!document.querySelector('#today-settings')?.offsetParent })"
    )
    assert focus_state["active"] == "today-settings", focus_state

    page.keyboard.press("Control+K")
    search.fill("plan")
    page.wait_for_function(
        "document.querySelectorAll('#search-results [role=\"option\"]').length >= 4"
    )
    page.keyboard.press("Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    active = search.get_attribute("aria-activedescendant")
    assert page.locator(f"#{active}").get_attribute("data-view") == "plan"
    page.keyboard.press("Enter")
    page.wait_for_selector("#plan-view:visible")
    _assert_no_overflow(page)
    context.close()

    context = _new_context(browser, 390, 844, light=True, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(10_000)
    _record_errors(page, errors, "universal command mobile")
    page.route("**/api/search?*", search_fixture)
    page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_selector("#today-view:visible")
    _dismiss_setup_if_needed(page)
    page.keyboard.press("Control+K")
    search = page.locator("#search-input")
    search.fill("plan")
    page.wait_for_function(
        "document.querySelectorAll('#search-results [role=\"option\"]').length >= 4"
    )
    box = page.locator("#search-modal .search-card").bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390.5, box
    assert page.locator("#search-results .search-actions").evaluate(
        "el => getComputedStyle(el).gridTemplateColumns.split(' ').length === 1"
    )
    assert search.evaluate("el => parseFloat(getComputedStyle(el).fontSize) >= 15")
    _assert_no_overflow(page)
    page.screenshot(path=str(OUTPUT / "universal-command-mobile.png"), full_page=True)
    page.locator("#search-close").click()
    context.close()


def _specialist_partial_states(browser: Browser, errors: list[str]) -> None:
    context = _new_context(browser, 1280, 900, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(10_000)
    _record_errors(page, errors, "specialist partial states")
    page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_selector("#today-view:visible")

    scenarios = (
        ("plan", "plan-view", "**/api/calendar/agenda*", "calendar unavailable"),
        ("inbox", "inbox-view", "**/api/mail/accounts", "mail accounts unavailable"),
        ("library", "library-view", "**/api/read*", "saved reading unavailable"),
        ("health", "health-group-view", "**/api/health/overview", "measurements unavailable"),
    )
    for view, root_id, route_pattern, expected in scenarios:
        page.route(
            route_pattern,
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"forced partial-state gate"}',
            ),
        )
        page.evaluate("view => window._navigateTo(view)", view)
        root = page.locator(f"#{root_id}")
        root.wait_for(state="visible")
        page.wait_for_function(
            "rootId => document.getElementById(rootId)?.getAttribute('aria-busy') === 'false'",
            arg=root_id,
        )
        partial = root.locator('.specialist-group-note[role="status"]')
        partial.wait_for(state="visible")
        assert expected in partial.inner_text().lower(), (view, partial.inner_text())
        assert expected in root.inner_text().lower(), (view, root.inner_text())
        errors[:] = [
            error
            for error in errors
            if error
            != (
                "specialist partial states console: Failed to load resource: "
                "the server responded with a status of 503 (Service Unavailable)"
            )
        ]
        page.unroute(route_pattern)
    context.close()


def _andromeda(browser: Browser, errors: list[str]) -> None:
    for width, height, label in ((1440, 1000, "desktop"), (390, 844, "mobile")):
        context = _new_context(browser, width, height, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(10_000)
        _record_errors(page, errors, f"andromeda {label}")
        response = page.goto(f"http://andromeda.localhost:{PORT}/", wait_until="domcontentloaded")
        try:
            page.wait_for_selector("#andromeda-view:visible")
        except PlaywrightTimeoutError as error:
            diagnostic = page.evaluate(
                """() => ({
                  url: location.href,
                  readyState: document.readyState,
                  bodyApp: document.body?.dataset.app || '',
                  activeElement: document.activeElement?.id || '',
                  andromedaStyle: document.getElementById('andromeda-view')?.getAttribute('style') || '',
                  visibleRoots: [...document.querySelectorAll('[id$="-view"]')]
                    .filter(element => element.offsetParent !== null)
                    .map(element => element.id),
                  bodyText: document.body?.innerText.slice(0, 500) || '',
                })"""
            )
            diagnostic["status"] = response.status if response else None
            diagnostic["browserErrors"] = errors[-10:]
            raise AssertionError(f"Andromeda did not become visible: {diagnostic}") from error
        root = page.locator("#andromeda-view")
        assert root.get_attribute("data-kokuen-surface") == "andromeda"
        assert page.locator(".andromeda-brand").count() == 0
        page.locator("#andromeda-idle-settings:visible, #andromeda-settings-button:visible").click()
        panel = page.locator("#andromeda-settings-panel")
        panel.wait_for(state="visible")
        page.wait_for_function(
            "document.getElementById('andromeda-searxng-status')?.textContent.trim() !== 'checking local search…'"
        )
        provider_order_row = page.locator("#andromeda-provider-order").locator("..").locator("..")
        assert provider_order_row.locator(".custom-select").count() == 0
        result_count_row = page.locator("#andromeda-result-count").locator("..")
        assert result_count_row.locator("strong").inner_text().strip() == "result count"
        assert page.locator("#andromeda-provider-summary").count() == 0
        panel_box = panel.bounding_box()
        assert panel_box and panel_box["x"] >= 52
        assert panel_box["x"] + panel_box["width"] <= width + 0.5
        assert panel.evaluate("el => getComputedStyle(el).boxShadow === 'none'")
        assert panel.locator("select:visible").count() == 0
        choice = panel.locator(".custom-select:visible").first
        choice.click()
        menu = page.locator(".custom-dropdown-panel:visible")
        menu.wait_for(state="visible")
        assert menu.get_attribute("data-kokuen-surface") == "andromeda"
        page.keyboard.press("Escape")
        panel.evaluate("el => { el.scrollTop = 0; }")
        page.wait_for_timeout(50)
        assert page.locator(".andromeda-settings-head").is_visible()
        assert page.locator("#andromeda-search-settings-title").is_visible()
        _assert_no_overflow(page)
        page.screenshot(path=str(OUTPUT / f"andromeda-{label}.png"))
        context.close()


def _light_theme_family(browser: Browser, errors: list[str]) -> None:
    context = _new_context(browser, 1024, 768, light=True, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(10_000)
    _record_errors(page, errors, "finished surfaces light theme")

    routes = (
        (f"http://127.0.0.1:{PORT}/", "#today-view"),
        (f"http://aide.localhost:{PORT}/", "#chat"),
        (f"http://andromeda.localhost:{PORT}/", "#andromeda-view"),
        (f"http://docs.localhost:{PORT}/", "#wiki-view"),
        (f"http://server.localhost:{PORT}/", "#system-view"),
    )
    for url, selector in routes:
        page.goto(url, wait_until="domcontentloaded")
        root = page.locator(selector)
        root.wait_for(state="visible")
        assert page.locator("html").get_attribute("data-theme") == "light"
        assert root.evaluate(
            "el => getComputedStyle(el).getPropertyValue('--k-default-page').trim() === '#f4f3f0'"
        )
        _assert_no_overflow(page)

    page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_selector("#today-view:visible")
    page.locator("#app-drawer-btn").click()
    page.wait_for_selector("#app-drawer:visible")
    assert page.locator("#app-drawer").evaluate(
        "el => getComputedStyle(el).getPropertyValue('--k-default-page').trim() === '#f4f3f0'"
    )
    page.locator("#app-drawer-close").click()
    page.wait_for_function("typeof window._openSettings === 'function'")
    page.evaluate("window._openSettings('general')")
    page.wait_for_selector("#settings-modal:visible")
    assert page.locator("#settings-modal").evaluate(
        "el => getComputedStyle(el).getPropertyValue('--k-default-page').trim() === '#f4f3f0'"
    )
    _assert_no_overflow(page)
    page.screenshot(path=str(OUTPUT / "finished-surfaces-light.png"), full_page=True)
    context.close()


def _zoom_reflow_family(browser: Browser, errors: list[str]) -> None:
    # Half the CSS viewport in each axis while retaining a 720x500 physical
    # canvas. This exercises 200% browser-zoom reflow, not just HiDPI.
    context = browser.new_context(
        viewport={"width": 360, "height": 250},
        device_scale_factor=2,
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(10_000)
    _record_errors(page, errors, "finished surfaces 200 percent zoom")

    routes = (
        (f"http://127.0.0.1:{PORT}/", "#today-view"),
        (f"http://aide.localhost:{PORT}/", "#chat"),
        (f"http://andromeda.localhost:{PORT}/", "#andromeda-view"),
        (f"http://docs.localhost:{PORT}/", "#wiki-view"),
        (f"http://files.localhost:{PORT}/", "#files-view"),
        (f"http://server.localhost:{PORT}/", "#system-view"),
    )
    for url, selector in routes:
        page.goto(url, wait_until="domcontentloaded")
        page.locator(selector).wait_for(state="visible")
        _assert_no_overflow(page)

    page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_selector("#today-view:visible")
    _dismiss_setup_if_needed(page)
    page.locator("#today-settings").focus()
    page.keyboard.press("Control+K")
    page.wait_for_selector("#search-modal:visible")
    command_box = page.locator("#search-modal .search-card").bounding_box()
    assert command_box, command_box
    assert command_box["x"] >= 0 and command_box["x"] + command_box["width"] <= 360.5
    assert command_box["y"] >= 0 and command_box["y"] + command_box["height"] <= 250.5
    _assert_no_overflow(page)
    page.locator("#search-close").click()
    page.wait_for_function("typeof window._openSettings === 'function'")
    page.evaluate("window._openSettings('general')")
    page.wait_for_selector("#settings-modal:visible")
    assert page.locator("#settings-modal").evaluate("el => getComputedStyle(el).opacity === '1'")
    assert page.locator("#settings-modal .s-modal").evaluate(
        "el => getComputedStyle(el).backgroundColor !== 'rgba(0, 0, 0, 0)'"
    )
    _assert_no_overflow(page)
    page.screenshot(path=str(OUTPUT / "finished-surfaces-zoom-200.png"))
    context.close()


def _docs_notes_journal(browser: Browser, errors: list[str]) -> None:
    for width, height, label in ((1440, 1000, "desktop"), (390, 844, "mobile")):
        context = _new_context(browser, width, height, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(10_000)
        _record_errors(page, errors, f"docs {label}")
        page.goto(f"http://docs.localhost:{PORT}/", wait_until="domcontentloaded")
        page.wait_for_selector("#wiki-view:visible")
        root = page.locator("#wiki-view")
        assert root.get_attribute("data-kokuen-surface") == "docs"
        if width > 760:
            assert (
                page.locator("#docs-nav-panel").evaluate(
                    "el => Math.round(el.getBoundingClientRect().width)"
                )
                == 244
            )
            assert page.locator("#docs-workbench-title").inner_text() == "docs"
            assert page.locator(".docs-wordmark").count() == 0
        else:
            assert page.locator("#docs-nav-panel").is_hidden()
            assert (
                page.locator(".docs-reader-head").evaluate(
                    "el => Math.round(el.getBoundingClientRect().height)"
                )
                == 52
            )
        assert root.locator("select:visible").count() == 0
        undersized = root.locator("button:visible").evaluate_all(
            """elements => elements.map(element => {
                const box = element.getBoundingClientRect();
                return {label: element.textContent.trim(), width: box.width, height: box.height};
            }).filter(item => item.width < 43.5 || item.height < 43.5)"""
        )
        assert not undersized, undersized

        if width <= 760:
            page.locator("#wiki-tree-toggle").click()
            page.wait_for_selector("#docs-nav-panel:visible")
        root.locator('.docs-sec-btn[data-section="notes"]').click()
        page.wait_for_selector("#wiki-notes:visible")
        assert root.get_attribute("data-docs-section") == "notes"
        if width <= 760:
            assert page.locator("#docs-nav-panel").is_hidden()
            page.locator("#wiki-tree-toggle").click()
            page.wait_for_selector("#docs-nav-panel:visible")
        navigation_count = page.evaluate("performance.getEntriesByType('navigation').length")
        page.locator('#docs-tabs [data-group-section="journal"]').click()
        page.wait_for_selector("#docs-journal-section:visible")
        page.wait_for_selector("#journal-body .jrnl-wrap")
        assert root.get_attribute("data-docs-section") == "journal"
        assert (
            page.evaluate("performance.getEntriesByType('navigation').length") == navigation_count
        )
        _assert_no_overflow(page)
        page.screenshot(path=str(OUTPUT / f"docs-journal-{label}.png"), full_page=True)
        context.close()


def _system(browser: Browser, errors: list[str]) -> None:
    for width, height, label in ((1440, 1000, "desktop"), (390, 844, "mobile")):
        context = _new_context(browser, width, height, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(10_000)
        _record_errors(page, errors, f"system {label}")
        page.goto(f"http://server.localhost:{PORT}/", wait_until="domcontentloaded")
        page.wait_for_selector("#system-view:visible")
        root = page.locator("#system-view")
        assert root.get_attribute("data-kokuen-surface") == "system"
        assert (
            root.locator(":scope > .page-view-head").evaluate(
                "el => Math.round(el.getBoundingClientRect().height)"
            )
            == 52
        )
        page.wait_for_selector("#system-body .nf-logo")
        assert root.locator(".btop-box").first.evaluate(
            "el => getComputedStyle(el).boxShadow === 'none'"
        )
        _assert_no_overflow(page)
        page.screenshot(path=str(OUTPUT / f"system-{label}.png"), full_page=True)
        context.close()


def _settings(browser: Browser, errors: list[str]) -> None:
    for width, height, label in ((1440, 1000, "desktop"), (390, 844, "mobile")):
        context = _new_context(browser, width, height, reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(10_000)
        _record_errors(page, errors, f"settings {label}")
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
        page.wait_for_function("typeof window._openSettings === 'function'")
        page.evaluate("window._openSettings('general')")
        modal = page.locator("#settings-modal")
        modal.wait_for(state="visible")
        assert modal.get_attribute("data-kokuen-surface") == "settings"
        assert (
            modal.locator(".s-header").evaluate(
                "el => Math.round(el.getBoundingClientRect().height)"
            )
            == 52
        )
        if width > 760:
            assert (
                modal.locator(".s-nav").evaluate(
                    "el => Math.round(el.getBoundingClientRect().width)"
                )
                == 204
            )
        else:
            assert modal.locator(".s-nav").evaluate(
                "el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX)"
            )
        assert modal.locator("select:visible").count() == 0
        choice = modal.locator(".custom-select:visible").first
        if choice.count():
            choice.click()
            menu = page.locator(".custom-dropdown-panel:visible")
            menu.wait_for(state="visible")
            assert menu.get_attribute("data-kokuen-surface") == "settings"
            page.keyboard.press("Escape")
        _assert_no_overflow(page)
        page.screenshot(path=str(OUTPUT / f"settings-{label}.png"), full_page=True)
        context.close()


def run() -> None:
    _require_throwaway_data_root()
    files = DATA / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / "project notes.txt").write_text("KOKUEN browser fixture\n", encoding="utf-8")
    (files / "reference.md").write_text("# reference\n", encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        _files_desktop(browser, errors)
        _files_light(browser, errors)
        _files_mobile(browser, errors)
        _files_reduced_motion(browser, errors)
        _home_and_apps(browser, errors)
        _universal_command(browser, errors)
        _specialist_partial_states(browser, errors)
        _aide_smoke(browser, errors)
        _aide_mobile(browser, errors)
        _andromeda(browser, errors)
        _docs_notes_journal(browser, errors)
        _system(browser, errors)
        _settings(browser, errors)
        _light_theme_family(browser, errors)
        _zoom_reflow_family(browser, errors)
        browser.close()

    if errors:
        raise AssertionError("browser errors:\n" + "\n".join(errors))
    print("KOKUEN finished-surface browser gate passed")


if __name__ == "__main__":
    run()
