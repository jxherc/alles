// 5c - declarative command registry feeding the palette, hotkeys, and context menus from one place.
// vanilla ESM, no DOM deps so it's node-testable.

export function parseHotkey(combo) {
  const parts = (combo || '').toLowerCase().split('+').map((s) => s.trim()).filter(Boolean);
  const out = { mod: false, shift: false, alt: false, key: '' };
  for (const p of parts) {
    if (p === 'mod' || p === 'ctrl' || p === 'cmd' || p === 'meta') out.mod = true;
    else if (p === 'shift') out.shift = true;
    else if (p === 'alt' || p === 'option') out.alt = true;
    else out.key = p;
  }
  return out;
}

export function createRegistry() {
  const cmds = new Map(); // id -> cmd

  function register(cmd) {
    if (!cmd || !cmd.id) return;
    cmds.set(cmd.id, { keywords: [], group: '', hotkey: '', run: () => {}, ...cmd });
  }

  function all() { return [...cmds.values()]; }
  function has(id) { return cmds.has(id); }
  function byGroup(g) { return all().filter((c) => c.group === g); }

  function search(q) {
    const ql = (q || '').trim().toLowerCase();
    if (!ql) return all();
    const scored = [];
    for (const c of cmds.values()) {
      const title = (c.title || '').toLowerCase();
      const kw = (c.keywords || []).map((k) => k.toLowerCase());
      let score = 0;
      if (title.startsWith(ql)) score = 3;
      else if (title.includes(ql)) score = 2;
      else if (kw.some((k) => k.includes(ql))) score = 1;
      if (score) scored.push([score, c]);
    }
    scored.sort((a, b) => b[0] - a[0]);
    return scored.map((s) => s[1]);
  }

  function matchHotkey(ev) {
    if (!ev) return null;
    const mod = !!(ev.ctrlKey || ev.metaKey);
    const shift = !!ev.shiftKey;
    const alt = !!ev.altKey;
    const key = (ev.key || '').toLowerCase();
    if (!mod && !alt) return null; // a bare key isn't a command hotkey
    for (const c of cmds.values()) {
      if (!c.hotkey) continue;
      const h = parseHotkey(c.hotkey);
      if (h.mod === mod && h.shift === shift && h.alt === alt && h.key === key) return c;
    }
    return null;
  }

  function run(id, ctx) {
    const c = cmds.get(id);
    return c ? c.run(ctx) : undefined;
  }

  return { register, all, has, byGroup, search, matchHotkey, run };
}
