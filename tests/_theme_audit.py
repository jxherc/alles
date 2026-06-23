"""
data-driven contrast audit. for each theme x view, composite the real background
behind every visible text node and compute the WCAG contrast ratio. anything that
lands under THRESH is a visibility bug (the #39 family: journal/login/etc invisible
on light themes). writes docs/evidence/theme/contrast.json + screenshots.

run: python tests/_theme_audit.py   (server must be up on PORT below, AUTH off)
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("AUDIT_PORT", "8823"))
OUT = Path("docs/evidence/theme")
OUT.mkdir(parents=True, exist_ok=True)
THRESH = 3.0   # below this, UI text is effectively unreadable

# subset of presets (the light-bg risky ones + 2 dark baselines to catch false positives)
THEMES = {
    "dark":       dict(bg="#0a0a0a", text="#e8e6e3", panel="#0e0e0e", faint="#2e2e2e", accent="#818cf8"),
    "midnight":   dict(bg="#0d1117", text="#c9d1d9", panel="#161b22", faint="#30363d", accent="#58a6ff"),
    "light":      dict(bg="#f5f4f1", text="#111111", panel="#efede9", faint="#d4d2ce", accent="#818cf8"),
    "blossom":    dict(bg="#faf4f6", text="#4a2c34", panel="#ffffff", faint="#e8ccd4", accent="#d6537a"),
    "sakura":     dict(bg="#fff0f3", text="#5c3a44", panel="#ffe5ea", faint="#f0c8d2", accent="#ff85a1"),
    "paper":      dict(bg="#faf8f5", text="#3b3836", panel="#ffffff", faint="#d5d0c8", accent="#b07d3a"),
    "lavender":   dict(bg="#f3eef8", text="#3d3551", panel="#faf7ff", faint="#cec3de", accent="#9b6dcc"),
    "solarlight": dict(bg="#fdf6e3", text="#586e75", panel="#eee8d5", faint="#cfc7ac", accent="#268bd2"),
    "sand":       dict(bg="#f3ecdf", text="#4a4136", panel="#fbf6ec", faint="#d8cdb8", accent="#b8893a"),
    "steel":      dict(bg="#eef1f4", text="#2a3038", panel="#ffffff", faint="#cdd4dc", accent="#4a6f9c"),
    "coral":      dict(bg="#fff5f0", text="#5a3a32", panel="#ffffff", faint="#f0d0c4", accent="#ff6b4a"),
    "ice":        dict(bg="#eef6fb", text="#24414f", panel="#ffffff", faint="#c8dce8", accent="#2a9fd0"),
    "peach":      dict(bg="#fff3e8", text="#5a3e2a", panel="#ffffff", faint="#f0d6bc", accent="#f08a3a"),
    "cute":       dict(bg="#fff0f5", text="#d4608a", panel="#fff8fa", faint="#f0c0d0", accent="#ff6b9d"),
}

# view id -> how to get there. login is special-cased (force-show the overlay).
VIEWS = ["home", "journal", "money", "wiki", "calendar", "aide", "login"]

# injected once per page: composite the true bg behind an element, then WCAG ratio.
EVAL = r"""
(view) => {
  const lum = (r,g,b)=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)};
  const parse = s => { const m=(s||'').match(/rgba?\(([^)]+)\)/); if(!m) return null; const p=m[1].split(',').map(x=>parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p[3]==null?1:p[3]}; };
  const over = (fg,bg)=>({r:fg.r*fg.a+bg.r*(1-fg.a),g:fg.g*fg.a+bg.g*(1-fg.a),b:fg.b*fg.a+bg.b*(1-fg.a),a:1});
  const pageBg = parse(getComputedStyle(document.documentElement).getPropertyValue('--bg')) || {r:255,g:255,b:255,a:1};
  function effBg(el){ let acc=null; let n=el; while(n && n!==document.documentElement){ const c=parse(getComputedStyle(n).backgroundColor); if(c && c.a>0){ acc = acc? over(acc,c): c; if(acc.a>=0.999) return acc; } n=n.parentElement; } return acc? over(acc,pageBg): pageBg; }
  function ratio(fg,bg){ const L1=lum(fg.r,fg.g,fg.b),L2=lum(bg.r,bg.g,bg.b); const a=Math.max(L1,L2),b=Math.min(L1,L2); return (a+0.05)/(b+0.05); }
  const root = document.querySelector(view) || document.body;
  const out=[];
  const els = root.querySelectorAll('*');
  for(const el of els){
    const st=getComputedStyle(el);
    if(st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity)<0.15) continue;
    const rc=el.getBoundingClientRect(); if(rc.width<4||rc.height<4) continue;
    // only nodes with their own visible text
    const txt=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('');
    if(!txt) continue;
    const fg=parse(st.color); if(!fg) continue;
    const bg=effBg(el);
    const r=ratio(fg,bg);
    if(r<3.0){
      let sel=el.tagName.toLowerCase();
      if(el.id) sel+='#'+el.id; else if(el.className && typeof el.className==='string') sel+='.'+el.className.trim().split(/\s+/).slice(0,2).join('.');
      out.push({sel, text:txt.slice(0,40), color:st.color, bg:`rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)})`, ratio:+r.toFixed(2)});
    }
  }
  // dedupe by selector, keep worst
  const m={}; for(const o of out){ if(!m[o.sel]||o.ratio<m[o.sel].ratio) m[o.sel]=o; }
  return Object.values(m).sort((a,b)=>a.ratio-b.ratio);
}
"""

def set_theme(pg, name, cols):
    app = {"preset": name, "colors": cols, "font": "sans", "density": "comfortable",
           "bgPattern": "none", "frosted": False, "effect": {"color": "", "intensity": 1, "size": 1},
           "customThemes": {}}
    pg.evaluate("(a) => { localStorage.setItem('alles-appearance', JSON.stringify(a)); localStorage.removeItem('aide-accent'); localStorage.removeItem('aide-theme'); }", app)


def main():
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.goto(f"http://localhost:{PORT}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        for tname, cols in THEMES.items():
            set_theme(pg, tname, cols)
            pg.reload(wait_until="domcontentloaded")
            pg.wait_for_timeout(700)
            results[tname] = {}
            for view in VIEWS:
                try:
                    if view == "login":
                        pg.evaluate("() => { const l=document.getElementById('login-screen'); if(l){ l.style.display='flex'; } }")
                        pg.wait_for_timeout(150)
                        fails = pg.evaluate(EVAL, "#login-screen")
                        pg.evaluate("() => { const l=document.getElementById('login-screen'); if(l) l.style.display='none'; }")
                    else:
                        pg.evaluate("(v) => window._navigateTo && window._navigateTo(v)", view)
                        pg.wait_for_timeout(450)
                        sel = "#" + (view + "-view" if view in ("journal",) else
                                    {"home": "home-view", "money": "money-view", "wiki": "wiki-view",
                                     "calendar": "calendar-view", "aide": "aide-view"}.get(view, view + "-view"))
                        fails = pg.evaluate(EVAL, sel)
                    results[tname][view] = fails
                except Exception as e:
                    results[tname][view] = [{"error": str(e)[:120]}]
            # one screenshot per theme on the journal view (most-reported)
            try:
                pg.evaluate("() => window._navigateTo && window._navigateTo('journal')")
                pg.wait_for_timeout(300)
                pg.screenshot(path=str(OUT / f"journal-{tname}.png"))
            except Exception:
                pass
        b.close()

    (OUT / "contrast.json").write_text(json.dumps(results, indent=1))
    # summary to stdout
    print(f"{'THEME':<12} {'fails (ratio<%.1f)':<18} worst views" % THRESH)
    total = 0
    for t, views in results.items():
        n = sum(len([f for f in fl if "ratio" in f]) for fl in views.values())
        total += n
        worst = sorted(((v, len([f for f in fl if "ratio" in f])) for v, fl in views.items()), key=lambda x: -x[1])
        wstr = ", ".join(f"{v}:{c}" for v, c in worst if c)
        print(f"{t:<12} {n:<18} {wstr}")
    print(f"\nTOTAL failing text/bg pairs: {total}")
    print(f"wrote {OUT/'contrast.json'} + journal screenshots")


if __name__ == "__main__":
    main()
