"""4d UI verification — goals (progress/ETA), reports, base-currency net worth. :8835."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MONEY = "http://money.localhost:8835"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "4d"
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

        # ---- reset + seed: two accounts (USD/EUR), a couple txns, clear goals ----
        pg.goto(f"{MONEY}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        pg.evaluate(
            """async () => {
                const J = o => ({method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(o)});
                for (const a of await fetch('/api/money/accounts').then(r=>r.json())) await fetch('/api/money/accounts/'+a.id,{method:'DELETE'});
                for (const g of (await fetch('/api/money/goals').then(r=>r.json())).goals) await fetch('/api/money/goals/'+g.id,{method:'DELETE'});
                const a = await fetch('/api/money/accounts', J({name:'US',kind:'checking',currency:'USD',opening:100})).then(r=>r.json());
                await fetch('/api/money/accounts', J({name:'EU',kind:'savings',currency:'EUR',opening:100}));
                await fetch('/api/money/transactions', J({account_id:a.id,date:'2026-06-05',amount:1000,category:'salary'}));
                await fetch('/api/money/transactions', J({account_id:a.id,date:'2026-06-12',amount:-200,category:'food',payee:'Cafe'}));
            }"""
        )
        pg.goto(f"{MONEY}/?m=2026-06", wait_until="domcontentloaded")
        pg.wait_for_selector('[data-card="goals"]', timeout=15000)

        # ---- add a goal ----
        pg.fill("#gl-name", "Emergency Fund")
        pg.fill("#gl-target", "1000")
        pg.fill("#gl-current", "250")
        pg.fill("#gl-monthly", "150")
        pg.click("#gl-add")
        pg.wait_for_selector(".goal-row", timeout=6000)
        r["goals_add_shows_progress"] = pg.query_selector(
            ".goal-row .goal-bar"
        ) is not None and "25%" in (pg.text_content(".goal-row .goal-eta") or "")
        r["goal_eta_shows"] = "5mo" in (pg.text_content(".goal-row .goal-eta") or "")
        pg.screenshot(path=str(EVID / "goals.png"))

        # ---- reports ----
        pg.eval_on_selector("#rp-start", "el => el.dataset.value = '2026-06-01'")
        pg.eval_on_selector("#rp-end", "el => el.dataset.value = '2026-06-30'")
        pg.click("#rp-run")
        pg.wait_for_selector("#rp-out .rp-tot", timeout=6000)
        rep = pg.text_content("#rp-out") or ""
        r["report_runs_totals"] = "1,000" in rep and "200" in rep
        r["report_export_link"] = pg.is_visible("#rp-export") and "/report/export.csv" in (
            pg.get_attribute("#rp-export", "href") or ""
        )

        # ---- base-currency net worth: US 900 (100 + 1000 − 200) + EU 100 EUR→USD 108.70 ----
        pg.fill("#nw-base-cur", "USD")
        pg.click("#nw-base-go")
        pg.wait_for_timeout(800)
        base_out = pg.text_content("#nw-base-out") or ""
        r["base_currency_rollup"] = "1,008" in base_out and "USD" in base_out

        # ---- goals persist on reload ----
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector('[data-card="goals"]', timeout=10000)
        r["goals_persist_reload"] = "Emergency Fund" in (
            pg.text_content('[data-card="goals"]') or ""
        )

        # remove the goal (idempotency)
        pg.click(".goal-row [data-del-goal]")
        pg.wait_for_timeout(700)
        r["goal_remove"] = pg.query_selector(".goal-row") is None

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_goals_4d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
