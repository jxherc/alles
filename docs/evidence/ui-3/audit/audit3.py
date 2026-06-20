"""
DOCS audit part 3 — fully resilient. force-clicks all toolbar buttons,
wraps everything in try/except, never hangs.
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
F = {}   # findings dict

def ss(page, name, note=""):
    path = os.path.join(AUDIT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path)
        print(f"  [ss] {name}.png  {note}")
    except Exception as e:
        print(f"  [ss-ERR] {name}: {e}")

def force_click(page, selector, wait_ms=400):
    """Click with force=True to bypass overlay interception."""
    try:
        el = page.query_selector(selector)
        if not el:
            return "NOT_FOUND"
        el.click(force=True)
        page.wait_for_timeout(wait_ms)
        # dismiss dialog if one appeared
        di = page.query_selector("#_di")
        if di:
            vis = page.evaluate("!!(document.querySelector('#_di') && document.querySelector('.dialog-overlay') && window.getComputedStyle(document.querySelector('.dialog-overlay')).display !== 'none')")
            if vis:
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
        return "ok"
    except Exception as e:
        return f"err:{type(e).__name__}"

def ev(page, js, default=None):
    try:
        return page.evaluate(js)
    except:
        return default

def close_all_panels(page):
    """Close every open panel by force-clicking active buttons."""
    panel_btns = ["wiki-ai-toggle","wiki-ask-btn","wiki-outline-btn","wiki-props-btn",
                  "wiki-query-btn","wiki-history-btn","wiki-split-btn","wiki-comments-btn",
                  "wiki-board-btn","wiki-canvas-btn","wiki-theme-btn"]
    for bid in panel_btns:
        try:
            b = page.query_selector(f"#{bid}")
            if b and "active" in (b.get_attribute("class") or ""):
                b.click(force=True)
                page.wait_for_timeout(200)
        except:
            pass
    # close board overlay if visible
    try:
        board = page.query_selector("#wiki-board")
        if board and board.is_visible():
            close_x = board.query_selector(".wiki-graph-head button, [class*=close]")
            if close_x:
                close_x.click(force=True)
                page.wait_for_timeout(200)
    except:
        pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    page.on("console", lambda m: console_log.append({"t": m.type, "m": m.text})
            if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: console_log.append({"t": "pageerror", "m": str(e)}))

    # ── SETUP: load page and create doc ─────────────────────────────────────
    print("=== Setup ===")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(1200)
    ss(page, "a3-01-home", "docs home")

    nb = page.query_selector("#wiki-empty-new")
    if nb and nb.is_visible():
        nb.click()
        page.wait_for_timeout(600)
    di = page.query_selector("#_di")
    if di and di.is_visible():
        di.fill("audit3")
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
    ss(page, "a3-02-doc-with-content", "rich markdown typed")

    # ── REMAINING TOOLBAR BUTTONS (with force-click + close after) ──────────
    print("\n=== Remaining toolbar buttons ===")
    remaining = [
        ("wiki-board-btn",   "kanban board (opens overlay)"),
        ("wiki-todos-btn",   "AI extract todos"),
        ("wiki-taskroll-btn","all tasks"),
        ("wiki-history-btn", "version history"),
        ("wiki-bookmark-btn","bookmark star"),
        ("wiki-comments-btn","inline comments"),
        ("wiki-publish-btn", "publish link"),
        ("wiki-split-btn",   "split view"),
        ("wiki-theme-btn",   "css theme"),
        ("wiki-export-btn",  "export dropdown"),
        ("wiki-delete-btn",  "delete doc"),
    ]
    tb_res = {}
    for bid, desc in remaining:
        print(f"  {bid}")
        close_all_panels(page)
        page.wait_for_timeout(200)

        btn = page.query_selector(f"#{bid}")
        if not btn:
            tb_res[bid] = "NOT_FOUND"
            continue
        vis = btn.is_visible()
        cls_before = btn.get_attribute("class") or ""

        st = force_click(page, f"#{bid}", wait_ms=600)
        cls_after = (btn.get_attribute("class") or "") if btn else ""
        lbl = btn.text_content().strip() if btn else ""

        shot = f"a3-tb-{bid}"
        ss(page, shot, desc)
        tb_res[bid] = {
            "vis": vis, "st": st,
            "active_before": "active" in cls_before,
            "active_after": "active" in cls_after,
            "label": lbl,
        }
        # special: if delete dialog opened, dismiss it
        di_vis = ev(page, "!!document.querySelector('#_di') && document.querySelector('.dialog-overlay') && window.getComputedStyle(document.querySelector('.dialog-overlay')).display!=='none'", False)
        if di_vis:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)

    F["toolbar_remaining"] = tb_res
    close_all_panels(page)
    page.wait_for_timeout(300)

    # ── MUTUAL EXCLUSIVITY TEST ──────────────────────────────────────────────
    print("\n=== Mutual exclusivity: outline+props+query ===")
    for bid in ["wiki-outline-btn", "wiki-props-btn", "wiki-query-btn"]:
        b = page.query_selector(f"#{bid}")
        if b and "active" not in (b.get_attribute("class") or ""):
            force_click(page, f"#{bid}", wait_ms=300)
    ss(page, "a3-mutual-excl", "all 3 panel btns activated")
    mexcl = {}
    for bid in ["wiki-outline-btn", "wiki-props-btn", "wiki-query-btn"]:
        b = page.query_selector(f"#{bid}")
        mexcl[bid] = "active" in (b.get_attribute("class") or "") if b else False
    F["mutual_exclusivity"] = mexcl
    print(f"  Active: {mexcl}")
    close_all_panels(page)
    page.wait_for_timeout(200)

    # ── INDIVIDUAL PANEL SCREENSHOTS ────────────────────────────────────────
    print("\n=== Individual panels ===")

    panels = [
        ("wiki-outline-btn", "a3-panel-outline", "outline"),
        ("wiki-props-btn",   "a3-panel-props",   "properties"),
        ("wiki-query-btn",   "a3-panel-query",   "query"),
        ("wiki-history-btn", "a3-panel-history", "history"),
        ("wiki-comments-btn","a3-panel-comments","comments"),
        ("wiki-theme-btn",   "a3-panel-css",     "css theme"),
        ("wiki-ask-btn",     "a3-panel-ask",     "ask AI"),
    ]
    panel_content = {}
    for bid, shot, name in panels:
        close_all_panels(page)
        page.wait_for_timeout(200)
        force_click(page, f"#{bid}", wait_ms=700)
        ss(page, shot, f"{name} panel open")
        # grab text content of the panel
        txt = ev(page, f"""(() => {{
            const p = document.querySelector('.wiki-{name}, #wiki-{name}-panel, [class*="{name}"]');
            return p ? p.innerText.trim().substring(0,300) : 'not found';
        }})()""", "n/a")
        panel_content[name] = txt
        print(f"  {name}: {str(txt)[:100]}")

    F["panel_content"] = panel_content
    close_all_panels(page)
    page.wait_for_timeout(200)

    # ── FORMAT TOOLBAR ───────────────────────────────────────────────────────
    print("\n=== Format toolbar ===")
    fmts = ["h1","h2","h3","bold","italic","strike","highlight","code",
            "bullet","olist","check","quote",
            "link","image","wiki","table","codeblock","callout","toggle","columns","hr"]
    fmt_res = {}
    for fmt in fmts:
        fb = page.query_selector(f"[data-fmt='{fmt}']")
        if not fb or not fb.is_visible():
            fmt_res[fmt] = "NOT_FOUND_OR_HIDDEN"
            continue
        cm2 = page.query_selector("#wiki-live .cm-content")
        if cm2 and cm2.is_visible():
            try:
                cm2.click()
                page.keyboard.press("Control+End")
                page.keyboard.press("Enter")
                page.keyboard.type(f"sample {fmt}")
                page.wait_for_timeout(50)
                page.keyboard.press("Home")
                page.keyboard.press("Shift+End")
                page.wait_for_timeout(50)
            except:
                pass
        try:
            fb.click(force=True)
            page.wait_for_timeout(300)
            di = page.query_selector("#_di")
            has_dialog = di is not None and ev(page,
                "!!(document.querySelector('.dialog-overlay') && window.getComputedStyle(document.querySelector('.dialog-overlay')).display!=='none')", False)
            if has_dialog:
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
            fmt_res[fmt] = {"ok": True, "dialog": has_dialog}
        except Exception as e:
            fmt_res[fmt] = f"err:{type(e).__name__}"
    ss(page, "a3-fmt-toolbar", "after all format-button clicks")
    F["fmt_toolbar"] = fmt_res
    print(f"  Results: {fmt_res}")

    # ── MULTILINE SELECTION ──────────────────────────────────────────────────
    print("\n=== Multiline selection ===")
    cm2 = page.query_selector("#wiki-live .cm-content")
    if cm2 and cm2.is_visible():
        cm2.click()
        page.wait_for_timeout(150)
        page.keyboard.press("Control+Home")
        page.wait_for_timeout(100)
        for _ in range(5):
            page.keyboard.press("Shift+Down")
        page.wait_for_timeout(250)
        ss(page, "a3-multiline-sel", "5-line selection")
        geo = ev(page, """(() => {
            const sel = window.getSelection();
            if (!sel || !sel.rangeCount) return null;
            const r = sel.getRangeAt(0).getBoundingClientRect();
            const ed = document.querySelector('#wiki-live .cm-editor');
            const edR = ed ? ed.getBoundingClientRect() : null;
            return { sel:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},
                     ed: edR ? {x:Math.round(edR.x),w:Math.round(edR.width)} : null };
        })()""")
        F["multiline_geo"] = geo
        print(f"  Geo: {geo}")

    # ── RIGHT-CLICK ──────────────────────────────────────────────────────────
    print("\n=== Right-click ===")
    cm2 = page.query_selector("#wiki-live .cm-content")
    if cm2 and cm2.is_visible():
        cm2.click()
        page.wait_for_timeout(150)
        cm2.click(button="right")
        page.wait_for_timeout(600)
        ss(page, "a3-right-click", "right-click in editor")
        custom = page.query_selector(".context-menu,.ctx-menu,[class*='ctxmenu'],[class*='context-menu']")
        F["right_click"] = {"custom": custom is not None}
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    print(f"  Right-click custom menu: {F.get('right_click')}")

    # ── EXPORT MENU ──────────────────────────────────────────────────────────
    print("\n=== Export menu ===")
    close_all_panels(page)
    force_click(page, "#wiki-export-btn", wait_ms=600)
    ss(page, "a3-export-menu", "export dropdown")
    dd = page.query_selector(".dropdown-menu,.docs-export-menu,[class*='export-menu'],[class*='export-dd']")
    export_items = []
    if dd:
        export_items = [el.text_content().strip() for el in dd.query_selector_all("button,a,[class*='item']")]
    # also look for any newly visible items near the export button
    all_btns_near = ev(page, """(() => {
        const exp = document.querySelector('#wiki-export-btn');
        if (!exp) return [];
        const r = exp.getBoundingClientRect();
        return Array.from(document.querySelectorAll('button,a')).filter(el => {
            const er = el.getBoundingClientRect();
            return er.y > r.y && er.y < r.y + 200 && er.x > r.x - 100 && er.x < r.x + 200
                   && er.width > 0 && window.getComputedStyle(el).display !== 'none';
        }).map(el => el.innerText.trim());
    })()""", [])
    F["export"] = {"dropdown_el": dd is not None, "items_from_dd": export_items, "nearby_els": all_btns_near}
    print(f"  Export: {F['export']}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)

    # ── SPLIT VIEW ───────────────────────────────────────────────────────────
    print("\n=== Split view ===")
    close_all_panels(page)
    sp = page.query_selector("#wiki-split-btn")
    if sp and "active" not in (sp.get_attribute("class") or ""):
        force_click(page, "#wiki-split-btn", wait_ms=800)
    ss(page, "a3-split-view", "split view")
    split_info = ev(page, """(() => {
        const panes = document.querySelectorAll('.wiki-pane,.wiki-col,.wiki-split-col,[class*="pane"]');
        const editors = document.querySelectorAll('[id*="wiki-live"],[class*="cm-editor"]');
        return {pane_count: panes.length, editor_count: editors.length,
                pane_classes: Array.from(panes).map(p=>p.className).slice(0,4)};
    })()""")
    F["split"] = split_info
    print(f"  Split: {split_info}")
    # close split
    sp = page.query_selector("#wiki-split-btn")
    if sp and "active" in (sp.get_attribute("class") or ""):
        force_click(page, "#wiki-split-btn", wait_ms=400)

    # ── MULTIPLE DOCS / TABS BAR ─────────────────────────────────────────────
    print("\n=== Multiple docs / tabs bar ===")
    home = page.query_selector("#wiki-home-btn")
    if home and home.is_visible():
        home.click(force=True)
        page.wait_for_timeout(800)
    ss(page, "a3-home-tree", "home with docs in tree")

    for i in range(3):
        nb = page.query_selector("#wiki-new-btn") or page.query_selector("#wiki-empty-new")
        if nb and nb.is_visible():
            nb.click(force=True)
            page.wait_for_timeout(500)
        di = page.query_selector("#_di")
        if di and di.is_visible():
            di.fill(f"tab{i+1}")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1000)
        cm3 = page.query_selector("#wiki-live .cm-content")
        if cm3 and cm3.is_visible():
            cm3.click()
            page.keyboard.type(f"# Tab {i+1}\nContent.")
            page.wait_for_timeout(250)

    ss(page, "a3-tabs-bar", "tabs bar — 4 docs open")
    tabs_info = ev(page, """(() => {
        const bar = document.querySelector('#wiki-tabs');
        if (!bar) return {found:false};
        const tabs = bar.querySelectorAll('.wiki-tab,[class*="wiki-tab"]');
        const all = bar.children;
        return {found:true, tab_cls_count: tabs.length, children: all.length,
                bar_cls: bar.className,
                sample_html: bar.innerHTML.substring(0,500)};
    })()""")
    F["tabs"] = tabs_info
    print(f"  Tabs: found={tabs_info.get('found')}, tab_count={tabs_info.get('tab_cls_count')}, children={tabs_info.get('children')}")

    # ── BACKLINKS ────────────────────────────────────────────────────────────
    print("\n=== Backlinks ===")
    bl = page.query_selector("#wiki-backlinks")
    if bl:
        ev(page, "document.querySelector('#wiki-backlinks').scrollIntoView()")
        page.wait_for_timeout(300)
        ss(page, "a3-backlinks", "backlinks section")
        bl_text = ev(page, "document.querySelector('#wiki-backlinks')?.innerText?.trim()?.substring(0,200)", "")
        F["backlinks"] = {"found": True, "text": bl_text}
    else:
        F["backlinks"] = {"found": False}
    print(f"  Backlinks: {F['backlinks']}")

    # ── DELETE BUTTON ────────────────────────────────────────────────────────
    print("\n=== Delete button ===")
    del_btn = page.query_selector("#wiki-delete-btn")
    if del_btn and del_btn.is_visible():
        del_btn.click(force=True)
        page.wait_for_timeout(600)
        ss(page, "a3-delete-confirm", "delete confirmation dialog")
        dialog_vis = ev(page, """(() => {
            const ov = document.querySelector('.dialog-overlay');
            return ov ? window.getComputedStyle(ov).display : 'none';
        })()""", "err")
        F["delete"] = {"dialog_display": dialog_vis}
        print(f"  Delete dialog: {dialog_vis}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    # ── LIVE MODE RENDERING DETAILS ──────────────────────────────────────────
    print("\n=== Live mode rendering ===")
    # ensure live mode
    mode_btn = page.query_selector("#wiki-mode-toggle")
    if mode_btn:
        for _ in range(4):
            if "live" in mode_btn.text_content().strip().lower():
                break
            mode_btn.click(force=True)
            page.wait_for_timeout(400)

    live_render = ev(page, """(() => {
        const live = document.querySelector('#wiki-live');
        if (!live) return {found:false};
        return {
            found: true,
            strong: !!live.querySelector('.cm-strong'),
            em: !!live.querySelector('.cm-em'),
            h1: !!live.querySelector('.cm-header-1,.cm-line.cm-header-1,[class*="header-1"]'),
            table: !!live.querySelector('.cm-table,.cm-hmd-table,[class*="hmd-table"]'),
            img_el: !!live.querySelector('img'),
            inline_code: !!live.querySelector('.cm-inline-code,.cm-code'),
            link: !!live.querySelector('.cm-link,.cm-url'),
            checkbox: !!live.querySelector('input[type=checkbox],.cm-taskMarker'),
            quote: !!live.querySelector('.cm-quote'),
            lines: live.querySelectorAll('.cm-line').length,
        };
    })()""")
    F["live_render"] = live_render
    print(f"  Live render: {live_render}")

    # scroll to top of doc
    cm2 = page.query_selector("#wiki-live .cm-content")
    if cm2 and cm2.is_visible():
        cm2.click()
        page.keyboard.press("Control+Home")
        page.wait_for_timeout(200)
    ss(page, "a3-editor-live-top", "live editor — top of doc")

    # ── PREVIEW MODE FULL ────────────────────────────────────────────────────
    print("\n=== Preview mode ===")
    if mode_btn:
        for _ in range(4):
            if "preview" in mode_btn.text_content().strip().lower():
                break
            mode_btn.click(force=True)
            page.wait_for_timeout(400)

    ss(page, "a3-preview-full", "preview — full render")

    prev_render = ev(page, """(() => {
        const prev = document.querySelector('#wiki-preview');
        if (!prev) return {found:false};
        const callout = prev.querySelector('.callout,[class*="callout"],[data-callout]');
        const wl = prev.querySelector('.wiki-link,a[class*="wiki"]');
        const imgs = prev.querySelectorAll('img');
        return {
            found: true,
            h1: !!prev.querySelector('h1'),
            h2: !!prev.querySelector('h2'),
            table: !!prev.querySelector('table'),
            img_count: imgs.length, img_src: imgs[0]?.src || null,
            strong: !!prev.querySelector('strong'),
            em: !!prev.querySelector('em'),
            pre_code: !!prev.querySelector('pre code'),
            blockquote: !!prev.querySelector('blockquote'),
            callout: !!callout, callout_cls: callout?.className || null,
            checkbox_count: prev.querySelectorAll('input[type=checkbox]').length,
            checked_count: prev.querySelectorAll('input[type=checkbox]:checked').length,
            wikilink: !!wl, wikilink_cls: wl?.className || null,
            li_count: prev.querySelectorAll('li').length,
        };
    })()""")
    F["preview_render"] = prev_render
    print(f"  Preview render: {prev_render}")

    # ── CSS INSPECTION ────────────────────────────────────────────────────────
    print("\n=== CSS checks ===")
    # check toolbar styling
    toolbar_style = ev(page, """(() => {
        const tb = document.querySelector('#docs-toolbar');
        if (!tb) return null;
        const s = window.getComputedStyle(tb);
        return {display:s.display, flexWrap:s.flexWrap, overflow:s.overflow,
                height:s.height, bg:s.backgroundColor};
    })()""")
    F["toolbar_css"] = toolbar_style

    wiki_btn_styles = ev(page, """(() => {
        const btn = document.querySelector('#wiki-mode-toggle');
        if (!btn) return null;
        const s = window.getComputedStyle(btn);
        return {fontSize:s.fontSize, padding:s.padding, borderRadius:s.borderRadius};
    })()""")
    F["wiki_btn_style"] = wiki_btn_styles

    # check if any toolbar buttons are wrapping / overflowing
    top_bar_overflow = ev(page, """(() => {
        const bar = document.querySelector('.wiki-toolbar, .docs-top-bar, [class*="wiki-top"]');
        return bar ? {scrollWidth:bar.scrollWidth, clientWidth:bar.clientWidth,
                      overflow: bar.scrollWidth > bar.clientWidth} : null;
    })()""")
    F["topbar_overflow"] = top_bar_overflow

    # ── FINAL STATE ──────────────────────────────────────────────────────────
    # back to live
    if mode_btn:
        for _ in range(4):
            if "live" in mode_btn.text_content().strip().lower():
                break
            mode_btn.click(force=True)
            page.wait_for_timeout(400)
    ss(page, "a3-final", "final state")

    F["console_errors"] = [e for e in console_log if e["t"] == "error"]
    F["console_warnings"] = [e for e in console_log if e["t"] == "warning"]

    out = os.path.join(AUDIT_DIR, "raw_findings3.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(F, f, indent=2, default=str)
    print(f"\nSaved: {out}")
    browser.close()

print("\n=== DONE ===")
errs = [e for e in console_log if e["t"] == "error"]
warns = [e for e in console_log if e["t"] == "warning"]
print(f"Errors: {len(errs)}, Warnings: {len(warns)}")
for e in errs[:30]:
    print(f"  [ERR] {e['m'][:200]}")
for w in warns[:15]:
    print(f"  [WARN] {w['m'][:180]}")
