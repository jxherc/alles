"""settings automations UI smoke. :8897."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AIDE = "http://aide.localhost:8897"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "automations"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


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
        pg.wait_for_function("typeof window._openSettings === 'function'")
        pg.evaluate(
            """async () => {
                const rules = await fetch('/api/automations').then(r => r.json());
                for (const rule of rules) await fetch('/api/automations/' + rule.id, {method:'DELETE'});
            }"""
        )

        pg.evaluate("window._openSettings('rules')")
        pg.wait_for_selector("#settings-modal .s-modal", timeout=8000)
        pg.wait_for_selector("#s-pane-rules.active #rule-add-btn", timeout=8000)
        pg.wait_for_function("document.getElementById('rule-trigger')?.dataset.populated === '1'")
        r["rules_pane_opens"] = pg.is_visible("#s-pane-rules.active")
        r["empty_state_shows"] = "no rules yet" in (pg.text_content("#rules-list") or "")

        # use the local-only push preset; no external channel or model call
        pg.click('.rule-preset[data-i="3"]')
        pg.wait_for_function(
            "document.getElementById('rule-trigger')?.dataset.value === 'sub_renewing' && "
            "document.getElementById('rule-action')?.dataset.value === 'push'"
        )
        r["preset_prefills"] = (
            pg.input_value("#rule-trigger-arg") == "3"
            and "renews in 3 days" in pg.input_value("#rule-action-arg")
        )

        pg.fill("#rule-name", "audit renewal reminder")
        pg.click("#rule-add-btn")
        pg.wait_for_function(
            "document.querySelector('#rules-list')?.textContent.includes('audit renewal reminder')"
        )
        r["rule_add_lists"] = pg.query_selector("#rules-list .rule-row") is not None

        pg.click("#rules-list .rule-row [data-act='test']")
        pg.wait_for_function(
            "[...document.querySelectorAll('.toast')].some(t => "
            "t.textContent.includes('rule fired'))"
        )
        r["test_button_fires"] = pg.evaluate(
            "[...document.querySelectorAll('.toast')].some(t => "
            "t.textContent.includes('rule fired'))"
        )

        pg.click("#rules-list .rule-row [data-act='toggle']")
        pg.wait_for_selector("#rules-list .rule-row.off", timeout=5000)
        r["pause_marks_off"] = pg.query_selector("#rules-list .rule-row.off") is not None
        pg.click("#rules-list .rule-row.off [data-act='toggle']")
        pg.wait_for_function(
            "!document.querySelector('#rules-list .rule-row')?.classList.contains('off')"
        )
        r["resume_marks_on"] = pg.query_selector("#rules-list .rule-row.off") is None

        pg.click("#rules-list .rule-row-main")
        pg.wait_for_function("document.getElementById('rule-add-btn')?.textContent.includes('save')")
        pg.fill("#rule-name", "audit renewal edited")
        pg.click("#rule-add-btn")
        pg.wait_for_function(
            "document.querySelector('#rules-list')?.textContent.includes('audit renewal edited')"
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
