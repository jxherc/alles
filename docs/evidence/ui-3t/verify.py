"""ui-3t verify — docs settings popup: AI status + model picker (sets docs_ai_model);
the markdown 'guide' button is gone (everything is visual now)."""
import json
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
        # make /api/models report a connected endpoint with two models
        pg.route("**/api/models", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps([{"id": "e1", "name": "TestEP", "base_url": "http://x", "provider": "openai", "models": ["m1", "m2"]}])))
        patched = {}
        pg.route("**/api/settings", lambda route: (
            patched.update(json.loads(route.request.post_data or "{}")) or route.fulfill(status=200, content_type="application/json", body="{}"))
            if route.request.method == "PATCH"
            else route.fulfill(status=200, content_type="application/json", body=json.dumps({"docs_ai_model": ""})))
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(1000)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        ok("guide button removed from toolbar", pg.query_selector("#wiki-help-btn") is None)
        ok("docs settings button present", pg.query_selector("#wiki-docs-settings") is not None)

        pg.click("#wiki-docs-settings")
        pg.wait_for_timeout(500)
        pop = pg.query_selector("#wiki-docs-settings-pop")
        ok("settings popup opens", pop is not None)
        if pop:
            d = pg.evaluate("""() => {
              const p = document.querySelector('#wiki-docs-settings-pop');
              return {
                statusOk: !!p.querySelector('.wds-status.ok'),
                statusText: p.querySelector('.wds-status')?.textContent || '',
                models: p.querySelectorAll('.wds-model').length,
                on: p.querySelector('.wds-model.on')?.dataset.m || '',
              };
            }""")
            ok("status shows AI ready", d["statusOk"] and "ready" in d["statusText"].lower())
            ok("lists both models", d["models"] == 2)
            ok("a model is marked current", d["on"] != "")
            # pick the second model
            pg.eval_on_selector("#wiki-docs-settings-pop .wds-model[data-m='m2']", "el => el.click()")
            pg.wait_for_timeout(400)
            on2 = pg.evaluate("() => document.querySelector('#wiki-docs-settings-pop .wds-model.on')?.dataset.m")
            ok("selecting a model marks it on", on2 == "m2")
        ok("PATCH wrote docs_ai_model", patched.get("docs_ai_model") == "m2")

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-3t/settings.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()
