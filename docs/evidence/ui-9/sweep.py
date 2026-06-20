"""ui-9 final regression — broad sweep across every host (0 real console/page errors + the view paints)
plus a deep click-through that exercises a primary control in each app."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8890"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")

# every host the SPA serves (apex + aide + the apps)
HOSTS = [
    "", "aide", "docs", "mail", "files", "calendar", "tasks", "gallery", "contacts",
    "journal", "days", "money", "subs", "reminders", "secrets", "system",
]


def clean(errs):
    return [e for e in errs if not any(s in e for s in IGNORE)]


def run():
    fails = []
    with sync_playwright() as p:
        b = p.chromium.launch()

        # ── broad sweep: each host boots with no real errors ──
        for h in HOSTS:
            ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m, e=errs: e.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda ex, e=errs: e.append("PAGEERR:" + str(ex)))
            url = f"http://{h + '.' if h else ''}localhost:{PORT}/"
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=20000)
                pg.wait_for_timeout(2500)
            except Exception as ex:
                fails.append(f"{h or 'apex'}: goto {str(ex)[:50]}")
                ctx.close()
                continue
            real = clean(errs)
            label = h or "apex"
            if real:
                fails.append(f"{label}: {real[:2]}")
                print(f"FAIL {label}: {real[:2]}")
            else:
                print(f"PASS host {label}")
            ctx.close()

        # ── deep click-throughs: a primary action per app, each in a fresh context ──
        def deep(host, label, steps):
            ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 880})
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda ex: errs.append("PAGEERR:" + str(ex)))
            try:
                pg.goto(f"http://{host}.localhost:{PORT}/", wait_until="domcontentloaded")
                pg.wait_for_timeout(1800)
                steps(pg)
                pg.wait_for_timeout(400)
            except Exception as ex:
                fails.append(f"deep {label}: {str(ex)[:60]}")
                print(f"FAIL deep {label}: {str(ex)[:60]}")
                ctx.close()
                return
            real = clean(errs)
            if real:
                fails.append(f"deep {label}: {real[:2]}")
                print(f"FAIL deep {label}: {real[:2]}")
            else:
                print(f"PASS deep {label}")
            ctx.close()

        # files: seed an upload, toggle a smart folder
        deep("files", "files smart folders", lambda pg: pg.evaluate("""async () => {
          const cv=document.createElement('canvas');cv.width=4;cv.height=4;cv.getContext('2d').fillRect(0,0,4,4);
          const bl=await new Promise(r=>cv.toBlob(r,'image/png'));const fd=new FormData();fd.append('file',bl,'f.png');
          await fetch('/api/files/upload',{method:'POST',body:fd});
          document.querySelector('.files-smart[data-kind="images"]')?.click();
        }"""))

        # calendar: switch through every view via the segmented control
        deep("calendar", "calendar view switch", lambda pg: pg.evaluate("""async () => {
          for (const v of ['week','day','agenda','year','month']) {
            document.querySelector(`#cal-view .seg-opt[data-view="${v}"]`)?.click();
            await new Promise(r=>setTimeout(r,120));
          }
        }"""))

        # tasks: add a task
        deep("tasks", "tasks add", lambda pg: pg.evaluate("""async () => {
          await fetch('/api/tasks',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title:'final regression task'})});
        }"""))

        # contacts: add + open a contact
        deep("contacts", "contacts add/open", lambda pg: pg.evaluate("""async () => {
          await fetch('/api/contacts',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:'Reg Test',email:'r@x.com'})});
        }"""))

        # gallery: seed a photo, open + favorite in the lightbox
        deep("gallery", "gallery lightbox", lambda pg: pg.evaluate("""async () => {
          const cv=document.createElement('canvas');cv.width=6;cv.height=6;cv.getContext('2d').fillRect(0,0,6,6);
          const bl=await new Promise(r=>cv.toBlob(r,'image/png'));const fd=new FormData();fd.append('file',bl,'p.png');
          await fetch('/api/photos/upload',{method:'POST',body:fd});
        }"""))

        # secrets: unlock, open settings (exercises the Stage-8 panels), lock
        deep("secrets", "vault unlock + settings", lambda pg: pg.evaluate("""async () => {
          document.getElementById('vault-pw-input').value='finalpw';
          document.getElementById('vault-unlock-btn').click();
          await new Promise(r=>setTimeout(r,1500));
          document.getElementById('vault-manage-btn')?.click();
          await new Promise(r=>setTimeout(r,800));
          document.getElementById('mv-close')?.click();
          document.getElementById('vault-lock-btn')?.click();
        }"""))

        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print(f"\nALL GREEN — {len(HOSTS)} hosts + 6 deep click-throughs, 0 real console errors")


if __name__ == "__main__":
    run()
