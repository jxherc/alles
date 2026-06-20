"""9b UI — encrypted attachments + per-item share (public WebCrypto decrypt).
secrets.localhost:8869.  ALLES_DATA=/tmp/alles9b PORT=8869 AUTH_ENABLED=false python app.py
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

SEC = "http://secrets.localhost:8869"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "9b"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")
MASTER = "master-9b"


def _api(path, body, token=None):
    h = {"content-type": "application/json"}
    if token:
        h["X-Vault-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:8869{path}", data=json.dumps(body).encode(), headers=h, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    tok = _api("/api/vault/unlock", {"password": MASTER})["token"]
    eid = _api(
        "/api/vault",
        {
            "name": "WiFi",
            "type": "login",
            "fields": {"username": "guest", "password": "hunter2-wifi"},
        },
        tok,
    )["id"]

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

        def unlock_and_wait():
            for _ in range(4):
                if pg.query_selector(".vault-entry"):
                    return True
                if pg.query_selector("#vault-pw-input") and pg.is_visible("#vault-pw-input"):
                    pg.fill("#vault-pw-input", MASTER)
                    pg.eval_on_selector("#vault-unlock-btn", "el => el.click()")
                try:
                    pg.wait_for_selector(".vault-entry", timeout=6000)
                    return True
                except Exception:
                    pg.goto(f"{SEC}/", wait_until="domcontentloaded")
                    pg.wait_for_timeout(400)
            return False

        pg.goto(f"{SEC}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#vault-pw-input", timeout=15000)
        unlock_and_wait()
        pg.wait_for_selector(".vault-entry", timeout=8000)

        # open the entry → form with attachments section
        pg.eval_on_selector(".vault-entry:has-text('WiFi')", "el => el.click()")
        pg.wait_for_selector("#vf-attach", timeout=8000)

        # ---- upload an attachment ----
        tmp = Path(EVID) / "_codes.txt"
        tmp.write_text("backup codes: 11111 22222")
        pg.set_input_files("#vf-attach-input", str(tmp))
        pg.wait_for_selector(".vf-attach-row", timeout=8000)
        r["attach_upload_shows"] = "codes.txt" in (pg.text_content("#vf-attach") or "")

        # ---- download works (no error) ----
        with pg.expect_download() as dl:
            pg.eval_on_selector(".vf-attach-row [data-dl]", "el => el.click()")
        r["attach_download"] = dl.value is not None

        # ---- share item: button present in the form; mint the link (server-side, real token) ----
        r["share_item_button"] = pg.query_selector("#vf-share") is not None
        sd = _api(f"/api/vault/{eid}/share", {}, tok)
        r["share_mints_link"] = "#" in sd["url"] and bool(sd["key"])

        # ---- public page decrypts the item read-only ----
        pg.goto(f"{SEC}{sd['url']}", wait_until="domcontentloaded")
        for _ in range(20):
            if "hunter2-wifi" in (pg.text_content("#body") or ""):
                break
            pg.wait_for_timeout(300)
        r["public_share_decrypts"] = "hunter2-wifi" in (pg.text_content("#body") or "")
        pg.screenshot(path=str(EVID / "public-share.png"))

        # ---- revoke → public page no longer decrypts ----
        urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:8869/api/vault/{eid}/share",
                headers={"X-Vault-Token": tok},
                method="DELETE",
            )
        )
        # cache-bust + force a real navigation (a same-URL goto incl. fragment may be same-document)
        token = sd["url"].split("/sv/")[1].split("#")[0]
        key = sd["url"].split("#")[1]
        pg.goto("about:blank")
        pg.goto(f"{SEC}/sv/{token}?r=1#{key}", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        body = pg.content()
        r["public_share_revoked_gone"] = "hunter2-wifi" not in body

        # ---- remove attachment ----
        pg.goto(f"{SEC}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#vault-pw-input", timeout=10000)
        unlock_and_wait()
        pg.eval_on_selector(".vault-entry:has-text('WiFi')", "el => el.click()")
        pg.wait_for_selector(".vf-attach-row", timeout=8000)
        pg.eval_on_selector(".vf-attach-row [data-rm]", "el => el.click()")
        pg.wait_for_timeout(800)
        r["attach_remove"] = "codes.txt" not in (pg.text_content("#vf-attach") or "")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_vault_share_9b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
