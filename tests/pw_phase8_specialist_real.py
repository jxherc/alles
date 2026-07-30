"""Rendered Phase 8 gate against the real specialist group UI and isolated backend."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Browser, Page, Route, sync_playwright

PORT = os.environ.get("PORT", "8048")
BASE = f"http://127.0.0.1:{PORT}"
OUTPUT = Path(tempfile.gettempdir()) / "alles-phase8-real"

THEMES = {
    "dark": {
        "_stored": True,
        "preset": "dark",
        "colors": {
            "bg": "#090909",
            "text": "#f0f0f0",
            "panel": "#121212",
            "faint": "#777777",
            "accent": "#818cf8",
        },
        "font": "sans",
        "density": "comfortable",
        "bgPattern": "none",
        "frosted": False,
    },
    "light": {
        "_stored": True,
        "preset": "light",
        "colors": {
            "bg": "#f5f4f1",
            "text": "#111111",
            "panel": "#efede9",
            "faint": "#666666",
            "accent": "#686fd8",
        },
        "font": "sans",
        "density": "comfortable",
        "bgPattern": "none",
        "frosted": False,
    },
}


def _require_throwaway_data_root() -> None:
    raw_data = os.environ.get("ALLES_DATA", "").strip()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if not raw_data or os.environ.get("ALLES_TEST_DATA") != "1" or len(run_id) < 16:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    data = Path(raw_data).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    try:
        owner = (data / ".alles-test-owner").read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, run_id)


def _capture_errors(page: Page, errors: list[str], label: str) -> None:
    page.on("pageerror", lambda error: errors.append(f"{label} page: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"{label} console: {message.text}") if message.type == "error" else None
        ),
    )


def _status(mode: str = "alles") -> dict:
    return {
        "service": {
            "available": True,
            "installed": True,
            "running": True,
            "healthy": True,
            "owned": True,
            "version": "26.7.0",
            "node_version": "22.17.0",
            "bind": "127.0.0.1:5007",
        },
        "ledger": {
            "mode": mode,
            "base_currency_code": "CAD",
            "legacy_read_only": mode == "actual",
            "active_run_id": "run-browser",
            "run": {
                "id": "run-browser",
                "status": "canonical" if mode == "actual" else "ready",
                "links": 14,
                "report": {"pass": True},
                "error": "",
            },
        },
    }


def _route_actual(route: Route, state: dict, calls: list[str]) -> None:
    request = route.request
    path = urlparse(request.url).path
    if request.method == "GET" and path == "/api/finance/actual":
        route.fulfill(status=200, content_type="application/json", body=json.dumps(state["status"]))
        return
    if request.method == "POST" and path == "/api/finance/actual/cutover/run-browser":
        calls.append(path)
        state["status"] = _status("actual")
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(state["status"]["ledger"])
        )
        return
    if request.method == "POST" and path == "/api/finance/actual/rollback-ledger":
        calls.append(path)
        route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"detail": "rollback stopped: Actual-only transactions need review"}),
        )
        return
    route.continue_()


def _assert_no_overflow(page: Page) -> None:
    metrics = page.evaluate(
        """
        () => ({
          page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          root: document.querySelector('#finance-view').scrollWidth - document.querySelector('#finance-view').clientWidth,
          offenders: [...document.querySelectorAll('#finance-view *')].map(element => {
            const box = element.getBoundingClientRect();
            return { tag: element.tagName, className: element.className || '', left: box.left, right: box.right };
          }).filter(item => item.left < -1 || item.right > document.documentElement.clientWidth + 1).slice(0, 10),
        })
        """
    )
    assert metrics["page"] <= 1, metrics
    assert metrics["root"] <= 1, metrics


def _assert_owned_shell(page: Page, root_selector: str, label: str, width: int) -> None:
    root = page.locator(root_selector)
    assert root.get_attribute("data-kokuen-surface") == "specialist"
    assert page.locator(".main > .topbar").evaluate(
        "element => getComputedStyle(element).display === 'none'"
    )
    header = root.locator(":scope > .specialist-app-head")
    app_name = header.locator(".specialist-app-name")
    assert app_name.is_visible() and app_name.inner_text() == label
    assert (
        round(app_name.evaluate("element => parseFloat(getComputedStyle(element).fontSize)")) == 15
    )
    assert root.locator(":scope > .specialist-group-head").count() == 0
    assert header.locator("[data-specialist-home]").count() == 0
    assert page.locator("#space-rail").is_visible()
    shell_trigger = page.locator("#app-drawer-btn")
    assert shell_trigger.is_visible()
    assert shell_trigger.evaluate(
        "element => element.getBoundingClientRect().width >= 44 && element.getBoundingClientRect().height >= 44"
    )
    toggle = header.locator("[data-specialist-sidebar-toggle]")
    assert toggle.is_visible()
    assert toggle.get_attribute("aria-expanded") == "true"
    controlled = toggle.get_attribute("aria-controls")
    assert controlled and root.locator(f"#{controlled}").count() == 1
    assert toggle.evaluate(
        "element => element.getBoundingClientRect().width >= 44 && element.getBoundingClientRect().height >= 44"
    )
    assert not page.locator("#app-crumb").is_visible()
    brand_box = header.locator(".specialist-app-brand").evaluate(
        "element => element.getBoundingClientRect()"
    )
    tabs_box = header.locator(".specialist-group-tabs").evaluate(
        "element => element.getBoundingClientRect()"
    )
    assert round(brand_box["height"]) == 52, brand_box
    root_box = root.evaluate("element => element.getBoundingClientRect()")
    assert round(brand_box["width"]) == round(root_box["width"]), (brand_box, root_box)
    assert round(tabs_box["y"] - brand_box["y"]) == 52, (brand_box, tabs_box)
    toggle.focus()
    page.keyboard.press("Enter")
    assert root.get_attribute("data-sidebar-collapsed") == "true"
    assert toggle.get_attribute("aria-expanded") == "false"
    assert not root.locator(f"#{controlled}").is_visible()
    active_content = root.locator(
        "[data-group-overview]:not([hidden]), [data-group-slot]:not([hidden])"
    )
    collapsed_box = active_content.evaluate("element => element.getBoundingClientRect()")
    assert round(collapsed_box["x"]) == round(root_box["x"]), (collapsed_box, root_box)
    assert round(collapsed_box["width"]) == round(root_box["width"]), (collapsed_box, root_box)
    page.keyboard.press("Space")
    assert root.get_attribute("data-sidebar-collapsed") == "false"
    assert toggle.get_attribute("aria-expanded") == "true"
    if width <= 760:
        assert round(root_box["x"]) == 52, root_box
        assert round(root_box["width"]) == width - 52, root_box
        assert round(tabs_box["width"]) == width - 52, tabs_box
        assert round(tabs_box["height"]) >= 44, tabs_box
        clipped_tabs = header.locator('.specialist-group-tabs [role="tab"]').evaluate_all(
            """tabs => tabs.filter(tab => {
              const tabBox = tab.getBoundingClientRect();
              const listBox = tab.parentElement.getBoundingClientRect();
              return tabBox.left < listBox.left - 1 || tabBox.right > listBox.right + 1;
            }).map(tab => tab.textContent.trim())"""
        )
        assert not clipped_tabs, clipped_tabs


def _assert_controls(page: Page) -> None:
    root = page.locator("#finance-view")
    assert (
        root.locator(
            'select:visible, input[type="checkbox"]:visible, input[type="radio"]:visible'
        ).count()
        == 0
    )
    small = root.locator("button:visible").evaluate_all(
        """
        buttons => buttons.map(button => {
          const box = button.getBoundingClientRect();
          return { label: button.textContent.trim(), width: box.width, height: box.height };
        }).filter(item => item.width < 43.5 || item.height < 43.5)
        """
    )
    assert not small, small
    unreadable = root.locator(
        "button:visible, p:visible, dt:visible, dd:visible, h2:visible, strong:visible"
    ).evaluate_all(
        """
        elements => elements.map(element => ({
          label: element.textContent.trim().slice(0, 60),
          size: parseFloat(getComputedStyle(element).fontSize),
        })).filter(item => item.label && item.size < 11.9)
        """
    )
    assert not unreadable, unreadable


def _assert_readable(page: Page, root_selector: str) -> None:
    failures = page.evaluate(
        r"""
        selector => {
          const luminance = ({ r, g, b }) => {
            const channel = value => {
              value /= 255;
              return value <= 0.03928
                ? value / 12.92
                : Math.pow((value + 0.055) / 1.055, 2.4);
            };
            return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
          };
          const parse = value => {
            const match = (value || '').match(/rgba?\(([^)]+)\)/);
            if (!match) return null;
            const parts = match[1].split(',').map(Number);
            return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] ?? 1 };
          };
          const over = (foreground, background) => ({
            r: foreground.r * foreground.a + background.r * (1 - foreground.a),
            g: foreground.g * foreground.a + background.g * (1 - foreground.a),
            b: foreground.b * foreground.a + background.b * (1 - foreground.a),
            a: 1,
          });
          const pageBackground = parse(
            getComputedStyle(document.documentElement).getPropertyValue('--bg')
          ) || { r: 255, g: 255, b: 255, a: 1 };
          const effectiveBackground = element => {
            let accumulated = null;
            for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
              const color = parse(getComputedStyle(node).backgroundColor);
              if (!color || color.a <= 0) continue;
              accumulated = accumulated ? over(accumulated, color) : color;
              if (accumulated.a >= 0.999) return accumulated;
            }
            return accumulated ? over(accumulated, pageBackground) : pageBackground;
          };
          const ratio = (foreground, background) => {
            const a = luminance(foreground);
            const b = luminance(background);
            return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
          };
          const root = document.querySelector(selector);
          const failures = [];
          for (const element of root.querySelectorAll('*')) {
            const style = getComputedStyle(element);
            const bounds = element.getBoundingClientRect();
            if (
              style.display === 'none'
              || style.visibility === 'hidden'
              || parseFloat(style.opacity) < 0.15
              || bounds.width < 4
              || bounds.height < 4
            ) continue;
            const text = [...element.childNodes]
              .filter(node => node.nodeType === Node.TEXT_NODE)
              .map(node => node.textContent.trim())
              .join(' ');
            if (!text || !/[A-Za-z0-9]/.test(text) || /\p{Extended_Pictographic}/u.test(text)) continue;
            const foreground = parse(style.color);
            if (!foreground) continue;
            const contrast = ratio(foreground, effectiveBackground(element));
            const fontSize = parseFloat(style.fontSize);
            const fontWeight = parseInt(style.fontWeight, 10) || 400;
            const threshold = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700) ? 3 : 4.5;
            if (contrast < threshold) {
              failures.push({
                tag: element.tagName.toLowerCase(),
                className: element.className || '',
                text: text.slice(0, 60),
                contrast: Number(contrast.toFixed(2)),
                threshold,
              });
            }
          }
          return failures;
        }
        """,
        root_selector,
    )
    assert not failures, failures


def _open_finance(page: Page) -> None:
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function("typeof window._navigateTo === 'function'", timeout=15_000)
    if page.locator("#setup-wizard").is_visible():
        page.locator("#setup-skip").click()
        page.locator("#setup-wizard").wait_for(state="hidden")
    page.evaluate("window._navigateTo('finance')")
    page.locator("#finance-view").wait_for(state="visible")
    page.locator(".finance-actual-ready").wait_for(state="visible")


def _exercise_case(
    browser: Browser, width: int, height: int, theme: str, errors: list[str]
) -> None:
    appearance = THEMES[theme]
    state = {"status": _status()}
    calls: list[str] = []
    context = browser.new_context(
        viewport={"width": width, "height": height},
        reduced_motion="reduce",
        service_workers="block",
    )
    context.add_init_script(
        "localStorage.setItem('alles-appearance', " + json.dumps(json.dumps(appearance)) + ");"
    )
    context.add_init_script(
        """
        (() => {
          const networkFetch = window.fetch.bind(window);
          window.fetch = (input, options) => {
            const url = typeof input === 'string' ? input : input?.url || '';
            if (url.endsWith('/api/finance/actual/rollback-ledger')) {
              return Promise.resolve(new Response(
                JSON.stringify({ detail: 'rollback stopped: Actual-only transactions need review' }),
                { status: 409, headers: { 'content-type': 'application/json' } },
              ));
            }
            return networkFetch(input, options);
          };
        })();
        """
    )
    page = context.new_page()
    page.set_default_timeout(15_000)
    _capture_errors(page, errors, f"{width}x{height}/{theme}")
    page.route(
        "**/api/appearance",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(appearance)
        ),
    )
    page.route("**/api/finance/actual**", lambda route: _route_actual(route, state, calls))
    _open_finance(page)
    _assert_owned_shell(page, "#finance-view", "finance", width)
    page.wait_for_function(
        "theme => theme === 'light' ? document.documentElement.dataset.theme === 'light' : document.documentElement.dataset.theme !== 'light'",
        arg=theme,
    )
    assert "staging parity passed" in page.locator(".finance-actual-head").inner_text()
    assert page.locator(".finance-actual-facts dd").all_text_contents()[:3] == [
        "Alles",
        "CAD",
        "26.7.0 · healthy",
    ]
    _assert_controls(page)
    _assert_no_overflow(page)

    selected = page.locator('#finance-view [role="tab"][aria-selected="true"]')
    assert page.locator("#finance-tabs").get_attribute("aria-orientation") == (
        "horizontal" if width <= 760 else "vertical"
    )
    assert selected.get_attribute("aria-controls")
    assert page.locator(f"#{selected.get_attribute('aria-controls')}").get_attribute(
        "aria-labelledby"
    ) == selected.get_attribute("id")
    selected.focus()
    page.keyboard.press("ArrowDown")
    page.wait_for_function("document.querySelector('#finance-view').dataset.section === 'money'")
    selected = page.locator('#finance-view [role="tab"][aria-selected="true"]')
    assert page.locator(f"#{selected.get_attribute('aria-controls')}").get_attribute(
        "aria-labelledby"
    ) == selected.get_attribute("id")
    page.evaluate("window._navigateTo('finance')")
    page.locator(".finance-actual-ready").wait_for(state="visible")
    page.locator('#finance-view [data-group-section="money"]').click()
    page.locator("#money-view").wait_for(state="visible")
    page.locator('#finance-view [data-group-section="overview"]').click()
    page.locator(".finance-actual-ready").wait_for(state="visible")
    page.locator('#finance-view [data-group-section="money"]').click()
    page.locator("#money-view").wait_for(state="visible")
    page.locator('#finance-view [data-group-section="overview"]').click()
    page.locator(".finance-actual-ready").wait_for(state="visible")

    trigger = page.get_by_role("button", name="review cutover")
    trigger.focus()
    trigger.click()
    confirmation = page.locator(".finance-actual-confirm")
    assert confirmation.is_visible()
    assert page.evaluate("document.activeElement?.textContent.trim()") == "keep current authority"
    page.keyboard.press("Escape")
    assert confirmation.count() == 0
    assert trigger.evaluate("element => document.activeElement === element")

    trigger.click()
    page.get_by_role("button", name="switch writes to Actual").click()
    page.locator(".finance-actual-canonical").wait_for(state="visible")
    assert calls == ["/api/finance/actual/cutover/run-browser"]
    assert page.get_by_role("button", name="stop Actual").count() == 0

    rollback = page.get_by_role("button", name="review ledger rollback")
    rollback.click()
    page.get_by_role("button", name="restore Alles authority").click()
    page.locator(".finance-actual-error").wait_for(state="visible")
    assert (
        "Actual-only transactions need review" in page.locator(".finance-actual-error").inner_text()
    )
    assert rollback.evaluate("element => document.activeElement === element")

    _assert_controls(page)
    _assert_no_overflow(page)
    _assert_readable(page, "#finance-view")
    page.screenshot(path=str(OUTPUT / f"finance-{width}-{theme}.png"), full_page=True)
    context.close()


def _compatibility_routes(browser: Browser, errors: list[str]) -> None:
    state = {"status": _status()}
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, reduced_motion="reduce", service_workers="block"
    )
    page = context.new_page()
    page.set_default_timeout(15_000)
    _capture_errors(page, errors, "compatibility")
    page.route("**/api/finance/actual**", lambda route: _route_actual(route, state, []))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function("typeof window._navigateTo === 'function'", timeout=15_000)
    cases = (
        ("calendar", "plan-view", "calendar"),
        ("mail", "inbox-view", "mail"),
        ("books", "library-view", "books"),
        ("habits", "health-group-view", "habits"),
        ("money", "finance-view", "money"),
    )
    for identifier, root_id, section in cases:
        page.evaluate("view => window._navigateTo(view)", identifier)
        root = page.locator(f"#{root_id}")
        root.wait_for(state="visible")
        page.wait_for_function(
            "args => document.querySelector(`#${args.root}`).dataset.section === args.section",
            arg={"root": root_id, "section": section},
        )
        assert (
            page.locator(f'#{root_id} [role="tab"][aria-selected="true"]').get_attribute(
                "data-group-section"
            )
            == section
        )
        assert f"view={identifier}" in page.url
    context.close()


def _group_overviews(browser: Browser, errors: list[str], width: int) -> None:
    today = date.today().isoformat()
    state = {"status": _status()}
    context = browser.new_context(
        viewport={"width": width, "height": 900 if width > 500 else 844},
        reduced_motion="reduce",
        service_workers="block",
    )
    context.add_init_script(
        """
        (() => {
          const networkFetch = window.fetch.bind(window);
          window.fetch = (input, options = {}) => {
            const url = typeof input === 'string' ? input : input?.url || '';
            if (url.endsWith('/api/tasks') && String(options.method || 'GET').toUpperCase() === 'POST') {
              return Promise.resolve(new Response(
                JSON.stringify({ detail: 'task write unavailable' }),
                { status: 500, headers: { 'content-type': 'application/json' } },
              ));
            }
            return networkFetch(input, options);
          };
        })();
        """
    )
    page = context.new_page()
    page.set_default_timeout(15_000)
    _capture_errors(page, errors, f"group overviews {width}")
    fixtures = {
        "/api/calendar/agenda": {
            "days": [
                {
                    "date": today,
                    "events": [
                        {
                            "id": "event-1",
                            "title": "dentist",
                            "start_dt": f"{today}T09:45:00",
                            "location": "Zhongshan",
                        }
                    ],
                }
            ]
        },
        "/api/tasks": [
            {
                "id": "task-1",
                "title": "review Stage 8",
                "due_date": f"{today}T08:30:00",
                "status": "open",
            },
            {"id": "task-2", "title": "renew library card", "due_date": "", "status": "open"},
        ],
        "/api/reminders": [
            {
                "id": "reminder-1",
                "text": "put passport by the door",
                "trigger_at": f"{today}T21:15:00",
            }
        ],
        "/api/mail/accounts": [{"id": 7, "name": "personal"}],
        "/api/contacts": [{"id": "contact-1", "name": "Min Chen", "email": "min@example.test"}],
        "/api/read": {
            "items": [
                {
                    "id": "read-1",
                    "title": "saved article",
                    "site": "example.test",
                    "status": "unread",
                }
            ]
        },
        "/api/books/overview": {
            "shelves": {
                "reading": [
                    {"id": "book-1", "title": "The Dispossessed", "author": "Ursula K. Le Guin"}
                ],
                "want": [],
                "done": [],
            }
        },
        "/api/health/overview": {
            "kinds": [
                {
                    "kind": "weight",
                    "label": "weight",
                    "latest": {"value": 64.2, "unit": "kg", "date": today},
                }
            ]
        },
        "/api/habits/overview": {
            "habits": [{"id": "habit-1", "name": "walk", "done_today": True, "streak": 4}]
        },
    }

    def fixture_route(route: Route) -> None:
        path = urlparse(route.request.url).path
        if path.startswith("/api/mail/cached/"):
            payload = {
                "messages": [
                    {
                        "id": "message-1",
                        "subject": "Sunday dinner",
                        "from_name": "Min Chen",
                        "from_email": "min@example.test",
                        "received_at": f"{today}T09:42:00",
                        "snippet": "Does 18:30 work?",
                    },
                    {
                        "id": "message-2",
                        "subject": "statement ready",
                        "from_name": "CIBC",
                        "received_at": f"{today}T08:15:00",
                        "snippet": "Your eStatement is ready.",
                    },
                ]
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
            return
        if path in fixtures:
            route.fulfill(
                status=200, content_type="application/json", body=json.dumps(fixtures[path])
            )
            return
        route.continue_()

    page.route("**/api/**", fixture_route)
    page.route("**/api/finance/actual**", lambda route: _route_actual(route, state, []))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function("typeof window._navigateTo === 'function'", timeout=15_000)

    page.evaluate("window._navigateTo('plan')")
    page.locator(".specialist-workbench-plan").wait_for(state="visible")
    _assert_owned_shell(page, "#plan-view", "plan", width)
    assert parse_qs(urlparse(page.url).query).get("view") == ["plan"]
    page.locator("#app-drawer-btn").click()
    page.locator('.app-drawer-item[data-view="today"]').click()
    page.locator("#today-view:visible, #home-view:visible").wait_for(state="visible")
    page.evaluate("window._navigateTo('plan')")
    page.locator(".specialist-workbench-plan").wait_for(state="visible")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("typeof window._navigateTo === 'function'", timeout=15_000)
    page.locator(".specialist-workbench-plan").wait_for(state="visible")
    dentist = page.locator(
        ".specialist-workbench-plan .specialist-record-title"
    ).filter(has_text="dentist")
    dentist.wait_for(state="visible")
    assert dentist.count() == 1
    page.locator('.specialist-workbench-plan [data-value="unscheduled"]').click()
    assert (
        page.locator(".specialist-workbench-main .specialist-record-title")
        .filter(has_text="renew library card")
        .count()
        == 1
    )
    capture = page.locator('.specialist-group-capture[aria-label="quick task"]')
    capture.locator('input[name="title"]').fill("retry this task")
    capture.locator('button[type="submit"]').click()
    status = capture.locator('[role="status"]')
    status.wait_for(state="visible")
    assert status.inner_text() == "task write unavailable"
    assert capture.locator('input[name="title"]').input_value() == "retry this task"
    assert capture.locator('input[name="title"]').evaluate("el => document.activeElement === el")
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    _assert_readable(page, "#plan-view")
    page.screenshot(path=str(OUTPUT / f"plan-real-{width}.png"), full_page=True)

    page.evaluate("window._navigateTo('reminders')")
    page.locator("#reminders-view").wait_for(state="visible")
    assert page.locator("#reminders-view").evaluate(
        "element => element.parentElement.hasAttribute('data-group-slot')"
    )
    page.evaluate("window._navigateTo('chat')")
    page.locator('.aide-tool-link[data-view="aide-reminders"]').evaluate(
        "element => element.click()"
    )
    page.locator("#reminders-view").wait_for(state="visible")
    assert page.locator("#plan-view").is_hidden()
    assert not page.locator("#reminders-view").evaluate(
        "element => element.parentElement.hasAttribute('data-group-slot')"
    )

    page.evaluate("window._navigateTo('inbox')")
    page.locator(".specialist-workbench-inbox").wait_for(state="visible")
    _assert_owned_shell(page, "#inbox-view", "inbox", width)
    assert page.locator(".specialist-message-row").count() == 2
    page.locator('.specialist-workbench-inbox [data-value="7"]').click()
    assert page.locator(".specialist-message-row").count() == 2
    page.locator(".specialist-message-row").nth(1).click()
    assert (
        "statement ready"
        in page.locator(".specialist-workbench-inbox .specialist-workbench-detail").inner_text()
    )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    _assert_readable(page, "#inbox-view")
    page.screenshot(path=str(OUTPUT / f"inbox-real-{width}.png"), full_page=True)

    page.evaluate("window._navigateTo('library')")
    page.locator(".specialist-workbench-library").wait_for(state="visible")
    _assert_owned_shell(page, "#library-view", "library", width)
    assert page.locator(".specialist-library-row").count() == 2
    page.locator('.specialist-workbench-library [data-value="books"]').click()
    assert page.locator(".specialist-library-row").count() == 1
    assert "The Dispossessed" in page.locator(".specialist-library-row").inner_text()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    _assert_readable(page, "#library-view")
    page.screenshot(path=str(OUTPUT / f"library-real-{width}.png"), full_page=True)

    page.evaluate("window._navigateTo('health')")
    page.locator(".specialist-workbench-health").wait_for(state="visible")
    _assert_owned_shell(page, "#health-group-view", "health", width)
    health_tab = page.locator('#health-group-view [data-group-section="overview"]')
    health_tab_state = health_tab.evaluate(
        """element => ({
          text: element.textContent,
          color: getComputedStyle(element).color,
          background: getComputedStyle(element).backgroundColor,
          opacity: getComputedStyle(element).opacity,
          visibility: getComputedStyle(element).visibility,
          width: element.getBoundingClientRect().width,
        })"""
    )
    assert (
        health_tab_state["text"] == "overview"
        and health_tab_state["color"] != health_tab_state["background"]
    ), health_tab_state
    assert "walk" in page.locator(".specialist-habit-row").inner_text()
    assert "64.2 kg" in page.locator(".specialist-workbench-health").inner_text()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    _assert_readable(page, "#health-group-view")
    page.screenshot(path=str(OUTPUT / f"health-real-{width}.png"), full_page=True)
    context.close()


def _all_workbench_shells(browser: Browser, errors: list[str], width: int) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": 900 if width > 500 else 844},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(15_000)
    _capture_errors(page, errors, f"all workbench shells {width}")
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_function("typeof window._navigateTo === 'function'", timeout=15_000)
    cases = [
        ("plan", "#plan-view", "plan"),
        ("inbox", "#inbox-view", "inbox"),
        ("docs", "#docs-workbench-view", "docs"),
        ("files", "#files-workbench-view", "files"),
        ("library", "#library-view", "library"),
        ("health", "#health-group-view", "health"),
        ("finance", "#finance-view", "finance"),
        ("vault", "#vault-workbench-view", "vault"),
        ("server", "#server-workbench-view", "server"),
    ]
    for route, root_selector, label in cases:
        page.evaluate("route => window._navigateTo(route)", route)
        page.locator(root_selector).wait_for(state="visible")
        _assert_owned_shell(page, root_selector, label, width)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
        ), route
    context.close()


def run() -> None:
    _require_throwaway_data_root()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        _exercise_case(browser, 1440, 900, "dark", errors)
        _exercise_case(browser, 1440, 900, "light", errors)
        _exercise_case(browser, 390, 844, "dark", errors)
        _exercise_case(browser, 390, 844, "light", errors)
        _group_overviews(browser, errors, 1280)
        _group_overviews(browser, errors, 390)
        _all_workbench_shells(browser, errors, 1280)
        _all_workbench_shells(browser, errors, 390)
        _compatibility_routes(browser, errors)
        browser.close()
    if errors:
        raise AssertionError("browser errors:\n" + "\n".join(errors))
    print(
        "Phase 8 real UI passed desktop/mobile, both themes, keyboard cutover/rollback preview, "
        "focus return, reduced motion, control sizing, type floor, rendered contrast, overflow, "
        "compatibility routes, visible errors, and clean console checks"
    )


if __name__ == "__main__":
    run()
