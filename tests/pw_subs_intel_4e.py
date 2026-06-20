"""4e UI verification — detect/adopt, unused badge, cancel helper, cancel-by, money
low-balance chip + threshold field. :8837."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SUBS = "http://subs.localhost:8837"
MONEY = "http://money.localhost:8837"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "4e"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def main():
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

        # ---- reset + seed (subs + a money account with recurring charges) ----
        pg.goto(f"{SUBS}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        pg.evaluate(
            """async () => {
                const J = o => ({method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(o)});
                for (const s of (await fetch('/api/subscriptions').then(r=>r.json())).subscriptions) await fetch('/api/subscriptions/'+s.id,{method:'DELETE'});
                for (const a of await fetch('/api/money/accounts').then(r=>r.json())) await fetch('/api/money/accounts/'+a.id,{method:'DELETE'});
                // a low-balance account (20 < 100)
                const a = await fetch('/api/money/accounts', J({name:'Wallet',kind:'cash',opening:20,low_balance:100})).then(r=>r.json());
                // recurring charges → detection should propose "Cloud Co"
                for (const d of ['2026-02-05','2026-03-05','2026-04-05','2026-05-05'])
                    await fetch('/api/money/transactions', J({account_id:a.id,date:d,amount:-10,payee:'Cloud Co'}));
                // a sub with no charge (unused) and one with a cancel-by date
                await fetch('/api/subscriptions', J({name:'Netflix',price:15,cycle:'monthly',next_due:'2026-07-01'}));
                await fetch('/api/subscriptions', J({name:'TrialApp',price:5,cycle:'monthly',next_due:'2026-07-10',trial_end:'2026-06-25'}));
            }"""
        )
        pg.goto(f"{SUBS}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".sub-item", timeout=15000)
        pg.wait_for_timeout(600)

        # ---- detected strip + adopt ----
        r["detected_strip_or_empty"] = pg.query_selector(".subs-detected [data-adopt]") is not None
        pg.screenshot(path=str(EVID / "subs-intel.png"))
        pg.click(".subs-detected [data-adopt]")
        pg.wait_for_timeout(1200)
        r["adopt_creates_sub"] = "Cloud Co" in (pg.text_content("#subs-list") or "")

        # ---- unused badge (Netflix has no matching charge) ----
        r["unused_badge_shows"] = pg.query_selector(".sub-item .sub-unused") is not None

        # ---- cancel-by badge (TrialApp trial_end) ----
        r["cancel_by_shows"] = pg.query_selector(".sub-item .sub-trial") is not None

        # ---- cancel_url: edit Netflix, set it, save → link appears ----
        net = pg.evaluate(
            """() => { for (const el of document.querySelectorAll('.sub-item')) {
                if ((el.querySelector('.sub-name')||{}).textContent === 'Netflix') return el.dataset.id; } return ''; }"""
        )
        pg.click(f'.sub-item[data-id="{net}"] [data-act="edit"]')
        pg.wait_for_selector(f'.sub-item[data-id="{net}"] [data-f="cancel_url"]', timeout=5000)
        pg.fill(f'.sub-item[data-id="{net}"] [data-f="cancel_url"]', "https://netflix.com/cancel")
        pg.click(f'.sub-item[data-id="{net}"] [data-act="save"]')
        pg.wait_for_timeout(1200)
        href = pg.get_attribute(f'.sub-item[data-id="{net}"] .sub-cancel-link', "href") or ""
        r["cancel_url_saves_and_links"] = "netflix.com/cancel" in href

        # ---- money: low-balance chip + threshold field ----
        pg.goto(f"{MONEY}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".money-grid", timeout=12000)
        pg.wait_for_timeout(600)
        r["low_balance_alert_chip"] = "low" in (pg.text_content(".money-alerts") or "").lower()
        pg.click("#money-add-acct")
        pg.wait_for_selector("#af-low", timeout=5000)
        r["low_balance_threshold_settable"] = pg.query_selector("#af-low") is not None

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_subs_intel_4e.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
