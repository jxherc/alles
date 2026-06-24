"""4b - verify the journal 'what moves your mood' panel surfaces a habit<->mood correlation.

needs a fresh instance with the current routes:
  ALLES_DATA=.tmp_mc AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_journal_moodcorr.py
"""
from playwright.sync_api import sync_playwright

BASE = "http://journal.localhost:8077"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(900)
        # seed 8 days: good mood + habit done on even days, bad mood + not done on odd days
        pg.evaluate(
            """async () => {
                const days = [...Array(8).keys()].map(i => new Date(Date.now() - i*86400000).toISOString().slice(0,10));
                const hid = await fetch('/api/habits', {method:'POST', headers:{'content-type':'application/json'},
                    body: JSON.stringify({name:'run'})}).then(r=>r.json()).then(j=>j.id);
                for (let i=0;i<days.length;i++) {
                    const good = i % 2 === 0;
                    await fetch('/api/journal/'+days[i], {method:'PUT', headers:{'content-type':'application/json'},
                        body: JSON.stringify({content:'day '+i, mood: good ? '😄' : '😢', tags:''})});
                    if (good) await fetch('/api/habits/'+hid+'/toggle', {method:'POST', headers:{'content-type':'application/json'},
                        body: JSON.stringify({date: days[i]})});
                }
            }"""
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(1200)
        panel = pg.evaluate("() => document.getElementById('jrnl-moodcorr')?.textContent || '(none)'")
        print("mood-corr panel:", repr(panel))
        rows = pg.evaluate(
            """() => [...document.querySelectorAll('.jrnl-corr-row')].map(r => ({
                text: r.querySelector('.jrnl-corr-text')?.textContent,
                n: r.querySelector('.jrnl-corr-n')?.textContent,
                pos: !!r.querySelector('.jrnl-corr-dot.pos') }))"""
        )
        print("rows:", rows)
        assert any("run" in (r["text"] or "") and r["pos"] for r in rows), rows
        b.close()
    print("PASS: mood-correlation panel shows the habit link")


if __name__ == "__main__":
    main()
