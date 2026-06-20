"""ui-3m verify — the select-text -> comment flow works in the default LIVE editor
(not just preview): selecting shows the comment chip, and a thread is created + rendered."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1200, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(1100)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        # select some text in the LIVE editor and fire mouseup
        sel_ok = pg.evaluate("""() => {
          const c = document.querySelector('.cm-content');
          const w = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
          let node;
          while (w.nextNode()) { if (w.currentNode.textContent.includes('Heading')) { node = w.currentNode; break; } }
          if (!node) return false;
          const r = document.createRange(); r.setStart(node, 0); r.setEnd(node, Math.min(7, node.textContent.length));
          const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          document.querySelector('#wiki-live').dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
          return true;
        }""")
        ok("could select text in the live editor", sel_ok)
        pg.wait_for_timeout(300)
        fab_shown = pg.evaluate("() => { const f = document.querySelector('#wiki-comment-fab'); return f && f.style.display === 'block'; }")
        ok("comment chip appears on live selection", fab_shown)

        # click the chip → prompt dialog → fill + ok
        pg.eval_on_selector("#wiki-comment-fab", "el => el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))")
        pg.wait_for_timeout(400)
        di = pg.query_selector("#_di")
        ok("comment prompt opens", di is not None)
        if di:
            di.fill("this is my comment")
            pg.click("#_dy")
            pg.wait_for_timeout(700)
            d = pg.evaluate("""() => ({
              shown: document.querySelector('#wiki-comments')?.style.display === 'block',
              threads: document.querySelectorAll('.wiki-cmt-thread').length,
              body: (document.querySelector('.wiki-cmt-body')?.textContent || ''),
              anchor: (document.querySelector('.wiki-cmt-anchor')?.textContent || ''),
            })""")
            ok("comments panel opened", d["shown"])
            ok("a thread was created", d["threads"] >= 1)
            ok("thread shows the comment body", "this is my comment" in d["body"])
            ok("thread anchors the selected text", "Head" in d["anchor"])

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()
