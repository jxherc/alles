"""7a UI verification — lightbox caption/keywords editor + hide button + hidden
(vault-gated) album + favorites filter. Talks to photos.localhost:8861.
Start a server first with a throwaway ALLES_DATA, e.g.:
  ALLES_DATA=/tmp/alles7a PORT=8861 AUTH_ENABLED=false python app.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PHOTOS = "http://photos.localhost:8861"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "7a"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")

# tiny canvas->png uploads so the run seeds its own deterministic photos
_SEED = """async (n) => {
  const mk = (name) => new Promise(res => {
    const c = document.createElement('canvas'); c.width = c.height = 24;
    const x = c.getContext('2d');
    x.fillStyle = '#' + ((name.charCodeAt(0) * 99991) & 0xffffff).toString(16).padStart(6,'0');
    x.fillRect(0,0,24,24);
    c.toBlob(async b => {
      const fd = new FormData(); fd.append('file', b, name);
      await fetch('/api/photos/upload', { method:'POST', body: fd }); res();
    }, 'image/png');
  });
  for (let i = 0; i < n; i++) await mk('seed7a_' + i + '.png');
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

        # seed 3 photos, reload so the grid renders them
        pg.evaluate(_SEED, 3)
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".photos-cell", timeout=12000)
        ids = pg.eval_on_selector_all(".photos-cell", "els => els.map(e => e.dataset.id)")
        assert len(ids) >= 3, f"expected 3 seeded photos, got {ids}"
        id0, id1, id2 = ids[0], ids[1], ids[2]

        def open_lb(pid):
            pg.wait_for_selector(f'.photos-cell[data-id="{pid}"]', timeout=8000)
            pg.eval_on_selector(f'.photos-cell[data-id="{pid}"]', "el => el.click()")
            pg.wait_for_selector("#photos-lightbox", state="visible", timeout=5000)

        def close_lb():
            pg.eval_on_selector("#photos-close-btn", "el => el.click()")
            pg.wait_for_selector("#photos-lightbox", state="hidden", timeout=5000)

        def grid_ids():
            return pg.eval_on_selector_all(".photos-cell", "els => els.map(e => e.dataset.id)")

        def set_album(val):
            pg.eval_on_selector(
                "#photos-album",
                "(el, v) => { el.value=v; el.dispatchEvent(new Event('change',{bubbles:true})); }",
                val,
            )

        def wait_grid(pred, desc):
            pg.wait_for_function(
                "p => { const ids=[...document.querySelectorAll('.photos-cell')]"
                ".map(e=>e.dataset.id); return (new Function('ids','return '+p))(ids); }",
                arg=pred,
                timeout=8000,
            )

        def caption_of(pid):
            return pg.evaluate(
                "pid => fetch('/api/photos/list').then(r=>r.json())"
                ".then(d => (d.moments||[]).flatMap(m=>m.items).find(p=>p.id===pid))",
                pid,
            )

        # ---- caption + keywords save (lightbox editor → PATCH) ----
        open_lb(id0)
        pg.fill("#photos-caption", "a day at the beach")
        pg.fill("#photos-keywords", "Beach, Sunset, beach")  # dup + case → normalized
        pg.eval_on_selector("#photos-meta-save", "el => el.click()")
        pg.wait_for_timeout(500)
        saved = caption_of(id0)
        r["caption_saves"] = bool(saved) and saved.get("caption") == "a day at the beach"
        r["keywords_save"] = bool(saved) and saved.get("keywords") == ["beach", "sunset"]

        # ---- caption shows on reopen ----
        close_lb()
        open_lb(id0)
        r["caption_shows_on_reopen"] = (
            pg.input_value("#photos-caption") == "a day at the beach"
            and pg.input_value("#photos-keywords") == "beach, sunset"
        )
        close_lb()

        # ---- favorites filter shows ♥ and excludes non-favorites ----
        open_lb(id1)
        pg.eval_on_selector("#photos-fav-btn", "el => el.click()")
        pg.wait_for_timeout(400)
        close_lb()
        set_album("__fav__")
        # wait until the filter has actually re-rendered: a known non-fav (id0) drops out
        wait_grid(f"ids.includes('{id1}') && !ids.includes('{id0}')", "fav-only rendered")
        fav_ids = grid_ids()
        # this run's favorite is shown; this run's non-favorites are excluded
        r["favorites_filter_works"] = id1 in fav_ids and id0 not in fav_ids and id2 not in fav_ids

        # back to the full gallery
        set_album("")
        wait_grid(f"ids.includes('{id2}')", "back to all")

        # ---- hide removes from the grid ----
        open_lb(id2)
        pg.eval_on_selector("#photos-hide-btn", "el => el.click()")
        wait_grid(f"!ids.includes('{id2}')", "hidden gone from grid")
        grid_now = grid_ids()
        r["hide_removes_from_grid"] = id2 not in grid_now and id0 in grid_now

        # ---- hidden album prompts for the master password ----
        set_album("__hidden__")
        pg.wait_for_selector("#_di", timeout=6000)
        r["hidden_album_prompts_unlock"] = pg.query_selector("#_di") is not None

        # ---- after unlock, the hidden photo lists ----
        pg.fill("#_di", "test-master-7a")
        pg.eval_on_selector("#_dy", "el => el.click()")
        pg.wait_for_selector('.photos-cell[data-id="%s"]' % id2, timeout=8000)
        hid_ids = grid_ids()
        r["hidden_album_lists_after_unlock"] = id2 in hid_ids and id0 not in hid_ids
        pg.screenshot(path=str(EVID / "hidden-album.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_photos_organize_7a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
