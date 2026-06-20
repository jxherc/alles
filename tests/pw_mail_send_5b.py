"""5b UI verification — schedule send, undo send, snooze. Seeded cache, no live IMAP. :8841.
Run with ALLES_DATA pointing at the server's data dir."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

MAIL = "http://mail.localhost:8841"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "5b"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")

SEED = [
    ("1", "Alice <alice@news.com>", "Weekly Newsletter", "2026-06-18"),
    ("2", "Bob <bob@work.com>", "Project plan", "2026-06-17"),
    ("3", "Carol <carol@shop.com>", "Your receipt", "2026-06-15"),
]


def _ts(d):
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()


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
            "list_unsubscribe": "",
            "account_name": "Test",
        }
        for uid, frm, subj, date in SEED
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
            "() => document.querySelectorAll('.mail-row').length >= 3", timeout=20000
        )

        # ---- compose has a schedule control ----
        pg.click("#mail-compose-btn")
        pg.wait_for_selector("#mc-schedule-at", timeout=6000)
        r["compose_has_schedule"] = pg.query_selector("#mc-schedule-at") is not None

        # ---- schedule a send → pending strip ----
        pg.fill("#mc-to", "bob@x.com")
        pg.fill("#mc-subj", "Quarterly report")
        pg.fill("#mc-schedule-at", "2026-12-01T09:00")
        pg.click("#mc-schedule")
        pg.wait_for_selector("#mail-scheduled .mail-sched-chip", timeout=6000)
        r["schedule_creates_pending"] = (
            pg.query_selector("#mail-scheduled .mail-sched-chip") is not None
        )
        r["scheduled_strip_shows"] = "Quarterly report" in (
            pg.text_content("#mail-scheduled") or ""
        )
        pg.screenshot(path=str(EVID / "mail-send.png"))

        # ---- cancel the scheduled send ----
        pg.click("#mail-scheduled .mail-sched-cancel")
        pg.wait_for_timeout(800)
        r["cancel_scheduled"] = pg.query_selector("#mail-scheduled .mail-sched-chip") is None

        # ---- send with undo ----
        pg.click("#mail-compose-btn")
        pg.wait_for_selector("#mc-send", timeout=6000)
        pg.fill("#mc-to", "carol@x.com")
        pg.fill("#mc-subj", "Oops")
        pg.click("#mc-send")
        pg.wait_for_selector("#mail-undo-bar", state="visible", timeout=6000)
        r["send_shows_undo"] = pg.is_visible("#mail-undo-bar")

        # ---- undo cancels the queued send ----
        pg.click("#mail-undo-btn")
        pg.wait_for_timeout(800)
        pending = pg.evaluate(
            "() => fetch('/api/mail/scheduled').then(r=>r.json()).then(j=>j.scheduled.length)"
        )
        r["undo_cancels"] = pending == 0

        # ---- snooze a row → it disappears ----
        before = pg.evaluate("() => document.querySelectorAll('.mail-row').length")
        pg.eval_on_selector(".mail-row [data-snooze]", "el => el.click()")
        pg.wait_for_function(
            f"() => document.querySelectorAll('.mail-row').length === {before - 1}", timeout=6000
        )
        r["snooze_hides_row"] = (
            pg.evaluate("() => document.querySelectorAll('.mail-row').length") == before - 1
        )

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_mail_send_5b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
