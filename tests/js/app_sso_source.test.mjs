import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const src = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');

test('sso boot retries failed codes and preserves the full target URL', () => {
  assert.doesNotMatch(src, /alles_sso_tried/);
  assert.match(src, /redeemedAuthCode = response\.ok/);
  assert.match(src, /buildApexBrokerUrl\(location\.href, parseHost\(\)\.base\)/);
  assert.match(src, /location\.replace\(addSsoAuthCode\(target, code\)\)/);
  assert.match(src, /if \(_pendingSso\) \{ _ssoRedirect\(_pendingSso\); return; \}/);
});
