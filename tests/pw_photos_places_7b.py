"""7b UI verification — places map (Leaflet/OSM) + memories/collage. photos.localhost:8862.
Start a server first with the matching ALLES_DATA, e.g.:
  ALLES_DATA=/tmp/alles7b PORT=8862 AUTH_ENABLED=false python app.py
The map needs GPS and memories need a prior-year date, which the upload API can't set, so we
seed via /upload and then patch exif/taken_at straight into the server's sqlite db.
"""

import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

PHOTOS = "http://photos.localhost:8862"
DATA = Path(os.environ.get("ALLES_DATA", "/tmp/alles7b"))
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "7b"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")

_SEED = """async (name) => {
  return await new Promise(res => {
    const c = document.createElement('canvas'); c.width = c.height = 48;
    const x = c.getContext('2d');
    x.fillStyle = '#' + ((name.charCodeAt(5) * 99991) & 0xffffff).toString(16).padStart(6,'0');
    x.fillRect(0,0,48,48);
    c.toBlob(async b => {
      const fd = new FormData(); fd.append('file', b, name);
      const r = await fetch('/api/photos/upload', { method:'POST', body: fd });
      res((await r.json()).id);
    }, 'image/png');
  });
}"""


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

        pg.goto(f"{PHOTOS}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#photos-grid", timeout=15000)

        # seed: one located photo (for the map) + two prior-year on-this-day photos (memories)
        pid_map = pg.evaluate(_SEED, "mapme.png")
        pid_m1 = pg.evaluate(_SEED, "memone.png")
        pid_m2 = pg.evaluate(_SEED, "memtwo.png")

        ly = date.today().replace(year=date.today().year - 1)
        taken = f"{ly.year:04d}-{ly.month:02d}-{ly.day:02d} 12:00:00.000000"
        con = sqlite3.connect(str(DATA / "aide.db"), timeout=10)
        con.execute("PRAGMA busy_timeout=8000")
        con.execute(
            "UPDATE photos SET exif=? WHERE id=?",
            ('{"lat": 37.7749, "lon": -122.4194}', pid_map),
        )
        con.execute("UPDATE photos SET taken_at=? WHERE id=?", (taken, pid_m1))
        con.execute("UPDATE photos SET taken_at=? WHERE id=?", (taken, pid_m2))
        con.commit()
        con.close()

        def set_album(val):
            pg.eval_on_selector(
                "#photos-album",
                "(el, v) => { el.value=v; el.dispatchEvent(new Event('change',{bubbles:true})); }",
                val,
            )

        # ---- map option present in the dropdown ----
        opts = pg.eval_on_selector("#photos-album", "el => el.dataset.options || ''")
        r["map_option_present"] = "__map__" in opts
        r["memories_option_present"] = "__memories__" in opts

        # ---- map renders Leaflet + a marker, marker opens the lightbox ----
        set_album("__map__")
        # Leaflet puts the leaflet-container class on the target el itself
        pg.wait_for_selector("#photos-mapview.leaflet-container", timeout=12000)
        r["map_renders_leaflet"] = (
            pg.query_selector("#photos-mapview.leaflet-container") is not None
        )
        pg.wait_for_selector("#photos-mapview path.leaflet-interactive", timeout=12000)
        r["map_has_marker"] = (
            pg.query_selector("#photos-mapview path.leaflet-interactive") is not None
        )
        pg.screenshot(path=str(EVID / "map.png"))
        pg.eval_on_selector(
            "#photos-mapview path.leaflet-interactive",
            "el => el.dispatchEvent(new MouseEvent('click', {bubbles:true}))",
        )
        pg.wait_for_selector("#photos-lightbox", state="visible", timeout=6000)
        r["marker_opens_lightbox"] = pg.is_visible("#photos-lightbox")
        pg.eval_on_selector("#photos-close-btn", "el => el.click()")
        pg.wait_for_selector("#photos-lightbox", state="hidden", timeout=5000)

        # ---- memories section renders ----
        set_album("__memories__")
        pg.wait_for_selector(".photos-moment-label", timeout=10000)
        label = pg.text_content(".photos-moment-label") or ""
        r["memories_section_renders"] = "year ago" in label
        pg.screenshot(path=str(EVID / "memories.png"))

        # ---- collage button creates a new photo ----
        def list_count():
            return pg.evaluate("() => fetch('/api/photos/list').then(r=>r.json()).then(d=>d.count)")

        count_before = list_count()
        pg.eval_on_selector(".photos-collage-btn", "el => el.click()")
        count_after = count_before
        for _ in range(20):  # poll up to ~10s for the collage to be saved
            pg.wait_for_timeout(500)
            count_after = list_count()
            if count_after > count_before:
                break
        r["collage_button_makes_photo"] = count_after == count_before + 1

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_photos_places_7b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
