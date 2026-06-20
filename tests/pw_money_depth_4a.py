"""4a UI verification — splits, tags + filter, receipts, cleared, reconcile. :8829."""

import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

MONEY = "http://money.localhost:8829"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "4a"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")

# 1x1 png for the receipt upload
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6360000002000154a24f9f0000000049454e44ae426082"
)


def main():
    r = {}
    errs = []
    tmp = Path(tempfile.gettempdir()) / "alles_receipt_4a.png"
    tmp.write_bytes(PNG)
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

        # ---- reset money + seed a fresh account + txns (idempotent) ----
        pg.goto(f"{MONEY}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        pg.evaluate(
            """async () => {
                const accts = await fetch('/api/money/accounts').then(r=>r.json());
                for (const a of accts) await fetch('/api/money/accounts/'+a.id,{method:'DELETE'});
                const a = await fetch('/api/money/accounts',{method:'POST',headers:{'content-type':'application/json'},
                    body:JSON.stringify({name:'Test Checking',kind:'checking',opening:100})}).then(r=>r.json());
                await fetch('/api/money/transactions',{method:'POST',headers:{'content-type':'application/json'},
                    body:JSON.stringify({account_id:a.id,date:'2026-06-10',amount:-50,category:'shopping',payee:'Target',tags:'food, home'})});
                await fetch('/api/money/transactions',{method:'POST',headers:{'content-type':'application/json'},
                    body:JSON.stringify({account_id:a.id,date:'2026-06-09',amount:-30,category:'coffee',payee:'Cafe',tags:'food'})});
            }"""
        )
        pg.goto(f"{MONEY}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".txns .txn", timeout=15000)
        tid = pg.get_attribute(".txns .txn", "data-id")

        # ---- tags show as chips ----
        r["tag_add_shows_chip"] = pg.query_selector(".txns .txn .tx-tag") is not None

        # ---- split editor opens ----
        pg.click(f'.txn[data-id="{tid}"] .tx-split-btn')
        pg.wait_for_selector(".txn-split-editor", timeout=5000)
        r["split_editor_opens"] = pg.is_visible(".txn-split-editor")

        # ---- split saves → badge ----
        pg.fill(".txn-split-editor .split-row .split-cat", "groceries")
        pg.fill(".txn-split-editor .split-row .split-amt", "20")
        pg.click("#split-save")
        pg.wait_for_timeout(1000)
        r["split_saves_badge"] = (
            pg.query_selector(f'.txn[data-id="{tid}"] .tx-split-btn.on') is not None
        )
        pg.screenshot(path=str(EVID / "txn-depth.png"))

        # ---- tag filter ----
        pg.click(f'.txn[data-id="{tid}"] .tx-tag[data-tag="home"]')
        pg.wait_for_timeout(800)
        rows_after = pg.query_selector_all(".txns .txn")
        r["tag_filter_lists"] = len(rows_after) == 1 and pg.is_visible(".txn-tagfilter")
        pg.click("#tag-clear")
        pg.wait_for_timeout(500)

        # ---- receipt attach (file chooser) ----
        with pg.expect_file_chooser() as fc:
            pg.click(f'.txn[data-id="{tid}"] .tx-receipt-btn')
        fc.value.set_files(str(tmp))
        pg.wait_for_timeout(1200)
        href = pg.get_attribute(f'.txn[data-id="{tid}"] .tx-receipt', "href") or ""
        r["receipt_attaches"] = "/api/uploads/" in href

        # ---- cleared toggle persists ----
        pg.click(f'.txn[data-id="{tid}"] .tx-clear')
        pg.wait_for_timeout(900)
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(f'.txn[data-id="{tid}"]', timeout=10000)
        r["cleared_toggle_persists"] = (
            pg.query_selector(f'.txn[data-id="{tid}"] .tx-clear.on') is not None
        )

        # ---- reconcile shows a difference ----
        pg.click(".money-acct .ma-rc")
        pg.wait_for_timeout(400)
        stmt = pg.query_selector(".money-acct .rc-panel input")
        stmt.fill("999")
        pg.click(".money-acct [data-rc-run]")
        pg.wait_for_timeout(700)
        out = pg.text_content(".money-acct .rc-out") or ""
        r["reconcile_shows_difference"] = (
            "off by" in out and pg.query_selector(".rc-out.bad") is not None
        )
        pg.screenshot(path=str(EVID / "reconcile.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_money_depth_4a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
