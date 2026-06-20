"""5c UI verification — rich compose: HTML toolbar, inline image, signatures. :8843.
Run with ALLES_DATA pointing at the server's data dir (seeder shares the db)."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

MAIL = "http://mail.localhost:8843"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "5c"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6360000002000154a24f9f0000000049454e44ae426082"
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
            "uid": "1",
            "folder": "INBOX",
            "from": "A <a@x.com>",
            "subject": "Hi",
            "date": "2026-06-18",
            "date_ts": datetime(2026, 6, 18, tzinfo=timezone.utc).timestamp(),
            "seen": True,
            "flagged": False,
            "list_unsubscribe": "",
            "account_name": "Test",
        }
    ]
    prime = f"localStorage.setItem('mail-cache-{aid}-inbox', {json.dumps(json.dumps(msgs))});"
    tmp_png = Path(EVID) / "_img.png"
    tmp_png.write_bytes(PNG)

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
            "() => document.querySelectorAll('.mail-row').length >= 1", timeout=20000
        )

        # reset signatures + add one
        pg.evaluate(
            """async () => {
                const J = o => ({method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(o)});
                for (const s of (await fetch('/api/mail/signatures').then(r=>r.json())).signatures) await fetch('/api/mail/signatures/'+s.id,{method:'DELETE'});
                await fetch('/api/mail/signatures', J({name:'Work', body:'Best,\\nMe'}));
            }"""
        )

        pg.click("#mail-compose-btn")
        pg.wait_for_selector("#mc-richbar", timeout=6000)
        r["compose_has_richbar"] = pg.query_selector("#mc-richbar") is not None

        # ---- bold wraps the selection ----
        pg.click("#mc-html")
        pg.keyboard.type("hello world")
        pg.keyboard.press("Control+A")
        pg.click('#mc-richbar [data-cmd="bold"]')
        pg.wait_for_timeout(300)
        html = pg.eval_on_selector("#mc-html", "el => el.innerHTML")
        r["bold_wraps_selection"] = "<b>" in html or "<strong>" in html or "font-weight" in html

        # ---- signature chip present + appends ----
        # reopen compose so it loads the freshly-added signature
        pg.click("#mc-close")
        pg.wait_for_timeout(200)
        pg.click("#mail-compose-btn")
        pg.wait_for_selector("#mc-sig-list .mc-sig-chip", timeout=6000)
        r["signature_picker_present"] = pg.query_selector("#mc-sig-list .mc-sig-chip") is not None
        pg.click("#mc-sig-list .mc-sig-chip")
        pg.wait_for_timeout(300)
        r["signature_appends"] = "Best" in (
            pg.eval_on_selector("#mc-html", "el => el.innerText") or ""
        )
        pg.screenshot(path=str(EVID / "compose.png"))

        # ---- inline image inserts an <img> ----
        with pg.expect_file_chooser() as fc:
            pg.click("#mc-image")
        fc.value.set_files(str(tmp_png))
        pg.wait_for_timeout(1000)
        r["image_btn_inserts_img"] = "/api/uploads/" in (
            pg.eval_on_selector("#mc-html", "el => el.innerHTML") or ""
        )

        # ---- add a new signature via the +sig prompts ----
        pg.click("#mc-sig-add")
        pg.wait_for_selector("#_di", timeout=4000)
        pg.fill("#_di", "Personal")
        pg.click("#_dy")
        pg.wait_for_selector("#_di", timeout=4000)
        pg.fill("#_di", "cheers")
        pg.click("#_dy")
        pg.wait_for_function(
            "() => document.querySelectorAll('#mc-sig-list .mc-sig-chip').length >= 2", timeout=6000
        )
        r["add_signature"] = len(pg.query_selector_all("#mc-sig-list .mc-sig-chip")) >= 2

        # ---- send queues (undo bar) — exercises the html send path ----
        pg.fill("#mc-to", "bob@x.com")
        pg.click("#mc-send")
        pg.wait_for_selector("#mail-undo-bar", state="visible", timeout=6000)
        r["html_sent_or_queued"] = pg.is_visible("#mail-undo-bar")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_mail_compose_5c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
