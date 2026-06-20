"""
DOCS app UI audit script — v3
Target: http://docs.localhost:8870/
Output: docs/evidence/ui-3/audit/*.png + raw_findings.json
"""

import os, json
from playwright.sync_api import sync_playwright

AUDIT_DIR = r"C:\Users\jxh\alles\docs\evidence\ui-3\audit"
BASE_URL = "http://docs.localhost:8870/"
os.makedirs(AUDIT_DIR, exist_ok=True)

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


def new_doc(page, name="audit-doc"):
    """Create a new doc via the dialog. Returns True on success."""
    # try empty-state button first
    nb = page.query_selector("#wiki-empty-new")
    if nb and nb.is_visible():
        nb.click()
    else:
        nb = page.query_selector("#wiki-new-btn")
        if nb and nb.is_visible():
            nb.click()
        else:
            return False
    page.wait_for_timeout(600)
    # fill the dialog input
    di = page.query_selector("#_di")
    if di and di.is_visible():
        di.fill(name)
        page.wait_for_timeout(200)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1200)
        return True
    # fallback: just press enter (may use default name)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1200)
    return True


def focus_editor(page):
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.wait_for_timeout(150)
        return cm
    return None


def elem_visible(page, sel):
    el = page.query_selector(sel)
    if not el:
        return False
    return page.evaluate(f"!!document.querySelector('{sel}') && document.querySelector('{sel}').offsetParent !== null")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 900})
    page = ctx.new_page()

    page.on("console", lambda msg: console_log.append({"t": msg.type, "m": msg.text})
            if msg.type in ("error", "warning") else None)
    page.on("pageerror", lambda err: console_log.append({"t": "pageerror", "m": str(err)}))

    # ── 1. INITIAL LOAD ──────────────────────────────────────────────────────
    print("\n=== 1. Initial load ===")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(1500)
    ss(page, "01-initial-load", "docs home — empty state")
    findings["initial_body"] = page.evaluate("document.body.innerText").strip()[:300]

    # ── 2. NEW DOC + DIALOG ──────────────────────────────────────────────────
    print("\n=== 2. New doc modal ===")
    # first, screenshot the home page
    ss(page, "02a-home-empty", "empty home state")

    # click new doc
    nb = page.query_selector("#wiki-empty-new")
    if nb and nb.is_visible():
        nb.click()
        page.wait_for_timeout(700)
        ss(page, "02b-new-doc-dialog", "new doc name dialog")

    # fill name and confirm
    ok = new_doc.__wrapped__ = False
    di = page.query_selector("#_di")
    if di and di.is_visible():
        di.fill("audit-main")
        page.wait_for_timeout(200)
        ok_btn = page.query_selector(".dialog-ok, button:text('ok'), [class*=dialog] button.btn.primary")
        if ok_btn and ok_btn.is_visible():
            ok_btn.click()
        else:
            page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        findings["new_doc"] = "ok"
    else:
        findings["new_doc"] = "dialog input not found"

    ss(page, "02c-after-new-doc-created", "after new doc created")

    # verify editor surfaces
    surfaces = {}
    for sel in ["#wiki-live", "#wiki-source", "#wiki-preview"]:
        surfaces[sel] = elem_visible(page, sel)
    findings["editor_surfaces"] = surfaces
    print(f"  Editor surfaces: {surfaces}")

    # ── 3. TYPE RICH MARKDOWN ────────────────────────────────────────────────
    print("\n=== 3. Type rich markdown ===")
    cm = focus_editor(page)
    if cm:
        page.keyboard.press("Control+a")
        page.wait_for_timeout(100)
        page.keyboard.press("Delete")
        page.wait_for_timeout(100)
        for line in RICH_MD.split("\n"):
            page.keyboard.type(line)
            page.keyboard.press("Enter")
            page.wait_for_timeout(8)
        page.wait_for_timeout(800)
        findings["typing"] = "ok"
        ss(page, "03-rich-md-live-mode", "rich markdown typed — live mode")
    else:
        findings["typing"] = "editor not found/visible"

    # ── 4. MODE TOGGLE ───────────────────────────────────────────────────────
    print("\n=== 4. Mode toggle ===")
    mode_btn = page.query_selector("#wiki-mode-toggle")
    mode_findings = {}

    if mode_btn and mode_btn.is_visible():
        for step in range(4):
            label = mode_btn.text_content().strip()
            live_v = elem_visible(page, "#wiki-live")
            src_v = elem_visible(page, "#wiki-source")
            prev_v = elem_visible(page, "#wiki-preview")

            render = {}
            if prev_v:
                render["table"] = page.evaluate("!!document.querySelector('#wiki-preview table')")
                render["img"] = page.evaluate("!!document.querySelector('#wiki-preview img')")
                render["checkbox"] = page.evaluate("!!document.querySelector('#wiki-preview input[type=checkbox]')")
                render["strong"] = page.evaluate("!!document.querySelector('#wiki-preview strong')")
                render["em"] = page.evaluate("!!document.querySelector('#wiki-preview em')")
                render["pre_code"] = page.evaluate("!!document.querySelector('#wiki-preview pre code')")
                render["blockquote"] = page.evaluate("!!document.querySelector('#wiki-preview blockquote')")
                render["h1"] = page.evaluate("!!document.querySelector('#wiki-preview h1')")
            if live_v:
                render["cm_strong"] = page.evaluate("!!document.querySelector('#wiki-live .cm-strong, #wiki-live strong')")
                render["cm_em"] = page.evaluate("!!document.querySelector('#wiki-live .cm-em, #wiki-live em')")
                render["cm_header"] = page.evaluate("!!document.querySelector('#wiki-live .cm-header, #wiki-live .cm-line.cm-header-1')")
                render["cm_table"] = page.evaluate("!!document.querySelector('#wiki-live .cm-table, #wiki-live .cm-hmd-table-sep')")

            mode_findings[f"step{step}"] = {
                "label": label, "live": live_v, "source": src_v, "preview": prev_v,
                "render": render,
            }
            print(f"  step{step} [{label}]: live={live_v} src={src_v} prev={prev_v} render={render}")
            ss(page, f"04-mode-step{step}-{label.replace(' ','_').replace('/','_')}", f"mode: {label}")

            if step < 3:
                mode_btn.click()
                page.wait_for_timeout(800)

    findings["mode_toggle"] = mode_findings

    # return to live mode
    if mode_btn:
        for _ in range(6):
            lbl = mode_btn.text_content().strip()
            if "live" in lbl.lower():
                break
            mode_btn.click()
            page.wait_for_timeout(400)

    page.wait_for_timeout(500)

    # ── 5. TOOLBAR BUTTONS (one by one) ─────────────────────────────────────
    print("\n=== 5. Toolbar buttons ===")
    toolbar_items = [
        ("wiki-ai-toggle",   "ai edit mode toggle"),
        ("wiki-ask-btn",     "ask AI across notes"),
        ("wiki-help-btn",    "markdown guide"),
        ("wiki-outline-btn", "outline panel"),
        ("wiki-props-btn",   "properties/frontmatter"),
        ("wiki-query-btn",   "query/dataview"),
        ("wiki-base-btn",    "database/base view"),
        ("wiki-canvas-btn",  "canvas whiteboard"),
        ("wiki-board-btn",   "kanban board"),
        ("wiki-todos-btn",   "AI extract todos"),
        ("wiki-taskroll-btn","all tasks roll-up"),
        ("wiki-history-btn", "version history"),
        ("wiki-bookmark-btn","bookmark"),
        ("wiki-comments-btn","comments"),
        ("wiki-publish-btn", "publish"),
        ("wiki-split-btn",   "split view"),
        ("wiki-theme-btn",   "custom CSS theme"),
        ("wiki-export-btn",  "export dropdown"),
    ]
    tb_findings = {}

    for idx, (btn_id, desc) in enumerate(toolbar_items):
        print(f"  [{idx+1}] #{btn_id}")
        btn = page.query_selector(f"#{btn_id}")
        if not btn:
            tb_findings[btn_id] = {"status": "NOT FOUND"}
            continue
        if not btn.is_visible():
            tb_findings[btn_id] = {"status": "NOT VISIBLE"}
            continue

        cls_before = btn.get_attribute("class") or ""
        active_before = "active" in cls_before

        try:
            btn.click()
            page.wait_for_timeout(800)
        except Exception as e:
            tb_findings[btn_id] = {"status": f"error: {e}"}
            continue

        cls_after = btn.get_attribute("class") or ""
        active_after = "active" in cls_after
        label_after = btn.text_content().strip()

        shot = f"05-tb{idx+1:02d}-{btn_id}"
        ss(page, shot, f"#{btn_id}: {desc}")

        tb_findings[btn_id] = {
            "desc": desc,
            "vis": True,
            "active_before": active_before,
            "active_after": active_after,
            "label_after": label_after,
        }

    findings["toolbar"] = tb_findings

    # close any open panels/modes
    # click active toolbar buttons to toggle off
    for bid in ["wiki-ai-toggle","wiki-outline-btn","wiki-props-btn","wiki-query-btn",
                "wiki-history-btn","wiki-split-btn"]:
        b2 = page.query_selector(f"#{bid}")
        if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
            b2.click()
            page.wait_for_timeout(200)

    # mutual exclusivity test: open outline + props + query simultaneously
    print("  Testing mutual exclusivity (outline+props+query) ...")
    panel_active_states = {}
    for bid in ["wiki-outline-btn", "wiki-props-btn", "wiki-query-btn"]:
        b2 = page.query_selector(f"#{bid}")
        if b2 and b2.is_visible():
            cls = b2.get_attribute("class") or ""
            if "active" not in cls:
                b2.click()
                page.wait_for_timeout(400)
    ss(page, "05-three-panels-test", "outline+props+query all activated")
    for bid in ["wiki-outline-btn", "wiki-props-btn", "wiki-query-btn"]:
        b2 = page.query_selector(f"#{bid}")
        if b2:
            panel_active_states[bid] = "active" in (b2.get_attribute("class") or "")
    findings["three_panels_active"] = panel_active_states
    print(f"  Panel active states: {panel_active_states}")

    # close all
    for bid in ["wiki-outline-btn", "wiki-props-btn", "wiki-query-btn"]:
        b2 = page.query_selector(f"#{bid}")
        if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
            b2.click()
            page.wait_for_timeout(200)

    # ── 6. FORMAT TOOLBAR ────────────────────────────────────────────────────
    print("\n=== 6. Format toolbar ===")
    fmt_list = ["h1","h2","h3","bold","italic","strike","highlight","code",
                "bullet","olist","check","quote",
                "link","image","wiki","table","codeblock","callout","toggle","columns","hr"]
    fmt_findings = {}

    for fmt in fmt_list:
        print(f"  fmt:{fmt}")
        fmt_btn = page.query_selector(f"[data-fmt='{fmt}']")
        if not fmt_btn:
            fmt_findings[fmt] = "NOT FOUND"
            continue
        if not fmt_btn.is_visible():
            fmt_findings[fmt] = "NOT VISIBLE"
            continue

        # add some text, select it
        cm = page.query_selector("#wiki-live .cm-content")
        if cm and cm.is_visible():
            cm.click()
            page.wait_for_timeout(100)
            page.keyboard.press("Control+End")
            page.keyboard.press("Enter")
            page.keyboard.type(f"sample text {fmt}")
            page.wait_for_timeout(80)
            page.keyboard.press("Home")
            page.keyboard.press("Shift+End")
            page.wait_for_timeout(80)

        try:
            fmt_btn.click()
            page.wait_for_timeout(500)
            dialog_up = page.evaluate("!!document.querySelector('.dialog-overlay, [class*=\"dialog\"][style*=\"display: flex\"], [class*=\"dialog\"][style*=\"display:flex\"]')")
            fmt_findings[fmt] = {"clicked": True, "dialog": dialog_up}
            if dialog_up:
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
        except Exception as e:
            fmt_findings[fmt] = f"error: {e}"

    ss(page, "06-fmt-toolbar-after", "after format toolbar test")
    findings["format_toolbar"] = fmt_findings

    # ── 7. MULTI-LINE SELECTION ───────────────────────────────────────────────
    print("\n=== 7. Multi-line selection ===")
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.wait_for_timeout(150)
        page.keyboard.press("Control+Home")
        page.wait_for_timeout(150)
        for _ in range(5):
            page.keyboard.press("Shift+Down")
        page.wait_for_timeout(300)
        ss(page, "07-multiline-selection", "5-line selection — does highlight extend into margin?")

        # measure selection rect vs editor
        geo = page.evaluate("""() => {
            const sel = window.getSelection();
            const r = sel && sel.rangeCount ? sel.getRangeAt(0).getBoundingClientRect() : null;
            const scroller = document.querySelector('#wiki-live .cm-scroller');
            const content = document.querySelector('#wiki-live .cm-content');
            return {
                sel: r ? {x: r.x, y: r.y, w: r.width, h: r.height} : null,
                scroller: scroller ? scroller.getBoundingClientRect() : null,
                content: content ? content.getBoundingClientRect() : null,
            };
        }""")
        findings["multiline_sel_geo"] = geo
        print(f"  Geo: {geo}")

    # ── 8. RIGHT-CLICK ───────────────────────────────────────────────────────
    print("\n=== 8. Right-click context menu ===")
    cm = page.query_selector("#wiki-live .cm-content")
    if cm and cm.is_visible():
        cm.click()
        page.wait_for_timeout(150)
        cm.click(button="right")
        page.wait_for_timeout(700)
        ss(page, "08-right-click", "right-click — custom or native menu?")
        custom = page.query_selector(".context-menu, .ctx-menu, [class*='ctxmenu'], [class*='context-menu']")
        findings["right_click"] = {"custom": custom is not None}
        if custom:
            findings["right_click"]["class"] = custom.get_attribute("class")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    # ── 9. HISTORY PANEL ─────────────────────────────────────────────────────
    print("\n=== 9. History panel ===")
    hist = page.query_selector("#wiki-history-btn")
    if hist and hist.is_visible():
        # close any active panels first
        for bid in ["wiki-outline-btn","wiki-props-btn","wiki-query-btn"]:
            b2 = page.query_selector(f"#{bid}")
            if b2 and b2.is_visible() and "active" in (b2.get_attribute("class") or ""):
                b2.click()
                page.wait_for_timeout(200)
        cls = hist.get_attribute("class") or ""
        if "active" not in cls:
            hist.click()
            page.wait_for_timeout(900)
        ss(page, "09-history-panel", "history panel open")
        findings["history"] = {
            "active": "active" in (hist.get_attribute("class") or ""),
        }
        hist.click()
        page.wait_for_timeout(400)

    # ── 10. EXPORT MENU ──────────────────────────────────────────────────────
    print("\n=== 10. Export menu ===")
    exp = page.query_selector("#wiki-export-btn")
    if exp and exp.is_visible():
        exp.click()
        page.wait_for_timeout(700)
        ss(page, "10-export-menu", "export dropdown open")
        dropdown = page.query_selector(".dropdown-menu, .docs-export-menu, [class*='export-menu']")
        findings["export"] = {
            "dropdown_found": dropdown is not None,
            "dropdown_class": dropdown.get_attribute("class") if dropdown else None,
        }
        # try to read export options
        if dropdown:
            items = dropdown.query_selector_all("button, a, [class*='item']")
            findings["export"]["items"] = [i.text_content().strip() for i in items]
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    # ── 11. SPLIT VIEW ───────────────────────────────────────────────────────
    print("\n=== 11. Split view ===")
    split = page.query_selector("#wiki-split-btn")
    if split and split.is_visible():
        cls = split.get_attribute("class") or ""
        if "active" not in cls:
            split.click()
            page.wait_for_timeout(900)
        ss(page, "11-split-view", "split view open")
        pane2 = page.query_selector(".wiki-split-pane, .wiki-pane-b, [class*='split-pane'], [class*='pane-b']")
        findings["split"] = {
            "active": "active" in (split.get_attribute("class") or ""),
            "pane2_found": pane2 is not None,
        }
        # close split
        split.click()
        page.wait_for_timeout(400)

    # ── 12. MULTIPLE DOCS / TABS ──────────────────────────────────────────────
    print("\n=== 12. Multiple docs for tabs ===")
    home = page.query_selector("#wiki-home-btn")
    if home and home.is_visible():
        home.click()
        page.wait_for_timeout(800)
    ss(page, "12a-docs-home", "docs home with 1 doc in tree")

    # create more docs
    for i in range(3):
        nb = page.query_selector("#wiki-new-btn")
        if not nb or not nb.is_visible():
            nb = page.query_selector("#wiki-empty-new")
        if nb and nb.is_visible():
            nb.click()
            page.wait_for_timeout(600)
            di = page.query_selector("#_di")
            if di and di.is_visible():
                di.fill(f"audit-tab-{i+1}")
                page.keyboard.press("Enter")
                page.wait_for_timeout(1200)
                cm2 = page.query_selector("#wiki-live .cm-content")
                if cm2 and cm2.is_visible():
                    cm2.click()
                    page.keyboard.type(f"# Tab Doc {i+1}\n\nContent of tab doc {i+1}.")
                    page.wait_for_timeout(300)

    ss(page, "12b-tabs-bar-multiple", "tabs bar after 4 docs open")
    tabs_el = page.query_selector("#wiki-tabs")
    if tabs_el:
        tab_count = page.evaluate("document.querySelectorAll('#wiki-tabs .wiki-tab, #wiki-tabs [class*=\"wiki-tab\"]').length")
        findings["tabs"] = {"found": True, "count": tab_count}
        print(f"  Tabs found: {tab_count}")
    else:
        findings["tabs"] = {"found": False}

    # ── 13. BACKLINKS ────────────────────────────────────────────────────────
    print("\n=== 13. Backlinks ===")
    bl = page.query_selector("#wiki-backlinks")
    if bl:
        page.evaluate("document.querySelector('#wiki-backlinks').scrollIntoView()")
        page.wait_for_timeout(400)
        ss(page, "13-backlinks", "backlinks panel")
        findings["backlinks"] = {"found": True}
    else:
        findings["backlinks"] = {"found": False}

    # ── 14. DELETE ───────────────────────────────────────────────────────────
    print("\n=== 14. Delete button ===")
    del_btn = page.query_selector("#wiki-delete-btn")
    if del_btn and del_btn.is_visible():
        del_btn.click()
        page.wait_for_timeout(700)
        ss(page, "14-delete-confirm", "delete confirmation dialog")
        confirm = page.evaluate("!!document.querySelector('.dialog-overlay, [class*=\"dialog\"][style*=\"flex\"]')")
        findings["delete"] = {"confirm_dialog": confirm}
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    # ── 15. VISUAL SPOT-CHECKS ────────────────────────────────────────────────
    print("\n=== 15. Visual spot-checks ===")
    # make sure we have a doc open
    tb_bar = page.query_selector("#docs-toolbar")
    if tb_bar:
        ss(page, "15a-format-toolbar", "format toolbar visual")
    ss(page, "15b-editor-final", "final editor state")

    # check if wiki-tabs bar is present and styled
    tabs_el = page.query_selector("#wiki-tabs")
    if tabs_el:
        tabs_el.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        ss(page, "15c-wiki-tabs-closeup", "wiki-tabs bar close-up")

    # ── SAVE ────────────────────────────────────────────────────────────────
    findings["console_errors"] = [e for e in console_log if e["t"] == "error"]
    findings["console_warnings"] = [e for e in console_log if e["t"] == "warning"]
    findings["console_all"] = console_log[:80]

    out = os.path.join(AUDIT_DIR, "raw_findings.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)
    print(f"\nSaved: {out}")

    browser.close()

print("\n=== DONE ===")
errs = [e for e in console_log if e["t"] == "error"]
warns = [e for e in console_log if e["t"] == "warning"]
print(f"Console errors: {len(errs)}, warnings: {len(warns)}")
for e in errs[:20]:
    print(f"  [ERR] {e['m'][:200]}")
for w in warns[:10]:
    print(f"  [WARN] {w['m'][:200]}")
