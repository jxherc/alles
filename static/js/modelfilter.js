// pure model-list ordering + "newest only" collapsing. NO dom deps on purpose so it's
// unit-testable without a browser or any api keys (see tests/test_modelfilter.mjs — we feed
// it fake provider model-id lists). models.js imports sortModels/filterNewest from here.

// strip an embedded context-window token (128k, 32k, 1m) so it isn't mistaken for a version.
// moonshot-v1-128k / -32k / -8k are the SAME old model at different context sizes — without
// this they score as "v1.128" and one of them masquerades as the newest moonshot.
function stripCtx(s) {
  return s.replace(/\b\d+(\.\d+)?\s*[km]\b/gi, ' ');
}

// ── sorting: class-grouped, newest-first ────────────────────────────────────
// providers hand back model lists in arbitrary order. rank each id by class/tier
// (flagship → mini) then recency (date, then version) so the headline + newest
// models sit on top and a family stays grouped together. heuristic, but covers
// the common provider ladders; falls back to alpha.
export function modelRank(id) {
  const s = String(id).toLowerCase();
  const TIERS = [
    [/opus|gpt-5|o3|o4|grok-4|ultra|-pro\b|reasoner|405b/, 6],
    [/sonnet|gpt-4o|gpt-4\.1|o1\b|deepseek-r1|grok-3|72b|-70b|large/, 5],
    [/haiku|gpt-4\b|deepseek-v3|deepseek-chat|gemini-[12]\.\d-pro|-3[234]b|medium/, 4],
    [/mini|flash\b|turbo|coder|small|-(7|8|9)b\b/, 3],
    [/nano|lite|tiny|gemma|phi|-[1-3]b\b/, 2],
  ];
  let tier = 1;
  for (const [re, t] of TIERS) if (re.test(s)) { tier = t; break; }
  // a release date (if present) — only a tiebreaker; newest families often have none
  const dm = s.match(/(20\d{2})[-_]?(\d{2})[-_]?(\d{2})/);
  const dscore = dm ? Number(dm[1] + dm[2] + dm[3]) : 0;
  // version = the FIRST number once dates + size/ctx tokens are gone. (max-number trips on
  // "70b", "128k" and the date digits; first-number tracks the family version.)
  const cleaned = stripCtx(s).replace(/(20\d{2})[-_]?\d{2}[-_]?\d{2}/g, ' ').replace(/\d+(\.\d+)?b\b/g, ' ');
  const nums = (cleaned.match(/\d+(\.\d+)?/g) || []).map(parseFloat);
  let ver = nums.length ? nums[0] + Math.min(nums[1] || 0, 99) / 100 : 0;
  if (/latest|preview|exp|thinking/.test(s)) ver += 0.25;
  return { tier, ver, dscore };
}

export function sortModels(models) {
  return [...models].sort((a, b) => {
    const x = modelRank(a), y = modelRank(b);
    return (y.tier - x.tier) || (y.ver - x.ver) || (y.dscore - x.dscore) || a.localeCompare(b);
  });
}

// ── "newest only" — collapse each family to its latest release ───────────────
// family = the id with ctx-size, versions + dates stripped, so opus-4-8 / opus-4-5 / 3-opus
// all collapse to "claude opus" and we keep just the newest.
function familyKey(id) {
  let s = stripCtx(String(id).toLowerCase().split('/').pop())
    .replace(/(20\d{2})[-_]?\d{2}[-_]?\d{2}/g, ' ')   // dates
    .replace(/\d+(\.\d+)?/g, ' ')                       // version numbers
    .replace(/[-_.]+/g, ' ').replace(/\s+/g, ' ').trim();
  // openai's base line is noisy: gpt-4o, o1/o3, gpt-4o-mini, chatgpt-4o-latest, gpt-5.5…
  // fold the whole base family — the o-series plus size/qualifier variants — into one "gpt"
  // so newest-only keeps just the latest flagship. "gpt pro", "gpt image", "sora" are real
  // distinct tiers and stay separate (so 5.5-pro / gpt-image / sora each still show).
  s = s.replace(/\bchatgpt\b/g, 'gpt');
  const bare = s.replace(/\b(o|mini|nano|turbo|latest|preview|exp|chat)\b/g, ' ').replace(/\s+/g, ' ').trim();
  if (s === 'o' || /^o /.test(s) || bare === 'gpt') s = 'gpt';
  return s;
}

// finer than modelRank.ver: major.minor so 4-8 (4.08) beats 4-5 (4.05). ctx size stripped
// first so 128k doesn't read as version 1.128.
function verScore(id) {
  const nums = (stripCtx(String(id).toLowerCase()).replace(/(20\d{2})[-_]?\d{2}[-_]?\d{2}/g, ' ')
    .match(/\d+(\.\d+)?/g) || []).map(parseFloat);
  if (!nums.length) return 0;
  return nums[0] + Math.min(nums[1] || 0, 99) / 100;
}

function dateScore(id) {
  const m = String(id).match(/(20\d{2})[-_]?(\d{2})[-_]?(\d{2})/);
  return m ? Number(m[1] + m[2] + m[3]) : 0;
}

export function filterNewest(models, on) {
  if (!on) return models;
  const best = new Map();
  for (const m of models) {
    const k = familyKey(m), cur = best.get(k);
    if (!cur) { best.set(k, m); continue; }
    const newer = verScore(m) > verScore(cur) ||
      (verScore(m) === verScore(cur) && dateScore(m) > dateScore(cur));
    if (newer) best.set(k, m);
  }
  const keep = new Set(best.values());
  return models.filter(m => keep.has(m));
}

// exported for the test harness only
export const _internals = { stripCtx, familyKey, verScore, dateScore };
