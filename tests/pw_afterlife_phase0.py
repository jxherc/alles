"""Phase 0 desktop/mobile browser baseline.

Run against an isolated server, for example:

    ALLES_DATA=/tmp/alles-phase0 PORT=8899 AUTH_ENABLED=false python app.py
    ALLES_DATA=/tmp/alles-phase0 PHASE0_PORT=8899 python tests/pw_afterlife_phase0.py

Only synthetic rows are added to that throwaway database.
"""

import os
import sys
from datetime import UTC, datetime

from playwright.sync_api import Page, Route, sync_playwright

from core.database import (
    AutomationAttempt,
    AutomationRule,
    ScheduledMail,
    SessionLocal,
)

PORT = os.environ.get("PHASE0_PORT", os.environ.get("PORT", "8899"))
BASE = f"localhost:{PORT}"
HOSTS = {
    "": ("alles", "today-view"),
    "aide": ("aide", "chat"),
    "mail": ("inbox", "mail-view"),
    "docs": ("docs", "wiki-view"),
    "gallery": ("files", "photos-view"),
    "calendar": ("plan", "calendar-view"),
    "tasks": ("plan", "tasks-view"),
    "subs": ("finance", "subs-view"),
    "money": ("finance", "money-view"),
    "days": ("days", "days-view"),
    "journal": ("docs", "docs-journal-section"),
    "activity": ("alles", "activity-view"),
    "system": ("server", "system-view"),
    "watch": ("watch", "watch-view"),
    "habits": ("health", "habits-view"),
    "read": ("library", "read-view"),
    "books": ("library", "books-view"),
    "health": ("health", "health-view"),
    "files": ("files", "files-view"),
    "contacts": ("inbox", "contacts-view"),
    "secrets": ("passwords", "vault-view"),
}


def _seed_synthetic_rows() -> None:
    with SessionLocal() as db:
        old_rules = db.query(AutomationRule).filter_by(name="phase zero failed delivery").all()
        for old_rule in old_rules:
            db.query(AutomationAttempt).filter_by(rule_id=old_rule.id).delete()
            db.delete(old_rule)
        db.query(ScheduledMail).filter_by(subject="synthetic uncertain delivery").delete()
        now = datetime.now(UTC).replace(tzinfo=None)
        rule = AutomationRule(
            name="phase zero failed delivery",
            trigger="daily_at",
            trigger_arg="08:00",
            action="notify",
            action_arg="synthetic check",
        )
        db.add(rule)
        db.flush()
        db.add(
            AutomationAttempt(
                rule_id=rule.id,
                occurrence_key="0" * 64,
                status="failed",
                action="notify",
                error="no delivery channel configured",
                started_at=now,
                finished_at=now,
            )
        )
        db.add(
            ScheduledMail(
                account_id="phase-zero-synthetic",
                to="receiver@example.test",
                subject="synthetic uncertain delivery",
                send_at="2026-01-01T08:00:00",
                status="uncertain",
            )
        )
        db.commit()


def _wire(page: Page, errors: list[str], server_errors: list[str]) -> None:
    def on_console(message) -> None:
        text = message.text
        ignored = ("favicon", "ERR_", "Failed to load resource", "net::", "Load failed")
        if message.type == "error" and not any(part in text for part in ignored):
            errors.append(text)

    page.on("console", on_console)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "response",
        lambda response: (
            server_errors.append(f"{response.status} {response.url}")
            if response.status >= 500 and response.url.startswith("http")
            else None
        ),
    )


def _mock_mail(route: Route) -> None:
    url = route.request.url
    if "/api/mail/accounts" in url:
        route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id":"phase-zero-synthetic","name":"synthetic","email":"qa@example.test"}]',
        )
    elif "/api/mail/inbox/" in url:
        route.fulfill(status=200, content_type="application/json", body='{"messages":[]}')
    else:
        route.continue_()


def _url(subdomain: str) -> str:
    host = f"{subdomain}.localhost" if subdomain else "localhost"
    return f"http://{host}:{PORT}/"


def _check_hosts(browser, viewport: dict, mobile: bool, results: dict[str, bool]) -> None:
    label = "mobile" if mobile else "desktop"
    context = browser.new_context(
        viewport=viewport,
        is_mobile=mobile,
        reduced_motion="reduce",
    )
    errors: list[str] = []
    server_errors: list[str] = []
    try:
        for subdomain, (app_name, view_id) in HOSTS.items():
            page = context.new_page()
            _wire(page, errors, server_errors)
            if subdomain == "mail":
                page.route("**/api/mail/**", _mock_mail)
            page.goto(_url(subdomain), wait_until="domcontentloaded")
            page.wait_for_selector(".app", timeout=20_000)
            page.wait_for_selector(f"#{view_id}", state="visible", timeout=15_000)
            page.wait_for_timeout(120)
            key = subdomain or "hub"
            results[f"{label}_{key}_scope"] = (
                page.locator("body").get_attribute("data-app") == app_name
            )
            overflow = page.evaluate(
                "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) "
                "- window.innerWidth"
            )
            results[f"{label}_{key}_fits"] = overflow <= 2
            results[f"{label}_{key}_reduced_motion"] = page.evaluate(
                "matchMedia('(prefers-reduced-motion: reduce)').matches"
            )
            page.close()
    finally:
        context.close()
    results[f"{label}_zero_console_errors"] = not errors
    results[f"{label}_zero_server_errors"] = not server_errors
    if errors:
        print(f"{label} console errors: {errors[:10]}")
    if server_errors:
        print(f"{label} server errors: {server_errors[:10]}")


def _check_changed_surfaces(browser, results: dict[str, bool]) -> None:
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        reduced_motion="reduce",
    )
    errors: list[str] = []
    server_errors: list[str] = []
    try:
        aide = context.new_page()
        _wire(aide, errors, server_errors)
        aide.goto(_url("aide"), wait_until="domcontentloaded")
        aide.wait_for_function("typeof window._openSettings === 'function'")
        aide.evaluate("window._openSettings('rules')")
        aide.wait_for_selector("#s-pane-rules.active .rule-row", timeout=15_000)
        results["automation_failed_attempt_visible"] = "last attempt: failed" in (
            aide.locator("#rules-list").inner_text()
        )
        aide.keyboard.press("Tab")
        results["keyboard_focus_reaches_control"] = aide.evaluate(
            "document.activeElement && document.activeElement !== document.body"
        )
        aide.close()

        mail = context.new_page()
        _wire(mail, errors, server_errors)
        mail.route("**/api/mail/**", _mock_mail)
        mail.goto(_url("mail"), wait_until="domcontentloaded")
        mail.wait_for_selector("#mail-scheduled .mail-sched-chip", timeout=15_000)
        outbox = mail.locator("#mail-scheduled").inner_text()
        results["uncertain_outbox_visible"] = (
            "delivery uncertain" in outbox and "synthetic uncertain delivery" in outbox
        )
        mail.close()
    finally:
        context.close()
    results["changed_surfaces_zero_console_errors"] = not errors
    results["changed_surfaces_zero_server_errors"] = not server_errors
    if errors:
        print(f"changed-surface console errors: {errors[:10]}")
    if server_errors:
        print(f"changed-surface server errors: {server_errors[:10]}")


def main() -> int:
    if not os.environ.get("ALLES_DATA"):
        print("ALLES_DATA must point to the isolated server data directory", file=sys.stderr)
        return 2
    _seed_synthetic_rows()
    results: dict[str, bool] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            _check_hosts(
                browser,
                viewport={"width": 1280, "height": 800},
                mobile=False,
                results=results,
            )
            _check_hosts(
                browser,
                viewport={"width": 390, "height": 844},
                mobile=True,
                results=results,
            )
            _check_changed_surfaces(browser, results)
        finally:
            browser.close()

    failed = [name for name, passed in results.items() if not passed]
    print(f"{len(results) - len(failed)}/{len(results)} browser assertions passed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
