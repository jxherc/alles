"""verify the appearance overhaul (#33 inline editor, #34 lock/default/bg, #35 reorg).
needs a server up (AUTH off). exits non-zero on any failed assertion.

  AUDIT_PORT=8823 python tests/pw_theme_overhaul.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("AUDIT_PORT", "8823"))
results, fails, errs = {}, [], []

def check(name, cond):
    results[name] = bool(cond)
    if not cond:
        fails.append(name)

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block", viewport={"width": 1300, "height": 900}).new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "favicon" not in m.text and "net::" not in m.text else None)
        pg.goto(f"http://localhost:{PORT}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        # start from a clean default theme
        pg.evaluate("()=>{localStorage.removeItem('alles-appearance');localStorage.removeItem('aide-accent');localStorage.removeItem('aide-theme');}")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(700)

        # ── #35: open alles-scope settings, themes pane ──
        pg.evaluate("()=>window._openSettings('themes', true)")
        pg.wait_for_timeout(500)
        navs = pg.eval_on_selector_all(
            "#settings-modal.alles-scope .s-nav-item",
            "els => els.filter(e => getComputedStyle(e).display!=='none').map(e=>e.dataset.pane)")
        check("nav_is_general_security_themes_backup", sorted(navs) == ["backup", "general", "security", "themes"])

        # ── #33: inline editor present, no 'open editor' button ──
        check("inline_editor_present", pg.query_selector("#theme-editor-inline .te-presets") is not None)
        check("no_open_editor_button", pg.query_selector("#s-open-theme-editor") is None)
        check("default_tile_present", pg.query_selector('.te-preset[data-preset="default"]') is not None)
        check("no_dark_light_tiles", pg.query_selector('.te-preset[data-preset="dark"]') is None and pg.query_selector('.te-preset[data-preset="light"]') is None)

        # ── #34: pick a fancy preset (sakura) → mode/accent lock + its bg turns on ──
        pg.eval_on_selector('.te-preset[data-preset="sakura"]', "el=>el.click()")
        pg.wait_for_timeout(500)
        check("preset_locks_controls", pg.eval_on_selector("#s-default-theme", "el=>el.classList.contains('locked')"))
        check("lock_note_visible", pg.eval_on_selector("#s-theme-lock-note", "el=>el.offsetParent!==null && el.textContent.includes('sakura')"))
        check("sakura_bg_on", pg.evaluate("()=>document.body.classList.contains('bg-pattern-petals')"))
        check("sakura_is_light", pg.evaluate("()=>document.documentElement.dataset.theme==='light'"))

        # ── #34: default tile unlocks + clears bg ──
        pg.eval_on_selector('.te-preset[data-preset="default"]', "el=>el.click()")
        pg.wait_for_timeout(450)
        check("default_unlocks", pg.eval_on_selector("#s-default-theme", "el=>!el.classList.contains('locked')"))
        check("default_bg_none", pg.evaluate("()=>![...document.body.classList].some(c=>c.startsWith('bg-pattern-'))"))

        # ── #34: accent survives reload (the core bug) ──
        pg.eval_on_selector('#s-accent-swatches .accent-swatch[data-hex="#a78bfa"]', "el=>el.click()")
        pg.wait_for_timeout(400)
        acc_now = pg.evaluate("()=>(JSON.parse(localStorage.getItem('alles-appearance')||'{}').colors||{}).accent")
        check("accent_written_to_appearance", (acc_now or "").lower() == "#a78bfa")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        acc_after = pg.evaluate("()=>(JSON.parse(localStorage.getItem('alles-appearance')||'{}').colors||{}).accent")
        applied = pg.evaluate("()=>getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
        check("accent_persists_after_reload", (acc_after or "").lower() == "#a78bfa")
        check("accent_applied_after_reload", applied.lower() in ("#a78bfa", "rgb(167, 139, 250)"))

        b.close()

    check("no_console_errors", not errs)
    print("THEME OVERHAUL VERIFY")
    for k, v in results.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    if errs:
        print("console errors:", errs[:5])
    if fails:
        print(f"\n{len(fails)} FAILED: {fails}")
        sys.exit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
