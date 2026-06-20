"""5d UI verification — rules panel, vacation responder, smart-reply (gated). :8845.
Run with ALLES_DATA pointing at the server's data dir."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

MAIL = "http://mail.localhost:8845"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "5d"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "_seed_mail.py")],
        check=True,
        capture_output=True,
        text=True,
    )
    aid = res.stdout.strip().splitlines()[-1]
    msgs = [
        {
            "account_id": aid,
            "uid": "2",
            "folder": "INBOX",
            "from": "Bob <bob@x.com>",
            "subject": "Project plan",
            "date": "2026-06-17",
            "date_ts": datetime(2026, 6, 17, tzinfo=timezone.utc).timestamp(),
            "seen": True,
            "flagged": False,
            "list_unsubscribe": "",
            "account_name": "Test",
        }
    ]
    prime = f"localStorage.setItem('mail-cache-{aid}-inbox', {json.dumps(json.dumps(msgs))});"

    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        ctx.add_init_script(prime)
        pg = ctx.new_page()
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

        pg.goto(f"{MAIL}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#mail-rules-btn", timeout=15000)

        # clear rules for idempotency
        pg.evaluate(
            "async () => { for (const x of (await fetch('/api/mail/rules').then(r=>r.json())).rules) await fetch('/api/mail/rules/'+x.id,{method:'DELETE'}); }"
        )

        # ---- rules panel opens ----
        pg.click("#mail-rules-btn")
        pg.wait_for_selector("#mail-rules-list", timeout=6000)
        r["rules_panel_opens"] = pg.query_selector("#mail-rules-list") is not None

        # ---- add a rule ----
        pg.fill("#mr-value", "bob")
        pg.click("#mr-add")
        pg.wait_for_selector(".mail-rule-row", timeout=6000)
        r["add_rule"] = "bob" in (pg.text_content("#mail-rules-list") or "")
        pg.screenshot(path=str(EVID / "rules.png"))

        # ---- persists on reload ----
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#mail-rules-btn", timeout=12000)
        pg.click("#mail-rules-btn")
        pg.wait_for_selector(".mail-rule-row", timeout=6000)
        r["rule_persists_reload"] = "bob" in (pg.text_content("#mail-rules-list") or "")

        # ---- run rules now ----
        pg.click("#mr-run")
        pg.wait_for_function(
            "() => (document.getElementById('mr-run-status')||{}).textContent?.includes('applied')",
            timeout=6000,
        )
        r["run_rules"] = "applied" in (pg.text_content("#mr-run-status") or "")

        # ---- vacation saves ----
        pg.click("#mv-enabled")
        pg.fill("#mv-subject", "Away until Monday")
        pg.click("#mv-save")
        pg.wait_for_timeout(700)
        vac = pg.evaluate("() => fetch('/api/mail/vacation').then(r=>r.json())")
        r["vacation_saves"] = (
            vac.get("enabled") is True and vac.get("subject") == "Away until Monday"
        )

        # ---- delete the rule ----
        pg.click(".mail-rule-del")
        pg.wait_for_timeout(700)
        r["delete_rule"] = pg.query_selector(".mail-rule-row") is None

        # ---- smart suggest is graceful with no model ----
        pg.click("#mail-compose-btn")
        pg.wait_for_selector("#mc-suggest", timeout=6000)
        pg.click("#mc-suggest")
        pg.wait_for_selector("#mc-suggest-box .mail-suggest-off", timeout=6000)
        r["smart_suggest_graceful"] = "configure a model" in (
            pg.text_content("#mc-suggest-box") or ""
        )

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_mail_rules_5d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
