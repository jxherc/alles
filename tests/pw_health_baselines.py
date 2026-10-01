"""4b - verify health cards show a baseline band and flag a latest anomalous value.

needs a fresh instance with the current routes:
  ALLES_DATA=.tmp_h AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_health_baselines.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://health.localhost:8077"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        pg.evaluate(
            """async () => {
                const mk = (kind, value, date) => fetch('/api/health', {method:'POST', headers:{'content-type':'application/json'},
                    body: JSON.stringify({kind, value, date})});
                const day = offset => {
                    const value = new Date();
                    value.setHours(12, 0, 0, 0);
                    value.setDate(value.getDate() - offset);
                    const year = value.getFullYear();
                    const month = String(value.getMonth() + 1).padStart(2, '0');
                    const date = String(value.getDate()).padStart(2, '0');
                    return `${year}-${month}-${date}`;
                };
                const sleep = [7,8,6,7,8,6,7];   // varied baseline
                for (let i=0;i<sleep.length;i++) await mk('sleep', sleep[i], day(sleep.length - i));
                await mk('sleep', 2, day(0));   // latest way low
                // a steady metric that should NOT be flagged
                const w = [80,81,79,80,81,80];
                for (let i=0;i<w.length;i++) await mk('weight', w[i], day(w.length - 1 - i));
            }"""
        )
        pg.reload(wait_until="domcontentloaded")
        # Health now opens on the unified workbench overview. Exercise the real
        # specialist tab instead of querying the legacy screen while it is hidden.
        pg.locator('[data-group-section="health"]').click()
        pg.wait_for_selector('.health-card[data-kind="sleep"]', timeout=15_000)
        cards = pg.evaluate(
            """() => [...document.querySelectorAll('.health-card[data-kind]')].map(c => ({
                kind: c.dataset.kind,
                anom: c.querySelector('.health-anom')?.textContent || '',
                base: c.querySelector('.health-baseline')?.textContent?.replace(/\\s+/g,' ').trim() || '' }))"""
        )
        print("cards:", cards)
        sleep = next(c for c in cards if c["kind"] == "sleep")
        weight = next(c for c in cards if c["kind"] == "weight")
        assert "below usual" in sleep["anom"], sleep
        assert "usual" in sleep["base"], sleep
        assert weight["anom"] == "", weight  # steady metric not flagged
        b.close()
    print("PASS: baseline band shown, latest anomaly flagged, steady metric clean")


if __name__ == "__main__":
    main()
