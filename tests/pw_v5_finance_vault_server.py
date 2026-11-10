"""Focused real-app gate for KOKUEN v5 Finance, Vault, and Server recovery paths."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Page, Route, sync_playwright

PORT = os.environ.get("PORT", "8145")
BASE = f"http://127.0.0.1:{PORT}"
MASTER = "browser-v5-master-password"


def _require_throwaway_data_root() -> None:
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    if os.environ.get("ALLES_TEST_DATA") != "1" or len(run_id) < 16:
        raise RuntimeError("missing isolated test ownership proof")
    temp_root = Path(tempfile.gettempdir()).resolve()
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be below the system temporary directory")
    if (data / ".alles-test-owner").read_text("utf-8").strip() != run_id:
        raise RuntimeError("test ownership sentinel does not match")
    require_server_ownership(BASE, run_id)


def _api(path: str, body: dict, token: str | None = None) -> dict:
    headers = {"content-type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def _seed_vault() -> None:
    token = _api("/api/vault/unlock", {"password": MASTER})["token"]
    _api(
        "/api/vault",
        {
            "name": "deploy key",
            "type": "ssh",
            "fields": {
                "private_key": "-----BEGIN PRIVATE KEY-----\nsecret material\n-----END PRIVATE KEY-----",
                "public_key": "ssh-ed25519 public",
            },
        },
        token,
    )
    _api(
        "/api/vault",
        {
            "name": "test card",
            "type": "card",
            "fields": {"number": "4242424242424242", "cvv": "123", "expiry": "12/30"},
        },
        token,
    )


def _seed_money() -> None:
    account = _api(
        "/api/money/accounts",
        {"name": "browser checking", "kind": "checking", "opening": 100},
    )
    _api(
        "/api/money/transactions",
        {
            "account_id": account["id"],
            "date": date.today().isoformat(),
            "amount": -12.5,
            "category": "verification",
            "payee": "browser target",
            "tags": "browser",
        },
    )


def _wait_app(page: Page) -> None:
    # a fresh data folder opens on setup (first run); this gate is about finance, vault, server
    assert page.request.post(f"{BASE}/api/setup/dismiss").ok
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_function("typeof window._navigateTo === 'function'")


def _finance_recent_owner(page: Page) -> None:
    state = {"writes": 0, "reauth": 0}

    def actual(route: Route) -> None:
        request = route.request
        path = urlparse(request.url).path
        if request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "service": {
                            "available": True,
                            "installed": True,
                            "running": True,
                            "healthy": True,
                            "owned": True,
                            "version": "26.7.0",
                        },
                        "ledger": {"mode": "alles", "base_currency_code": "CAD"},
                    }
                ),
            )
            return
        if path == "/api/finance/actual/service/backup":
            state["writes"] += 1
            if state["writes"] == 1:
                route.fulfill(
                    status=403,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "code": "recent_auth_required",
                            "message": "recent owner authentication required",
                        }
                    ),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"backup_id": "browser-proof"}),
                )
            return
        route.continue_()

    def auth(route: Route) -> None:
        path = urlparse(route.request.url).path
        if path == "/api/auth/me":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"enabled": True}),
            )
            return
        if path == "/api/auth/reauth":
            state["reauth"] += 1
            route.fulfill(status=200, content_type="application/json", body="{}")
            return
        route.continue_()

    page.route("**/api/finance/actual**", actual)
    page.route("**/api/auth/**", auth)
    page.evaluate("window._navigateTo('finance')")
    page.locator("#finance-view").wait_for(state="visible")
    page.get_by_role("link", name="ledger setup", exact=True).click()
    row = page.locator("#s-ledger .conn-catalog-row .btn")
    page.locator(
        "#s-ledger .conn-catalog-row .btn, #s-ledger .finance-actual-panel"
    ).first.wait_for(state="visible")
    if row.count():
        row.click()
    page.locator("#s-ledger .finance-actual-panel").wait_for(state="visible")
    backup = page.get_by_role("button", name="create backup")
    backup.focus()
    backup.press("Enter")
    prompt = page.locator(".dialog-overlay")
    prompt.wait_for(state="visible")
    prompt.locator(".dialog-input").fill("local-test-password")
    prompt.get_by_role("button", name="continue").click()
    page.locator(".finance-actual-message").filter(has_text="browser-proof verified").wait_for()
    assert state == {"writes": 2, "reauth": 1}, state
    assert backup.get_attribute("aria-busy") is None
    page.locator("#settings-modal").press("Escape")
    page.locator("#settings-modal").wait_for(state="hidden")
    page.unroute("**/api/finance/actual**", actual)
    page.unroute("**/api/auth/**", auth)


def _finance_money_keyboard_targets(page: Page) -> None:
    page.evaluate("window._navigateTo('money')")
    page.locator("#money-view").wait_for(state="visible")
    row = page.locator(".txn[data-id]").first
    row.wait_for(state="visible")
    edit = row.locator("[data-edit-txn]")
    tag = row.locator(".tx-tag")
    for control in (edit, tag):
        box = control.bounding_box()
        assert box and box["width"] >= 44 and box["height"] >= 44, box
    edit.focus()
    edit.press("Enter")
    editor = page.locator(".txn-edit")
    editor.wait_for(state="visible")
    assert editor.get_by_role("button", name="save").bounding_box()["height"] >= 44
    editor.locator("[data-cancel-txn]").click()


def _opener(page: Page, name: str):
    """an entry's open button. it is named by its own words (label in name), the entry's name
    then its type, so it is found by the name it shows"""
    return page.locator("[data-vault-open]").filter(
        has=page.locator(".vault-entry-name", has_text=name)
    )


def _vault_keyboard_focus_and_recovery(page: Page) -> None:
    page.evaluate("window._navigateTo('vault')")
    page.locator("#vault-workbench-view").wait_for(state="visible")
    page.locator("#vault-pw-input").fill(MASTER)
    page.locator("#vault-unlock-btn").click()
    page.locator("[data-vault-open]").first.wait_for()

    opener = _opener(page, "deploy key")
    assert opener.count() == 1
    assert opener.get_attribute("aria-label") is None
    assert opener.evaluate("element => element.textContent.trim()").startswith("deploy key")
    opener.focus()
    opener.press("Enter")
    dialog = page.locator(".vault-modal [role=dialog]")
    dialog.wait_for(state="visible")
    private_key = dialog.locator("#vf-f-private_key")
    assert private_key.evaluate("element => getComputedStyle(element).webkitTextSecurity") == "disc"
    assert private_key.input_value().startswith("-----BEGIN PRIVATE KEY-----")
    dialog.locator("#vf-name").focus()
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement?.id") == "vf-save"
    page.keyboard.press("Escape")
    assert opener.evaluate("element => document.activeElement === element")

    card = _opener(page, "test card")
    card.press("Enter")
    dialog.wait_for(state="visible")
    assert dialog.locator("#vf-f-cvv").get_attribute("type") == "password"
    page.keyboard.press("Escape")

    def fail_entries(route: Route) -> None:
        if route.request.method == "GET" and urlparse(route.request.url).path == "/api/vault":
            route.fulfill(status=503, content_type="application/json", body='{"message":"offline"}')
        else:
            route.continue_()

    page.route("**/api/vault", fail_entries)
    page.evaluate("window._navigateTo('vault')")
    error = page.locator(".vault-load-error")
    error.wait_for(state="visible")
    assert "unlocked session is unchanged" in error.inner_text()
    assert page.locator("#vault-unlocked").is_visible()
    page.unroute("**/api/vault", fail_entries)
    error.get_by_role("button", name="retry loading entries").click()
    _opener(page, "deploy key").wait_for()


def _server_choice_rollback(page: Page) -> None:
    def fail_patch(route: Route) -> None:
        if route.request.method == "PATCH":
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"message": "settings temporarily unavailable"}),
            )
        else:
            route.continue_()

    page.route("**/api/settings", fail_patch)
    page.evaluate("window._navigateTo('server-search')")
    # more than 3 providers: the list is the dropdown (choice controls rule), so a failed save
    # puts the old pick back in the trigger and says why
    pick = page.get_by_role("combobox", name="primary search provider")
    pick.wait_for(state="visible")
    previous_value = pick.get_attribute("data-value")
    previous_label = pick.inner_text().strip()
    pick.click()
    panel = page.locator(".custom-dropdown-panel")
    target = panel.locator('[role="option"][aria-selected="false"]').first
    target.click()
    page.locator(".server-workbench-status.is-error").wait_for(state="visible")
    assert pick.get_attribute("data-value") == previous_value
    assert pick.inner_text().strip() == previous_label
    assert not pick.is_disabled()
    page.unroute("**/api/settings", fail_patch)


def run() -> None:
    _require_throwaway_data_root()
    _seed_vault()
    _seed_money()
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.on(
            "pageerror",
            lambda error: errors.append(str(error)),
        )
        page.on(
            "console",
            lambda message: (
                errors.append(message.text)
                if message.type == "error" and "Failed to load resource" not in message.text
                else None
            ),
        )
        _wait_app(page)
        _finance_recent_owner(page)
        _finance_money_keyboard_targets(page)
        _vault_keyboard_focus_and_recovery(page)
        _server_choice_rollback(page)
        assert (
            page.locator(
                'select:visible, input[type="checkbox"]:visible, input[type="radio"]:visible'
            ).count()
            == 0
        )
        assert not errors, errors
        context.close()
        browser.close()
    print(
        "KOKUEN v5 Finance/Vault/Server gate passed recent-owner retry, Finance 44px keyboard targets, exact focus return, "
        "keyboard rows, masked secrets, persistent Vault recovery, Server rollback, reduced motion, "
        "native-choice exclusion, and clean unexpected-console checks"
    )


if __name__ == "__main__":
    run()
