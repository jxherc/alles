"""8c UI — labeled fields, avatar, Me badge, address map, groups, duplicate merge.
contacts.localhost:8866.  ALLES_DATA=/tmp/alles8c PORT=8866 AUTH_ENABLED=false python app.py
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


def _seed(contact):
    """create a contact straight against the server (IPv4, no browser/SW) and return its id."""
    req = urllib.request.Request(
        "http://127.0.0.1:8866/api/contacts",
        data=json.dumps(contact).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["id"]


CON = "http://contacts.localhost:8866"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "8c"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
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

        ada = _seed({"name": "Ada Lovelace", "address": "12 Baker St, London", "tags": ["vip"]})
        _seed({"name": "Jane Doe", "email": "jane@x.com"})
        _seed({"name": "jane doe", "email": "jane2@x.com"})

        pg.goto(f"{CON}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#contacts-view", timeout=15000)
        pg.wait_for_selector(".contact-item", timeout=12000)

        # ---- open Ada's detail; add a labeled field ----
        pg.eval_on_selector(f'[data-open="{ada}"]', "el => el.click()")
        pg.wait_for_selector(".contact-detail", timeout=8000)
        r["address_map_link"] = pg.query_selector(".contact-map") is not None
        pg.eval_on_selector("#cd-fkind", "el => { el.value='phone'; }")
        pg.fill("#cd-flabel", "mobile")
        pg.fill("#cd-fvalue", "555-9000")
        pg.eval_on_selector("#cd-fadd", "el => el.click()")
        pg.wait_for_selector(".cd-field-row", timeout=8000)
        r["field_add_shows"] = "555-9000" in (pg.text_content("#cd-fields") or "")

        # ---- avatar upload ----
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        tmp = Path(EVID) / "_av.png"
        tmp.write_bytes(png)
        pg.set_input_files("#cd-avatar", str(tmp))
        pg.wait_for_selector(".contact-detail-head img.contact-av-lg", timeout=8000)
        r["avatar_uploads"] = (
            pg.query_selector(".contact-detail-head img.contact-av-lg") is not None
        )

        # ---- set as me, back to list, badge shows ----
        pg.eval_on_selector("#cd-me", "el => el.click()")
        pg.wait_for_selector("#cd-back", timeout=8000)
        pg.eval_on_selector("#cd-back", "el => el.click()")
        # a dropped keep-alive can make loadContacts show "failed to load"; reload once if so
        try:
            pg.wait_for_selector(".contact-item", timeout=6000)
        except Exception:
            pg.goto(f"{CON}/", wait_until="domcontentloaded")
            pg.wait_for_selector(".contact-item", timeout=10000)
        r["me_badge"] = pg.query_selector(".contact-me-badge") is not None
        pg.screenshot(path=str(EVID / "contacts-list.png"))

        # ---- groups: create a smart group by tag ----
        pg.eval_on_selector("#contacts-groups-btn", "el => el.click()")
        pg.wait_for_selector("#cg-add", timeout=8000)
        pg.eval_on_selector("#cg-add", "el => el.click()")
        pg.wait_for_selector("#_di", timeout=5000)
        pg.fill("#_di", "VIPs")
        pg.eval_on_selector("#_dy", "el => el.click()")
        pg.wait_for_selector("#_di", timeout=5000)
        pg.fill("#_di", "vip")
        pg.eval_on_selector("#_dy", "el => el.click()")
        pg.wait_for_selector("#cg-list .settings-list-row", timeout=8000)
        gtext = pg.text_content("#cg-list") or ""
        r["group_create"] = "VIPs" in gtext
        # smart membership computed: the VIPs group resolves >=1 vip-tagged contact
        smart_n = pg.evaluate(
            "() => fetch('/api/contacts/groups').then(r=>r.json())"
            ".then(gs => { const g = gs.find(x=>x.name==='VIPs' && x.smart); return g ? "
            "fetch('/api/contacts/groups/'+g.id+'/members').then(r=>r.json()).then(m=>m.length) : 0; })"
        )
        r["smart_group_lists"] = (smart_n or 0) >= 1
        pg.screenshot(path=str(EVID / "groups.png"))

        # ---- duplicates: merge the two janes ----
        pg.eval_on_selector("#contacts-dups-btn", "el => el.click()")
        pg.wait_for_selector(".dup-cluster", timeout=8000)
        before = pg.evaluate("() => fetch('/api/contacts').then(r=>r.json()).then(a=>a.length)")
        pg.eval_on_selector("[data-merge]", "el => el.click()")
        merged = False
        for _ in range(20):
            pg.wait_for_timeout(300)
            now = pg.evaluate("() => fetch('/api/contacts').then(r=>r.json()).then(a=>a.length)")
            if now == before - 1:
                merged = True
                break
        r["duplicate_merge"] = merged

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_contacts_8c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
