"""Browser-engine regression for keyboard access to bounded source text."""

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows, failures = [], []
    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        for engine in ("webkit", "chromium"):
            browser = getattr(pw, engine).launch()
            page = browser.new_page(
                viewport={"width": 390, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            page.goto(base + "/?view=chat", wait_until="networkidle")
            # Use the actual renderers and styles with synthetic in-memory source data.
            page.evaluate("""async () => {
                const sessions = await import('/static/js/sessions.js');
                const {contextProvenanceElement} = await import('/static/js/memoryactions.js');
                sessions.showMessages();
                const documents = Array.from({length: 8}, (_, i) => ({path: `source-${i}-` + 'long-note-name-'.repeat(20) + '.md', hash: 'a'.repeat(64), content: Array.from({length: 100}, (_, line) => `source line ${line}`).join('\\n')}));
                sessions.appendUserMsg('local keyboard fixture', {documents});
                const provenance = contextProvenanceElement({document: {documents}});
                document.getElementById('messages').append(provenance);
                provenance.open = true;
                provenance.querySelector('.source-snapshot').open = true;
                document.querySelector('.user-context-scope').open = true;
            }""")
            for name, selector in (
                ("passage", ".source-snapshot pre"),
                ("selected-list", ".user-context-scope ul"),
            ):
                region = page.locator(selector).first
                try:
                    assert region.evaluate("el => el.scrollHeight > el.clientHeight"), (
                        "fixture must overflow"
                    )
                    region.focus()
                    assert region.evaluate("el => document.activeElement === el"), (
                        "scroll region cannot receive keyboard focus"
                    )
                    page.keyboard.press("PageDown")
                    page.wait_for_function(
                        "(selector) => document.querySelector(selector).scrollTop > 0",
                        arg=selector,
                        timeout=1500,
                    )
                    rows.append(
                        {
                            "scenario_id": "knowledge.source-keyboard." + name,
                            "profile": engine,
                            "status": "passed",
                        }
                    )
                except Exception as exc:
                    failures.append(str(exc))
                    rows.append(
                        {
                            "scenario_id": "knowledge.source-keyboard." + name,
                            "profile": engine,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
            page.screenshot(path=str(output / f"{engine}-source-keyboard.png"), full_page=True)
            browser.close()
        api.dispose()
    (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
    assert not failures, failures


if __name__ == "__main__":
    run()
