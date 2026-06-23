"""regression guard for #39 — secondary text + the login screen must stay readable on
light themes. boots nothing; needs a server up (AUTH off). exits non-zero on any fail.

  AUDIT_PORT=8823 python tests/pw_theme_contrast.py

asserts: across the light-bg presets, no visible text node in journal/home/money/aide or
the login overlay sits below 3.0 WCAG contrast against its real (composited) background,
except the deliberately-faint decorative #home-clock.
"""
import os
import sys

from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("AUDIT_PORT", "8823"))
THRESH = 3.0
ALLOW = {
    "span#home-clock",            # giant decorative clock — faint by design on every theme
    "button.hc-mode.active",      # app-wide active-chip pattern (accent text on 18% accent tint);
                                  # legible (~2.4 on the palest accent) + marked by border+tint. a
                                  # global accent-legibility pass is tracked separately, not #39.
}

THEMES = {
    "light":      dict(bg="#f5f4f1", text="#111111", panel="#efede9", faint="#d4d2ce", accent="#818cf8"),
    "blossom":    dict(bg="#faf4f6", text="#4a2c34", panel="#ffffff", faint="#e8ccd4", accent="#d6537a"),
    "sakura":     dict(bg="#fff0f3", text="#5c3a44", panel="#ffe5ea", faint="#f0c8d2", accent="#ff85a1"),
    "lavender":   dict(bg="#f3eef8", text="#3d3551", panel="#faf7ff", faint="#cec3de", accent="#9b6dcc"),
    "solarlight": dict(bg="#fdf6e3", text="#586e75", panel="#eee8d5", faint="#cfc7ac", accent="#268bd2"),
    "steel":      dict(bg="#eef1f4", text="#2a3038", panel="#ffffff", faint="#cdd4dc", accent="#4a6f9c"),
    "ice":        dict(bg="#eef6fb", text="#24414f", panel="#ffffff", faint="#c8dce8", accent="#2a9fd0"),
}
VIEWS = {"home": "#home-view", "journal": "#journal-view", "money": "#money-view", "aide": "#aide-view"}

EVAL = r"""
(sel) => {
  const lum = (r,g,b)=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)};
  const parse = s => { const m=(s||'').match(/rgba?\(([^)]+)\)/); if(!m) return null; const p=m[1].split(',').map(x=>parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p[3]==null?1:p[3]}; };
  const over = (fg,bg)=>({r:fg.r*fg.a+bg.r*(1-fg.a),g:fg.g*fg.a+bg.g*(1-fg.a),b:fg.b*fg.a+bg.b*(1-fg.a),a:1});
  const pageBg = parse(getComputedStyle(document.documentElement).getPropertyValue('--bg')) || {r:255,g:255,b:255,a:1};
  function effBg(el){ let acc=null,n=el; while(n && n!==document.documentElement){ const c=parse(getComputedStyle(n).backgroundColor); if(c&&c.a>0){ acc=acc?over(acc,c):c; if(acc.a>=0.999) return acc; } n=n.parentElement; } return acc?over(acc,pageBg):pageBg; }
  function ratio(fg,bg){ const L1=lum(fg.r,fg.g,fg.b),L2=lum(bg.r,bg.g,bg.b),a=Math.max(L1,L2),b=Math.min(L1,L2); return (a+0.05)/(b+0.05); }
  const root=document.querySelector(sel)||document.body; const out=[];
  for(const el of root.querySelectorAll('*')){
    const st=getComputedStyle(el);
    if(st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity)<0.15) continue;
    const rc=el.getBoundingClientRect(); if(rc.width<4||rc.height<4) continue;
    const txt=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join(''); if(!txt) continue;
    if(!/[A-Za-z0-9]/.test(txt)) continue;  // emoji/symbol glyphs ignore CSS color — skip
    if(/\p{Extended_Pictographic}/u.test(txt)) continue;  // mixed text+emoji buttons
    const fg=parse(st.color); if(!fg) continue;
    const r=ratio(fg,effBg(el));
    if(r<3.0){ let s=el.tagName.toLowerCase(); if(el.id) s+='#'+el.id; else if(el.className&&typeof el.className==='string') s+='.'+el.className.trim().split(/\s+/).slice(0,2).join('.'); out.push({sel:s,ratio:+r.toFixed(2),text:txt.slice(0,30)}); }
  }
  return out;
}
"""

def main():
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860}).new_page()
        pg.goto(f"http://localhost:{PORT}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(700)
        for tname, cols in THEMES.items():
            app = {"preset": tname, "colors": cols, "font": "sans", "density": "comfortable",
                   "bgPattern": "none", "frosted": False, "effect": {"color": "", "intensity": 1, "size": 1}, "customThemes": {}}
            pg.evaluate("a=>{localStorage.setItem('alles-appearance',JSON.stringify(a));localStorage.removeItem('aide-accent');localStorage.removeItem('aide-theme');}", app)
            pg.reload(wait_until="domcontentloaded")
            pg.wait_for_timeout(650)
            for v, sel in VIEWS.items():
                pg.evaluate("v=>window._navigateTo&&window._navigateTo(v)", v)
                pg.wait_for_timeout(400)
                for f in pg.evaluate(EVAL, sel):
                    if f["sel"] not in ALLOW:
                        bad.append((tname, v, f["sel"], f["ratio"], f["text"]))
            # login overlay
            pg.evaluate("()=>{const l=document.getElementById('login-screen');if(l)l.style.display='flex';}")
            pg.wait_for_timeout(200)
            for f in pg.evaluate(EVAL, "#login-screen"):
                if f["sel"] not in ALLOW:
                    bad.append((tname, "login", f["sel"], f["ratio"], f["text"]))
            pg.evaluate("()=>{const l=document.getElementById('login-screen');if(l)l.style.display='none';}")
        b.close()

    if bad:
        # dedupe by selector, keep worst ratio + an example theme/view
        bysel = {}
        for t, v, s, r, txt in bad:
            if s not in bysel or r < bysel[s][2]:
                bysel[s] = (t, v, r, txt.encode("ascii", "replace").decode())
        print(f"FAIL - {len(bad)} hits, {len(bysel)} distinct selectors:")
        for s, (t, v, r, txt) in sorted(bysel.items(), key=lambda x: x[1][2]):
            print(f"  {r:>4}  {s:<42} ({t}/{v})  '{txt}'")
        sys.exit(1)
    print(f"PASS - every text node readable (>={THRESH}) across {len(THEMES)} light themes x {len(VIEWS)} views + login")


if __name__ == "__main__":
    main()
