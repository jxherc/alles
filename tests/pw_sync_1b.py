"""1b verification — offline write-queue (SW outbox) + replay + pending indicator.
drives the live isolated server on :8812. boot it first:

  ALLES_DATA=…/alles1b_data PORT=8812 AUTH_ENABLED=false python app.py
  python tests/pw_sync_1b.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://tasks.localhost:8812"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "1b"
# real JS errors only — ignore offline network-failure noise
IGNORE = (
    "Failed to load resource",
    "net::",
    "ERR_",
    "favicon",
    "401",
    "503",
    "Load failed",
    "dynamically imported module",
    "Failed to fetch",
)

IDB_COUNT = """
() => new Promise(res => {
  let r; try { r = indexedDB.open('alles-sync', 1); } catch (e) { return res(-1); }
  r.onupgradeneeded = () => { try { if (!r.result.objectStoreNames.contains('outbox')) r.result.createObjectStore('outbox', {keyPath:'id', autoIncrement:true}); } catch(e){} };
  r.onsuccess = () => { const db = r.result; if (!db.objectStoreNames.contains('outbox')) return res(0);
    const t = db.transaction('outbox','readonly'); const q = t.objectStore('outbox').getAll();
    q.onsuccess = () => res(q.result.length); q.onerror = () => res(-1); };
  r.onerror = () => res(-1);
})
"""

POST_TASK = """
async () => { try {
  const r = await fetch('/api/tasks', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({title:'offline-sync-task'})});
  let j=null; try { j = await r.json(); } catch(e){}
  return {ok:true, status:r.status, json:j};
} catch(e) { return {ok:false, error:String(e)}; } }
"""


def wait_controller(pg):
    for _ in range(2):
        try:
            pg.wait_for_function(
                "navigator.serviceWorker && navigator.serviceWorker.controller", timeout=8000
            )
            return True
        except Exception:
            pg.reload(wait_until="domcontentloaded")
    return pg.evaluate("!!(navigator.serviceWorker && navigator.serviceWorker.controller)")


def main():
    res = {}
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

        pg.goto(URL, wait_until="domcontentloaded")
        pg.evaluate("navigator.serviceWorker && navigator.serviceWorker.register('/sw.js')")
        res["sw_controls"] = wait_controller(pg)

        # ---- offline write ----
        ctx.set_offline(True)
        w = pg.evaluate(POST_TASK)
        res["offline_write_returns_queued"] = bool(
            w.get("ok") and w.get("status") == 200 and (w.get("json") or {}).get("queued")
        )
        pg.wait_for_timeout(400)
        res["outbox_has_entry"] = pg.evaluate(IDB_COUNT) >= 1
        try:
            pg.wait_for_function(
                "(() => { const e=document.getElementById('sync-indicator'); return e && getComputedStyle(e).display!=='none' && /pending/i.test(e.textContent); })()",
                timeout=4000,
            )
            res["indicator_shows_pending"] = True
        except Exception:
            res["indicator_shows_pending"] = False
        pg.screenshot(path=str(EVID / "offline-pending.png"))

        # durable storage: a fresh IndexedDB connection still sees the entry (not page memory)
        pg.wait_for_timeout(500)
        res["queue_persisted_idb"] = pg.evaluate(IDB_COUNT) >= 1

        # ---- back online, then RELOAD (fresh page = simulates tab reopen) → entry must replay ----
        ctx.set_offline(False)
        pg.reload(wait_until="domcontentloaded")
        wait_controller(pg)
        drained = False
        for _ in range(20):
            if pg.evaluate(IDB_COUNT) == 0:
                drained = True
                break
            pg.evaluate(
                "navigator.serviceWorker.controller && navigator.serviceWorker.controller.postMessage({type:'alles-flush'})"
            )
            pg.wait_for_timeout(500)
        res["survives_reload_and_replays"] = drained

        tasks = pg.evaluate("fetch('/api/tasks').then(r=>r.json())")
        res["server_received_write"] = any(
            (t.get("title") == "offline-sync-task") for t in (tasks or [])
        )

        try:
            pg.wait_for_function(
                "(() => { const e=document.getElementById('sync-indicator'); return !e || getComputedStyle(e).display==='none'; })()",
                timeout=4000,
            )
            res["indicator_clears"] = True
        except Exception:
            res["indicator_clears"] = False
        pg.screenshot(path=str(EVID / "after-replay.png"))

        res["zero_console_errors"] = len(errs) == 0
        ctx.close()
        b.close()

    ok = all(res.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in res.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_sync_1b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(res.values())}/{len(res)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
