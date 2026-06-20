"""1a audit — capture current share surface across views. read-only."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "localhost:8811"
OUT = Path(__file__).parent
VIEWS = ["aide", "docs", "files", "secrets", "photos", "contacts", "calendar"]

def main():
    findings = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for v in VIEWS:
            pg = b.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(f"{m.type}:{m.text}") if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(f"pageerror:{e}"))
            url = f"http://{v}.{BASE}/"
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=15000)
                pg.wait_for_timeout(1500)
                # is there any share/publish affordance visible in the DOM?
                share_hits = pg.eval_on_selector_all(
                    "*",
                    """els => els.filter(e => {
                        const t=(e.textContent||'').trim().toLowerCase();
                        const a=(e.getAttribute&&(e.getAttribute('data-a')||'')+''+(e.id||'')).toLowerCase();
                        return (t==='share'||t==='publish'||a.includes('share')||a.includes('publish'));
                    }).length"""
                )
                pg.screenshot(path=str(OUT / f"view-{v}.png"), full_page=False)
                findings.append(f"{v}: loaded, console_errors={len(errs)}, share_affordances={share_hits}")
                if errs:
                    findings.append(f"    errs: {errs[:5]}")
            except Exception as e:
                findings.append(f"{v}: FAILED {e}")
            pg.close()
        b.close()
    (OUT / "pw_audit.txt").write_text("\n".join(findings), encoding="utf-8")
    print("\n".join(findings))

if __name__ == "__main__":
    sys.exit(main())
