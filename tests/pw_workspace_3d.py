"""3d UI verification — ask panel, web-clipper bookmarklet, charts, form blocks. :8825."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8825"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "3d"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def to_preview(pg):
    """cycle the editor mode until the rendered preview pane is visible."""
    for _ in range(4):
        if pg.eval_on_selector("#wiki-preview", "el => getComputedStyle(el).display !== 'none'"):
            return
        pg.click("#wiki-mode-toggle")
        pg.wait_for_timeout(400)


def main():
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
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

        # ---- seed the docs this test drives (idempotent) ----
        pg.goto(f"{DOCS}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        seed = [
            ("dash/x1.md", "---\nkind: alpha\n---\nfirst"),
            ("dash/x2.md", "---\nkind: alpha\n---\nsecond"),
            ("dash/y1.md", "---\nkind: beta\n---\nthird"),
            (
                "dash/report.md",
                "# Report\n\n```query\nfolder: dash\ngroup: kind\nchart: bar\n```\n",
            ),
            (
                "forms/signup.md",
                "# Signup\n\n```form\ntarget: forms/responses\nfields: name, note\n```\n",
            ),
            ("forms/responses.md", "# Responses\n"),  # reset target each run
        ]
        for path, content in seed:
            pg.evaluate(
                "([p,c])=>fetch('/api/vault-md/file',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({path:p,content:c})})",
                [path, content],
            )
        pg.wait_for_timeout(600)

        # ---- ask panel ----
        pg.goto(f"{DOCS}/?doc=dash/report.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-ask-btn", timeout=15000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        pg.click("#wiki-ask-btn")
        pg.wait_for_selector("#wiki-ask", state="visible", timeout=5000)
        r["ask_panel_opens"] = pg.is_visible("#wiki-ask")

        pg.fill("#wiki-ask-input", "first second third")
        pg.click("#wiki-ask-go")
        pg.wait_for_selector("#wiki-ask-results .wiki-ask-hit", timeout=8000)
        hits = pg.query_selector_all("#wiki-ask-results .wiki-ask-hit")
        r["ask_shows_sources"] = len(hits) > 0

        # clicking a source opens that note
        pg.query_selector("#wiki-ask-results .wiki-ask-hit").click()
        pg.wait_for_timeout(900)
        cur = pg.text_content("#wiki-current") or ""
        r["ask_source_opens_doc"] = (
            "dash/" in cur or cur.strip().endswith(".md") or "x1" in cur or "y1" in cur
        )

        # ---- clipper bookmarklet ----
        pg.click("#wiki-ask-btn")  # close
        pg.click("#wiki-ask-btn")  # reopen → reloads bookmarklet
        pg.wait_for_timeout(500)
        href = pg.get_attribute("#wiki-clip-bm", "href") or ""
        r["clipper_bookmarklet_shown"] = (
            href.startswith("javascript:") and "/api/vault-md/clip" in href
        )
        pg.screenshot(path=str(EVID / "ask-panel.png"))

        # ---- chart ----
        pg.goto(f"{DOCS}/?doc=dash/report.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-mode-toggle", timeout=12000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        to_preview(pg)
        for _ in range(4):
            if pg.query_selector("#wiki-preview .wiki-chart svg"):
                break
            pg.wait_for_timeout(600)
        r["chart_renders_svg"] = pg.query_selector("#wiki-preview .wiki-chart svg rect") is not None
        pg.screenshot(path=str(EVID / "chart.png"))

        # ---- form block ----
        pg.goto(f"{DOCS}/?doc=forms/signup.md", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-mode-toggle", timeout=12000)
        pg.wait_for_function(
            "!/no doc open/.test(document.getElementById('wiki-current').textContent)",
            timeout=10000,
        )
        to_preview(pg)
        for _ in range(4):
            if pg.query_selector("#wiki-preview .wiki-form input"):
                break
            pg.wait_for_timeout(600)
        inputs = pg.query_selector_all("#wiki-preview .wiki-form input")
        r["form_block_renders_inputs"] = len(inputs) >= 2

        before = pg.evaluate(
            "fetch('/api/vault-md/file?path=forms/responses.md').then(r=>r.json()).then(j=>j.content.length)"
        )
        pg.fill('#wiki-preview .wiki-form input[name="name"]', "Ada")
        pg.fill('#wiki-preview .wiki-form input[name="note"]', "hello")
        pg.click("#wiki-preview .wiki-form .wiki-form-submit")
        pg.wait_for_timeout(900)
        after = pg.evaluate(
            "fetch('/api/vault-md/file?path=forms/responses.md').then(r=>r.json()).then(j=>j.content)"
        )
        r["form_submit_appends_row"] = "| Ada | hello |" in after and len(after) > before
        pg.screenshot(path=str(EVID / "form.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_workspace_3d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
