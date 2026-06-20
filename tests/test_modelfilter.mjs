// node test for the "newest only" model collapse + sort heuristic. no api keys needed — we
// feed it representative provider model-id lists (what /v1/models would hand back) and assert
// the newest-only view. run:  node tests/test_modelfilter.mjs
//
// (there's no JS test runner in this repo; this is a standalone assert script, exit 1 on fail.)

import { filterNewest, sortModels, _internals } from '../static/js/modelfilter.js';

let failures = 0;
function eq(label, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.error(`FAIL ${label}\n  got:  ${g}\n  want: ${w}`); failures++; }
  else console.log(`ok   ${label}`);
}
// set-equal: newest-only order doesn't matter, membership does
function setEq(label, got, want) {
  eq(label, [...got].sort(), [...want].sort());
}

const newest = m => filterNewest(m, true);

// ── OpenAI: the noisy real lineup should collapse to the current flagships ──────────────────
// chat list (what _is_chat_model keeps)
const openaiChat = [
  'gpt-5.5', 'gpt-5.5-pro', 'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo',
  'o3', 'o1', 'o1-mini', 'chatgpt-4o-latest', 'gpt-3.5-turbo',
];
setEq('openai chat → 5.5 + 5.5-pro', newest(openaiChat), ['gpt-5.5', 'gpt-5.5-pro']);

// image list (what is_image_model keeps — incl. sora now)
const openaiImg = ['gpt-image-1', 'gpt-image-2', 'sora-2', 'dall-e-3'];
setEq('openai image → gpt-image-2 + sora-2 + dall-e-3',
  newest(openaiImg), ['gpt-image-2', 'sora-2', 'dall-e-3']);

// ── Moonshot: the old moonshot-v1 context-size variants must NOT masquerade as "v1.128" ─────
const moonshot = [
  'moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k',
  'kimi-k2.7-instruct', 'kimi-k2-instruct',
];
const msNewest = newest(moonshot);
// the three v1 size variants collapse to a single entry (no separate 8k/32k/128k)
const v1count = msNewest.filter(m => m.startsWith('moonshot-v1')).length;
eq('moonshot v1 size-variants collapse to one', v1count, 1);
// and the newest kimi survives
eq('moonshot keeps newest kimi (k2.7)', msNewest.includes('kimi-k2.7-instruct'), true);
eq('moonshot drops older kimi (k2)', msNewest.includes('kimi-k2-instruct'), false);
// crucially: none of the kept ids is a 32k/8k (the "v1.128" eyesore is gone)
eq('moonshot drops 32k variant', msNewest.includes('moonshot-v1-32k'), false);

// ── Anthropic: opus/sonnet/haiku are distinct families, newest of each ───────────────────────
const anthropic = [
  'claude-opus-4-8', 'claude-opus-4-5', 'claude-sonnet-4-6', 'claude-sonnet-4-5',
  'claude-haiku-4-5-20251001', 'claude-3-opus-20240229',
];
setEq('anthropic → newest opus/sonnet/haiku',
  newest(anthropic), ['claude-opus-4-8', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001']);

// ── ctx-strip unit checks ───────────────────────────────────────────────────────────────────
eq('verScore(moonshot-v1-128k) == 1 (128k not read as .128)',
  _internals.verScore('moonshot-v1-128k'), 1);
eq('familyKey folds gpt-4o-mini → gpt', _internals.familyKey('gpt-4o-mini'), 'gpt');
eq('familyKey keeps gpt-5.5-pro separate', _internals.familyKey('gpt-5.5-pro'), 'gpt pro');
eq('familyKey keeps sora separate', _internals.familyKey('sora-2'), 'sora');

// ── sort sanity: flagship before mini ───────────────────────────────────────────────────────
const sorted = sortModels(openaiChat);
eq('sort puts a 5.x flagship first', /gpt-5\.5/.test(sorted[0]), true);

// ── "works for many of them": run newest-only over each provider's offline seed (chat ids) ──
// these mirror routes/models.py _PROVIDER_FALLBACK so the picker populates with no api keys.
const SEED = {
  deepseek: ['deepseek-chat', 'deepseek-reasoner'],
  moonshot: ['kimi-k2.7', 'kimi-k2-turbo-preview', 'kimi-latest',
    'moonshot-v1-128k', 'moonshot-v1-32k', 'moonshot-v1-8k'],
  xai: ['grok-4', 'grok-4-fast-reasoning', 'grok-3', 'grok-3-mini'],
  gemini: ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.0-flash'],
  mistral: ['mistral-large-latest', 'mistral-medium-latest', 'mistral-small-latest',
    'codestral-latest', 'pixtral-large-latest', 'magistral-medium-latest'],
  perplexity: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'],
  cohere: ['command-a-03-2025', 'command-r-plus', 'command-r', 'command-r7b'],
  openrouter: ['anthropic/claude-opus-4-8', 'openai/gpt-5.5', 'openai/gpt-4o',
    'google/gemini-2.5-pro', 'x-ai/grok-4', 'deepseek/deepseek-r1'],
};
// every provider seed must yield a non-empty newest set that's a subset of the input
for (const [prov, ids] of Object.entries(SEED)) {
  const out = newest(ids);
  eq(`${prov}: newest non-empty + subset`, out.length > 0 && out.every(m => ids.includes(m)), true);
}
// provider-specific sanity
eq('deepseek keeps both tiers', newest(SEED.deepseek).length, 2);
eq('gemini drops 2.0-flash for 2.5-flash', newest(SEED.gemini).includes('gemini-2.0-flash'), false);
eq('gemini keeps 2.5-pro', newest(SEED.gemini).includes('gemini-2.5-pro'), true);
eq('xai keeps grok-4', newest(SEED.xai).includes('grok-4'), true);
eq('xai drops superseded grok-3', newest(SEED.xai).includes('grok-3'), false);
eq('perplexity keeps all 5 sonar tiers', newest(SEED.perplexity).length, 5);
eq('moonshot collapses v1 size variants',
  newest(SEED.moonshot).filter(m => m.startsWith('moonshot-v1')).length, 1);
eq('openrouter folds gpt-4o into gpt-5.5', newest(SEED.openrouter).includes('openai/gpt-4o'), false);

// off → passthrough unchanged
eq('newest-only off = identity', filterNewest(openaiChat, false), openaiChat);

if (failures) { console.error(`\n${failures} assertion(s) failed`); process.exit(1); }
console.log('\nall model-filter assertions passed');
