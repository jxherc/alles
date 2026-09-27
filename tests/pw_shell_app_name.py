"""The app name is the only global switcher on every shipped workspace."""

from __future__ import annotations

import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

SURFACES = (
    ("home", "", ".today-topbar", "alles"),
    ("aide", "chat", ".sidebar-head", "aide"),
    ("andromeda", "andromeda", ".andromeda-app-head", "andromeda"),
    *(
        (app, app, f'.specialist-group[data-specialist-app="{app}"] .specialist-app-brand', app)
        for app in (
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
    ),
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
        for width in (1440, 720, 390, 320):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(15_000)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            dismissed = context.request.post(base + "/api/setup/dismiss")
            assert dismissed.ok, dismissed.text()
            for name, view, desktop_host, label in SURFACES:
                url = base + (f"/?view={view}" if view else "/")
                page.goto(url, wait_until="domcontentloaded")
                trigger = page.locator("#app-drawer-btn")
                trigger.wait_for(state="visible")
                assert page.locator("#space-rail").count() == 0, name
                expected_host = ".topbar-left" if name == "aide" and width <= 700 else desktop_host
                assert page.locator(expected_host).locator("#app-drawer-btn").count() == 1, (
                    name,
                    width,
                )
                assert trigger.locator("#app-drawer-label").inner_text() == label, (name, width)
                box = trigger.bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44, (name, width, box)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                ), (name, width)
                if name in ("home", "aide", "andromeda", "files"):
                    page.screenshot(path=str(output / f"switcher-{name}-{width}.png"))
                trigger.focus()
                trigger.press("Enter")
                drawer = page.locator("#app-drawer")
                drawer.wait_for(state="visible")
                assert drawer.locator(".app-drawer-item").count() == 12
                assert page.locator(".main").get_attribute("inert") is not None
                page.keyboard.press("Escape")
                drawer.wait_for(state="hidden")
                assert trigger.evaluate("node => document.activeElement === node"), (name, width)
                assert page.locator(".main").get_attribute("inert") is None
                if name == "home" and width > 420:
                    trigger.click()
                    page.locator("#app-drawer-scrim").click(position={"x": width - 8, "y": 300})
                    drawer.wait_for(state="hidden")
                    assert trigger.evaluate("node => document.activeElement === node"), width

            page.goto(base, wait_until="domcontentloaded")
            page.locator("#app-drawer-btn").click()
            page.locator('.app-drawer-item[data-view="files"]').click()
            page.locator("#files-workbench-view").wait_for(state="visible")
            page.locator("#app-drawer").wait_for(state="hidden")
            assert (
                page.locator("#files-workbench-view .specialist-app-brand #app-drawer-btn").count()
                == 1
            )
            assert page.locator("#app-drawer-btn").evaluate(
                "node => document.activeElement === node"
            )
            page.locator("#app-drawer-btn").click()
            page.locator('.app-drawer-item[data-view="today"]').click()
            page.locator("#today-view").wait_for(state="visible")
            page.locator("#app-drawer").wait_for(state="hidden")
            assert page.locator(".today-topbar #app-drawer-btn").count() == 1
            assert page.locator("#app-drawer-btn").evaluate(
                "node => document.activeElement === node"
            )

            for host, view, expected in (
                ("aide", "", ".topbar-left" if width <= 700 else ".sidebar-head"),
                ("docs", "wiki", "#docs-workbench-view .specialist-app-brand"),
                ("files", "photos", "#files-workbench-view .specialist-app-brand"),
            ):
                page.goto(
                    f"http://{host}.localhost:{port}/" + (f"?view={view}" if view else ""),
                    wait_until="domcontentloaded",
                )
                page.locator("#app-drawer-btn").wait_for(state="visible")
                assert page.locator(expected).locator("#app-drawer-btn").count() == 1, (
                    host,
                    view,
                    width,
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )

            assert not errors, errors
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
