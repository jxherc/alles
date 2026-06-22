"""playwright test for the recall settings pane.
run against a throwaway server:
  $env:PORT='8156'; $env:AUTH_ENABLED='false'; $env:ALLES_DATA='.tmp_c3_pw'; python app.py
then: python tests/pw_recall_settings.py 8156
"""
import sys
from playwright.sync_api import sync_playwright

IGN = ("favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8156"
    r, errs = {}, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.on("console", lambda m: errs.append(m.text)
              if m.type == "error" and not any(x in m.text for x in IGN) else None)

        pg.goto(f"http://localhost:{port}/", wait_until="domcontentloaded")
        # wait for app module + window._openSettings to be wired
        pg.wait_for_function("() => typeof window._openSettings === 'function'", timeout=15000)
        pg.evaluate("() => window._openSettings('recall')")
        # wait for modal to open and recall pane to become active
        pg.wait_for_selector("#s-pane-recall.active", timeout=8000)
        pg.wait_for_timeout(500)

        r["pane_renders"]   = pg.eval_on_selector("#s-pane-recall", "el => !!el") or False
        r["master_toggle"]  = pg.eval_on_selector("#s-pidx-enabled", "el => !!el") or False
        r["stats_shows"]    = pg.eval_on_selector("#s-pidx-stats", "el => !!el") or False
        r["reindex_btn"]    = pg.eval_on_selector("#s-pidx-reindex", "el => !!el") or False
        r["clear_btn"]      = pg.eval_on_selector("#s-pidx-clear", "el => !!el") or False
        r["no_console_errors"] = len([e for e in errs if "favicon" not in e]) == 0

        pg.close()
        b.close()

    for k, v in r.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    if errs:
        print("console errors:", errs[:6])
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if all(r.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
