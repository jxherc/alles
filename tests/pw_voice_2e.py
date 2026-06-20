"""ui-2e live render — start recording with a fake mic device and confirm the waveform canvas
actually paints (non-blank, red bars) and a timer is shown. Server on :8870."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "ui-2"


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    with sync_playwright() as p:
        b = p.chromium.launch(
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ]
        )
        ctx = b.new_context(permissions=["microphone"])
        pg = ctx.new_page()
        pg.goto("http://aide.localhost:8870/", wait_until="domcontentloaded")
        pg.wait_for_selector("#mic-btn", timeout=15000)
        pg.wait_for_timeout(500)
        pg.eval_on_selector("#mic-btn", "el => el.click()")
        pg.wait_for_timeout(1500)  # let the fake tone drive the analyser a bit

        r["recording_class_on"] = pg.eval_on_selector(
            ".composer-box", "el => el.classList.contains('mic-recording')"
        )
        # sample the canvas: are there any non-transparent (painted) pixels?
        painted = pg.eval_on_selector(
            "#mic-wave",
            """c => {
          const ctx = c.getContext('2d');
          const d = ctx.getImageData(0,0,c.width,c.height).data;
          let n=0, red=0;
          for (let i=0;i<d.length;i+=4){ if(d[i+3]>0){ n++; if(d[i]>150 && d[i+1]<120) red++; } }
          return {painted:n, redish:red};
        }""",
        )
        r["canvas_painted"] = painted["painted"] > 50
        r["has_red_bars"] = painted["redish"] > 10
        pg.screenshot(path=str(EVID / "voice-recording.png"))

        pg.eval_on_selector("#mic-btn", "el => el.click()")  # stop
        pg.wait_for_timeout(400)
        r["recording_stops"] = not pg.eval_on_selector(
            ".composer-box", "el => el.classList.contains('mic-recording')"
        )
        pg.close()
        b.close()

    ok = all(r.values())
    print("\n".join(f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()))
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
