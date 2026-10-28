"""UI consistency audit across every Alles route, run through the owned browser runner.

Scores three rubrics on the real app with synthetic data:
  kokuen  - design-system/QA-CHECKLIST.md + FOUNDATIONS.md, measured
  wcag    - WCAG 2.2 AA criteria a browser can measure
  vercel  - Web Interface Guidelines rules that fit the house style

Every visible button is hovered, clicked, and whatever it opens is measured too.
Writes results.json + screenshots to ALLES_BROWSER_ARTIFACTS. Exits 1 below 100%.

  python scripts/run_browser_gates.py --suite ui-audit
  UI_AUDIT_ROUTES=home,aide UI_AUDIT_PROFILES=desktop-dark python tests/pw_ui_audit.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

ROUTES = [
    "home", "aide", "andromeda",
    "plan", "plan-week", "plan-board", "calendar", "tasks", "reminders", "days",
    "inbox", "mail", "contacts",
    "library", "books", "read",
    "health-overview", "health", "habits",
    "finance-overview", "money", "subs", "imports",
    "docs", "journal",
    "files", "files-gallery",
    "vault",
    "server", "server-services", "server-search", "server-backups", "server-updates",
    "server-logs", "server-activity", "server-watch", "server-policy",
    "memory", "compare", "brain", "models", "cookbook", "usage", "skills", "scheduled",
    "aide-reminders", "gallery",
    "settings", "setup",
]  # fmt: skip

PROFILES = {
    "desktop-dark": dict(width=1440, height=900, theme="dark", mobile=False, click=True),
    "desktop-light": dict(width=1440, height=900, theme="light", mobile=False, click=False),
    "phone-dark": dict(width=390, height=844, theme="dark", mobile=True, click=False),
    "phone-light": dict(width=390, height=844, theme="light", mobile=True, click=True),
    "reflow-320": dict(
        width=320, height=640, theme="dark", mobile=True, click=False, only="layout"
    ),
    "zoom-200": dict(width=720, height=450, theme="dark", mobile=False, click=False, only="layout"),
}

# never clicked: they end the process, the session, or reach outside the sandbox
SKIP_NAME = re.compile(
    r"\b(sign ?out|log ?out|lock( now)?|restart|shut ?down|reboot|update now|install|"
    r"restore|start call|call|microphone|record|dictate|pair|connect dsh|upgrade|"
    r"export|download|print)\b",
    re.I,
)

PROBE = r"""
(opts) => {
  const scope = opts.scope ? document.querySelector(opts.scope) : document;
  const out = { checks: {}, fails: [] };
  const SCALE = [0, 4, 8, 12, 16, 24, 32, 48, 64];
  const RADII = [0, 6, 8, 12, 16];
  // 20 is the page title (decision 0041: page 20, section 16, row 14, label 12)
  // the role scale (0044) at this root, plus the 16px floor of a touch text field
  const rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize);
  const TYPE = [13, 14, 15, 16, 18, 20, 22, 24, 28, 32].map(role => role * rootPx / 16).concat(16);
  const vw = document.documentElement.clientWidth, vh = window.innerHeight;
  const tally = (rubric, check, ok, el, detail) => {
    const k = rubric + ':' + check;
    out.checks[k] = out.checks[k] || [0, 0];
    out.checks[k][ok ? 0 : 1]++;
    if (!ok) out.fails.push({ rubric, check, sig: el ? sig(el) : '', detail });
  };
  const sig = el => {
    let s = el.tagName.toLowerCase();
    if (el.id) return s + '#' + el.id;
    const cls = [...el.classList].slice(0, 2).join('.');
    if (cls) s += '.' + cls;
    const r = el.getAttribute('role'); if (r) s += '[role=' + r + ']';
    let p = el.parentElement, hops = 0;
    while (p && !p.id && hops < 6) { p = p.parentElement; hops++; }
    return (p && p.id ? '#' + p.id + ' ' : '') + s;
  };
  const visible = el => {
    if (!el.isConnected) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) return false;
    if (el.closest('[inert],[aria-hidden="true"]')) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    if (r.bottom < 0 || r.right < 0 || r.top > vh * 4 || r.left > vw) return false;
    // clipped away by an overflow ancestor (collapsed panels, sr-only)
    let p = el.parentElement;
    while (p && p !== document.body) {
      const pc = getComputedStyle(p);
      if (pc.overflow !== 'visible' || pc.clipPath !== 'none') {
        const pr = p.getBoundingClientRect();
        if (pr.width < 2 || pr.height < 2) return false;
        if (r.right <= pr.left || r.left >= pr.right || r.bottom <= pr.top || r.top >= pr.bottom) return false;
      }
      p = p.parentElement;
    }
    return true;
  };
  const px = v => parseFloat(v) || 0;
  const parse = s => { const m = (s || '').match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p[3] == null ? 1 : p[3] }; };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const pageBg = parse(getComputedStyle(document.body).backgroundColor) || parse(getComputedStyle(document.documentElement).backgroundColor) || { r: 9, g: 9, b: 9, a: 1 };
  const effBg = el => { let acc = null, n = el; while (n && n.nodeType === 1) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0) { acc = acc ? over(acc, c) : c; if (acc.a >= 0.999) return acc; } n = n.parentElement; } return acc ? over(acc, pageBg) : pageBg; };
  const onScale = v => SCALE.some(s => Math.abs(s - v) < 0.6);
  const name = el => {
    const l = el.getAttribute('aria-label'); if (l && l.trim()) return l.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(i => document.getElementById(i)?.textContent || '').join(' ').trim(); if (t) return t; }
    if (el.labels && el.labels.length) { const t = [...el.labels].map(x => x.textContent).join(' ').trim(); if (t) return t; }
    const t = (el.innerText || el.textContent || '').trim(); if (t) return t;
    const img = el.querySelector('img[alt]'); if (img && img.alt.trim()) return img.alt.trim();
    const svgt = el.querySelector('svg title'); if (svgt) return svgt.textContent.trim();
    return (el.getAttribute('title') || '').trim();
  };
  const isText = el => el.matches('textarea, input:not([type]), input[type=text], input[type=search], input[type=email], input[type=url], input[type=tel], input[type=password], input[type=number]');
  const CTRL = 'button, [role=button], [role=tab], [role=menuitem], [role=menuitemradio], [role=menuitemcheckbox], [role=option], [role=switch], [role=combobox], [role=checkbox], [role=radio], summary, input:not([type=hidden]), textarea, select, a[href]';
  const root = scope || document;
  const all = [...root.querySelectorAll(CTRL)].filter(visible);
  const ctrls = all.filter(el => {
    if (el.tagName === 'A') {
      const d = getComputedStyle(el).display;
      if (d === 'inline') return false; // inline prose links: exempt from target rules
    }
    if (el.isContentEditable) return false;
    return true;
  });
  // long-form editors decide their own height (FOUNDATIONS spacing exemption)
  const longForm = el => el.tagName === 'TEXTAREA' && (el.getBoundingClientRect().height > 120 || el.closest('[data-kokuen-longform], .wiki-editor, .md-editor, .note-editor, .source-editor, .journal-editor, .mail-compose-body'));

  for (const el of ctrls) {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
    // hit area may be widened by an absolute pseudo element
    let hw = r.width, hh = r.height;
    for (const ps of ['::before', '::after']) {
      const p = getComputedStyle(el, ps);
      if (p.content !== 'none' && p.position === 'absolute') {
        const t = px(p.top), b = px(p.bottom), l = px(p.left), rr = px(p.right);
        if (p.top !== 'auto' && p.bottom !== 'auto') hh = Math.max(hh, r.height - t - b);
        if (p.left !== 'auto' && p.right !== 'auto') hw = Math.max(hw, r.width - l - rr);
      }
    }
    const nm = name(el);
    // K: 44px target (W: 24px)
    if (!longForm(el) && el.type !== 'range') {
      tally('kokuen', 'target-44', hh >= 43.5 && hw >= 43.5 || (el.tagName === 'A' && hh >= 43.5), el, `${hw.toFixed(1)}x${hh.toFixed(1)}`);
      tally('wcag', '2.5.8-target', hh >= 24 && hw >= 24, el, `${hw.toFixed(1)}x${hh.toFixed(1)}`);
    }
    // K: radius on the balanced scale (decision 0040), circles and round chips ok
    const rad = px(cs.borderTopLeftRadius);
    const minSide = Math.min(r.width, r.height);
    const round = rad >= minSide / 2 - 1;
    const radOk = RADII.some(v => Math.abs(rad - v) < 0.3) || round || el.type === 'range';
    tally('kokuen', 'radius', radOk, el, `${rad}px ${r.width.toFixed(0)}x${r.height.toFixed(0)}`);
    // K: type size on scale
    const fs = px(cs.fontSize);
    if ((el.innerText || el.value || el.placeholder || '').trim()) tally('kokuen', 'type-scale', TYPE.some(t => Math.abs(t - fs) < 0.3), el, `${fs}px`);
    // K: padding on spacing scale (border included)
    // a switch's padding places its label past the fixed 42px track (COMPONENTS.md toggle)
    if (!longForm(el) && !el.matches('[role=switch]')) {
      let sides = ['Top', 'Right', 'Bottom', 'Left'].map(s => px(cs['padding' + s]) + px(cs['border' + s + 'Width']));
      // a 44px entry centers one line of text; its vertical padding is derived, not chosen
      const entry44 = isText(el) && Math.abs(r.height - 44) < 1;
      const bad = sides.filter((v, k) => !(entry44 && k % 2 === 0) && !onScale(v) && !onScale(v - 1) && !onScale(v - 2));
      tally('kokuen', 'padding-scale', bad.length === 0, el, sides.join('/'));
      if (/flex|grid/.test(cs.display) && cs.columnGap !== 'normal') tally('kokuen', 'gap-scale', onScale(px(cs.columnGap)), el, cs.columnGap);
    }
    // K: no bloom at rest (decision 0040): a shadow is an inset edge, a tight lift (blur <= 3px)
    // or a flat ring; anything softer is the glow the design law bans
    const shadows = cs.boxShadow === 'none' ? [] : cs.boxShadow.split(/,(?![^(]*\))/);
    const tight = s => {
      if (/inset/.test(s)) return true;
      const [x = 0, y = 0, blur = 0] = (s.replace(/rgba?\([^)]*\)|#[0-9a-f]+/gi, '').match(/-?[\d.]+px/g) || []).map(parseFloat);
      return blur <= 3 && Math.abs(x) <= 1 && Math.abs(y) <= 2;
    };
    tally('kokuen', 'no-shadow', shadows.every(tight), el, cs.boxShadow);
    // K: no native choice controls
    if (el.tagName === 'SELECT' || (el.tagName === 'INPUT' && /checkbox|radio/.test(el.type)))
      tally('kokuen', 'no-native-choice', cs.appearance === 'none' && cs.opacity !== '1' ? true : false, el, el.tagName + ' ' + el.type);
    // W: accessible name
    tally('wcag', '4.1.2-name', !!nm, el, '');
    // V: icon-only buttons named
    const txt = (el.innerText || '').trim();
    if (el.matches('button,[role=button]') && !txt && el.querySelector('svg,img,i,span')) tally('vercel', 'icon-button-label', !!nm, el, '');
    // V: no transition: all
    const tp = cs.transitionProperty.split(',').map(s => s.trim());
    const td = cs.transitionDuration.split(',').map(px);
    tally('vercel', 'no-transition-all', !tp.some((p, i) => p === 'all' && (td[i] ?? td[0]) > 0.01), el, cs.transitionProperty);
    // V: touch-action manipulation on buttons
    if (el.matches('button,[role=button]')) tally('vercel', 'touch-action', /manipulation|none|pan/.test(cs.touchAction), el, cs.touchAction);
    // K: contents centered and on one line
    if (el.matches('button,[role=button],[role=tab],[role=menuitem],a') && !longForm(el)) {
      const kids = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let n; while ((n = walker.nextNode())) { if (n.textContent.trim()) { const rg = document.createRange(); rg.selectNodeContents(n); const rects = [...rg.getClientRects()].filter(x => x.width > 0); if (rects.length) kids.push({ t: 'text', rects, node: n.parentElement }); } }
      // icons are aria-hidden on purpose, so test their box, not their a11y visibility
      el.querySelectorAll('svg, img').forEach(s => { const sr = s.getBoundingClientRect(); if (sr.width > 0 && getComputedStyle(s).display !== 'none' && getComputedStyle(s).visibility !== 'hidden') kids.push({ t: 'icon', rects: [sr], node: s }); });
      if (kids.length) {
        const top = Math.min(...kids.flatMap(k => k.rects.map(x => x.top)));
        const bot = Math.max(...kids.flatMap(k => k.rects.map(x => x.bottom)));
        const ct = r.top + px(cs.borderTopWidth) + px(cs.paddingTop), cb = r.bottom - px(cs.borderBottomWidth) - px(cs.paddingBottom);
        const lines = new Set(kids.filter(k => k.t === 'text').flatMap(k => k.rects.map(x => Math.round(x.top / 4)))).size;
        const singleLine = !el.matches('[role=option],[role=menuitem]') ? lines <= 1 : true;
        if (singleLine && cb - ct > 0 && r.height <= 64) {
          const off = ((top + bot) / 2) - ((ct + cb) / 2);
          tally('kokuen', 'v-center', Math.abs(off) <= 1.5, el, `off ${off.toFixed(1)}px`);
        }
        // the first text run is the label; it must not wrap (a hint below it may)
        const label = kids.find(k => k.t === 'text');
        if (el.matches('button,[role=button],[role=tab],[role=menuitem],[role=menuitemradio]') && label) {
          const wraps = new Set(label.rects.map(x => Math.round(x.top / 4))).size > 1;
          tally('kokuen', 'one-line-label', !wraps, el, `"${label.node.textContent.trim().slice(0, 40)}"`);
        }
        // icon + label share a center line
        const icon = kids.find(k => k.t === 'icon'), text = kids.find(k => k.t === 'text');
        if (icon && text && lines <= 1) {
          const ic = (icon.rects[0].top + icon.rects[0].bottom) / 2;
          const tr = text.rects[0]; const tc = (tr.top + tr.bottom) / 2;
          tally('kokuen', 'icon-text-center', Math.abs(ic - tc) <= 1.5, el, `off ${(ic - tc).toFixed(1)}px`);
        }
        // centered labels are centered horizontally
        if (cs.justifyContent === 'center' || (cs.textAlign === 'center' && !/flex|grid/.test(cs.display))) {
          const left = Math.min(...kids.flatMap(k => k.rects.map(x => x.left))), right = Math.max(...kids.flatMap(k => k.rects.map(x => x.right)));
          const cl = r.left + px(cs.borderLeftWidth) + px(cs.paddingLeft), cr = r.right - px(cs.borderRightWidth) - px(cs.paddingRight);
          if (right - left < cr - cl) tally('kokuen', 'h-center', Math.abs((left + right) / 2 - (cl + cr) / 2) <= 1.5, el, `off ${((left + right) / 2 - (cl + cr) / 2).toFixed(1)}px`);
        }
      }
      // clipped text without an ellipsis
      if (txt && el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== 'ellipsis' && cs.overflow !== 'visible')
        tally('kokuen', 'no-clipped-label', false, el, `"${txt.slice(0, 30)}"`);
    }
    // W: text contrast inside controls
    if (txt && !disabled) {
      const fg = parse(cs.color); const bg = effBg(el);
      if (fg) {
        const c = ratio(over(fg, bg), bg);
        const large = fs >= 24 || (fs >= 18.66 && +cs.fontWeight >= 700);
        tally('wcag', '1.4.3-contrast', c >= (large ? 3 : 4.5) - 0.01, el, `${c.toFixed(2)}:1`);
      }
    }
  }

  // K: one filled primary action per surface (decision 0040); raised secondary actions are fine
  const inOverlay = el => !opts.scope && el.closest('[role=dialog],[role=alertdialog],[role=menu],[role=listbox],.modal-overlay,[popover]');
  const contained = el => {
    const cs = getComputedStyle(el);
    const bg = parse(cs.backgroundColor);
    const behind = effBg(el.parentElement || document.body);
    const fill = bg && bg.a > 0.05 && ratio(over(bg, behind), behind) > 1.08;
    const line = ['Top', 'Right', 'Bottom', 'Left'].filter(s => px(cs['border' + s + 'Width']) >= 1 && (() => { const c = parse(cs['border' + s + 'Color']); return c && c.a > 0.05 && ratio(over(c, behind), behind) > 1.25; })()).length >= 3;
    return fill || line;
  };
  const accent = parse(getComputedStyle(document.documentElement).getPropertyValue('--k-accent').trim().replace(/^#(..)(..)(..)$/, (m, a, b, c) => `rgb(${parseInt(a, 16)}, ${parseInt(b, 16)}, ${parseInt(c, 16)})`));
  const filledPrimary = el => {
    const bg = parse(getComputedStyle(el).backgroundColor);
    return !!(bg && accent && bg.a > 0.9 && Math.abs(bg.r - accent.r) + Math.abs(bg.g - accent.g) + Math.abs(bg.b - accent.b) < 60);
  };
  const choice = el => el.matches('[role=tab],[role=switch],[role=radio],[role=checkbox],[role^=menuitem],[role=option],[role=combobox],[aria-pressed],[aria-checked],[aria-selected],[aria-current],[aria-expanded="true"],.active,.custom-select,.date-input,[aria-haspopup=listbox],.s-section-trigger') || el.closest('[role=radiogroup],[role=tablist],[role=group][aria-label],[role=listbox],[role=menu],[role=grid],[role=row],table,.s-toggle-row');
  // settings keeps a resting line on every action (decision 0031, settings outline pass)
  const boxed = ctrls.filter(el => el.matches('button,[role=button],a') && (el.innerText || '').trim() && !choice(el) && !inOverlay(el) && !el.matches('.send-btn') && !el.closest('#settings-modal') && contained(el) && filledPrimary(el));
  // a labelled region or dialog is its own surface with its own primary (COMPONENTS.md side panel)
  const surfaceOf = el => el.closest('[role=dialog],[role=alertdialog],[role=region][aria-label],[role=region][aria-labelledby]') || document.body;
  const bySurface = new Map();
  boxed.forEach(el => { const k = surfaceOf(el); if (!bySurface.has(k)) bySurface.set(k, []); bySurface.get(k).push(el); });
  for (const group of bySurface.values()) group.forEach(el => tally('kokuen', 'one-contained-action', group.length <= 1, el, `${group.length} boxed: ` + group.slice(0, 4).map(b => '"' + (b.innerText || '').trim().slice(0, 18) + '"').join(', ')));
  if (!boxed.length) tally('kokuen', 'one-contained-action', true, null, '');
  // K: selected tabs use tone and type, no tile and no underline (COMPONENTS.md tabs, decision 0026)
  ctrls.filter(el => el.matches('[role=tab][aria-selected=true], [aria-current]:not([aria-current=false]), .s-nav-item.active')).forEach(el => {
    const cs = getComputedStyle(el);
    const behind = effBg(el.parentElement || document.body);
    const bg = parse(cs.backgroundColor);
    const tile = bg && bg.a > 0.05 && ratio(over(bg, behind), behind) > 1.08;
    // a full strong border is a box (settings nav), not an underline
    const sides = ['Top', 'Right', 'Bottom', 'Left'].filter(k => px(cs['border' + k + 'Width']) >= 1 && (() => { const c = parse(cs['border' + k + 'Color']); return c && c.a > 0.05 && ratio(over(c, behind), behind) > 1.25; })()).length;
    const under = cs.textDecorationLine.includes('underline') || (sides < 4 && px(cs.borderBottomWidth) >= 1 && (() => { const c = parse(cs.borderBottomColor); return c && c.a > 0.05 && ratio(over(c, behind), behind) > 1.25; })()) || /inset 0px -/.test(cs.boxShadow);
    // rows may use the raised surface (data row contract); neither tabs nor rows add an underline
    if (el.matches('[role=tab]')) tally('kokuen', 'selected-tab-plain', !tile && !under, el, `${tile ? 'tile ' : ''}${under ? 'underline' : ''}`);
    else tally('kokuen', 'selected-row-no-underline', !under, el, 'underline');
  });

  // sibling rows: controls in the same flex row share a center line and, for buttons, a height
  const rows = new Map();
  for (const el of ctrls) {
    const p = el.parentElement; if (!p) continue;
    const pcs = getComputedStyle(p);
    if (!/flex/.test(pcs.display) || /column/.test(pcs.flexDirection)) continue;
    if (!rows.has(p)) rows.set(p, []); rows.get(p).push(el);
  }
  for (const [p, els] of rows) {
    if (els.length < 2) continue;
    const pcs = getComputedStyle(p);
    const rects = els.map(e => ({ e, r: e.getBoundingClientRect() }));
    // only items on the same visual line
    const byLine = new Map();
    rects.forEach(x => { const k = Math.round(x.r.top / 20); if (!byLine.has(k)) byLine.set(k, []); byLine.get(k).push(x); });
    for (const line of byLine.values()) {
      if (line.length < 2) continue;
      const centers = line.map(x => (x.r.top + x.r.bottom) / 2);
      const spread = Math.max(...centers) - Math.min(...centers);
      if (pcs.alignItems !== 'baseline') tally('kokuen', 'row-center', spread <= 1.5, p, `spread ${spread.toFixed(1)}px: ` + line.map(x => sig(x.e).split(' ').pop()).join(', '));
      const btns = line.filter(x => x.e.matches('button,[role=button]') && !longForm(x.e));
      if (btns.length >= 2) {
        const hs = btns.map(x => Math.round(x.r.height));
        tally('kokuen', 'row-height', Math.max(...hs) - Math.min(...hs) <= 1, p, hs.join('/') + ': ' + btns.map(x => sig(x.e).split(' ').pop()).join(', '));
      }
    }
  }

  // V: three dots instead of an ellipsis; em dash in ui copy (taste lens)
  if (!opts.scope) {
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = tw.nextNode())) {
      const t = n.textContent; if (!t.trim()) continue;
      const pe = n.parentElement; if (!pe || pe.closest('script,style,code,pre,textarea,[contenteditable]') || !visible(pe)) continue;
      if (/\w\.\.\.(\s|$)/.test(t)) tally('vercel', 'ellipsis-char', false, pe, t.trim().slice(0, 40));
      // meter glyphs (block and box drawing) are graphics, not text (decision 0010)
      if (/^[\s\u2500-\u259f\[\]|]+$/.test(t)) continue;
      // W: body text contrast
      const cs = getComputedStyle(pe); const fg = parse(cs.color); if (!fg) continue;
      if (pe.closest('button,[role=button],a,input,textarea,[aria-disabled=true],:disabled')) continue;
      const bg = effBg(pe); let op = 1, q = pe; while (q) { op *= +getComputedStyle(q).opacity; q = q.parentElement; }
      const c = ratio(over({ ...fg, a: fg.a * op }, bg), bg);
      const fs = px(cs.fontSize); const large = fs >= 24 || (fs >= 18.66 && +cs.fontWeight >= 700);
      tally('wcag', '1.4.3-contrast', c >= (large ? 3 : 4.5) - 0.01, pe, `${c.toFixed(2)}:1 "${t.trim().slice(0, 24)}"`);
      tally('kokuen', 'type-floor', fs >= 11.9, pe, `${fs}px "${t.trim().slice(0, 24)}"`);
    }
    // V: pointer cursor on a non-control
    document.querySelectorAll('div, span, li, td, img, svg').forEach(el => {
      if (!visible(el)) return;
      if (getComputedStyle(el).cursor !== 'pointer') return;
      if (el.closest(CTRL + ', label, [role=row], [role=gridcell], [role=treeitem], [role=link], [tabindex]')) return;
      if (el.parentElement && getComputedStyle(el.parentElement).cursor === 'pointer') return;
      // a clickable card that holds a real button for the same action (keyboard path) is fine
      if (el.querySelector('button, a[href]')) return;
      tally('vercel', 'clickable-non-control', false, el, '');
    });
    document.querySelectorAll('[role=row],[role=gridcell],[role=treeitem]').forEach(el => {
      if (visible(el) && getComputedStyle(el).cursor === 'pointer') tally('vercel', 'clickable-non-control', el.hasAttribute('tabindex') || !!el.querySelector('button,a,[tabindex]'), el, 'not focusable');  // roving tabindex: -1 cells are reachable by arrows
    });
    // K/W: page overflow
    const ow = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
    tally('kokuen', 'no-page-overflow', ow <= vw + 1, document.body, `${ow} > ${vw}`);
    tally('wcag', '1.4.10-reflow', ow <= vw + 1, document.body, `${ow} > ${vw}`);
    // K: header height
    const hdr = [...document.querySelectorAll('.app-header, .kokuen-header, [data-kokuen-header], .topbar, .local-header')].filter(visible);
    hdr.forEach(h => tally('kokuen', 'header-52', Math.abs(h.getBoundingClientRect().height - 52) < 1 || Math.abs(h.getBoundingClientRect().height - 44) < 1, h, h.getBoundingClientRect().height.toFixed(1)));
    // V: zoom not locked, color-scheme and theme-color match
    const vp = document.querySelector('meta[name=viewport]')?.content || '';
    tally('vercel', 'no-zoom-lock', !/user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b/.test(vp), document.body, vp);
    const dark = lum(pageBg) < 0.2;
    const scheme = getComputedStyle(document.documentElement).colorScheme;
    tally('vercel', 'color-scheme', dark ? /dark/.test(scheme) : !/^dark$/.test(scheme.trim()), document.documentElement, scheme);
    const tcm = [...document.querySelectorAll('meta[name=theme-color]')].find(m => !m.media || matchMedia(m.media).matches);
    if (tcm) { const t = tcm.content.trim().toLowerCase(); const h = '#' + [pageBg.r, pageBg.g, pageBg.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join(''); tally('vercel', 'theme-color', t === h, document.documentElement, `${t} vs ${h}`); }
    // V: images carry dimensions
    document.querySelectorAll('img').forEach(img => { if (visible(img)) tally('vercel', 'img-dimensions', img.hasAttribute('width') && img.hasAttribute('height') || /px|%/.test(img.style.width + img.style.height) || getComputedStyle(img).aspectRatio !== 'auto', img, img.src.slice(-40)); });
  }
  return out;
}
"""

FOCUS = r"""
(opts) => {
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && !el.closest('[inert],[aria-hidden="true"]'); };
  const root = opts.scope ? document.querySelector(opts.scope) : document;
  const sel = 'button, [role=button], [role=tab], [role=menuitem], [role=option], [role=switch], [role=combobox], textarea, input:not([type=hidden]):not([type=file]), a[href], summary, [tabindex="0"]';
  const els = [...root.querySelectorAll(sel)].filter(e => vis(e) && !e.disabled && e.tabIndex >= 0).slice(0, opts.limit || 400);
  window.__auditFocus = els;
  return els.length;
}
"""

FOCUS_ONE = r"""
(i) => {
  const el = window.__auditFocus[i];
  if (!el || !el.isConnected) return null;
  // a switch rings its track (::before), not its 44px target, so the pseudo element counts too
  const ol = c => c.outlineStyle !== 'none' && parseFloat(c.outlineWidth) > 0 ? c.outlineStyle + ' ' + c.outlineWidth + ' ' + c.outlineColor : '';
  const snap = e => { const c = getComputedStyle(e); return { o: ol(c), po: ol(getComputedStyle(e, '::before')), s: c.boxShadow, b: [c.borderTopColor, c.borderRightColor, c.borderBottomColor, c.borderLeftColor].join('|'), bw: c.borderBottomWidth, bg: c.backgroundColor, col: c.color, td: c.textDecorationLine }; };
  const chain = []; let p = el; for (let k = 0; k < 5 && p; k++) { chain.push(p); p = p.parentElement; }
  // overlays focus their first control on open; measure rest from an unfocused state
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  const before = chain.map(snap);
  el.focus({ preventScroll: false });
  if (document.activeElement !== el) return { skipped: true };
  const after = chain.map(snap);
  const diff = (a, b) => Object.keys(a).filter(k => a[k] !== b[k]);
  const own = diff(before[0], after[0]);
  const anc = chain.slice(1).map((e, k) => ({ k, d: diff(before[k + 1], after[k + 1]) })).filter(x => x.d.length);
  const isText = el.matches('textarea, input:not([type]), input[type=text], input[type=search], input[type=email], input[type=url], input[type=tel], input[type=password], input[type=number]');
  const r = el.getBoundingClientRect();
  const cx = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1), cy = Math.min(Math.max(r.top + Math.min(r.height / 2, 20), 1), innerHeight - 1);
  const hit = document.elementFromPoint(cx, cy);
  const obscured = !!hit && !(el === hit || el.contains(hit) || hit.contains(el) || hit.closest('label') === el.closest('label'));
  // describe the focus look of the field itself
  const c = getComputedStyle(el);
  const sh = c.boxShadow === 'none' ? [] : c.boxShadow.split(/,(?![^(]*\))/).map(s => s.trim());
  const ring = sh.some(s => { const n = (s.match(/-?[\d.]+px/g) || []).map(parseFloat); if (!/inset/.test(s)) return true; return n.length >= 4 ? (n[0] === 0 && n[1] === 0 && n[3] > 0) : false; });
  const outline = after[0].o || after[0].po;
  const borderBox = before[0].b !== after[0].b && new Set(after[0].b.split('|')).size === 1 && parseFloat(c.borderTopWidth) > 0 && parseFloat(c.borderLeftWidth) > 0;
  // outline contrast against what sits behind it
  let oc = null;
  if (outline) {
    const parse = s => { const m = (s || '').match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p[3] == null ? 1 : p[3] }; };
    const lum = q => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(q.r) + 0.7152 * f(q.g) + 0.0722 * f(q.b); };
    let n = el.parentElement, bg = null; while (n) { const x = parse(getComputedStyle(n).backgroundColor); if (x && x.a > 0.9) { bg = x; break; } n = n.parentElement; }
    bg = bg || parse(getComputedStyle(document.body).backgroundColor);
    const fg = parse(after[0].o ? c.outlineColor : getComputedStyle(el, '::before').outlineColor);
    if (fg && bg) { const a = lum(fg), b = lum(bg); oc = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); }
  }
  const s = (e => { let t = e.tagName.toLowerCase(); if (e.id) return t + '#' + e.id; const cl = [...e.classList].slice(0, 2).join('.'); if (cl) t += '.' + cl; let p = e.parentElement, h = 0; while (p && !p.id && h < 6) { p = p.parentElement; h++; } return (p && p.id ? '#' + p.id + ' ' : '') + t; })(el);
  el.blur();
  return { sig: s, isText, own, anc: anc.map(a => a.k + ':' + a.d.join('+')), ring, outline, borderBox, obscured, oc, entry: !!el.closest('[data-kokuen-entry]') || el.hasAttribute('data-kokuen-entry') };
}
"""

OVERLAY = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 2 && r.height > 2 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0; };
  const q = '[role=menu], [role=listbox], [role=dialog], [role=alertdialog], [role=tooltip], [popover], .kokuen-menu, .menu, .popover, .sheet, .modal-overlay, .context-menu, .dropdown';
  return [...document.querySelectorAll(q)].filter(vis).map((e, i) => { if (!e.dataset.auditOverlay) e.dataset.auditOverlay = 'o' + Math.random().toString(36).slice(2, 8); return e.dataset.auditOverlay; });
}
"""

OVERLAY_CHECK = r"""
(id) => {
  const el = document.querySelector('[data-audit-overlay="' + id + '"]');
  if (!el) return null;
  const out = [];
  const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
  const vw = document.documentElement.clientWidth, vh = innerHeight;
  const full = r.width >= vw - 1 && r.height >= vh - 1;
  out.push(['kokuen', 'overlay-in-viewport', r.left >= -0.5 && r.top >= -0.5 && r.right <= vw + 0.5 && r.bottom <= vh + 0.5, `${r.left.toFixed(0)},${r.top.toFixed(0)} ${r.width.toFixed(0)}x${r.height.toFixed(0)} in ${vw}x${vh}`]);
  if (!full) {
    const rad = parseFloat(cs.borderTopLeftRadius) || 0;
    out.push(['kokuen', 'overlay-radius', [0, 8, 12, 16].some(v => Math.abs(rad - v) < 0.3), rad + 'px']);
  }
  const items = [...el.querySelectorAll('[role=menuitem],[role=menuitemradio],[role=menuitemcheckbox],[role=option]')].filter(x => x.getBoundingClientRect().height > 0);
  if (items.length >= 2) {
    const lefts = items.map(x => Math.round(x.getBoundingClientRect().left)); const widths = items.map(x => Math.round(x.getBoundingClientRect().width));
    out.push(['kokuen', 'menu-items-aligned', Math.max(...lefts) - Math.min(...lefts) <= 1 && Math.max(...widths) - Math.min(...widths) <= 1, `lefts ${[...new Set(lefts)].join('/')} widths ${[...new Set(widths)].join('/')}`]);
    // text starts on one column
    const starts = items.map(x => { const w = document.createTreeWalker(x, NodeFilter.SHOW_TEXT); let n; while ((n = w.nextNode())) if (n.textContent.trim()) { const g = document.createRange(); g.selectNodeContents(n); return Math.round(g.getBoundingClientRect().left); } return null; }).filter(v => v != null);
    if (starts.length >= 2) out.push(['kokuen', 'menu-text-column', Math.max(...starts) - Math.min(...starts) <= 1 || items.some(x => x.querySelector('svg')), `starts ${[...new Set(starts)].join('/')}`]);
  }
  const scroller = [el, ...el.querySelectorAll('*')].find(x => { const c = getComputedStyle(x); return /auto|scroll/.test(c.overflowY) && x.scrollHeight > x.clientHeight + 1; });
  if (scroller && /dialog|sheet|modal/.test((el.getAttribute('role') || '') + el.className)) out.push(['vercel', 'overscroll-contain', /contain|none/.test(getComputedStyle(scroller).overscrollBehaviorY), getComputedStyle(scroller).overscrollBehaviorY]);
  return out;
}
"""

BUTTONS = r"""
() => {
  document.querySelectorAll('[data-audit-btn]').forEach(e => e.removeAttribute('data-audit-btn'));
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0 && !el.closest('[inert],[aria-hidden="true"]') && r.bottom > 0 && r.top < innerHeight * 3; };
  // skip what a pointer cannot reach: covered by a modal or scrim
  const reachable = e => { const r = e.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2; if (y < 0 || y > innerHeight || x < 0 || x > innerWidth) return true; const h = document.elementFromPoint(x, y); return !!h && (h === e || e.contains(h) || h.contains(e)); };
  const els = [...document.querySelectorAll('button, [role=button], [role=tab], summary')].filter(e => vis(e) && !e.disabled && e.getAttribute('aria-disabled') !== 'true' && reachable(e));
  return els.map((e, i) => { e.dataset.auditBtn = String(i); const nm = (e.getAttribute('aria-label') || e.innerText || e.title || '').trim().replace(/\s+/g, ' ').slice(0, 60); let p = e.parentElement, h = 0; while (p && !p.id && h < 6) { p = p.parentElement; h++; } return { i, name: nm, key: (p && p.id ? '#' + p.id + ' ' : '') + (e.id ? '#' + e.id : e.tagName.toLowerCase() + '.' + [...e.classList].slice(0, 2).join('.')) + ' ' + nm }; });
}
"""

# position in the page, scroll undone, so a scroll that follows a click is not a shift
DOC_BOX = r"""el => { const r = el.getBoundingClientRect(); let x = r.x + scrollX, y = r.y + scrollY;
  for (let p = el.parentElement; p; p = p.parentElement) { x += p.scrollLeft; y += p.scrollTop; }
  return { x, y }; }"""

VISIBLE_COUNT = r"""() => [...document.body.querySelectorAll('*')].filter(e => e.getClientRects().length).length"""

BUSY_STATUS = r"""
() => {
  const probe = document.createElement('span'); probe.style.color = 'var(--error)'; document.body.append(probe);
  const danger = getComputedStyle(probe).color; probe.remove();
  return [...document.querySelectorAll('[role=status],[aria-live]')].filter(e => {
    const t = (e.textContent || '').trim(); const r = e.getBoundingClientRect();
    return r.width > 0 && /…$|\.\.\.$/.test(t);
  }).map(e => ({ ok: getComputedStyle(e).color !== danger, detail: `"${e.textContent.trim().slice(0, 40)}" in ${getComputedStyle(e).color}` }));
}
"""

# words a person should never read: what the browser throws, and values that never got filled
# in. user content (code, fields, editors) is left out
RAW_TEXT = r"""
() => {
  const raw = /failed to fetch|\bload failed\b|networkerror|push service error|unexpected token|not valid json|\b(TypeError|ReferenceError|SyntaxError|DOMException|NotAllowedError)\b|\bundefined\b|\bNaN\b|\[object \w+\]|Invalid Date|Traceback \(most recent/;
  const skip = 'pre, code, textarea, input, [contenteditable], .cm-editor, script, style, noscript';
  const out = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const t = n.nodeValue; if (!t || !raw.test(t)) continue;
    const el = n.parentElement; if (!el || el.closest(skip)) continue;
    if (!el.getClientRects().length || getComputedStyle(el).visibility === 'hidden') continue;
    out.push(t.trim().slice(0, 120));
  }
  return [...new Set(out)].slice(0, 5);
}
"""


TILE_INSET = r"""
(i) => {
  const e = document.querySelector('[data-audit-btn="' + i + '"]'); if (!e) return null;
  const c = getComputedStyle(e);
  const parse = s => { const m = (s || '').match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(parseFloat); return p[3] == null ? 1 : p[3]; };
  const shadowRing = /inset/.test(c.boxShadow) && c.boxShadow !== 'none';
  if (!((parse(c.backgroundColor) || 0) > 0.05 || shadowRing)) return null;  // no tile showing
  const r = e.getBoundingClientRect();
  const kids = [];
  const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) if (n.textContent.trim()) { const g = document.createRange(); g.selectNodeContents(n); for (const q of g.getClientRects()) if (q.width) kids.push(q); }
  e.querySelectorAll('svg,img').forEach(s => { const q = s.getBoundingClientRect(); if (q.width) kids.push(q); });
  if (!kids.length || r.width < 1) return null;
  const left = Math.min(...kids.map(k => k.left)) - r.left, right = r.right - Math.max(...kids.map(k => k.right));
  const top = Math.min(...kids.map(k => k.top)) - r.top, bottom = r.bottom - Math.max(...kids.map(k => k.bottom));
  const icon = Math.abs(r.width - r.height) < 2;  // square icon targets center their mark
  const ok = icon || (left >= 6 && right >= 6 && top >= 2 && bottom >= 2);
  return { ok, detail: `inset l${left.toFixed(0)} r${right.toFixed(0)} t${top.toFixed(0)} b${bottom.toFixed(0)}` };
}
"""

STYLE_SNAP = r"""
(i) => {
  const e = document.querySelector('[data-audit-btn="' + i + '"]'); if (!e) return null;
  const one = x => { const c = getComputedStyle(x); return [c.backgroundColor, c.color, c.borderColor, c.opacity, c.textDecorationLine, c.textDecorationThickness, c.boxShadow, c.outlineStyle, c.fill, c.stroke].join('|'); };
  // hover may restyle the label or icon instead of the box
  return [e, ...[...e.querySelectorAll('*')].slice(0, 8)].map(one).join('#');
}
"""


class Audit:
    def __init__(self) -> None:
        self.checks: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        self.fails: list[dict] = []
        self.clicked = 0
        self.skipped: list[str] = []
        self.errors: list[str] = []

    def add(self, rubric, check, ok, sig, detail, where) -> None:
        k = f"{rubric}:{check}"
        self.checks[k][0 if ok else 1] += 1
        if not ok:
            self.fails.append(dict(rubric=rubric, check=check, sig=sig, detail=detail, **where))

    def merge(self, res, where) -> None:
        for k, (p, f) in res["checks"].items():
            self.checks[k][0] += p
            self.checks[k][1] += f
        for f in res["fails"]:
            self.fails.append({**f, **where})

    def scores(self) -> dict:
        out = {}
        for rubric in ("kokuen", "wcag", "vercel"):
            p = sum(v[0] for k, v in self.checks.items() if k.startswith(rubric + ":"))
            f = sum(v[1] for k, v in self.checks.items() if k.startswith(rubric + ":"))
            out[rubric] = {"passed": p, "failed": f, "score": round(100 * p / max(p + f, 1), 2)}
        return out


def goto(page, base, route) -> None:
    if route == "setup":
        page.goto(base + "/", wait_until="domcontentloaded")
        page.wait_for_function("typeof window._openSetupWizard === 'function'")
        page.evaluate("window._openSetupWizard()")
        page.locator("#setup-wizard").wait_for(state="visible")
    elif route == "settings":
        page.goto(base + "/", wait_until="domcontentloaded")
        page.locator("#today-settings").wait_for(state="visible")
        page.locator("#today-settings").click()
        page.locator("#settings-modal").wait_for(state="visible")
    else:
        page.goto(f"{base}/?view={route}", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=2500)
    except PWError:
        pass
    page.wait_for_timeout(250)


def grid_pass(page, audit, where) -> None:
    # every interactive grid moves focus with arrow keys (WCAG 2.1.1)
    grids = page.evaluate(
        """() => [...document.querySelectorAll('[role=grid]')].filter(g => g.getBoundingClientRect().width > 0)
          .map((g, i) => { g.dataset.auditGrid = String(i); return i; })"""
    )
    for i in grids:
        cell = page.locator(f'[data-audit-grid="{i}"] [role=gridcell][tabindex="0"]').first
        if not cell.count():
            audit.add("wcag", "2.1.1-keyboard-grid", False, f"grid {i}", "no tab stop", where)
            continue
        cell.focus()
        before = page.evaluate(
            "() => document.activeElement.id || document.activeElement.dataset.date || ''"
        )
        for key in ("ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"):
            page.keyboard.press(key)
            after = page.evaluate(
                "() => [document.activeElement.getAttribute('role'), document.activeElement.id || document.activeElement.dataset.date || '']"
            )
            if after[0] == "gridcell" and after[1] != before:
                break
        ok = after[0] == "gridcell" and after[1] != before
        audit.add("wcag", "2.1.1-keyboard-grid", ok, f"grid {i}", f"{before} -> {after}", where)


def focus_pass(page, audit, where, scope=None) -> None:
    n = page.evaluate(FOCUS, {"scope": scope, "limit": 300})
    page.keyboard.press("Shift")  # keyboard modality, so :focus-visible matches
    for i in range(n):
        try:
            r = page.evaluate(FOCUS_ONE, i)
        except PWError:
            continue
        if not r or r.get("skipped"):
            continue
        visible_change = bool(r["own"]) or bool(r["anc"])
        audit.add(
            "wcag", "2.4.7-focus-visible", visible_change, r["sig"], "no visible change", where
        )
        audit.add("wcag", "2.4.11-focus-not-hidden", not r["obscured"], r["sig"], "covered", where)
        if r["oc"] is not None:
            audit.add(
                "wcag", "1.4.11-focus-contrast", r["oc"] >= 3, r["sig"], f"{r['oc']:.2f}:1", where
            )
        if r["isText"]:
            # the text field rule (decision 0045): its own 1px edge brightens; no outline
            box = bool(r["outline"])
            audit.add(
                "kokuen",
                "field-focus-no-box",
                not box,
                r["sig"],
                f"outline={r['outline']} ring={r['ring']} borderbox={r['borderBox']}",
                where,
            )
            double = bool(r["own"]) and bool(r["anc"])
            audit.add(
                "kokuen",
                "field-focus-single-owner",
                not double,
                r["sig"],
                f"own={r['own']} anc={r['anc']}",
                where,
            )


# rendered spacing, not token values (owner, 2026-10-27: the old audit scored 100% while buttons
# touched row dividers, a hint sat flush on its field and header buttons hugged the top edge)
SPACING = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !el.closest('[hidden],[inert],[aria-hidden="true"]'); };
  const sig = el => (el.id ? '#' + el.id : el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '')).slice(0, 80);
  const out = [];
  const controls = [...document.querySelectorAll('button, a.btn, [role="button"], input:not([type="hidden"]), textarea, [role="combobox"]')].filter(vis);
  // a control inside a row whose bottom divider it touches
  for (const el of controls) {
    let row = el.parentElement;
    for (let i = 0; row && i < 3; i++, row = row.parentElement) {
      const s = getComputedStyle(row);
      if (parseFloat(s.borderBottomWidth) >= 1 && s.borderBottomStyle !== 'none' && !['INPUT', 'TEXTAREA'].includes(row.tagName)) {
        const gap = row.getBoundingClientRect().bottom - parseFloat(s.borderBottomWidth) - el.getBoundingClientRect().bottom;
        const tight = row.getBoundingClientRect().height <= el.getBoundingClientRect().height + 1;
        if (gap >= 0 && gap < 2 && tight)
          out.push(['spacing-control-on-divider', sig(el) + ' in ' + sig(row), Math.round(gap) + 'px']);
        break;
      }
    }
  }
  // a hint or label line flush on the field under it
  for (const field of controls.filter(el => ['INPUT', 'TEXTAREA'].includes(el.tagName))) {
    const prev = field.previousElementSibling || field.parentElement?.previousElementSibling;
    if (!prev || !vis(prev) || prev.matches('label, .setup-field, .s-field')) continue;
    if (!/^(P|SMALL|SPAN|DIV)$/.test(prev.tagName) || !(prev.textContent || '').trim() || prev.querySelector('button, a, input')) continue;
    // an underline-only field has no top edge for the hint to touch
    const fs = getComputedStyle(field);
    const edge = parseFloat(fs.borderTopWidth) > 0 || /inset/.test(fs.boxShadow) || !/rgba\(0, 0, 0, 0\)|transparent/.test(fs.backgroundColor);
    if (!edge) continue;
    const gap = field.getBoundingClientRect().top - prev.getBoundingClientRect().bottom;
    if (gap >= 0 && gap < 4) out.push(['spacing-hint-on-field', sig(prev) + ' over ' + sig(field), Math.round(gap) + 'px']);
  }
  // a header control pressed against the top of the page
  for (const el of controls) {
    const r = el.getBoundingClientRect();
    if (r.top >= 0 && r.top < 2 && r.height < 52 && el.closest('header, [class*="head"]')) {
      const fill = getComputedStyle(el).backgroundColor;
      if (fill && !/rgba\(0, 0, 0, 0\)|transparent/.test(fill)) out.push(['spacing-control-on-edge', sig(el), Math.round(r.top) + 'px']);
    }
  }
  return out.slice(0, 40);
}
"""


def spacing_pass(page, audit, where) -> None:
    found = page.evaluate(SPACING)
    for check, sig, detail in found:
        audit.add("kokuen", check, False, sig, detail, where)
    if not found:
        audit.add("kokuen", "spacing-rendered", True, "page", "", where)


def raw_text_pass(page, audit, sig, where) -> None:
    found = page.evaluate(RAW_TEXT)
    audit.add("kokuen", "plain-words", not found, sig, " | ".join(found), where)


def click_pass(page, base, route, audit, where, shots: Path, tag: str) -> None:
    buttons = page.evaluate(BUTTONS)
    seen_keys = set()
    url0 = page.url
    for b in buttons:
        if b["key"] in seen_keys:
            continue
        seen_keys.add(b["key"])
        if SKIP_NAME.search(b["name"] or ""):
            audit.skipped.append(f"{route}: {b['name']}")
            continue
        # buttons are re-tagged after every reset, so look up by key
        items = page.evaluate(BUTTONS)
        match = next((x for x in items if x["key"] == b["key"]), None)
        if not match:
            continue
        loc = page.locator(f'[data-audit-btn="{match["i"]}"]')
        try:
            before_overlays = set(page.evaluate(OVERLAY))
            if not where["mobile"]:
                page.mouse.move(
                    1, page.viewport_size["height"] // 2
                )  # leave any earlier hover first
                page.wait_for_timeout(60)
                rest = page.evaluate(STYLE_SNAP, match["i"])
                loc.hover(timeout=1500)
                page.wait_for_timeout(120)
                hov = page.evaluate(STYLE_SNAP, match["i"])
                # an already selected choice has nothing new to offer on hover
                selected = page.evaluate(
                    """(i) => { const e = document.querySelector('[data-audit-btn="' + i + '"]');
                    return !!e && (e.matches('.active,[aria-pressed=true],[aria-selected=true],[aria-checked=true],[aria-current]:not([aria-current=false])')); }""",
                    match["i"],
                )
                if not selected:
                    audit.add(
                        "vercel", "hover-state", rest != hov, b["key"], "no hover change", where
                    )
                # a tile that appears on hover needs room around its label (owner rule 2026-10-18)
                inset = page.evaluate(TILE_INSET, match["i"])
                if inset:
                    audit.add(
                        "kokuen", "hover-tile-inset", inset["ok"], b["key"], inset["detail"], where
                    )
            before_box = loc.evaluate(DOC_BOX)
            before_count = page.evaluate(VISIBLE_COUNT)
            loc.click(timeout=2500)
            audit.clicked += 1
            page.wait_for_timeout(300)
            # work in progress reads as progress, not as an error (owner rule 2026-10-18)
            for state in page.evaluate(BUSY_STATUS) or []:
                audit.add("kokuen", "busy-not-error", state["ok"], b["key"], state["detail"], where)
            page.wait_for_timeout(200)  # let a failed request land its toast
            raw_text_pass(page, audit, b["key"], where)
            # the clicked control stays put while it works (busy, loading, status text)
            if page.url == url0 and loc.count():
                after_box = loc.evaluate(DOC_BOX) if loc.is_visible() else None
                # a form, panel or list that opens moves things on purpose; a status line or a
                # weight change that nudges the control does not
                grew = abs(page.evaluate(VISIBLE_COUNT) - before_count) > 2
                if before_box and after_box and not grew and not page.evaluate(OVERLAY):
                    moved = max(
                        abs(before_box["x"] - after_box["x"]), abs(before_box["y"] - after_box["y"])
                    )
                    audit.add(
                        "kokuen",
                        "click-no-shift",
                        moved <= 1,
                        b["key"],
                        f"moved {moved:.0f}px",
                        where,
                    )
            new = [o for o in page.evaluate(OVERLAY) if o not in before_overlays]
            for oid in new:
                for rubric, check, ok, detail in page.evaluate(OVERLAY_CHECK, oid) or []:
                    audit.add(rubric, check, ok, b["key"], detail, where)
                res = page.evaluate(PROBE, {"scope": f'[data-audit-overlay="{oid}"]'})
                w2 = {**where, "opened_by": b["key"]}
                audit.merge(res, w2)
                focus_pass(page, audit, w2, scope=f'[data-audit-overlay="{oid}"]')
            if new and shots:
                safe = re.sub(r"[^a-z0-9]+", "-", b["key"].lower())[:60]
                page.screenshot(path=str(shots / f"{tag}--open--{safe}.png"))
            if new:
                # escape is judged with focus inside what opened, like a keyboard user
                page.evaluate(
                    """(id) => { const o = document.querySelector('[data-audit-overlay="' + id + '"]');
                    const f = o && [...o.querySelectorAll('button, [href], input, textarea, [tabindex="0"], [role=menuitem], [role=option]')].find(x => !x.disabled && x.getAttribute('aria-disabled') !== 'true' && x.getBoundingClientRect().width > 0);
                    if (f && !o.contains(document.activeElement)) f.focus(); }""",
                    new[0],
                )
                page.keyboard.press("Escape")
                page.wait_for_timeout(250)
                still = [o for o in page.evaluate(OVERLAY) if o in new]
                audit.add(
                    "kokuen", "escape-closes", not still, b["key"], "overlay stayed open", where
                )
        except PWError as exc:
            audit.errors.append(f"{route} {b['key']}: {str(exc).splitlines()[0][:140]}")
        # reset the route when anything moved
        if page.url != url0 or page.evaluate(OVERLAY):
            goto(page, base, route)
            url0 = page.url


def set_theme(request, base, theme) -> None:
    r = request.put(base + "/api/appearance", data={"preset": theme})
    assert r.ok, r.text()


def main() -> int:
    port = os.environ["PORT"]
    base = f"http://127.0.0.1:{port}"
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    require_server_ownership(base, run_id)
    out = Path(os.environ.get("ALLES_BROWSER_ARTIFACTS", "/tmp/alles-ui-audit"))
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    routes = [r for r in os.environ.get("UI_AUDIT_ROUTES", ",".join(ROUTES)).split(",") if r]
    profiles = [p for p in os.environ.get("UI_AUDIT_PROFILES", ",".join(PROFILES)).split(",") if p]
    no_click = os.environ.get("UI_AUDIT_NO_CLICK") == "1"
    audit = Audit()
    console: list[dict] = []
    started = time.monotonic()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for prof in profiles:
            cfg = PROFILES[prof]
            ctx = browser.new_context(
                viewport={"width": cfg["width"], "height": cfg["height"]},
                is_mobile=cfg["mobile"],
                has_touch=cfg["mobile"],
                locale="en-US",
                timezone_id="UTC",
                reduced_motion="reduce",
                service_workers="block",
            )
            set_theme(ctx.request, base, cfg["theme"])
            page = ctx.new_page()
            page.set_default_timeout(8000)
            page.on("dialog", lambda d: d.dismiss())
            page.on("filechooser", lambda fc: None)
            page.on(
                "pageerror", lambda e, p=prof: console.append({"profile": p, "error": str(e)[:300]})
            )
            page.on(
                "console",
                lambda m, p=prof: (
                    console.append({"profile": p, "error": m.text[:300]})
                    if m.type == "error"
                    else None
                ),
            )
            page.goto(base + "/", wait_until="domcontentloaded")
            skip = page.locator("#setup-skip")
            try:
                skip.wait_for(state="visible", timeout=2500)
                skip.click()
            except PWError:
                pass
            for route in routes:
                where = {"route": route, "profile": prof, "mobile": cfg["mobile"]}
                tag = f"{prof}--{route}"
                try:
                    goto(page, base, route)
                except PWError as exc:
                    audit.errors.append(f"{tag}: load {str(exc).splitlines()[0][:120]}")
                    continue
                page.screenshot(path=str(shots / f"{tag}.png"))
                res = page.evaluate(PROBE, {"scope": None})
                if cfg.get("only") == "layout":
                    res["checks"] = {
                        k: v
                        for k, v in res["checks"].items()
                        if "overflow" in k or "reflow" in k or "clipped" in k or "one-line" in k
                    }
                    res["fails"] = [
                        f for f in res["fails"] if f["rubric"] + ":" + f["check"] in res["checks"]
                    ]
                audit.merge(res, where)
                if cfg.get("only") != "layout":
                    raw_text_pass(page, audit, route, where)
                    spacing_pass(page, audit, where)
                    focus_pass(page, audit, where)
                    grid_pass(page, audit, where)
                    # surfaces already open on arrival (settings is a modal) get their own pass
                    for oid in page.evaluate(OVERLAY):
                        for rubric, check, ok, detail in page.evaluate(OVERLAY_CHECK, oid) or []:
                            audit.add(rubric, check, ok, oid, detail, where)
                        audit.merge(
                            page.evaluate(PROBE, {"scope": f'[data-audit-overlay="{oid}"]'}), where
                        )
                if cfg["click"] and not no_click:
                    goto(page, base, route)
                    click_pass(page, base, route, audit, where, shots, tag)
            ctx.close()
        browser.close()
    scores = audit.scores()
    # group failures so the report is readable
    grouped: dict[str, dict] = {}
    for f in audit.fails:
        k = f"{f['rubric']}:{f['check']}:{f['sig']}"
        g = grouped.setdefault(
            k,
            {
                "rubric": f["rubric"],
                "check": f["check"],
                "sig": f["sig"],
                "count": 0,
                "examples": [],
            },
        )
        g["count"] += 1
        if len(g["examples"]) < 3:
            g["examples"].append(
                {k2: f.get(k2) for k2 in ("route", "profile", "detail", "opened_by")}
            )
    result = {
        "scores": scores,
        "checks": {k: {"passed": v[0], "failed": v[1]} for k, v in sorted(audit.checks.items())},
        "clicked": audit.clicked,
        "skipped": sorted(set(audit.skipped)),
        "errors": audit.errors,
        "console": console[:200],
        "failures": sorted(grouped.values(), key=lambda g: (g["rubric"], g["check"], -g["count"])),
        "seconds": round(time.monotonic() - started, 1),
        "routes": routes,
        "profiles": profiles,
    }
    (out / "results.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                "scores": scores,
                "clicked": audit.clicked,
                "unique_failures": len(grouped),
                "errors": len(audit.errors),
                "console": len(console),
            },
            indent=1,
        )
    )
    return 0 if all(s["failed"] == 0 for s in scores.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
