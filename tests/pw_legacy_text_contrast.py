"""Measure real app text after legacy screens adopt foreground color tokens.

Run with the owned ALLES_DATA, ALLES_TEST_DATA, ALLES_TEST_RUN_ID and PORT
environment used by pw_v5_literal_resting_controls.py. No owner data or mocked UI.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from pw_v5_literal_resting_controls import BASE, SPACES, _require_owned_data

AUDIT = r"""() => {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  const rgba = value => {
    ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = value; ctx.fillRect(0, 0, 1, 1);
    const [r,g,b,a] = ctx.getImageData(0, 0, 1, 1).data;
    return [r,g,b,a/255];
  };
  const over = (front, back) => front.slice(0, 3).map((n, i) => n*front[3]+back[i]*(1-front[3])).concat(1);
  const lum = c => c.slice(0, 3).map(n => n/255).map(n => n <= 0.04045 ? n/12.92 : ((n+0.055)/1.055)**2.4)
    .reduce((sum, n, i) => sum + n*[0.2126,0.7152,0.0722][i], 0);
  const contrast = (a, b) => (Math.max(lum(a),lum(b))+0.05)/(Math.min(lum(a),lum(b))+0.05);
  const failures = [];
  let count = 0;
  for (const el of document.body.querySelectorAll('*')) {
    if (!el.checkVisibility({checkOpacity:true, checkVisibilityCSS:true})) continue;
    if (el.closest('[disabled],[aria-disabled="true"],[aria-hidden="true"]')) continue;
    const rect = el.getBoundingClientRect();
    if (rect.bottom <= 0 || rect.top >= innerHeight || rect.right <= 0 || rect.left >= innerWidth) continue;
    const text = [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join('').trim();
    const placeholder = el.matches('input,textarea') && !el.value ? el.getAttribute('placeholder') : '';
    if (!/[a-z0-9]/i.test(text || placeholder || '')) continue;
    const style = getComputedStyle(el, placeholder && !text ? '::placeholder' : null);
    const chain = []; for (let n = el; n; n = n.parentElement) chain.unshift(n);
    let bg = [255,255,255,1], opacity = 1;
    for (const n of chain) {
      const st = getComputedStyle(n);
      bg = over(rgba(st.backgroundColor), bg);
      opacity *= Number(st.opacity);
    }
    const color = rgba(style.color);
    color[3] *= opacity * (placeholder && !text ? Number(style.opacity) : 1);
    const ratio = contrast(over(color,bg), bg);
    const large = parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.67 && Number(style.fontWeight) >= 700);
    count++;
    if (ratio + 0.02 < (large ? 3 : 4.5)) failures.push({
      selector: el.id ? '#'+el.id : el.tagName.toLowerCase()+'.'+String(el.className).trim().replaceAll(' ','.'),
      text: (text || placeholder).slice(0,80), ratio: Math.round(ratio*100)/100, color: style.color,
    });
  }
  return {count, failures};
}"""


def run() -> None:
    _require_owned_data()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services.appearance import DARK_BASE, LIGHT_BASE

    output = Path(os.environ.get("ALLES_CONTRAST_OUTPUT", "/tmp/alles-legacy-contrast"))
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for theme, colors in (("dark", DARK_BASE), ("light", LIGHT_BASE)):
            for width in (1440, 390):
                context = browser.new_context(
                    viewport={"width": width, "height": 1000 if width == 1440 else 844},
                    reduced_motion="reduce",
                    service_workers="block",
                )
                context.add_init_script(
                    "localStorage.setItem('alles-appearance', JSON.stringify("
                    + json.dumps(
                        {
                            "preset": theme,
                            "colors": colors,
                            "font": "sans",
                            "density": "comfortable",
                        }
                    )
                    + "));"
                )
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console", lambda msg: errors.append(msg.text) if msg.type == "error" else None
                )
                assert page.request.post(f"{BASE}/api/setup/dismiss").ok
                for space, url in SPACES:
                    page.goto(url, wait_until="networkidle")
                    page.locator("#app-drawer-btn").wait_for(state="visible")
                    assert (
                        page.evaluate(
                            "getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"
                        )
                        == colors["bg"]
                    )
                    label = f"{theme}-{width}-{space}"
                    results[label] = page.evaluate(AUDIT)
                    page.screenshot(path=str(output / f"{label}.png"))
                    tabs = page.locator("main [role='tab']:visible")
                    names = tabs.all_text_contents()
                    for index, name in enumerate(names):
                        page.locator("main [role='tab']:visible").nth(index).click()
                        page.wait_for_load_state("networkidle")
                        key = f"{label}-{name.strip()}"
                        results[key] = page.evaluate(AUDIT)
                        if results[key]["failures"]:
                            page.screenshot(path=str(output / f"{label}-tab-{index}.png"))
                context.close()
        browser.close()
    (output / "contrast.json").write_text(json.dumps(results, indent=2))
    failures = {key: value["failures"] for key, value in results.items() if value["failures"]}
    print(
        f"Measured {len(results)} surfaces and {sum(r['count'] for r in results.values())} text observations"
    )
    assert not errors, errors
    assert not failures, json.dumps(failures, indent=2)
    print("legacy text contrast gate passed")


if __name__ == "__main__":
    run()
