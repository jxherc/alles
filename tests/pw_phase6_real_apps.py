"""Phase 6 browser regression matrix for the real specialist app screens.

This deliberately opens the application views themselves.  The Apps launcher and
standalone mockups are not accepted as evidence for this gate.
"""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8030")
BASE = f"http://127.0.0.1:{PORT}"

APPS = {
    "tasks": "tasks-view",
    "calendar": "calendar-view",
    "wiki": "wiki-view",
    "files": "files-view",
    "mail": "mail-view",
    "photos": "photos-view",
    "contacts": "contacts-view",
    "vault": "vault-view",
    "subs": "subs-view",
    "money": "money-view",
    "days": "days-view",
    "journal": "docs-journal-section",
    "activity": "activity-view",
    "system": "system-view",
    "watch": "watch-view",
    "habits": "habits-view",
    "read": "read-view",
    "books": "books-view",
    "health": "health-view",
}

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


def run() -> None:
    failures: list[str] = []
    screenshot_dir = os.environ.get("SCREENSHOT_DIR", "").strip()
    if screenshot_dir:
        Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        cases = (
            (1440, 1000, "desktop", "dark"),
            (1440, 1000, "desktop", "light"),
            (390, 844, "mobile", "dark"),
            (390, 844, "mobile", "light"),
        )
        for width, height, size, theme_name in cases:
            appearance = THEMES[theme_name]
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                service_workers="block",
            )
            context.add_init_script(
                "localStorage.setItem('alles-appearance', "
                + json.dumps(json.dumps(appearance))
                + ");"
            )
            page = context.new_page()
            case_errors: list[str] = []
            page.on("pageerror", lambda error: case_errors.append(f"page: {error}"))
            page.on(
                "console",
                lambda message: (
                    case_errors.append(f"console: {message.text}")
                    if message.type == "error"
                    else None
                ),
            )
            appearance_json = json.dumps(appearance)
            page.route(
                "**/api/appearance",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=appearance_json,
                ),
            )
            page.goto(BASE, wait_until="networkidle")
            page.wait_for_function(
                "theme => theme === 'light'"
                " ? document.documentElement.dataset.theme === 'light'"
                " : document.documentElement.dataset.theme !== 'light'",
                arg=theme_name,
            )
            # The shell loads app.js through a dynamic module import. Network idle can
            # happen just before that module exposes the router on a cold boot, so wait
            # for the application readiness signal we actually need.
            page.wait_for_function("typeof window._navigateTo === 'function'", timeout=15_000)

            reported_error_count = 0
            for view, element_id in APPS.items():
                page.evaluate("view => window._navigateTo(view)", view)
                root = page.locator(f"#{element_id}")
                try:
                    root.wait_for(state="visible", timeout=5_000)
                    page.wait_for_timeout(180)
                except Exception as exc:  # noqa: BLE001 - aggregate every screen in one run
                    failures.append(f"{size}/{theme_name}/{view}: did not open ({exc})")
                    continue

                metrics = root.evaluate(
                    """root => {
                      const box = root.getBoundingClientRect();
                      const style = getComputedStyle(root);
                      const native = [...root.querySelectorAll('select, input[type=checkbox], input[type=radio]')]
                        .filter(el => {
                          const s = getComputedStyle(el);
                          const r = el.getBoundingClientRect();
                          return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        });
                      const readableControls = [...root.querySelectorAll(
                        'button, a.btn, input:not([type=file]), textarea, .custom-select, [role=tab], [role=button]'
                      )].filter(el => {
                        const s = getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        const hasLabel = Boolean(
                          (el.textContent || '').trim()
                          || el.getAttribute('placeholder')
                          || el.getAttribute('aria-label')
                        );
                        return hasLabel && s.display !== 'none' && s.visibility !== 'hidden'
                          && r.width > 0 && r.height > 0 && !el.classList.contains('icon-btn');
                      }).map(el => ({
                        label: (el.textContent || el.getAttribute('placeholder') || el.getAttribute('aria-label') || '').trim().slice(0, 40),
                        size: parseFloat(getComputedStyle(el).fontSize),
                      }));
                      const title = root.querySelector('.page-view-title');
                      const titleStyle = title ? getComputedStyle(title) : null;
                      const titleBox = title ? title.getBoundingClientRect() : null;
                      const mailSidebar = root.id === 'mail-view'
                        ? root.querySelector('.mail-sidebar')
                        : null;
                      const mailSidebarStyle = mailSidebar ? getComputedStyle(mailSidebar) : null;
                      const mailSidebarBox = mailSidebar ? mailSidebar.getBoundingClientRect() : null;
                      return {
                        rootRight: box.right,
                        rootLeft: box.left,
                        rootWidth: box.width,
                        rootOverflow: root.scrollWidth - root.clientWidth,
                        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                        sidebarDisplay: getComputedStyle(document.querySelector('.sidebar')).display,
                        railDisplay: getComputedStyle(document.querySelector('#space-rail')).display,
                        bodySubapp: document.body.classList.contains('is-subapp'),
                        bodyAide: document.body.classList.contains('is-aide'),
                        crumbVisible: (() => {
                          const el = document.querySelector('#app-crumb');
                          const s = getComputedStyle(el);
                          return s.display !== 'none' && s.visibility !== 'hidden';
                        })(),
                        nativeControls: native.map(el => `${el.tagName.toLowerCase()}:${el.type || ''}:${el.id || el.className}`),
                        smallControls: readableControls.filter(item => item.size < 13).slice(0, 6),
                        titleSize: title && titleStyle.display !== 'none' && titleBox.width > 0
                          ? parseFloat(titleStyle.fontSize)
                          : null,
                        mailMobileLayout: mailSidebar ? {
                          width: mailSidebarBox.width,
                          flexDirection: mailSidebarStyle.flexDirection,
                        } : null,
                        animation: style.animationName,
                      };
                    }"""
                )
                prefix = f"{size}/{theme_name}/{view}"
                if not metrics["bodySubapp"] or metrics["bodyAide"]:
                    failures.append(f"{prefix}: wrong shell state {metrics}")
                if metrics["sidebarDisplay"] != "none" or metrics["railDisplay"] != "none":
                    failures.append(f"{prefix}: old global navigation is visible {metrics}")
                if not metrics["crumbVisible"]:
                    failures.append(f"{prefix}: app/home navigation is missing")
                if metrics["documentOverflow"] > 1 or metrics["rootOverflow"] > 1:
                    failures.append(f"{prefix}: horizontal overflow {metrics}")
                if metrics["rootLeft"] < -1 or metrics["rootRight"] > width + 1:
                    failures.append(f"{prefix}: root leaves the viewport {metrics}")
                if metrics["nativeControls"]:
                    failures.append(
                        f"{prefix}: visible native choice controls {metrics['nativeControls']}"
                    )
                if metrics["smallControls"]:
                    failures.append(
                        f"{prefix}: readable controls are below 13px {metrics['smallControls']}"
                    )
                if metrics["titleSize"] is not None and metrics["titleSize"] < 16:
                    failures.append(f"{prefix}: app heading is below 16px ({metrics['titleSize']})")
                if (
                    size == "mobile"
                    and view == "mail"
                    and (
                        metrics["mailMobileLayout"]["width"] < width - 2
                        or metrics["mailMobileLayout"]["flexDirection"] != "row"
                    )
                ):
                    failures.append(
                        f"{prefix}: folder navigation wastes the mobile width "
                        f"{metrics['mailMobileLayout']}"
                    )
                if metrics["animation"] not in ("none", ""):
                    failures.append(
                        f"{prefix}: reduced motion still animates root ({metrics['animation']})"
                    )
                if len(case_errors) > reported_error_count:
                    failures.append(
                        f"{prefix}: browser errors {case_errors[reported_error_count:]}"
                    )
                    reported_error_count = len(case_errors)
                if screenshot_dir:
                    page.screenshot(
                        path=str(Path(screenshot_dir) / f"{size}-{theme_name}-{view}.png"),
                        full_page=True,
                    )

            context.close()
        browser.close()

    if failures:
        raise AssertionError("real app browser regressions:\n" + "\n".join(failures))
    print("all 19 real specialist apps passed the phase 6 browser matrix")


if __name__ == "__main__":
    run()
