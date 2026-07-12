import test from 'node:test';
import assert from 'node:assert/strict';

import {
  AFTERLIFE_FEATURE_DEFAULTS,
  activeAfterlifeSpaces,
  loadAfterlifeFeatures,
  normalizeAfterlifeFeatures,
} from '../../static/js/afterlife.js';

test('unfinished features default off', () => {
  assert.deepEqual(normalizeAfterlifeFeatures(), AFTERLIFE_FEATURE_DEFAULTS);
  assert.equal(Object.values(AFTERLIFE_FEATURE_DEFAULTS).some(Boolean), false);
});

test('only exact boolean flags can enable a surface', () => {
  const flags = normalizeAfterlifeFeatures({
    afterlife_shell: true,
    afterlife_today: 'true',
    made_up_surface: true,
  });
  assert.equal(flags.afterlife_shell, true);
  assert.equal(flags.afterlife_today, false);
  assert.equal('made_up_surface' in flags, false);
});

test('runtime failure keeps the legacy shell', async () => {
  const networkFailure = await loadAfterlifeFeatures(async () => { throw new Error('offline'); });
  const badResponse = await loadAfterlifeFeatures(async () => ({ ok: false }));
  assert.deepEqual(networkFailure, AFTERLIFE_FEATURE_DEFAULTS);
  assert.deepEqual(badResponse, AFTERLIFE_FEATURE_DEFAULTS);
});

test('a destination needs its flag and a finished route', () => {
  const flags = {
    ...AFTERLIFE_FEATURE_DEFAULTS,
    afterlife_shell: true,
    afterlife_today: true,
    afterlife_andromeda: true,
  };
  assert.deepEqual(activeAfterlifeSpaces(flags), ['aide']);
  assert.deepEqual(
    activeAfterlifeSpaces(flags, { aide: true, today: true, andromeda: true }),
    ['today', 'aide', 'andromeda'],
  );
  assert.deepEqual(activeAfterlifeSpaces({ ...flags, afterlife_shell: false }), []);
});
