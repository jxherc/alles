"""surface-brain behavioral - mock the intelligence endpoints and drive the brain view + the
intelligence settings pane. proves the three new sections render, the action buttons POST the
right paths, and the disabled state offers a 'turn it on' shortcut. run with a server on :8077.

we drive the brain loader directly via #brain-refresh-btn (it calls loadBrainPanel) and force the
view visible, so we don't depend on the subdomain router (brain lives on the aide subdomain)."""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://aide.localhost:8077"  # brain lives on the aide subdomain; full app boots here
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "surface-brain"
IGN = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")

SHOW_BRAIN = "() => window._navigateTo && window._navigateTo('brain')"


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    posted = []
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and not any(x in m.text for x in IGN) else None)

        def rec(route):
            req = route.request
            if req.method in ("POST", "PATCH"):
                posted.append(req.url.replace(BASE, ""))
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "ran": True, "count": 1}))

        def fulfil(data):
            return lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        # catch-all first so later (more specific) routes win
        pg.route("**/api/**", fulfil({}))
        pg.route("**/api/auth/me", fulfil({"authenticated": True, "username": "test"}))
        pg.route("**/api/models", fulfil([]))
        pg.route("**/api/sessions", fulfil({"today": [], "yesterday": [], "earlier": []}))
        pg.route("**/api/settings", fulfil({"insights_enabled": True, "user_model_distill": True, "pidx_proactive_enabled": True}))
        pg.route("**/api/memories", fulfil([]))
        pg.route("**/api/insights", fulfil([
            {"id": "i1", "title": "spends more after travel", "body": "card spend rises the week after trips", "evidence": ["sub:air", "txn:hotel"], "pinned": False},
        ]))
        pg.route("**/api/memory/distilled", fulfil([
            {"id": "m1", "text": "prefers concise answers", "category": "preference", "confidence": 0.82, "provenance": "sessions:12", "vetoed": False, "pinned": False},
            {"id": "m2", "text": "vetoed hidden", "confidence": 0.9, "vetoed": True, "pinned": False},
        ]))
        pg.route("**/api/proactive/stats", fulfil({"task": {"acted": 5, "dismissed": 1, "ignored": 2, "act_rate": 0.625, "weight": 1.18}}))
        pg.route("**/api/insights/run", rec)
        pg.route("**/api/insights/*/pin", rec)
        pg.route("**/api/insights/*/dismiss", rec)
        pg.route("**/api/memory/distill/run", rec)
        pg.route("**/api/memory/*/veto", rec)
        pg.route("**/api/memories/*", rec)

        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        pg.evaluate(SHOW_BRAIN)
        pg.wait_for_timeout(700)

        ins = pg.inner_text("#brain-insights")
        um = pg.inner_text("#brain-usermodel")
        px = pg.inner_text("#brain-proxstats")
        assert "spends more after travel" in ins, f"insight missing: {ins!r}"
        assert "sub:air" in ins, f"evidence missing: {ins!r}"
        assert "prefers concise answers" in um, f"distilled fact missing: {um!r}"
        assert "82%" in um, f"confidence missing: {um!r}"
        assert "vetoed hidden" not in um, "vetoed fact should be hidden"
        assert "task" in px and "1.18" in px, f"prox stats missing: {px!r}"
        print("PASS render: all three brain sections populated")

        # action buttons POST the right paths (loadBrainPanel re-runs after each, view stays shown)
        pg.click("[data-ins-pin='i1']")
        pg.wait_for_timeout(350)
        pg.click("[data-um-veto='m1']")
        pg.wait_for_timeout(350)
        pg.click("#brain-insights-run")
        pg.wait_for_timeout(450)
        assert any("/api/insights/i1/pin" in u for u in posted), f"pin not posted: {posted}"
        assert any("/api/memory/m1/veto" in u for u in posted), f"veto not posted: {posted}"
        assert any("/api/insights/run" in u for u in posted), f"generate not posted: {posted}"
        print("PASS actions:", posted)

        pg.screenshot(path=str(EVID / "brain_dashboard.png"), full_page=True)

        # disabled state: everything off + empty, expect a "turn it on" shortcut
        pg.route("**/api/settings", fulfil({"insights_enabled": False, "user_model_distill": False, "pidx_proactive_enabled": False}))
        pg.route("**/api/insights", fulfil([]))
        pg.route("**/api/memory/distilled", fulfil([]))
        pg.route("**/api/proactive/stats", fulfil({}))
        pg.evaluate(SHOW_BRAIN)
        pg.wait_for_timeout(600)
        ins2 = pg.inner_text("#brain-insights")
        assert "turn it on" in ins2.lower(), f"disabled hint missing: {ins2!r}"
        print("PASS disabled-state hint shown")

        # intelligence settings pane renders its toggles + run buttons
        pg.evaluate("() => window._openSettings && window._openSettings('intelligence')")
        pg.wait_for_timeout(500)
        assert pg.is_visible("#s-intel-insights"), "intelligence pane toggle missing"
        assert pg.is_visible("#s-intel-distill-run"), "distill-now button missing"
        pg.screenshot(path=str(EVID / "intelligence_pane.png"), full_page=True)
        print("PASS intelligence settings pane renders")

        b.close()

    if errs:
        print("CONSOLE ERRORS:", errs[:8])
        sys.exit(1)
    print("ALL GOOD")


if __name__ == "__main__":
    main()
