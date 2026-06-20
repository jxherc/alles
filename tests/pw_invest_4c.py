"""4c UI verification — forecast stat, net-worth graph, holdings, alerts, dashboard hide. :8833."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MONEY = "http://money.localhost:8833"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "4c"
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

        # ---- reset + seed (dates relative to the real current date) ----
        pg.goto(f"{MONEY}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        pg.evaluate("() => localStorage.removeItem('money-hidden-cards')")
        pg.evaluate(
            """async () => {
                const J = o => ({method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(o)});
                for (const a of await fetch('/api/money/accounts').then(r=>r.json())) await fetch('/api/money/accounts/'+a.id,{method:'DELETE'});
                for (const h of (await fetch('/api/money/holdings').then(r=>r.json())).holdings) await fetch('/api/money/holdings/'+h.id,{method:'DELETE'});
                for (const w of (await fetch('/api/money/watches').then(r=>r.json())).watches) await fetch('/api/money/watches/'+w.id,{method:'DELETE'});
                const iso = d => d.toISOString().slice(0,10);
                const today = new Date();
                const ago = n => { const d = new Date(today); d.setMonth(d.getMonth()-n); return iso(d); };
                const plus = n => { const d = new Date(today); d.setDate(d.getDate()+n); return iso(d); };
                const a = await fetch('/api/money/accounts', J({name:'Main',kind:'checking',opening:1000})).then(r=>r.json());
                await fetch('/api/money/transactions', J({account_id:a.id,date:ago(2),amount:500,category:'salary'}));
                await fetch('/api/money/transactions', J({account_id:a.id,date:ago(1),amount:-200,category:'rent'}));
                await fetch('/api/money/transactions', J({account_id:a.id,date:iso(today),amount:-500,category:'shopping',payee:'TV'}));
                await fetch('/api/money/recurring', J({account_id:a.id,amount:-100,cycle:'monthly',next_date:plus(3),payee:'gym'}));
            }"""
        )
        pg.goto(f"{MONEY}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".money-grid", timeout=15000)

        # ---- forecast stat ----
        r["forecast_stat_shows"] = "projected" in (pg.text_content(".money-summary") or "")

        # ---- net worth graph ----
        r["networth_graph_renders"] = (
            pg.query_selector('[data-card="networth"] .nw-svg') is not None
        )

        # ---- alerts strip (large purchase −500 ≥ 200 default) ----
        pg.wait_for_selector(".money-alerts .alert-chip", timeout=6000)
        r["alerts_strip_shows"] = pg.query_selector(".money-alerts .alert-chip") is not None
        pg.screenshot(path=str(EVID / "invest.png"))

        # ---- holdings add ----
        pg.fill("#hd-sym", "AAPL")
        pg.fill("#hd-qty", "10")
        pg.fill("#hd-cost", "100")
        pg.fill("#hd-price", "150")
        pg.click("#hd-add")
        pg.wait_for_selector(".hold-row", timeout=6000)
        hv = pg.text_content(".hold-row .hold-val") or ""
        r["holding_add_shows_value"] = "1,500" in hv or "1500" in hv
        r["holding_gain_colored"] = pg.query_selector(".hold-row .hold-gain.pos") is not None

        # ---- holdings remove ----
        pg.click(".hold-row [data-del-hold]")
        pg.wait_for_timeout(900)
        r["holding_remove"] = pg.query_selector(".hold-row") is None

        # ---- dashboard hide persists ----
        pg.hover('[data-card="accounts"]')
        pg.click('[data-card="accounts"] .card-hide')
        pg.wait_for_timeout(400)
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".money-grid", timeout=10000)
        pg.wait_for_timeout(600)
        hidden = pg.eval_on_selector(
            '[data-card="accounts"]', "el => getComputedStyle(el).display === 'none'"
        )
        r["dashboard_hide_persists"] = bool(hidden)
        # restore for idempotency
        pg.evaluate("() => localStorage.removeItem('money-hidden-cards')")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_invest_4c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
