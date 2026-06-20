"""5e UI verification — category tabs + per-message labels. Seeded cache, no live IMAP. :8847.
Run with ALLES_DATA pointing at the server's data dir."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

MAIL = "http://mail.localhost:8847"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "5e"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")

# mirrors tests/_seed_mail.py so the localStorage prime matches the server cache
SEED = [
    (
        "1",
        "Alice <alice@news.com>",
        "Weekly Newsletter",
        "2026-06-18",
        "<https://news.com/unsub?id=1>",
    ),
    ("2", "Bob <bob@work.com>", "Project plan", "2026-06-17", ""),
    ("3", "Bob <bob@work.com>", "Re: Project plan", "2026-06-16", ""),
    ("4", "Carol <carol@shop.com>", "Your receipt", "2026-06-15", ""),
]


def _ts(d):
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()


def nrows(pg):
    return pg.evaluate("() => document.querySelectorAll('.mail-row').length")


def subjects(pg):
    return pg.evaluate(
        "() => [...document.querySelectorAll('.mail-row .mail-subject')].map(e => e.textContent)"
    )


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
            "uid": uid,
            "folder": "INBOX",
            "from": frm,
            "subject": subj,
            "date": date,
            "date_ts": _ts(date),
            "seen": True,
            "flagged": False,
            "list_unsubscribe": unsub,
            "labels": [],
            "account_name": "Test",
        }
        for uid, frm, subj, date, unsub in SEED
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
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length >= 4", timeout=20000
        )

        r["category_tabs_present"] = (
            pg.query_selector('[data-filter="cat:promotions"]') is not None
            and pg.query_selector('[data-filter="cat:primary"]') is not None
        )

        # ---- promotions tab → only the newsletter (has list-unsubscribe) ----
        pg.click('[data-filter="cat:promotions"]')
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length === 1", timeout=8000
        )
        r["promotions_tab_filters"] = "Newsletter" in " ".join(subjects(pg))
        pg.screenshot(path=str(EVID / "categories.png"))

        # ---- primary tab → the work/personal mail, not the newsletter ----
        pg.click('[data-filter="cat:primary"]')
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length >= 2", timeout=8000
        )
        subs = " ".join(subjects(pg))
        r["primary_tab_back"] = "Project plan" in subs and "Newsletter" not in subs

        # ---- back to inbox, add a label to the first row ----
        pg.click('[data-filter="inbox"]')
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length >= 4", timeout=8000
        )
        tid = pg.get_attribute(".mail-row", "data-uid")
        pg.eval_on_selector(f'.mail-row[data-uid="{tid}"] [data-label]', "el => el.click()")
        pg.wait_for_selector("#_di", timeout=4000)
        pg.fill("#_di", "work")
        pg.click("#_dy")
        pg.wait_for_selector(".mail-label-chip", timeout=6000)
        r["label_add"] = pg.query_selector(".mail-label-chip") is not None
        r["label_chip_shows"] = "work" in (pg.text_content(".mail-label-chip") or "")

        # ---- filter by the label chip ----
        pg.click(".mail-label-chip")
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length === 1", timeout=8000
        )
        r["label_filter"] = nrows(pg) == 1

        # ---- label persists across reload (server cache) ----
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length >= 1", timeout=20000
        )
        try:
            pg.wait_for_selector(".mail-label-chip", timeout=12000)
            r["label_persists_reload"] = True
        except Exception:
            r["label_persists_reload"] = False

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_mail_labels_5e.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
