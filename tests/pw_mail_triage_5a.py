"""5a UI verification — mail triage over a seeded cache (no live IMAP). :8839.
Run with ALLES_DATA pointing at the server's data dir so the seeder writes the shared db.
We also prime the browser localStorage cache so the inbox renders instantly (the IMAP fetch
just fails in the background) — this keeps the test off the flaky IMAP-timeout path."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

MAIL = "http://mail.localhost:8839"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "5a"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")

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


def subjects(pg):
    return pg.evaluate(
        "() => [...document.querySelectorAll('.mail-row .mail-subject')].map(e => e.textContent.trim())"
    )


def main():
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

        r["inbox_renders_seeded"] = len(subjects(pg)) >= 4
        r["unsubscribe_btn_shows"] = pg.query_selector(".mail-row [data-unsub]") is not None
        pg.screenshot(path=str(EVID / "mail-triage.png"))

        # ---- advanced search: from:alice → only Alice's row (cache adv-search) ----
        pg.fill("#mail-search", "from:alice")
        pg.press("#mail-search", "Enter")
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length === 1", timeout=8000
        )
        froms = pg.eval_on_selector_all(".mail-row .mail-from", "els=>els.map(e=>e.textContent)")
        r["adv_search_from_filters"] = "Alice" in (froms[0] if froms else "")

        # ---- save the current search → a chip appears ----
        pg.wait_for_selector("#mail-saved-save", timeout=5000)
        pg.click("#mail-saved-save")
        pg.wait_for_selector("#mail-saved .mail-saved-chip", timeout=5000)
        r["save_search_chip"] = pg.query_selector("#mail-saved .mail-saved-chip") is not None

        # ---- clicking the saved chip re-runs the search ----
        pg.fill("#mail-search", "zzz")
        pg.click("#mail-saved .mail-saved-chip")
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length === 1", timeout=8000
        )
        r["saved_search_runs"] = pg.input_value("#mail-search") == "from:alice"

        # ---- mute a thread → its rows gone after the cache re-render ----
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_function(
            "() => document.querySelectorAll('.mail-row').length >= 4", timeout=20000
        )
        muted = pg.evaluate(
            """() => {
                for (const row of document.querySelectorAll('.mail-row')) {
                    const subj = ((row.querySelector('.mail-subject')||{}).textContent || '').trim();
                    if (subj === 'Project plan') { row.querySelector('[data-mute]').click(); return true; }
                }
                return false;
            }"""
        )
        pg.wait_for_timeout(900)
        pg.reload(wait_until="domcontentloaded")
        # localStorage renders the stale set first; the ~2.3s server fetch re-renders without muted
        try:
            pg.wait_for_function(
                "() => document.querySelectorAll('.mail-row').length > 0 && ![...document.querySelectorAll('.mail-row .mail-subject')].some(e => e.textContent.trim() === 'Project plan')",
                timeout=14000,
            )
            settled = True
        except Exception:
            settled = False
        r["mute_hides_row"] = bool(muted) and settled

        # ---- archive a message → its row is removed ----
        before = len(subjects(pg))
        pg.eval_on_selector(".mail-row [data-archive]", "el => el.click()")
        pg.wait_for_function(
            f"() => document.querySelectorAll('.mail-row').length === {before - 1}", timeout=8000
        )
        r["archive_removes_row"] = len(subjects(pg)) == before - 1

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_mail_triage_5a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
