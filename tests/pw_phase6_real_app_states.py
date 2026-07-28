"""Runtime state regressions for every real specialist app.

The layout matrix proves shell, theme, reduced-motion, and overflow behavior.  This
second gate proves that each real screen exposes a live loading state, a usable
empty/ready screen, keyboard focus, hover stability, and a readable fatal error.
It deliberately does not inspect the Apps launcher or a mockup.
"""

import os

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
    "health-log": "health-view",
}

# These screens combine multiple independent sources, so one failed source can
# leave the rest of the screen useful. The remaining specialist screens have a
# single primary source and honestly move between ready/empty and error instead
# of inventing a partial state that contains no surviving data.
PARTIAL_APPS = {
    "calendar",
    "wiki",
    "files",
    "mail",
    "photos",
    "subs",
    "money",
    "journal",
    "system",
    "watch",
    "read",
    "health-log",
}

PARTIAL_SOURCE = {
    "calendar": "/api/calendars",
    "wiki": "/api/vault-md/tree",
    "files": "/api/files/offline",
    "mail": "/api/settings",
    "photos": "/api/photos/list",
    "subs": "/api/subscriptions",
    "money": "/api/money/recurring",
    "journal": "/api/vault-md/tree",
    "system": "/api/system/stats",
    "watch": "/api/watch/overview",
    "read": "/api/read?",
    "health-log": "/api/health/overview",
}


def _new_page(browser):
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"page: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"console: {message.text}") if message.type == "error" else None
        ),
    )
    # The app intentionally keeps live connections open. Waiting for networkidle
    # makes the test depend on those connections closing, which they never do.
    page.goto(BASE, wait_until="domcontentloaded")
    # _navigateTo is exported before the async boot finishes. Navigating as soon
    # as that symbol exists races the boot route, which then restores Home and
    # hides the specialist view. Wait for the real shell to finish booting.
    page.wait_for_function(
        "typeof window._navigateTo === 'function' && !document.body.classList.contains('preboot')",
        timeout=15_000,
    )
    return context, page, errors


def run() -> None:
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        for view, element_id in APPS.items():
            context, page, errors = _new_page(browser)
            initial_state = page.evaluate(
                """args => {
                  window._navigateTo(args.view);
                  return document.querySelector(`#${args.elementId} > .specialist-state`)?.dataset.state || '';
                }""",
                {"view": view, "elementId": element_id},
            )
            root = page.locator(f"#{element_id}")
            try:
                root.wait_for(state="visible", timeout=5_000)
                state = root.locator(":scope > .specialist-state")
                if initial_state != "loading":
                    failures.append(f"{view}: initial state is not loading")
                page.wait_for_function(
                    "id => document.querySelector('#' + id)?.getAttribute('aria-busy') === 'false'",
                    arg=element_id,
                    timeout=8_000,
                )
            except Exception as exc:  # noqa: BLE001 - aggregate every app failure
                failures.append(f"{view}: loading state failed ({exc})")
                context.close()
                continue

            live = root.evaluate(
                """root => {
                  const text = root.innerText.trim();
                  const eligible = [...root.querySelectorAll(
                    'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), [tabindex="0"]'
                  )].find(el => {
                    const s = getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                  });
                  if (eligible) {
                    eligible.focus();
                    eligible.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                  }
                  return {
                    text,
                    focusable: Boolean(eligible),
                    focused: Boolean(eligible && document.activeElement === eligible),
                    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                  };
                }"""
            )
            if len(live["text"]) < 8:
                failures.append(f"{view}: ready/empty screen has no readable content")
            if not live["focusable"] or not live["focused"]:
                failures.append(f"{view}: ready/empty screen has no working keyboard target")
            if live["overflow"] > 1:
                failures.append(f"{view}: hover/focus caused horizontal overflow")
            if errors:
                failures.append(f"{view}: ready/empty screen logged errors {errors}")
            context.close()

            if view in PARTIAL_APPS:
                context, page, errors = _new_page(browser)
                failed_source = {"active": True}

                def fail_one_source(route):
                    if PARTIAL_SOURCE[view] not in route.request.url:
                        route.continue_()
                        return
                    if not failed_source["active"]:
                        route.continue_()
                        return
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"phase 6 partial-source failure"}',
                    )

                page.route("**/api/**", fail_one_source)
                page.evaluate("view => window._navigateTo(view)", view)
                root = page.locator(f"#{element_id}")
                try:
                    root.wait_for(state="visible", timeout=5_000)
                    page.wait_for_function(
                        "id => document.querySelector('#' + id)?.getAttribute('aria-busy') === 'false'",
                        arg=element_id,
                        timeout=8_000,
                    )
                    state = root.locator(':scope > .specialist-state[data-state="partial"]')
                    state.wait_for(state="visible", timeout=2_000)
                    if "unavailable" not in state.inner_text().strip().lower():
                        failures.append(f"{view}: partial state is not readable")
                    retry = state.locator("button")
                    if retry.count() != 1 or not retry.is_enabled():
                        failures.append(f"{view}: partial state has no enabled retry")
                    else:
                        failed_source["active"] = False
                        retry.click()
                        state.wait_for(state="hidden", timeout=8_000)
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                    )
                    if overflow > 1:
                        failures.append(f"{view}: partial state caused horizontal overflow")
                except Exception as exc:  # noqa: BLE001 - aggregate every app failure
                    failures.append(f"{view}: partial state failed ({exc})")
                unexpected_errors = [
                    error
                    for error in errors
                    if "Failed to load resource: the server responded with a status of 503"
                    not in error
                ]
                if unexpected_errors:
                    failures.append(f"{view}: partial state logged errors {unexpected_errors}")
                context.close()

            context, page, errors = _new_page(browser)
            page.route(
                "**/api/**",
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"phase 6 forced failure"}',
                ),
            )
            page.evaluate("view => window._navigateTo(view)", view)
            root = page.locator(f"#{element_id}")
            try:
                root.wait_for(state="visible", timeout=5_000)
                state = root.locator(':scope > .specialist-state[data-state="error"]')
                state.wait_for(state="visible", timeout=5_000)
                text = state.inner_text().strip().lower()
                if "couldn" not in text and "failed" not in text and "unavailable" not in text:
                    failures.append(f"{view}: fatal state is not readable ({text!r})")
                retry = state.locator("button")
                if retry.count() != 1 or not retry.is_enabled():
                    failures.append(f"{view}: fatal state has no enabled retry")
            except Exception as exc:  # noqa: BLE001 - aggregate every app failure
                failures.append(f"{view}: fatal error state failed ({exc})")
            context.close()

        browser.close()

    if failures:
        raise AssertionError("real specialist app state regressions:\n" + "\n".join(failures))
    print(
        "all 19 real specialist apps passed loading, empty/ready, focus, hover, and "
        "error gates; all 12 multi-source apps passed partial and retry gates"
    )


if __name__ == "__main__":
    run()
