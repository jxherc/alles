"""
audit4 — multiline selection, right-click, export, split, tabs, backlinks,
delete, preview render, live render, final screenshots.
"""
import os, json
from playwright.sync_api import sync_playwright

AUDIT_DIR = r"C:\Users\jxh\alles\docs\evidence\ui-3\audit"
BASE_URL = "http://docs.localhost:8870/"

RICH_MD = """\
# Heading 1

## Heading 2

### Heading 3

This is **bold text** and *italic text* and `inline code` in a paragraph.

A [link to example](https://example.com) and an image below:

![placeholder image](https://via.placeholder.com/100)

---

| Column A | Column B | Column C |
|----------|----------|----------|
| row 1a   | row 1b   | row 1c   |
| row 2a   | row 2b   | row 2c   |

```python
def hello():
    print("hello world")
    return 42
```

> [!note]
> This is a callout block with some important information.

- [ ] Unchecked task item
- [x] Checked task item
- Regular bullet item
- Another bullet

1. First numbered item
2. Second numbered item
3. Third numbered item

> This is a blockquote paragraph
> spanning multiple lines

[[wikilink to another doc]]
"""

console_log = []
F = {}

def ss(page, name, note=""):
    try:
        page.screenshot(path=os.path.join(AUDIT_DIR, f"{name}.png"))
        print(f"  [ss] {name}.png  {note}")
    except Exception as e:
        print(f"  [ss-ERR] {name}: {e}")

def ev(page, js, default=None):
    try:
        return page.evaluate(js)
    except:
        return default

def force_click(page, selector, wait_ms=400):
    try:
        el = page.query_selector(selector)
        if not el: return "NOT_FOUND"
        el.click(force=True)
        page.wait_for_timeout(wait_ms)
        return "ok"
    except Exception as e:
        return f"err:{type(e).__name__}"

def close_panels(page):
    for bid in ["wiki-ai-toggle","wiki-ask-btn","wiki-outline-btn","wiki-props-btn",
                "wiki-query-btn","wiki-history-btn","wiki-split-btn","wiki-comments-btn",
                "wiki-board-btn","wiki-theme-btn"]:
        try:
            b = page.query_selector(f"#{bid}")
            if b and "active" in (b.get_attribute("class") or ""):
                b.click(force=True)
                page.wait_for_timeout(150)
        except: pass
    # close board overlay
    try:
        close_x = page.query_selector("#wiki-board .wiki-graph-head button, .wiki-board-close")
        if close_x: close_x.click(force=True); page.wait_for_timeout(200)
    except: pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    page.on("console", lambda m: console_log.append({"t":m.type,"m":m.text}) if m.type in ("error","warning") else None)
    page.on("pageerror", lambda e: console_log.append({"t":"pageerror","m":str(e)}))

    # setup
    print("=== Setup ===")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(1200)
    nb = page.query_selector("#wiki-empty-new")
    if nb and nb.is_visible():
        nb.click()
        page.wait_for_timeout(600)
    di = page.query_selector("#_di")
    if di and di.is_visible():
        di.fill("audit4")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.keyboard.press("Control+a")
        page.wait_for_timeout(50)
        for line in RICH_MD.split("\n"):
            page.keyboard.type(line)
            page.keyboard.press("Enter")
            page.wait_for_timeout(7)
        page.wait_for_timeout(600)
    ss(page, "a4-01-doc-ready", "doc with rich markdown")

    # ── MULTILINE SELECTION ──────────────────────────────────────────────────
    print("\n=== Multiline selection ===")
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.wait_for_timeout(150)
        page.keyboard.press("Control+Home")
        page.wait_for_timeout(100)
        # ArrowDown, not Down
        for _ in range(5):
            page.keyboard.press("Shift+ArrowDown")
        page.wait_for_timeout(250)
        ss(page, "a4-multiline-sel", "5-line selection — check if highlight bleeds into margin")
        geo = ev(page, """(() => {
            const sel = window.getSelection();
            if (!sel || !sel.rangeCount) return null;
            const r = sel.getRangeAt(0).getBoundingClientRect();
            const ed = document.querySelector('#wiki-live .cm-editor');
            const cont = document.querySelector('#wiki-live .cm-content');
            const edR = ed ? ed.getBoundingClientRect() : null;
            const cR = cont ? cont.getBoundingClientRect() : null;
            return {
                sel:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},
                editor:{x:Math.round(edR?.x||0),w:Math.round(edR?.width||0)},
                content:{x:Math.round(cR?.x||0),w:Math.round(cR?.width||0)},
            };
        })()""")
        F["multiline_geo"] = geo
        print(f"  Geo: {geo}")

    # ── RIGHT-CLICK ──────────────────────────────────────────────────────────
    print("\n=== Right-click context menu ===")
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.wait_for_timeout(150)
        cm.click(button="right")
        page.wait_for_timeout(700)
        ss(page, "a4-right-click", "right-click — native or custom menu?")
        custom = page.query_selector(".context-menu,.ctx-menu,[class*='ctxmenu'],[class*='context-menu']")
        # also check via evaluate
        custom_ev = ev(page, """(() => {
            const cands = ['.context-menu','.ctx-menu','[class*=ctxmenu]'];
            for (const s of cands) {
                const el = document.querySelector(s);
                if (el) return {found:true, cls:el.className};
            }
            return {found:false};
        })()""")
        F["right_click"] = {"custom_el": custom is not None, "custom_ev": custom_ev}
        print(f"  Right-click: {F['right_click']}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)

    # ── EXPORT MENU ──────────────────────────────────────────────────────────
    print("\n=== Export menu ===")
    close_panels(page)
    exp = page.query_selector("#wiki-export-btn")
    if exp and exp.is_visible():
        exp.click(force=True)
        page.wait_for_timeout(700)
        ss(page, "a4-export-menu", "export dropdown open")
        # find dropdown by looking for newly visible elements
        export_els = ev(page, """(() => {
            const btn = document.querySelector('#wiki-export-btn');
            if (!btn) return [];
            const r = btn.getBoundingClientRect();
            return Array.from(document.querySelectorAll('*')).filter(el => {
                if (!el.offsetParent) return false;
                const er = el.getBoundingClientRect();
                return er.y > r.bottom - 5 && er.top < r.bottom + 300
                    && er.left >= r.left - 50 && er.right <= r.right + 50
                    && el.tagName !== 'BODY' && el.tagName !== 'HTML'
                    && er.height > 0 && er.width > 0
                    && (el.tagName === 'BUTTON' || el.tagName === 'A' || el.tagName === 'LI');
            }).map(el => ({tag:el.tagName, text:el.innerText.trim().substring(0,40), cls:el.className.substring(0,40)}));
        })()""", [])
        F["export"] = {"dropdown_els": export_els}
        print(f"  Export els: {export_els}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    # ── SPLIT VIEW ───────────────────────────────────────────────────────────
    print("\n=== Split view ===")
    close_panels(page)
    sp = page.query_selector("#wiki-split-btn")
    if sp and "active" not in (sp.get_attribute("class") or ""):
        sp.click(force=True)
        page.wait_for_timeout(900)
    ss(page, "a4-split-view", "split view open")
    split_info = ev(page, """(() => {
        // look for structural clues of a second pane
        const wiki = document.querySelector('#wiki-container, .wiki-container, [class*="wiki-wrap"]');
        const body = document.querySelector('#docs-body, .docs-body, [class*="docs-body"]');
        const panes = document.querySelectorAll('[class*="pane"],[class*="split-col"],[class*="wiki-col"]');
        return {
            pane_els: Array.from(panes).map(p=>({cls:p.className.substring(0,60), vis:p.offsetParent!==null})),
            body_cls: body?.className || null,
        };
    })()""")
    F["split"] = split_info
    print(f"  Split: {split_info}")
    # turn off
    sp = page.query_selector("#wiki-split-btn")
    if sp and "active" in (sp.get_attribute("class") or ""):
        sp.click(force=True); page.wait_for_timeout(400)

    # ── TABS BAR ────────────────────────────────────────────────────────────
    print("\n=== Tabs bar ===")
    home = page.query_selector("#wiki-home-btn")
    if home and home.is_visible():
        home.click(force=True); page.wait_for_timeout(800)
    ss(page, "a4-home-tree", "docs home with tree")

    for i in range(3):
        nb = page.query_selector("#wiki-new-btn") or page.query_selector("#wiki-empty-new")
        if nb and nb.is_visible():
            nb.click(force=True); page.wait_for_timeout(500)
        di = page.query_selector("#_di")
        if di and di.is_visible():
            di.fill(f"t{i+1}"); page.keyboard.press("Enter"); page.wait_for_timeout(1000)
        cm3 = page.query_selector("#wiki-live .cm-content")
        if cm3 and cm3.is_visible():
            cm3.click(); page.keyboard.type(f"# T{i+1}\nHi."); page.wait_for_timeout(200)

    ss(page, "a4-tabs-bar", "tabs bar — multiple docs")
    tabs_info = ev(page, """(() => {
        const bar = document.querySelector('#wiki-tabs');
        if (!bar) return {found:false};
        const tabs = bar.querySelectorAll('.wiki-tab,[class*="wiki-tab"]');
        return {
            found: true,
            cls: bar.className,
            tab_count: tabs.length,
            children: bar.children.length,
            display: window.getComputedStyle(bar).display,
            overflows: bar.scrollWidth > bar.clientWidth,
            html_sample: bar.innerHTML.substring(0,400),
        };
    })()""")
    F["tabs"] = tabs_info
    print(f"  Tabs: {tabs_info}")

    # ── BACKLINKS ────────────────────────────────────────────────────────────
    print("\n=== Backlinks ===")
    bl = page.query_selector("#wiki-backlinks")
    if bl:
        ev(page, "document.querySelector('#wiki-backlinks')?.scrollIntoView()")
        page.wait_for_timeout(300)
        ss(page, "a4-backlinks", "backlinks panel")
        bl_text = ev(page, "document.querySelector('#wiki-backlinks')?.innerText?.trim()", "")
        F["backlinks"] = {"found": True, "text": bl_text[:300] if bl_text else ""}
    else:
        F["backlinks"] = {"found": False}
    print(f"  Backlinks: {F['backlinks']}")

    # ── DELETE CONFIRM ───────────────────────────────────────────────────────
    print("\n=== Delete button ===")
    del_btn = page.query_selector("#wiki-delete-btn")
    if del_btn and del_btn.is_visible():
        del_btn.click(force=True); page.wait_for_timeout(700)
        ss(page, "a4-delete-confirm", "delete confirmation dialog")
        dialog_state = ev(page, """(() => {
            const ov = document.querySelector('.dialog-overlay');
            if (!ov) return 'no overlay found';
            const s = window.getComputedStyle(ov);
            const inp = ov.querySelector('input,textarea');
            return {display:s.display, text: ov.innerText.trim().substring(0,200), has_input:!!inp};
        })()""")
        F["delete"] = dialog_state
        print(f"  Delete: {dialog_state}")
        page.keyboard.press("Escape"); page.wait_for_timeout(300)

    # ── LIVE RENDER DETAILS ──────────────────────────────────────────────────
    print("\n=== Live render ===")
    mode_btn = page.query_selector("#wiki-mode-toggle")
    if mode_btn:
        for _ in range(4):
            if "live" in mode_btn.text_content().strip().lower(): break
            mode_btn.click(force=True); page.wait_for_timeout(400)
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click(); page.keyboard.press("Control+Home"); page.wait_for_timeout(200)
    ss(page, "a4-live-top", "live mode — top of doc, headings")

    live_r = ev(page, """(() => {
        const l = document.querySelector('#wiki-live');
        if (!l) return {found:false};
        // check CodeMirror highlight classes
        return {
            found:true,
            strong: !!l.querySelector('.cm-strong'),
            em: !!l.querySelector('.cm-em'),
            hdr1: !!l.querySelector('[class*="header-1"]'),
            table_line: !!l.querySelector('[class*="hmd-table"],[class*="cm-table"]'),
            img_widget: !!l.querySelector('img,.cm-image-widget'),
            inline_code: !!l.querySelector('.cm-inline-code'),
            wikilink: !!l.querySelector('.cm-hmd-internal-link,.cm-wiki-link'),
            checkbox: !!l.querySelector('input[type=checkbox]'),
            quote_mark: !!l.querySelector('.cm-quote'),
            line_count: l.querySelectorAll('.cm-line').length,
        };
    })()""")
    F["live_render"] = live_r
    print(f"  Live: {live_r}")

    # ── PREVIEW RENDER ───────────────────────────────────────────────────────
    print("\n=== Preview render ===")
    if mode_btn:
        for _ in range(4):
            if "preview" in mode_btn.text_content().strip().lower(): break
            mode_btn.click(force=True); page.wait_for_timeout(400)
    ss(page, "a4-preview-top", "preview — top of doc")

    prev_r = ev(page, """(() => {
        const p = document.querySelector('#wiki-preview');
        if (!p) return {found:false};
        const callout = p.querySelector('.callout,[data-callout],[class*="callout"]');
        const wl = p.querySelector('.wiki-link,a[href*="wiki"],a[class*="wiki"]');
        const imgs = p.querySelectorAll('img');
        const chks = p.querySelectorAll('input[type=checkbox]');
        return {
            found:true,
            h1:!!p.querySelector('h1'), h2:!!p.querySelector('h2'), h3:!!p.querySelector('h3'),
            strong:!!p.querySelector('strong'), em:!!p.querySelector('em'),
            code:!!p.querySelector('code'), pre:!!p.querySelector('pre'),
            table:!!p.querySelector('table'), blockquote:!!p.querySelector('blockquote'),
            callout:!!callout, callout_text: callout?.innerText?.trim()?.substring(0,80)||null,
            img_count:imgs.length, img_loads: Array.from(imgs).map(i=>i.complete).slice(0,3),
            checkbox_count:chks.length, checked:p.querySelectorAll('input[type=checkbox]:checked').length,
            wikilink:!!wl, wikilink_text:wl?.innerText||null,
            ol:!!p.querySelector('ol'), ul:!!p.querySelector('ul'),
        };
    })()""")
    F["preview_render"] = prev_r
    print(f"  Preview: {prev_r}")

    ss(page, "a4-preview-full", "preview — full doc render")

    # back to live
    if mode_btn:
        for _ in range(4):
            if "live" in mode_btn.text_content().strip().lower(): break
            mode_btn.click(force=True); page.wait_for_timeout(400)

    # ── TOOLBAR OVERFLOW CHECK ───────────────────────────────────────────────
    print("\n=== Toolbar overflow / visual ===")
    ss(page, "a4-toolbar-visual", "main toolbar visual check")
    overflow = ev(page, """(() => {
        // find the top nav bar with all the doc buttons
        const bar = document.querySelector('.wiki-topbar, .docs-toolbar-row, [class*="wiki-header"], [class*="docs-top"]');
        const wikiBar = document.querySelector('#wiki-toolbar, .wiki-toolbar');
        return {
            bar: bar ? {cls:bar.className, scrollW:bar.scrollWidth, clientW:bar.clientWidth, overflow:bar.scrollWidth>bar.clientWidth} : null,
            wikiBar: wikiBar ? {cls:wikiBar.className, scrollW:wikiBar.scrollWidth, clientW:wikiBar.clientWidth} : null,
        };
    })()""")
    F["toolbar_overflow"] = overflow
    print(f"  Overflow: {overflow}")

    # inspect the button row class/layout
    btn_row = ev(page, """(() => {
        // the bar that holds live/ai/ask/guide/outline... buttons
        const first_tb_btn = document.querySelector('#wiki-mode-toggle');
        if (!first_tb_btn) return null;
        const row = first_tb_btn.parentElement;
        const s = window.getComputedStyle(row);
        return {cls:row.className, display:s.display, flexWrap:s.flexWrap,
                w:row.clientWidth, scrollW:row.scrollWidth,
                overflows: row.scrollWidth > row.clientWidth};
    })()""")
    F["btn_row_layout"] = btn_row
    print(f"  Btn row: {btn_row}")

    # ── FINAL ────────────────────────────────────────────────────────────────
    ss(page, "a4-final", "final state")

    F["console_errors"] = [e for e in console_log if e["t"] == "error"]
    F["console_warnings"] = [e for e in console_log if e["t"] == "warning"]

    out = os.path.join(AUDIT_DIR, "raw_findings4.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(F, f, indent=2, default=str)
    print(f"\nSaved: {out}")
    browser.close()

print("\n=== DONE ===")
errs = [e for e in console_log if e["t"]=="error"]
warns = [e for e in console_log if e["t"]=="warning"]
print(f"Errors:{len(errs)} Warnings:{len(warns)}")
for e in errs[:30]: print(f"  [ERR] {e['m'][:220]}")
for w in warns[:15]: print(f"  [WARN] {w['m'][:180]}")
