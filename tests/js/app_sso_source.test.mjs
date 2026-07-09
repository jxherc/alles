import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const src = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');

test('sso boot does not write the old unused retry flag', () => {
  assert.doesNotMatch(src, /alles_sso_tried/);
  assert.match(src, /const hadAuthCode = !!code/);
  assert.match(src, /location\.assign\(urlForApp\(''\) \+ '\?_sso='/);
  assert.match(src, /if \(_pendingSso\) \{ _ssoRedirect\(_pendingSso\); return; \}/);
});
