import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const style = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');

test('context handoff scrubs ctx before attempting redemption', () => {
  const boot = app.match(/async function _boot\([\s\S]*?\n}\n\n/)?.[0] || '';
  const redeemIndex = boot.indexOf('await _redeemPendingContextHandoff()');
  const consumeIndex = boot.indexOf("_stripParam('ctx')");
  assert.match(app, /`\/api\/auth\/context-handoff\/\$\{encodeURIComponent\(_pendingContextHandoffCode\)\}`/);
  assert.match(app, /context-handoff[^]*?method: 'POST'[^]*?cache: 'no-store'/);
  assert.ok(redeemIndex >= 0, 'context handoff redemption must exist');
  assert.ok(consumeIndex >= 0, 'ctx must be removed');
  assert.ok(consumeIndex < redeemIndex, 'ctx must be removed before the handoff request');
  assert.match(boot, /_pendingContextHandoffCode = contextCode;[^]*?_rememberContextHandoffCode\(contextCode\);[^]*?_stripParam\('ctx'\)/);
  assert.match(app, /sessionStorage\.getItem\(CONTEXT_HANDOFF_STORAGE_KEY\)/);
  assert.match(app, /sessionStorage\.getItem\(CONTEXT_HANDOFF_PAYLOAD_STORAGE_KEY\)/);
  assert.match(app, /sessionStorage\.setItem\(CONTEXT_HANDOFF_PAYLOAD_STORAGE_KEY, JSON\.stringify\(payload\)\)/);
  assert.match(app, /\[400, 404, 410, 422\]\.includes\(Number\(error\?\.status\)\)/);
  assert.match(boot, /_isTerminalContextHandoffError\(error\)[^]*?_discardContextHandoff\(\)[^]*?if \(urlContextCode\) handoffAsk = ''/);
  assert.match(app, /function _showContextHandoffRetry\([^]*?retry\.addEventListener\('click'/);
  const redeem = app.match(/async function _redeemPendingContextHandoff\(\)[^]*?\n}/)?.[0] || '';
  assert.ok(redeem.indexOf('await response.json()') < redeem.indexOf('_rememberContextHandoffPayload(payload)'));
  assert.ok(redeem.indexOf('_rememberContextHandoffPayload(payload)') < redeem.indexOf('_forgetContextHandoffCode()'));
  const retry = app.match(/function _showContextHandoffRetry\([^]*?\n}/)?.[0] || '';
  assert.match(retry, /const payload = await _redeemPendingContextHandoff\(\)/);
  assert.match(retry, /if \(!delivered\) throw new Error/);
  assert.match(retry, /_isTerminalContextHandoffError\(error\)[^]*?_discardContextHandoff\(\)[^]*?retry\.textContent = 'dismiss'/);
  assert.ok(
    retry.indexOf('await window._askInChat') < retry.indexOf('_discardContextHandoff()'),
    'private context must remain recoverable until chat delivery succeeds',
  );
  assert.match(boot, /const contextHandoffReady = Boolean\(_pendingContextHandoffPayload\)/);
  assert.match(boot, /await window\._askInChat\([^]*?if \(!delivered\)[^]*?_discardContextHandoff\(\)/);
});

test('Aide drawer and backdrop share the 700px responsive breakpoint', () => {
  const backdropIndex = style.indexOf('body.is-aide:not(.sidebar-hidden) .nav-backdrop');
  const start = style.lastIndexOf('@media (max-width: 700px)', backdropIndex);
  const responsive = style.slice(start, style.indexOf('@media', start + 1));
  assert.match(responsive, /body\.is-aide:not\(\.sidebar-hidden\) \.nav-backdrop/);
  assert.match(app, /matchMedia\('\(max-width: 700px\)'\)/);
  const closeHelper = app.match(/const closeCompactAideSidebar = \(\) => \{[\s\S]*?\n  \};/)?.[0] || '';
  assert.match(closeHelper, /max-width: 700px/);
  assert.match(app, /new-chat-btn'[\s\S]{0,220}closeCompactAideSidebar\(\)/);
  assert.match(app, /aide-scheduled-link'[\s\S]{0,180}closeCompactAideSidebar\(\)/);
  assert.doesNotMatch(app, /max-width: 480px/);
});
