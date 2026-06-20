"""2e UI verification — per-vault CSS, tabs + saved layout, split pane, offline edit. :8821."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8821"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "2e"
IGNORE = (
    "Failed to load resource",
    "net::",
    "ERR_",
    "favicon",
    "401",
    "Load failed",
    "dynamically imported module",
    "Failed to fetch",
)

IDB = """() => new Promise(res => { let r; try{r=indexedDB.open('alles-sync',1);}catch(e){return res(-1);}
  r.onupgradeneeded=()=>{try{if(!r.result.objectStoreNames.contains('outbox'))r.result.createObjectStore('outbox',{keyPath:'id',autoIncrement:true});}catch(e){}};
  r.onsuccess=()=>{const db=r.result;if(!db.objectStoreNames.contains('outbox'))return res(0);const t=db.transaction('outbox','readonly');const q=t.objectStore('outbox').getAll();q.onsuccess=()=>res(q.result.length);q.onerror=()=>res(-1);};
  r.onerror=()=>res(-1);})"""


def main():
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
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

        pg.goto(f"{DOCS}/?doc=alpha.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-theme-btn", timeout=15000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )

        # ---- per-vault CSS ----
        pg.click("#wiki-theme-btn")
        pg.wait_for_selector("#wiki-theme-input", state="visible", timeout=5000)
        pg.fill("#wiki-theme-input", ".cm-content { font-family: Georgia, serif }")
        pg.click("#wiki-theme-save")
        pg.wait_for_timeout(500)
        style = (
            pg.eval_on_selector("#vault-theme-style", "el => el.textContent")
            if pg.query_selector("#vault-theme-style")
            else ""
        )
        r["theme_applies"] = "Georgia" in style
        pg.click("#wiki-theme-btn")  # close panel

        # ---- tabs ----
        # open beta via the home gallery
        pg.click("#wiki-home-btn")
        pg.wait_for_selector('.docs-card[data-path="beta.md"]', timeout=8000)
        pg.click('.docs-card[data-path="beta.md"]')
        pg.wait_for_timeout(500)
        r["tabs_two"] = len(pg.query_selector_all("#wiki-tabs .wiki-tab")) == 2
        # switch back to alpha
        pg.click('#wiki-tabs .wiki-tab[data-path="alpha.md"] .wiki-tab-name')
        pg.wait_for_timeout(400)
        r["tab_switch"] = "alpha" in pg.inner_text("#wiki-current")

        # ---- split ----
        pg.click("#wiki-split-btn")
        pg.wait_for_timeout(500)
        r["split_visible"] = pg.is_visible("#wiki-split-pane")
        r["split_shows_other"] = "beta" in (pg.inner_text("#wiki-split-pane").lower())
        pg.screenshot(path=str(EVID / "panes.png"))
        pg.click("#wiki-split-btn")  # off

        # ---- close a tab + persist across reload ----
        pg.click('#wiki-tabs .wiki-tab[data-path="beta.md"] .wiki-tab-close')
        pg.wait_for_timeout(300)
        r["tab_close"] = len(pg.query_selector_all("#wiki-tabs .wiki-tab")) == 1
        pg.goto(f"{DOCS}/?doc=alpha.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-tabs .wiki-tab", timeout=10000)
        r["tabs_persist_reload"] = (
            pg.query_selector('#wiki-tabs .wiki-tab[data-path="alpha.md"]') is not None
        )

        # ---- offline editing (uses 1b SW outbox) ----
        for _ in range(2):
            try:
                pg.wait_for_function(
                    "navigator.serviceWorker && navigator.serviceWorker.controller", timeout=8000
                )
                break
            except Exception:
                pg.reload(wait_until="domcontentloaded")
                pg.wait_for_selector("#wiki-tabs", timeout=8000)
        # switch to source mode to edit raw
        for _ in range(3):
            if pg.is_visible("#wiki-source"):
                break
            pg.click("#wiki-mode-toggle")
            pg.wait_for_timeout(300)
        ctx.set_offline(True)
        pg.fill("#wiki-source", "# Alpha\n\nEDITED OFFLINE marker")
        pg.wait_for_timeout(2200)  # let autosave fire → SW queues the PUT
        r["offline_edit_queued"] = pg.evaluate(IDB) >= 1
        ctx.set_offline(False)
        pg.evaluate(
            "navigator.serviceWorker.controller && navigator.serviceWorker.controller.postMessage({type:'alles-flush'})"
        )
        drained = False
        for _ in range(20):
            if pg.evaluate(IDB) == 0:
                drained = True
                break
            pg.evaluate(
                "navigator.serviceWorker.controller && navigator.serviceWorker.controller.postMessage({type:'alles-flush'})"
            )
            pg.wait_for_timeout(500)
        content = pg.evaluate(
            "fetch('/api/vault-md/file?path=alpha.md').then(r=>r.json()).then(j=>j.content)"
        )
        r["offline_edit_persists"] = drained and "EDITED OFFLINE" in (content or "")

        r["zero_console_errors"] = len(errs) == 0
        ctx.close()
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_panes_2e.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
