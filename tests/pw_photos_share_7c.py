"""7c UI verification — shared albums + video assets + watch-folder setting. photos.localhost:8863.
ALLES_DATA=/tmp/alles7c PORT=8863 AUTH_ENABLED=false python app.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PHOTOS = "http://photos.localhost:8863"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "7c"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")

_IMG = """async (name) => await new Promise(res => {
  const c = document.createElement('canvas'); c.width=c.height=40;
  const x=c.getContext('2d'); x.fillStyle='#3a7'; x.fillRect(0,0,40,40);
  c.toBlob(async b => { const fd=new FormData(); fd.append('file',b,name);
    const r=await fetch('/api/photos/upload',{method:'POST',body:fd}); res((await r.json()).id); }, 'image/png');
})"""

_VID = """async (name) => {
  const fd = new FormData();
  fd.append('file', new Blob([new Uint8Array([0,0,0,24,102,116,121,112,109,112,52,50])], {type:'video/mp4'}), name);
  const r = await fetch('/api/photos/upload', {method:'POST', body: fd});
  return (await r.json()).id;
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

        # seed: an album with one image, plus a loose video and a loose image
        aid = pg.evaluate(
            "() => fetch('/api/photos/albums',{method:'POST',headers:{'content-type':'application/json'},"
            "body:JSON.stringify({name:'Trip 2026'})}).then(r=>r.json()).then(a=>a.id)"
        )
        img_in_album = pg.evaluate(_IMG, "inalbum.png")
        pg.evaluate(
            "([pid,aid]) => fetch('/api/photos/'+pid,{method:'PATCH',headers:{'content-type':'application/json'},"
            "body:JSON.stringify({album_id:aid})})",
            [img_in_album, aid],
        )
        vid = pg.evaluate(_VID, "clip.mp4")
        img = pg.evaluate(_IMG, "loose.png")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".photos-cell", timeout=12000)

        def set_album(val):
            pg.eval_on_selector(
                "#photos-album",
                "(el, v) => { el.value=v; el.dispatchEvent(new Event('change',{bubbles:true})); }",
                val,
            )

        # ---- share album button present ----
        r["share_album_button"] = pg.query_selector("#photos-share-album-btn") is not None

        # ---- selecting a real album + share mints a token ----
        set_album(aid)
        pg.wait_for_timeout(400)
        pg.eval_on_selector("#photos-share-album-btn", "el => el.click()")
        tok = None
        for _ in range(20):
            pg.wait_for_timeout(300)
            tok = pg.evaluate(
                "aid => fetch('/api/share?kind=album&ref='+aid).then(r=>r.json()).then(j=>j.token)",
                aid,
            )
            if tok:
                break
        r["share_mints_token"] = bool(tok)

        # ---- the public read-only album grid opens ----
        if tok:
            pg.goto(f"{PHOTOS}/s/{tok}", wait_until="domcontentloaded")
            grid_html = pg.content()
            r["public_album_grid_opens"] = f"/s/{tok}/{img_in_album}" in grid_html
            pg.screenshot(path=str(EVID / "shared-album.png"))
            pg.goto(f"{PHOTOS}/", wait_until="domcontentloaded")
            pg.wait_for_selector(".photos-cell", timeout=12000)
        else:
            r["public_album_grid_opens"] = False

        set_album("")
        pg.wait_for_selector(f'.photos-cell[data-id="{vid}"]', timeout=8000)

        # ---- video cell shows the badge ----
        r["video_badge_on_cell"] = (
            pg.query_selector(f'.photos-cell[data-id="{vid}"].video .photos-vbadge') is not None
        )

        # ---- clicking a video opens a <video> in the lightbox ----
        pg.eval_on_selector(f'.photos-cell[data-id="{vid}"]', "el => el.click()")
        pg.wait_for_selector("#photos-lightbox", state="visible", timeout=6000)
        r["lightbox_plays_video"] = pg.is_visible("#photos-lightbox-video") and not pg.is_visible(
            "#photos-lightbox-img"
        )
        pg.screenshot(path=str(EVID / "video-lightbox.png"))
        pg.eval_on_selector("#photos-close-btn", "el => el.click()")
        pg.wait_for_selector("#photos-lightbox", state="hidden", timeout=5000)

        # ---- clicking an image still uses <img> ----
        pg.eval_on_selector(f'.photos-cell[data-id="{img}"]', "el => el.click()")
        pg.wait_for_selector("#photos-lightbox", state="visible", timeout=6000)
        r["image_still_uses_img"] = pg.is_visible("#photos-lightbox-img") and not pg.is_visible(
            "#photos-lightbox-video"
        )
        pg.eval_on_selector("#photos-close-btn", "el => el.click()")
        pg.wait_for_selector("#photos-lightbox", state="hidden", timeout=5000)

        # ---- watch-folder setting saves ----
        pg.eval_on_selector('.app-cog[data-app="photos"]', "el => el.click()")
        pg.wait_for_selector('input[data-k="photos_watch_folder"]', timeout=6000)
        pg.fill('input[data-k="photos_watch_folder"]', "/tmp/phone-backup")
        saved = False
        for _ in range(20):
            pg.wait_for_timeout(300)
            saved = pg.evaluate(
                "() => fetch('/api/settings').then(r=>r.json()).then(s=>s.photos_watch_folder==='/tmp/phone-backup')"
            )
            if saved:
                break
        r["watch_folder_setting_saves"] = bool(saved)

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_photos_share_7c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
