"""surface-brain stress (frontend): XSS payloads + edge confidence values + volume in the brain
view. proves no script executes, the confidence bar stays clamped, no layout blowout, no console
errors. run with a server on :8077."""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://aide.localhost:8077"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "surface-brain"
IGN = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")

XSS = '<img src=x onerror="window.__xss=1">'
XSS2 = '"><script>window.__xss=1</script>'
HUGE = "W" * 6000

INSIGHTS = [
    {"id": "x1", "title": XSS, "body": XSS2, "evidence": ['<svg onload="window.__xss=1">', "ok:tag"], "pinned": False},
    {"id": "x2", "title": "normal title with a SENTINEL word", "body": HUGE, "evidence": [], "pinned": True},
] + [{"id": f"v{i}", "title": f"vol insight {i}", "body": "b", "evidence": ["e"], "pinned": False} for i in range(500)]

DISTILLED = [
    {"id": "d1", "text": XSS, "category": "x", "confidence": 5.0, "provenance": XSS2, "vetoed": False, "pinned": False},
    {"id": "d2", "text": "neg conf fact", "confidence": -1, "provenance": "p", "vetoed": False, "pinned": False},
    {"id": "d3", "text": "string conf fact", "confidence": "high", "provenance": "p", "vetoed": False, "pinned": False},
    {"id": "d4", "text": "null conf fact", "confidence": None, "provenance": "p", "vetoed": False, "pinned": False},
    {"id": "d5", "text": "normal SENTINEL2 fact", "confidence": 0.82, "provenance": "sessions:9", "vetoed": False, "pinned": False},
] + [{"id": f"q{i}", "text": f"vol fact {i}", "confidence": 0.6, "vetoed": False, "pinned": False} for i in range(500)]


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and not any(x in m.text for x in IGN) else None)
        # a real dialog (alert) firing would mean XSS executed — fail loudly
        pg.on("dialog", lambda d: (errs.append("DIALOG/ALERT FIRED - XSS"), d.dismiss()))

        def fulfil(data):
            return lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        pg.route("**/api/**", fulfil({}))
        pg.route("**/api/auth/me", fulfil({"authenticated": True, "username": "t"}))
        pg.route("**/api/models", fulfil([]))
        pg.route("**/api/sessions", fulfil({"today": [], "yesterday": [], "earlier": []}))
        pg.route("**/api/settings", fulfil({"insights_enabled": True, "user_model_distill": True, "pidx_proactive_enabled": True}))
        pg.route("**/api/memories", fulfil([]))
        pg.route("**/api/insights", fulfil(INSIGHTS))
        pg.route("**/api/memory/distilled", fulfil(DISTILLED))
        pg.route("**/api/proactive/stats", fulfil({"task": {"acted": 3, "dismissed": 1, "ignored": 0, "act_rate": 0.75, "weight": 1.3}}))

        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        pg.evaluate("() => window._navigateTo && window._navigateTo('brain')")
        pg.wait_for_timeout(1500)  # render 500+ items

        # 1. no XSS executed
        assert pg.evaluate("() => window.__xss === undefined"), "XSS EXECUTED (window.__xss set)"
        # the payloads must be present as ESCAPED text, not live nodes
        assert pg.evaluate("() => document.querySelectorAll('#brain-insights img, #brain-insights svg, #brain-insights script').length === 0"), "raw HTML node injected from insight payload"
        assert pg.evaluate("() => document.querySelectorAll('#brain-usermodel img, #brain-usermodel script').length === 0"), "raw HTML node injected from distilled payload"
        print("PASS xss: no execution, payloads rendered inert")

        # 2. confidence bar clamped 0..100 (no NaN / overflow widths)
        widths = pg.evaluate("""() => [...document.querySelectorAll('#brain-usermodel .um-conf i')].map(i => i.style.width)""")
        bad = [w for w in widths if w and (w == 'NaN%' or (w.endswith('%') and (float(w[:-1]) < 0 or float(w[:-1]) > 100)))]
        assert not bad, f"confidence bar widths out of range: {bad[:5]}"
        assert "NaN" not in pg.inner_text("#brain-usermodel"), "NaN% leaked into the UI"
        print("PASS confidence: all bars clamped 0..100, no NaN")

        # 3. volume rendered + no horizontal blowout from the 6000-char word
        body_w = pg.evaluate("() => document.body.scrollWidth")
        win_w = pg.evaluate("() => window.innerWidth")
        assert body_w <= win_w + 4, f"horizontal overflow: body {body_w} vs window {win_w}"
        n_ins = pg.evaluate("() => document.querySelectorAll('#brain-insights .brain-insight').length")
        n_um = pg.evaluate("() => document.querySelectorAll('#brain-usermodel .um-fact').length")
        assert n_ins >= 500 and n_um >= 500, f"volume not rendered: insights={n_ins} facts={n_um}"
        print(f"PASS volume: {n_ins} insights + {n_um} facts rendered, no overflow (body {body_w} <= win {win_w})")

        pg.screenshot(path=str(EVID / "brain_stress.png"))

        b.close()
    if errs:
        print("CONSOLE/XSS ERRORS:", errs[:8])
        sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()
