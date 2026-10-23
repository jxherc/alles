"""Rendered layout gate for Aide tools and the constrained effort menu."""

import os

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8030")
BASE = f"http://127.0.0.1:{PORT}"
TOOLS = {
    "scheduled": "aide-scheduled-view",
    "brain": "brain-view",
    "skills": "skills-view",
    "aide-reminders": "reminders-view",
}
SHARED_GEOMETRY_TOOLS = {"scheduled", "brain", "skills"}


def run() -> None:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height, label, scale in (
            (1440, 1000, "desktop", 1),
            (390, 844, "mobile", 1),
            # Half the CSS viewport in each axis retains a 720 x 500 physical
            # canvas while exercising the reflow geometry of 200% browser zoom.
            (360, 250, "zoom200", 2),
        ):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.goto(BASE, wait_until="networkidle")
            page.evaluate("window._navigateTo('chat')")
            page.wait_for_selector("#chat:visible")

            geometries = {}
            for view, root_id in TOOLS.items():
                page.evaluate("view => window._navigateTo(view)", view)
                root = page.locator(f"#{root_id}")
                root.wait_for(state="visible")
                assert page.locator("body").get_attribute("data-space") == "aide"
                assert page.locator("body").evaluate(
                    "el => el.classList.contains('is-aide') && !el.classList.contains('is-subapp')"
                )
                assert root.evaluate("el => el.scrollWidth <= el.clientWidth + 1"), (label, view)
                if view in SHARED_GEOMETRY_TOOLS:
                    geometries[view] = root.evaluate(
                        """root => {
                          const head = root.querySelector('.aide-tool-head').getBoundingClientRect();
                          const content = root.querySelector('.aide-tool-content').getBoundingClientRect();
                          const title = root.querySelector('h1, .page-view-title').getBoundingClientRect();
                          return {
                            head: [Math.round(head.left), Math.round(head.width)],
                            content: [Math.round(content.left), Math.round(content.width)],
                            titleLeft: Math.round(title.left),
                          };
                        }"""
                    )
            reference = geometries["scheduled"]
            for view, geometry in geometries.items():
                assert abs(geometry["head"][0] - reference["head"][0]) <= 1, (
                    label,
                    view,
                    geometries,
                )
                assert abs(geometry["head"][1] - reference["head"][1]) <= 1, (
                    label,
                    view,
                    geometries,
                )
                assert abs(geometry["titleLeft"] - reference["titleLeft"]) <= 1, (
                    label,
                    view,
                    geometries,
                )

            page.evaluate("window._navigateTo('chat')")
            page.wait_for_selector("#chat:visible")
            if width < 700:
                page.locator("body").evaluate("el => el.classList.add('sidebar-hidden')")
            page.locator("#perm-mode-btn").click()
            page.locator('#perm-menu [data-v="full_access"]').click()
            assert page.locator("#perm-mode-btn").evaluate(
                """el => {
                  const probe = document.createElement('span');
                  probe.style.color = 'var(--signal)';
                  document.body.append(probe);
                  const same = getComputedStyle(el).color === getComputedStyle(probe).color;
                  probe.remove();
                  return same;
                }"""
            )
            page.locator("#effort-btn").click()
            menu = page.locator("#perm-menu.effort-menu")
            menu.wait_for(state="visible")
            box = menu.bounding_box()
            assert box is not None
            assert box["x"] >= 8 and box["y"] >= 8, (label, box)
            assert box["x"] + box["width"] <= width - 8, (label, box, width)
            assert box["y"] + box["height"] <= height - 8, (label, box, height)
            assert menu.evaluate("el => el.scrollHeight >= el.clientHeight")
            page.keyboard.press("End")
            assert menu.locator("button").last.evaluate("el => el === document.activeElement")
            page.keyboard.press("Escape")
            assert menu.is_hidden()
            context.close()
        browser.close()

    if errors:
        raise AssertionError("Aide layout browser errors:\n" + "\n".join(errors))
    print("Aide shared tool layout and 200% zoom effort menu gate passed")


if __name__ == "__main__":
    run()
