// pure colour math — hex/rgb/hsl conversions, mix, luminance, palette harmony.
// no DOM, no imports → unit-testable in node (tests/js/color.test.mjs). lifted out
// of theme.js so the algorithms can be tested without a browser.

export function hexToRgb(hex) {
  hex = String(hex || '').replace('#', '');
  if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
  if (!/^[0-9a-f]{6}$/i.test(hex)) return { r: 0, g: 0, b: 0 };
  const n = parseInt(hex, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

export function hexToHSL(hex) {
  const { r: R, g: G, b: B } = hexToRgb(hex);
  const r = R / 255, g = G / 255, b = B / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h, s; const l = (max + min) / 2;
  if (max === min) { h = s = 0; }
  else {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  return [h * 360, s * 100, l * 100];
}

export function hslToHex(h, s, l) {
  h = ((h % 360) + 360) % 360; s = Math.max(0, Math.min(100, s)) / 100; l = Math.max(0, Math.min(100, l)) / 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => { const k = (n + h / 30) % 12; return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
  const toHex = v => Math.round(v * 255).toString(16).padStart(2, '0');
  return '#' + toHex(f(0)) + toHex(f(8)) + toHex(f(4));
}

export function mix(a, b, t) {
  const x = hexToRgb(a), y = hexToRgb(b);
  const m = k => Math.round(x[k] + (y[k] - x[k]) * t).toString(16).padStart(2, '0');
  return '#' + m('r') + m('g') + m('b');
}

export function lum(hex) { const { r, g, b } = hexToRgb(hex); return (0.299 * r + 0.587 * g + 0.114 * b) / 255; }

// WCAG relative luminance (gamma-corrected) + contrast ratio. used to keep --muted
// readable on light themes, where a flat 0.5 mix only lands ~2.8:1.
export function relLum(hex) {
  const { r, g, b } = hexToRgb(hex);
  const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
export function contrast(a, b) {
  const L1 = relLum(a), L2 = relLum(b);
  return (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
}
// muted secondary-text colour: start at the subtle 0.5 blend, then nudge toward text
// until it clears `floor` contrast against bg. dark themes already pass at 0.5 so they
// stay untouched; light themes get darkened just enough to read.
export function mutedFor(text, bg, panel = bg, floor = 3.2) {
  // secondary text lands on both --bg and --panel; clear `floor` against the harder one.
  const worst = m => Math.min(contrast(m, bg), contrast(m, panel));
  let t = 0.5, m = mix(text, bg, t);
  // nudge toward text until we clear `floor`; on pale themes whose text itself is low
  // contrast (e.g. cute) we can't reach 3.2, so best-effort down to ~text and stop.
  while (t > 0.06 && worst(m) < floor) { t -= 0.04; m = mix(text, bg, t); }
  return m;
}

export function generateHarmony(accentHex, type, mode) {
  const [h, s] = hexToHSL(accentHex);
  const dark = mode === 'dark';
  let bgH, bgS, bgL, fgS, fgL, panelL, bH, bS, bL;
  if (type === 'complementary') {
    bgH = h; bgS = Math.max(s * 0.15, 3); bgL = dark ? 13 : 95; fgL = dark ? 85 : 15; fgS = Math.max(s * 0.2, 5);
    panelL = dark ? 8 : 98; bH = h; bS = Math.max(s * 0.25, 8); bL = dark ? 28 : 75;
  } else if (type === 'analogous') {
    bgH = (h - 30 + 360) % 360; bgS = Math.max(s * 0.12, 3); bgL = dark ? 14 : 95; fgL = dark ? 84 : 18; fgS = Math.max(s * 0.15, 5);
    panelL = dark ? 9 : 97; bH = (h + 30) % 360; bS = Math.max(s * 0.3, 10); bL = dark ? 30 : 72;
  } else if (type === 'triadic') {
    bgH = (h + 240) % 360; bgS = Math.max(s * 0.1, 2); bgL = dark ? 13 : 96; fgL = dark ? 86 : 14; fgS = Math.max(s * 0.18, 5);
    panelL = dark ? 8 : 99; bH = (h + 120) % 360; bS = Math.max(s * 0.2, 8); bL = dark ? 28 : 74;
  } else {
    bgH = h; bgS = Math.max(s * 0.08, 2); bgL = dark ? 12 : 96; fgL = dark ? 87 : 13; fgS = Math.max(s * 0.15, 5);
    panelL = dark ? 7 : 99; bH = h; bS = Math.max(s * 0.2, 6); bL = dark ? 26 : 76;
  }
  return {
    bg: hslToHex(bgH, bgS, bgL), text: hslToHex(h, fgS, fgL),
    panel: hslToHex(bgH, bgS * 0.6, panelL), faint: hslToHex(bH, bS, bL), accent: accentHex,
  };
}
