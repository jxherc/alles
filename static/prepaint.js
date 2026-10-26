// pre-paint: apply the cached advanced theme so there's no flash before theme.js loads.
// a plain blocking script in <head> (not a module) so it runs before the first paint
(function () {
  var r = document.documentElement, st = r.style;
  try {
    var a = JSON.parse(localStorage.getItem('alles-appearance') || 'null');
    if (a && a.colors) {
      var c = a.colors, FM = { sans: "'Inter', sans-serif", mono: "'JetBrains Mono', monospace", serif: "Georgia, serif" };
      if (c.bg) st.setProperty('--bg', c.bg); if (c.text) st.setProperty('--text', c.text);
      if (c.panel) st.setProperty('--panel', c.panel); if (c.faint) st.setProperty('--faint', c.faint);
      if (c.accent) st.setProperty('--accent', c.accent);
      var n = parseInt((c.bg || '#0a0a0a').replace('#', ''), 16);
      if ((((n >> 16 & 255) * 0.299 + (n >> 8 & 255) * 0.587 + (n & 255) * 0.114) / 255) > 0.5) r.dataset.theme = 'light';
      st.setProperty('--font-family', FM[a.font] || FM.sans);
      if (a.density && a.density !== 'comfortable') r.classList.add('density-' + a.density);
      return;
    }
  } catch (e) {}
  var _t = localStorage.getItem('aide-theme'); if (_t) r.dataset.theme = _t;
  var _a = localStorage.getItem('aide-accent'); if (_a) st.setProperty('--accent', _a);
})();
