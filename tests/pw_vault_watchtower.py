"""Owned Vault scan availability, cancellation, malformed replies and TOTP display."""

import json
import os
import re
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    password = "synthetic-watchtower-master-only"
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        seed = pw.request.new_context()
        assert seed.post(base + "/api/setup/dismiss").ok
        unlocked = seed.post(base + "/api/vault/unlock", data={"password": password})
        assert unlocked.ok, unlocked.text()
        headers = {"X-Vault-Token": unlocked.json()["token"]}
        for name, fields in (
            ("Weak fixture", {"password": "123"}),
            ("Reuse fixture A", {"password": "Shared-synthetic-123!"}),
            ("Reuse fixture B", {"password": "Shared-synthetic-123!"}),
            (
                "TOTP fixture",
                {"password": "Unique-synthetic-456!", "totp": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"},
            ),
        ):
            result = seed.post(
                base + "/api/vault",
                headers=headers,
                data={"name": name, "type": "login", "fields": fields},
            )
            assert result.ok, result.text()
        seed.dispose()
        for name, width, forced in (
            ("desktop", 1440, "none"),
            ("tablet", 768, "none"),
            ("phone", 390, "none"),
            ("high-contrast", 1440, "active"),
        ):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                has_touch=width == 390,
                service_workers="block",
                reduced_motion="reduce",
                forced_colors=forced,
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_default_timeout(10000)
            page.goto(base + "/?view=vault", wait_until="networkidle")

            def unlock():
                page.locator("#vault-pw-input").fill(password)
                page.locator("#vault-unlock-btn").click()
                expect(page.locator(".vault-entry-main", has_text="TOTP fixture")).to_be_visible()

            unlock()
            page.locator(".vault-entry-main", has_text="TOTP fixture").click()
            expect(page.locator(".vault-totp-code")).to_have_text(
                re.compile(r"\s*\d{3}\s*\d{3}\s*")
            )
            expect(page.locator(".vault-totp-secs")).to_contain_text("s")
            page.screenshot(path=str(output / f"{name}-totp.png"))
            page.locator("#vf-cancel").click()
            scan = page.locator("#vault-watchtower-btn")
            scan.focus()
            scan.press("Enter")
            expect(page.locator("#vault-wt")).to_be_visible()
            expect(page.locator("#vault-wt")).to_contain_text("breach check incomplete")
            expect(page.locator("#vault-wt")).to_contain_text("Weak fixture")
            expect(page.locator("#vault-wt")).to_contain_text("Reuse fixture A")
            expect(page.locator("#vault-wt .wt-section").first).not_to_contain_text("all clear")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(output / f"{name}-unavailable.png"))
            page.locator("#wt-back").click()

            pending = []
            page.route("**/api/vault/watchtower", lambda route: pending.append(route))
            scan.click()
            expect(page.locator("#vault-entry-list")).to_have_text("scanning…")
            assert len(pending) == 1
            scan.click()
            expect(page.locator(".vault-entry-main", has_text="TOTP fixture")).to_be_visible()
            late = {
                "weak": [{"name": "stale scan"}],
                "reused": [],
                "breached": [],
                "breach_check": {"status": "complete", "checked": 1, "total": 1},
            }
            pending.pop().fulfill(json=late)
            page.wait_for_load_state("networkidle")
            expect(page.locator("#vault-wt")).to_have_count(0)
            expect(page.locator("#vault-entry-list")).not_to_contain_text("stale scan")

            scan.click()
            expect(page.locator("#vault-entry-list")).to_have_text("scanning…")
            page.locator("#vault-lock-btn").click()
            pending.pop().fulfill(json=late)
            page.wait_for_load_state("networkidle")
            expect(page.locator("#vault-pw-input")).to_be_visible()
            expect(page.locator("#vault-wt")).to_have_count(0)
            expect(page.locator("#vault-entry-list")).to_be_empty()
            page.unroute("**/api/vault/watchtower")
            unlock()
            page.route("**/api/vault/watchtower", lambda route: route.fulfill(json={}))
            scan.click()
            expect(page.locator(".vault-entry-main", has_text="TOTP fixture")).to_be_visible()
            expect(page.locator("#vault-wt")).to_have_count(0)
            expect(page.locator("#toast-container")).to_contain_text("scan failed")
            assert not errors, errors
            results.append(
                {
                    "profile": name,
                    "status": "passed",
                    "totp": "synthetic known secret; browser shows code and countdown",
                    "breach_lookup": "blocked by protected server; local weak/reused checks real",
                    "cancel_and_lock_ignore_late_scan": True,
                    "malformed_response_rejected": True,
                    "page_errors": errors,
                }
            )
            (output / "scenarios.json").write_text(json.dumps(results, indent=2))
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
