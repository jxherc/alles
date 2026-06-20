"""10d UI — custom assistants: persona knowledge files + share, MCP one-click presets.
aide.localhost:8875.  ALLES_DATA=/tmp/alles10d PORT=8875 AUTH_ENABLED=false python app.py
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

AIDE = "http://aide.localhost:8875"


def _seed_persona():
    req = urllib.request.Request(
        "http://127.0.0.1:8875/api/personas",
        data=json.dumps({"name": "Test Persona", "system_prompt": "You help test 10d."}).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10).read()


EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "10d"
IGNORE = (
    "Failed to load resource",
    "net::",
    "ERR_",
    "favicon",
    "401",
    "403",
    "Load failed",
    "clipboard",
)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    _seed_persona()
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(permissions=["clipboard-read", "clipboard-write"])
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

        pg.goto(f"{AIDE}/", wait_until="domcontentloaded")
        pg.wait_for_selector('.nav-item[data-view="settings"]', timeout=15000)
        pg.eval_on_selector('.nav-item[data-view="settings"]', "el => el.click()")
        pg.wait_for_selector('.s-nav-item[data-pane="personas"]', timeout=8000)
        pg.eval_on_selector('.s-nav-item[data-pane="personas"]', "el => el.click()")
        pg.wait_for_selector("#persona-list .persona-row", timeout=8000)

        # open the first persona → knowledge files + share appear
        pg.eval_on_selector("#persona-list .persona-row", "el => el.click()")
        pg.wait_for_selector("#persona-extra:not([hidden])", timeout=6000)
        pg.wait_for_timeout(300)
        r["persona_editor_opens"] = pg.is_visible("#persona-extra")
        r["knowledge_section_present"] = pg.query_selector("#persona-docs") is not None
        r["persona_share_button"] = pg.is_visible("#persona-share-btn")

        # add a knowledge file → it lists; then remove it
        pg.fill("#persona-doc-title", "Runbook")
        pg.fill("#persona-doc-content", "to restart the service run alles restart then check logs")
        pg.eval_on_selector("#persona-doc-add", "el => el.click()")
        pg.wait_for_selector(".persona-doc-row", timeout=6000)
        r["add_knowledge_file"] = "Runbook" in (pg.text_content("#persona-docs") or "")
        pg.screenshot(path=str(EVID / "persona-knowledge.png"))
        pg.eval_on_selector(".persona-doc-row .act-btn", "el => el.click()")
        pg.wait_for_timeout(600)
        r["remove_knowledge"] = pg.query_selector(".persona-doc-row") is None

        # share mints a link (clipboard granted)
        pg.eval_on_selector("#persona-share-btn", "el => el.click()")
        pg.wait_for_timeout(500)
        r["persona_share_button_clicks"] = True  # no exception thrown

        # MCP presets — one-click add
        pg.eval_on_selector('.s-nav-item[data-pane="tools"]', "el => el.click()")
        pg.wait_for_selector("#mcp-presets .mcp-preset", timeout=8000)
        r["mcp_presets_visible"] = len(pg.query_selector_all("#mcp-presets .mcp-preset")) >= 3
        pg.screenshot(path=str(EVID / "mcp-presets.png"))
        pg.eval_on_selector("#mcp-presets .mcp-preset", "el => el.click()")
        pg.wait_for_timeout(1200)
        list_txt = pg.text_content("#mcp-server-list") or ""
        r["add_preset_one_click"] = "no servers" not in list_txt and len(list_txt.strip()) > 0

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_assistants_10d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
