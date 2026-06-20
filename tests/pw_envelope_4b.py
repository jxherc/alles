"""4b UI verification — envelope budgeting: TBB, assign→available, targets, age of money,
rollover. :8831."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MONEY = "http://money.localhost:8831"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "4b"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def fnum(s):
    return float("".join(ch for ch in (s or "") if ch.isdigit() or ch in ".-") or 0)


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

        # ---- reset + seed: income + a food expense, clear assignments/targets ----
        pg.goto(f"{MONEY}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        pg.evaluate(
            """async () => {
                const accts = await fetch('/api/money/accounts').then(r=>r.json());
                for (const a of accts) await fetch('/api/money/accounts/'+a.id,{method:'DELETE'});
                const env = await fetch('/api/money/envelope?month=2026-06').then(r=>r.json());
                for (const c of env.categories) {
                    await fetch('/api/money/envelope/assign',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({category:c.category,month:'2026-06',amount:0})});
                    if (c.target) await fetch('/api/money/envelope/target',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({category:c.category,amount:0})});
                }
                const a = await fetch('/api/money/accounts',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:'Main',kind:'checking',opening:0})}).then(r=>r.json());
                await fetch('/api/money/transactions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({account_id:a.id,date:'2026-06-05',amount:1000,category:'salary'})});
                await fetch('/api/money/transactions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({account_id:a.id,date:'2026-06-10',amount:-200,category:'food'})});
            }"""
        )
        pg.goto(f"{MONEY}/?m=2026-06", wait_until="domcontentloaded")
        pg.wait_for_selector(".money-envelope", timeout=15000)

        r["envelope_card_renders"] = pg.query_selector(".money-envelope .env-tbb") is not None
        tbb = pg.text_content(".env-tbb .env-tbb-num") or ""
        r["tbb_banner_shows"] = "1,000" in tbb or "1000" in tbb

        # food row exists with negative available (spent, nothing assigned)
        pg.wait_for_selector('.env-row[data-cat="food"]', timeout=6000)
        avail0 = pg.text_content('.env-row[data-cat="food"] .env-avail') or ""
        r["available_reflects_spending"] = (
            pg.query_selector('.env-row[data-cat="food"] .env-avail.neg') is not None
            and "200" in avail0
        )

        # ---- assign updates available ----
        inp = pg.query_selector('.env-row[data-cat="food"] .env-assign')
        inp.fill("300")
        inp.dispatch_event("change")
        pg.wait_for_timeout(900)
        avail1 = pg.text_content('.env-row[data-cat="food"] .env-avail') or ""
        r["assign_updates_available"] = abs(fnum(avail1) - 100) < 0.5
        pg.screenshot(path=str(EVID / "envelope.png"))

        # ---- target via 🎯 (single fields dialog: amount + date) ----
        pg.click('.env-row[data-cat="food"] .env-tgt-btn')
        pg.wait_for_selector("#_df_amount", timeout=4000)
        pg.fill("#_df_amount", "1000")
        pg.fill("#_df_date", "2026-12-01")
        pg.click("#_dy")
        pg.wait_for_timeout(1000)
        r["target_progress_shows"] = (
            pg.query_selector('.env-row[data-cat="food"] .env-target-bar') is not None
        )

        # ---- age of money stat (income day 5, spend day 10 → 5d) ----
        aom = pg.text_content(".money-envelope .aom") or ""
        r["age_of_money_stat"] = "age of money" in aom

        # ---- rollover into next month ----
        pg.goto(f"{MONEY}/?m=2026-07", wait_until="domcontentloaded")
        pg.wait_for_selector(".money-envelope", timeout=10000)
        pg.wait_for_selector('.env-row[data-cat="food"]', timeout=6000)
        avail_jul = pg.text_content('.env-row[data-cat="food"] .env-avail') or ""
        r["rollover_visible_next_month"] = abs(fnum(avail_jul) - 100) < 0.5

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_envelope_4b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
