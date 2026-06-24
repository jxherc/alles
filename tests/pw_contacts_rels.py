"""4a - verify the contact relationship-graph UI end to end: add a typed link, see it from both
sides (inverse kind), navigate between linked contacts, then remove it.

run against a fresh instance with the current routes:
  ALLES_DATA=.tmp_rel AUTH_ENABLED=false PORT=8077 python app.py
  PYTHONIOENCODING=utf-8 python tests/pw_contacts_rels.py
(the contacts detail view needs GET /api/contacts/{id}, added after the early test servers booted)
"""
from playwright.sync_api import sync_playwright

BASE = "http://contacts.localhost:8077"


def _rels(pg):
    return pg.evaluate(
        """() => [...document.querySelectorAll('.cd-rel-row')].map(r => ({
            name: r.querySelector('.cd-rel-name').textContent,
            kind: r.querySelector('.cd-rel-kind').textContent }))"""
    )


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        a, bob = pg.evaluate(
            """async () => {
                const mk = n => fetch('/api/contacts', {method:'POST', headers:{'content-type':'application/json'},
                  body: JSON.stringify({name:n})}).then(r=>r.json()).then(j=>j.id);
                return [await mk('REL_Alice'), await mk('REL_Bob')];
            }"""
        )

        pg.evaluate("([a]) => window._editContact(a)", [a])
        pg.wait_for_timeout(600)
        pg.evaluate(
            """([bob]) => { document.getElementById('cd-relwho').value = bob;
                            document.getElementById('cd-relkind').value = 'manager'; }""",
            [bob],
        )
        pg.click("#cd-reladd")
        pg.wait_for_timeout(700)
        av = _rels(pg)
        assert any(x["name"] == "REL_Bob" and x["kind"] == "manager" for x in av), av

        pg.evaluate("() => document.querySelector('.cd-rel-name').click()")  # navigate to Bob
        pg.wait_for_timeout(700)
        bv = _rels(pg)
        assert any(x["name"] == "REL_Alice" and x["kind"] == "report" for x in bv), bv  # inverse

        pg.evaluate("() => document.querySelector('.cd-rel-row [data-unlink]').click()")
        pg.wait_for_timeout(700)
        assert "no relationships yet" in pg.evaluate("() => document.getElementById('cd-rels').textContent")

        pg.evaluate(
            "async ([a, bob]) => { for (const id of [a, bob]) await fetch('/api/contacts/'+id, {method:'DELETE'}); }",
            [a, bob],
        )
        b.close()
    print("PASS: relationship graph add/inverse/navigate/remove all work")


if __name__ == "__main__":
    main()
