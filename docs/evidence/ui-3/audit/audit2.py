"""
DOCS audit part 2 — continues from where part 1 hung (canvas dialog dismissed).
Covers: remaining toolbar btns, format toolbar, multiline selection, right-click,
history, export, split, tabs, backlinks, delete, visual checks.
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
findings = {}

def ss(page, name, note=""):
    path = os.path.join(AUDIT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path)
        print(f"  [ss] {name}.png — {note}")
    except Exception as e:
        print(f"  [ss-ERR] {name}: {e}")

def dismiss_any_dialog(page):
    """Press Escape if a dialog overlay is open."""
    try:
        di = page.query_selector("#_di")
        if di and di.is_visible():
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            return True
    except:
        pass
    return False

def safe_click(page, selector, wait_ms=700):
    """Click, dismiss any dialog that pops up, return status."""
    try:
        el = page.query_selector(selector)
        if not el:
            return "NOT FOUND"
        if not el.is_visible():
            return "NOT VISIBLE"
        el.click()
        page.wait_for_timeout(min(wait_ms, 500))
        dismiss_any_dialog(page)
        page.wait_for_timeout(200)
        return "ok"
    except Exception as e:
        return f"error:{e}"

def elem_vis(page, sel):
    try:
        el = page.query_selector(sel)
        return el is not None and el.is_visible()
    except:
        return False

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    page.on("console", lambda m: console_log.append({"t": m.type, "m": m.text})
            if m.type in ("error","warning") else None)
    page.on("pageerror", lambda e: console_log.append({"t":"pageerror","m":str(e)}))

    # Load and create a doc (same as part 1)
    print("=== Setup ===")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(1200)

    nb = page.query_selector("#wiki-empty-new")
    if nb and nb.is_visible():
        nb.click()
        page.wait_for_timeout(600)
        di = page.query_selector("#_di")
        if di and di.is_visible():
            di.fill("audit2-doc")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)

    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.keyboard.press("Control+a")
        page.wait_for_timeout(80)
        for line in RICH_MD.split("\n"):
            page.keyboard.type(line)
            page.keyboard.press("Enter")
            page.wait_for_timeout(8)
        page.wait_for_timeout(600)
        ss(page, "p2-01-doc-loaded", "doc with rich markdown loaded")

    # ── TOOLBAR BUTTONS (canvas onward, with dialog dismiss) ─────────────────
    print("\n=== Toolbar buttons (canvas onward) ===")
    remaining_btns = [
        ("wiki-canvas-btn",  "canvas — prompts for name"),
        ("wiki-board-btn",   "kanban board"),
        ("wiki-todos-btn",   "AI extract todos"),
        ("wiki-taskroll-btn","all tasks"),
        ("wiki-history-btn", "version history"),
        ("wiki-bookmark-btn","bookmark star"),
        ("wiki-comments-btn","comments panel"),
        ("wiki-publish-btn", "publish link"),
        ("wiki-split-btn",   "split view"),
        ("wiki-theme-btn",   "custom CSS"),
        ("wiki-export-btn",  "export dropdown"),
    ]
    tb2 = {}
    for idx, (bid, desc) in enumerate(remaining_btns):
        print(f"  {bid}")
        btn = page.query_selector(f"#{bid}")
        if not btn or not btn.is_visible():
            tb2[bid] = "NOT VISIBLE"
            continue
        cls_before = btn.get_attribute("class") or ""
        try:
            btn.click()
            page.wait_for_timeout(500)
            # dismiss any name prompt
            dismiss_any_dialog(page)
            page.wait_for_timeout(300)
        except Exception as e:
            tb2[bid] = f"error:{e}"
            continue
        cls_after = btn.get_attribute("class") or ""
        label = btn.text_content().strip()
        shot = f"p2-tb-{bid}"
        ss(page, shot, f"{desc}")
        tb2[bid] = {
            "active_before": "active" in cls_before,
            "active_after": "active" in cls_after,
            "label": label,
        }
    findings["toolbar_remaining"] = tb2

    # close open panels
    for bid in ["wiki-ai-toggle","wiki-ask-btn","wiki-outline-btn","wiki-props-btn",
                "wiki-query-btn","wiki-history-btn","wiki-split-btn","wiki-comments-btn"]:
        b2 = page.query_selector(f"#{bid}")
        if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
            b2.click()
            page.wait_for_timeout(150)

    # ── MUTUAL EXCLUSIVITY TEST ───────────────────────────────────────────────
    print("\n=== Mutual exclusivity: outline+props+query ===")
    for bid in ["wiki-outline-btn","wiki-props-btn","wiki-query-btn"]:
        b2 = page.query_selector(f"#{bid}")
        if b2 and b2.is_visible():
            if "active" not in (b2.get_attribute("class") or ""):
                b2.click()
                page.wait_for_timeout(350)
    ss(page, "p2-mutual-excl", "outline+props+query all triggered")
    mexcl = {}
    for bid in ["wiki-outline-btn","wiki-props-btn","wiki-query-btn"]:
        b2 = page.query_selector(f"#{bid}")
        mexcl[bid] = "active" in (b2.get_attribute("class") or "") if b2 else False
    findings["mutual_exclusivity"] = mexcl
    print(f"  Active states: {mexcl}")

    # close all
    for bid in ["wiki-outline-btn","wiki-props-btn","wiki-query-btn"]:
        b2 = page.query_selector(f"#{bid}")
        if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
            b2.click()
            page.wait_for_timeout(150)

    # ── INDIVIDUAL PANEL CONTENT CHECKS ──────────────────────────────────────
    print("\n=== Individual panel content ===")

    # Outline panel
    b2 = page.query_selector("#wiki-outline-btn")
    if b2 and b2.is_visible() and "active" not in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(700)
    ss(page, "p2-outline-panel", "outline panel — headings listed?")
    outline_items = page.evaluate("""() => {
        const p = document.querySelector('.wiki-outline, #wiki-outline-panel, [class*="outline"]');
        return p ? p.innerText.trim().substring(0,400) : 'panel not found';
    }""")
    findings["outline_content"] = outline_items
    print(f"  Outline: {outline_items[:150]}")
    b2 = page.query_selector("#wiki-outline-btn")
    if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(200)

    # Props panel
    b2 = page.query_selector("#wiki-props-btn")
    if b2 and b2.is_visible() and "active" not in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(700)
    ss(page, "p2-props-panel", "properties/frontmatter panel")
    props_content = page.evaluate("""() => {
        const p = document.querySelector('.wiki-props, #wiki-props-panel, [class*="props"]');
        return p ? p.innerText.trim().substring(0,400) : 'panel not found';
    }""")
    findings["props_content"] = props_content
    print(f"  Props: {props_content[:150]}")
    b2 = page.query_selector("#wiki-props-btn")
    if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(200)

    # Query panel
    b2 = page.query_selector("#wiki-query-btn")
    if b2 and b2.is_visible() and "active" not in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(700)
    ss(page, "p2-query-panel", "query/dataview panel")
    query_content = page.evaluate("""() => {
        const p = document.querySelector('.wiki-query, #wiki-query-panel, [class*="query"]');
        return p ? p.innerText.trim().substring(0,400) : 'panel not found';
    }""")
    findings["query_content"] = query_content
    print(f"  Query: {query_content[:150]}")
    b2 = page.query_selector("#wiki-query-btn")
    if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(200)

    # History panel
    b2 = page.query_selector("#wiki-history-btn")
    if b2 and b2.is_visible() and "active" not in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(700)
    ss(page, "p2-history-panel", "history panel")
    hist_content = page.evaluate("""() => {
        const p = document.querySelector('.wiki-history, #wiki-history-panel, [class*="hist"]');
        return p ? p.innerText.trim().substring(0,400) : 'panel not found';
    }""")
    findings["history_content"] = hist_content
    print(f"  History: {hist_content[:150]}")
    b2 = page.query_selector("#wiki-history-btn")
    if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(200)

    # Comments panel
    b2 = page.query_selector("#wiki-comments-btn")
    if b2 and b2.is_visible() and "active" not in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(700)
    ss(page, "p2-comments-panel", "comments panel")
    b2 = page.query_selector("#wiki-comments-btn")
    if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
        b2.click()
        page.wait_for_timeout(200)

    # ── FORMAT TOOLBAR ────────────────────────────────────────────────────────
    print("\n=== Format toolbar ===")
    fmts = ["h1","h2","h3","bold","italic","strike","highlight","code",
            "bullet","olist","check","quote",
            "link","image","wiki","table","codeblock","callout","toggle","columns","hr"]
    fmt_res = {}
    for fmt in fmts:
        print(f"  fmt:{fmt}")
        fb = page.query_selector(f"[data-fmt='{fmt}']")
        if not fb:
            fmt_res[fmt] = "NOT FOUND"
            continue
        if not fb.is_visible():
            fmt_res[fmt] = "NOT VISIBLE"
            continue
        cm = page.query_selector("#wiki-live .cm-content")
        if cm and cm.is_visible():
            cm.click()
            page.wait_for_timeout(80)
            page.keyboard.press("Control+End")
            page.keyboard.press("Enter")
            page.keyboard.type(f"testword{fmt}")
            page.wait_for_timeout(60)
            page.keyboard.press("Home")
            page.keyboard.press("Shift+End")
            page.wait_for_timeout(60)
        try:
            fb.click()
            page.wait_for_timeout(350)
            dismiss_any_dialog(page)
            fmt_res[fmt] = "ok"
        except Exception as e:
            fmt_res[fmt] = f"err:{e}"
    ss(page, "p2-fmt-toolbar", "after format toolbar clicks")
    findings["fmt_toolbar"] = fmt_res

    # ── MULTILINE SELECTION ──────────────────────────────────────────────────
    print("\n=== Multiline selection ===")
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.wait_for_timeout(150)
        page.keyboard.press("Control+Home")
        page.wait_for_timeout(100)
        for _ in range(5):
            page.keyboard.press("Shift+Down")
        page.wait_for_timeout(300)
        ss(page, "p2-multiline-sel", "5-line selection — does highlight go into margin?")
        geo = page.evaluate("""() => {
            const sel = window.getSelection();
            if (!sel || !sel.rangeCount) return null;
            const rng = sel.getRangeAt(0).getBoundingClientRect();
            const ed = document.querySelector('#wiki-live .cm-editor');
            const edRect = ed ? ed.getBoundingClientRect() : null;
            const scroll = document.querySelector('#wiki-live .cm-scroller');
            const scrollRect = scroll ? scroll.getBoundingClientRect() : null;
            return { sel: {x:rng.x,y:rng.y,w:rng.width,h:rng.height},
                     ed: edRect, scroll: scrollRect };
        }""")
        findings["multiline_geo"] = geo
        print(f"  Geo: {geo}")

    # ── RIGHT-CLICK ──────────────────────────────────────────────────────────
    print("\n=== Right-click ===")
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.wait_for_timeout(150)
        cm.click(button="right")
        page.wait_for_timeout(600)
        ss(page, "p2-right-click", "right-click — custom or native?")
        custom = page.query_selector(".context-menu, .ctx-menu, [class*='ctxmenu'], [class*='context-menu']")
        findings["right_click"] = {"custom": custom is not None}
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)

    # ── EXPORT MENU ──────────────────────────────────────────────────────────
    print("\n=== Export menu ===")
    exp = page.query_selector("#wiki-export-btn")
    if exp and exp.is_visible():
        exp.click()
        page.wait_for_timeout(600)
        ss(page, "p2-export-menu", "export dropdown")
        dd = page.query_selector(".dropdown-menu, .docs-export-menu, [class*='export']")
        items = []
        if dd:
            items = [el.text_content().strip() for el in dd.query_selector_all("button,a,[class*='item']")]
        findings["export"] = {"dropdown": dd is not None, "items": items}
        print(f"  Export items: {items}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)

    # ── SPLIT VIEW ───────────────────────────────────────────────────────────
    print("\n=== Split view ===")
    sp = page.query_selector("#wiki-split-btn")
    if sp and sp.is_visible():
        if "active" not in (sp.get_attribute("class") or ""):
            sp.click()
            page.wait_for_timeout(800)
        ss(page, "p2-split-view", "split view")
        # check for second pane
        second = page.evaluate("""() => {
            const cands = ['.wiki-pane', '.wiki-split', '.docs-pane', '[class*="pane-b"]', '[class*="split-pane"]'];
            for (const s of cands) {
                const els = document.querySelectorAll(s);
                if (els.length >= 2) return {selector: s, count: els.length};
                if (els.length === 1) return {selector: s, count: 1};
            }
            return null;
        }""")
        findings["split"] = {"found": second}
        print(f"  Split pane: {second}")
        sp.click()
        page.wait_for_timeout(400)

    # ── MULTIPLE DOCS / TABS ─────────────────────────────────────────────────
    print("\n=== Multiple docs / tabs ===")
    home = page.query_selector("#wiki-home-btn")
    if home and home.is_visible():
        home.click()
        page.wait_for_timeout(700)
    ss(page, "p2-home-with-docs", "home with docs in tree")

    # create 3 more docs
    for i in range(3):
        nb2 = page.query_selector("#wiki-new-btn")
        if not nb2 or not nb2.is_visible():
            nb2 = page.query_selector("#wiki-empty-new")
        if nb2 and nb2.is_visible():
            nb2.click()
            page.wait_for_timeout(500)
            di = page.query_selector("#_di")
            if di and di.is_visible():
                di.fill(f"tab-test-{i+1}")
                page.keyboard.press("Enter")
                page.wait_for_timeout(1000)
                cm2 = page.query_selector("#wiki-live .cm-content")
                if cm2 and cm2.is_visible():
                    cm2.click()
                    page.keyboard.type(f"# Tab {i+1}\n\nContent {i+1}.")
                    page.wait_for_timeout(300)

    ss(page, "p2-tabs-bar", "tabs bar with multiple docs")
    tabs = page.evaluate("""() => {
        const bar = document.querySelector('#wiki-tabs');
        if (!bar) return {found:false};
        const allCls = bar.className;
        const tabs = bar.querySelectorAll('[class*="tab"], li, button');
        return {found:true, cls:allCls, count: tabs.length,
                html: bar.innerHTML.substring(0,600)};
    }""")
    findings["tabs"] = tabs
    print(f"  Tabs: found={tabs.get('found')}, count={tabs.get('count')}")

    # ── BACKLINKS ────────────────────────────────────────────────────────────
    print("\n=== Backlinks ===")
    bl = page.query_selector("#wiki-backlinks")
    if bl:
        try:
            page.evaluate("document.querySelector('#wiki-backlinks').scrollIntoView()")
            page.wait_for_timeout(300)
            ss(page, "p2-backlinks", "backlinks section")
            bl_text = page.evaluate("document.querySelector('#wiki-backlinks').innerText.trim().substring(0,200)")
            findings["backlinks"] = {"found": True, "text": bl_text}
        except Exception as e:
            findings["backlinks"] = {"found": True, "error": str(e)}
    else:
        findings["backlinks"] = {"found": False}

    # ── DELETE BUTTON ────────────────────────────────────────────────────────
    print("\n=== Delete button ===")
    del_btn = page.query_selector("#wiki-delete-btn")
    if del_btn and del_btn.is_visible():
        del_btn.click()
        page.wait_for_timeout(600)
        ss(page, "p2-delete-confirm", "delete confirmation")
        confirm_vis = page.evaluate("""() => {
            const ov = document.querySelector('.dialog-overlay');
            return ov ? window.getComputedStyle(ov).display : 'no overlay';
        }""")
        findings["delete"] = {"confirm_display": confirm_vis}
        print(f"  Confirm dialog: {confirm_vis}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    # ── LIVE MODE DEEP INSPECTION ─────────────────────────────────────────────
    print("\n=== Live mode rendering detail ===")
    # ensure back to live
    mode_btn = page.query_selector("#wiki-mode-toggle")
    if mode_btn:
        for _ in range(4):
            if "live" in mode_btn.text_content().strip().lower():
                break
            mode_btn.click()
            page.wait_for_timeout(400)

    live_details = page.evaluate("""() => {
        const live = document.querySelector('#wiki-live');
        if (!live) return {};
        return {
            has_strong: !!live.querySelector('.cm-strong, strong'),
            has_em: !!live.querySelector('.cm-em, em'),
            has_header: !!live.querySelector('.cm-header, [class*="header"]'),
            has_table: !!live.querySelector('.cm-table, .cm-hmd-table, table'),
            has_img: !!live.querySelector('img, .cm-image'),
            has_code: !!live.querySelector('code, .cm-code, .cm-inline-code'),
            has_link: !!live.querySelector('a, .cm-link'),
            has_checkbox: !!live.querySelector('input[type=checkbox], .cm-taskMarker'),
            has_quote: !!live.querySelector('.cm-quote, blockquote'),
            cm_lines: live.querySelectorAll('.cm-line').length,
        };
    }""")
    findings["live_details"] = live_details
    print(f"  Live details: {live_details}")

    # ── VISUAL CHECKS ────────────────────────────────────────────────────────
    print("\n=== Visual spot checks ===")
    # scroll to top of editor
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.keyboard.press("Control+Home")
        page.wait_for_timeout(300)
    ss(page, "p2-editor-top", "editor top — headings rendering")

    # check live rendering of different features
    page.evaluate("""() => {
        const cm = document.querySelector('#wiki-live .cm-content');
        if (cm) cm.scrollTop = 0;
        const scroller = document.querySelector('#wiki-live .cm-scroller');
        if (scroller) scroller.scrollTop = 0;
    }""")
    page.wait_for_timeout(200)
    ss(page, "p2-editor-top2", "editor top after scroll reset")

    # preview mode for full visual
    if mode_btn:
        for _ in range(4):
            if "preview" in mode_btn.text_content().strip().lower():
                break
            mode_btn.click()
            page.wait_for_timeout(400)
    ss(page, "p2-preview-full", "preview mode full render")

    # check callout in preview
    callout_in_preview = page.evaluate("""() => {
        const prev = document.querySelector('#wiki-preview');
        if (!prev) return {found: false};
        const callout = prev.querySelector('.callout, [class*="callout"], [data-callout]');
        return {found: !!callout, cls: callout ? callout.className : null,
                text: callout ? callout.innerText.substring(0,100) : null};
    }""")
    findings["callout_preview"] = callout_in_preview
    print(f"  Callout in preview: {callout_in_preview}")

    # check checklist in preview
    chk_preview = page.evaluate("""() => {
        const prev = document.querySelector('#wiki-preview');
        if (!prev) return {};
        return {
            checkboxes: prev.querySelectorAll('input[type=checkbox]').length,
            li_items: prev.querySelectorAll('li').length,
            checked: prev.querySelectorAll('input[type=checkbox]:checked').length,
        };
    }""")
    findings["checklist_preview"] = chk_preview
    print(f"  Checklist in preview: {chk_preview}")

    # wikilink rendering in preview
    wikilink_prev = page.evaluate("""() => {
        const prev = document.querySelector('#wiki-preview');
        if (!prev) return null;
        const wl = prev.querySelector('.wiki-link, [class*="wiki-link"], a[href*="wikilink"]');
        return wl ? {cls: wl.className, text: wl.innerText} : 'none found';
    }""")
    findings["wikilink_preview"] = wikilink_prev
    print(f"  Wikilink in preview: {wikilink_prev}")

    # image in preview
    img_prev = page.evaluate("""() => {
        const prev = document.querySelector('#wiki-preview');
        if (!prev) return null;
        const imgs = prev.querySelectorAll('img');
        return {count: imgs.length, src: imgs[0]?.src || null};
    }""")
    findings["image_preview"] = img_prev
    print(f"  Image in preview: {img_prev}")

    ss(page, "p2-preview-full2", "preview full — checking callout/wikilink/image")

    # back to live
    if mode_btn:
        for _ in range(4):
            if "live" in mode_btn.text_content().strip().lower():
                break
            mode_btn.click()
            page.wait_for_timeout(400)

    # ── CSS/THEME CHECK ──────────────────────────────────────────────────────
    print("\n=== CSS theme btn ===")
    css_btn = page.query_selector("#wiki-theme-btn")
    if css_btn and css_btn.is_visible():
        if "active" not in (css_btn.get_attribute("class") or ""):
            css_btn.click()
            page.wait_for_timeout(700)
        ss(page, "p2-css-theme-panel", "css theme panel")
        css_btn.click()
        page.wait_for_timeout(300)

    # ── ASK PANEL ────────────────────────────────────────────────────────────
    print("\n=== Ask panel ===")
    ask = page.query_selector("#wiki-ask-btn")
    if ask and ask.is_visible():
        if "active" not in (ask.get_attribute("class") or ""):
            ask.click()
            page.wait_for_timeout(700)
        ss(page, "p2-ask-panel", "ask AI panel")
        ask.click()
        page.wait_for_timeout(300)

    # ── AI EDIT TOGGLE ────────────────────────────────────────────────────────
    print("\n=== AI edit toggle ===")
    ai = page.query_selector("#wiki-ai-toggle")
    if ai and ai.is_visible():
        if "active" not in (ai.get_attribute("class") or ""):
            ai.click()
            page.wait_for_timeout(700)
        ai_active = "active" in (ai.get_attribute("class") or "")
        ss(page, "p2-ai-edit-toggle", f"AI edit mode — active={ai_active}")
        findings["ai_toggle"] = {"active": ai_active}
        ai.click()
        page.wait_for_timeout(300)

    # ── FINAL FULL VIEW ──────────────────────────────────────────────────────
    ss(page, "p2-final", "final state")

    findings["console_errors"] = [e for e in console_log if e["t"] == "error"]
    findings["console_warnings"] = [e for e in console_log if e["t"] == "warning"]

    out = os.path.join(AUDIT_DIR, "raw_findings2.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)
    print(f"\nSaved: {out}")
    browser.close()

print("\n=== DONE ===")
errs = [e for e in console_log if e["t"] == "error"]
warns = [e for e in console_log if e["t"] == "warning"]
print(f"Errors: {len(errs)}, warnings: {len(warns)}")
for e in errs[:30]:
    print(f"  [ERR] {e['m'][:220]}")
for w in warns[:15]:
    print(f"  [WARN] {w['m'][:180]}")
