import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { lum, mix, mutedFor, generateHarmony } from '../../static/js/color.js';

const source = readFileSync(new URL('../../static/js/theme.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export \{.*\};\r?\n/gm, '').replace(/^export /gm, '');

function harness(saved) {
  const storage = new Map(saved ? [['alles-appearance', JSON.stringify(saved)]] : []);
  const style = new Map();
  const classes = { add() {}, remove() {}, toggle() {} };
  const context = vm.createContext({
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    document: { documentElement: { style: { setProperty: (key, value) => style.set(key, value) }, dataset: {}, classList: classes }, body: { classList: classes }, querySelector: () => null, querySelectorAll: () => [] },
    window: {}, setTimeout: () => 1, clearTimeout() {},
    _lum: lum, _mix: mix, _mutedFor: mutedFor, generateHarmony,
  });
  vm.runInContext(source + '\napplyBgPattern = () => {}; globalThis.subject = { resetToDefault, setAccent, getAppearance, PRESETS };', context);
  return { ...context.subject, storage, style };
}

test('untouched base accents follow dark → light → dark', () => {
  const h = harness();
  assert.equal(h.resetToDefault('light').colors.accent, h.PRESETS.light.colors.accent);
  assert.equal(h.resetToDefault('dark').colors.accent, h.PRESETS.dark.colors.accent);
});

test('explicit accent stays chosen across modes, reload, and same-as-default choice', () => {
  const h = harness();
  h.setAccent(h.PRESETS.dark.colors.accent);
  const light = h.resetToDefault('light');
  assert.equal(light.colors.accent, h.PRESETS.dark.colors.accent);
  assert.equal(light.accentCustom, true);
  const reloaded = harness(JSON.parse(h.storage.get('alles-appearance')));
  assert.equal(reloaded.resetToDefault('dark').colors.accent, h.PRESETS.dark.colors.accent);
  reloaded.setAccent('#ff9900');
  assert.equal(reloaded.resetToDefault('light').colors.accent, '#ff9900');
  reloaded.setAccent(null);
  assert.equal(reloaded.resetToDefault('dark').colors.accent, h.PRESETS.dark.colors.accent);
});

test('legacy base customization and saved custom themes survive switching modes', () => {
  const seed = harness();
  const h = harness({ preset: 'dark', colors: { ...seed.PRESETS.dark.colors, accent: '#ff9900' }, customThemes: { mine: { colors: { accent: '#123456' } } } });
  const result = h.resetToDefault('light');
  assert.equal(result.colors.accent, '#ff9900');
  assert.equal(result.customThemes.mine.colors.accent, '#123456');
});

test('a preset tint returns to the chosen base default', () => {
  const seed = harness();
  const h = harness({ preset: 'midnight', colors: seed.PRESETS.midnight.colors });
  assert.equal(h.resetToDefault('light').colors.accent, seed.PRESETS.light.colors.accent);
});

test('an explicit accent chosen on a preset survives base modes and reload', () => {
  const seed = harness();
  const h = harness({ preset: 'midnight', colors: seed.PRESETS.midnight.colors });
  h.setAccent('#ff9900');
  assert.equal(h.resetToDefault('light').colors.accent, '#ff9900');
  assert.equal(h.getAppearance().accentCustom, true);
  const reloaded = harness(JSON.parse(h.storage.get('alles-appearance')));
  assert.equal(reloaded.resetToDefault('dark').colors.accent, '#ff9900');
});

test('a preset with explicit inherited ownership returns to the base accent', () => {
  const seed = harness();
  const h = harness({ preset: 'midnight', colors: { ...seed.PRESETS.midnight.colors, accent: '#ff9900' }, accentCustom: false });
  assert.equal(h.resetToDefault('light').colors.accent, seed.PRESETS.light.colors.accent);
});
