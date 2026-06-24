"""4b - verify the journal topics chips render and clicking one threads the related entries.

needs a fresh instance: ALLES_DATA=.tmp_jt AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_journal_topics.py
"""
from playwright.sync_api import sync_playwright

BASE = "http://journal.localhost:8077"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(900)
        pg.evaluate(
            """async () => {
                const put = (d, tags, content) => fetch('/api/journal/'+d, {method:'PUT', headers:{'content-type':'application/json'},
                    body: JSON.stringify({content, mood:'🙂', tags})});
                const days = [...Array(4).keys()].map(i => new Date(Date.now()-i*86400000).toISOString().slice(0,10));
                await put(days[0], 'work, gym', 'busy day');
                await put(days[1], 'work', 'standup notes');
                await put(days[2], 'work', 'shipped a feature');
                await put(days[3], 'gym', 'leg day');
            }"""
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(1000)
        topics = pg.evaluate(
            "() => [...document.querySelectorAll('.jrnl-topic')].map(t => t.textContent.replace(/\\s+/g,' ').trim())"
        )
        print("topics:", topics)
        assert any("work" in t for t in topics), topics
        # clicking #work threads the related entries into the results
        pg.evaluate("() => [...document.querySelectorAll('.jrnl-topic')].find(t => t.textContent.includes('work')).click()")
        pg.wait_for_timeout(700)
        results = pg.evaluate("() => document.querySelectorAll('#jrnl-results .jrnl-otd-row').length")
        print("work entries threaded:", results)
        assert results >= 3, results
        b.close()
    print("PASS: topics chips render and thread related entries")


if __name__ == "__main__":
    main()
