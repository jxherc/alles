// command-palette fuzzy matcher — powers the "go to" group in the ⌘K search.
// pure (no DOM), unit-tested in tests/js/palette.test.mjs.

export function fuzzyMatch(text, query) {
  text = String(text || '').toLowerCase();
  query = String(query || '').toLowerCase();
  if (!query) return 0;
  if (query.length > text.length) return -1;
  let score = 0, from = 0, prev = -2;
  for (const ch of query) {
    let at = -1;
    for (let i = from; i < text.length; i++) { if (text[i] === ch) { at = i; break; } }
    if (at === -1) return -1;
    let pts = 1;
    if (at === prev + 1) pts += 3;                                   // consecutive run
    const before = text[at - 1];
    if (at === 0 || before === ' ' || before === '-' || before === '/') pts += 4;  // word start
    score += pts; prev = at; from = at + 1;
  }
  return score - text.length * 0.02;   // tiebreak toward tighter/shorter text
}

export function filterCommands(commands, query) {
  query = String(query || '').trim();
  if (!query) return commands.slice();
  const scored = [];
  for (const c of commands) {
    const ls = fuzzyMatch(c.label, query);
    const hs = c.hint ? fuzzyMatch(c.hint, query) : -1;
    const s = Math.max(ls, hs >= 0 ? hs - 2 : -1);   // hint hits rank slightly lower
    if (s >= 0) scored.push({ c, s });
  }
  scored.sort((a, b) => b.s - a.s);
  return scored.map(x => x.c);
}
