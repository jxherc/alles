"""settings automations UI smoke on an owned server (PORT, default 8897)."""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

AIDE = f"http://aide.localhost:{os.environ.get('PORT', '8897')}"
EVID = Path(
    os.environ.get("ALLES_BROWSER_ARTIFACTS")
    or Path(__file__).resolve().parent.parent / "docs" / "evidence" / "automations"
)
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def wait_js(pg, expr, timeout=8.0):
    # the app's csp has no unsafe-eval, so wait_for_function with a string can't run; poll instead
    end = time.monotonic() + timeout
    while not pg.evaluate(f"() => Boolean({expr})"):
        if time.monotonic() > end:
            raise TimeoutError(expr)
        pg.wait_for_timeout(100)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )
        pg.on(
            "pageerror",
            lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )

        pg.goto(f"{AIDE}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".app", timeout=15000)
        wait_js(pg, "typeof window._openSettings === 'function'")
        pg.evaluate(
            """async () => {
                const rules = await fetch('/api/automations').then(r => r.json());
                for (const rule of rules) await fetch('/api/automations/' + rule.id, {method:'DELETE'});
            }"""
        )

        pg.evaluate("window._openSettings('rules')")
        pg.wait_for_selector("#settings-modal .s-modal", timeout=8000)
        pg.wait_for_selector("#s-pane-rules.active #rule-add-btn", timeout=8000)
        wait_js(pg, "document.getElementById('rule-trigger')?.dataset.populated === '1'")
        r["rules_pane_opens"] = pg.is_visible("#s-pane-rules.active")
        # the list renders after its own read; under load it can still be empty here
        wait_js(
            pg, "document.querySelector('#rules-list .settings-row-empty, #rules-list .rule-row')"
        )
        r["empty_state_shows"] = "no rules yet" in (pg.text_content("#rules-list") or "")

        # use the local-only push preset; no external channel or model call
        pg.click(".rule-preset-pick")
        pg.click('.custom-dropdown-option[data-index="3"]')
        wait_js(
            pg,
            "document.getElementById('rule-trigger')?.dataset.value === 'sub_renewing' && "
            "document.getElementById('rule-action')?.dataset.value === 'push'",
        )
        r["preset_prefills"] = pg.input_value(
            "#rule-trigger-arg"
        ) == "3" and "renews in 3 days" in pg.input_value("#rule-action-arg")

        pg.fill("#rule-name", "audit renewal reminder")
        pg.click("#rule-add-btn")
        wait_js(
            pg,
            "document.querySelector('#rules-list')?.textContent.includes('audit renewal reminder')",
        )
        r["rule_add_lists"] = pg.query_selector("#rules-list .rule-row") is not None

        # since the afterlife 2e migration (ccdda121) a new rule becomes an aide scheduled workflow
        # that waits for review: it stays off, and the server refuses to fire it (409, pinned by
        # test_automations and test_jarvis_events_automation). the pane must not claim it fired.
        saved = pg.evaluate("fetch('/api/automations').then(r => r.json()).then(l => l[0])")
        r["new_rule_waits_for_review"] = (
            saved["migration_state"] == "needs_review"
            and saved["enabled"] is False
            and pg.query_selector("#rules-list .rule-row.off") is not None
        )
        with pg.expect_response(lambda res: res.url.endswith("/test")) as fired:
            pg.click("#rules-list .rule-row [data-act='test']")
        answer = fired.value
        wait_js(pg, "document.querySelector('.toast')")
        r["test_refused_for_review"] = (
            answer.status == 409 and "reviewed in Aide scheduled" in answer.text()
        )
        r["test_never_claims_fired"] = not pg.evaluate(
            "[...document.querySelectorAll('.toast')].some(t => "
            "t.textContent.includes('rule fired'))"
        )
        attempts = pg.evaluate(
            f"fetch('/api/automations/{saved['id']}/attempts').then(r => r.json())"
        )
        r["refused_test_records_no_attempt"] = attempts == []

        pg.click("#rules-list .rule-row-main")
        wait_js(pg, "document.getElementById('rule-add-btn')?.textContent.includes('save')")
        pg.fill("#rule-name", "audit renewal edited")
        pg.click("#rule-add-btn")
        wait_js(
            pg,
            "document.querySelector('#rules-list')?.textContent.includes('audit renewal edited')",
        )
        r["edit_updates_row"] = "audit renewal edited" in (pg.text_content("#rules-list") or "")
        pg.screenshot(path=str(EVID / "automation-rules.png"))

        pg.click("#rules-list .rule-row [data-act='del']")
        pg.wait_for_selector("#rules-list .settings-row-empty", timeout=5000)
        r["delete_returns_empty"] = "no rules yet" in (pg.text_content("#rules-list") or "")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_automations_settings.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
