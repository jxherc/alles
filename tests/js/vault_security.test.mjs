import assert from 'node:assert/strict';
import test, { mock } from 'node:test';

let clipboard = '';
let focused = true;
globalThis.window = { isSecureContext: true };
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async text => { clipboard = text; } } },
});
globalThis.document = { hasFocus: () => focused };

const { _vaultInternals, AUTO_LOCK_MS, CLIPBOARD_CLEAR_MS, activityLine } = await import('../../static/js/vault.js');

test('a copied secret is cleared after 90 seconds while alles has focus', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    focused = true;
    await _vaultInternals._copySecret('hunter2');
    assert.equal(clipboard, 'hunter2');
    assert.equal(CLIPBOARD_CLEAR_MS, 90_000);
    mock.timers.tick(CLIPBOARD_CLEAR_MS - 1);
    assert.equal(clipboard, 'hunter2');
    mock.timers.tick(1);
    await Promise.resolve();
    assert.equal(clipboard, '');
  } finally {
    mock.timers.reset();
  }
});

test('a newer copy restarts the clear timer, and an unfocused page leaves the clipboard', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    focused = true;
    await _vaultInternals._copySecret('first');
    mock.timers.tick(60_000);
    await _vaultInternals._copySecret('second');
    mock.timers.tick(60_000);
    await Promise.resolve();
    assert.equal(clipboard, 'second');
    focused = false;
    mock.timers.tick(30_000);
    await Promise.resolve();
    assert.equal(clipboard, 'second');
  } finally {
    mock.timers.reset();
    focused = true;
  }
});

test('the page locks after 10 idle minutes, the same clock as the server', () => {
  assert.equal(AUTO_LOCK_MS, 10 * 60 * 1000);
  const now = 1_000_000_000;
  assert.equal(_vaultInternals._shouldAutoLock(true, now - AUTO_LOCK_MS, now), true);
  assert.equal(_vaultInternals._shouldAutoLock(true, now - AUTO_LOCK_MS + 1, now), false);
  assert.equal(_vaultInternals._shouldAutoLock(false, 0, now), false);
});

test('activity rows name what happened without showing secrets', () => {
  assert.match(activityLine({ action: 'revealed', entry_name: 'gmail' }), /gmail/);
  assert.notEqual(activityLine({ action: 'unlocked', how: 'passkey' }), activityLine({ action: 'unlocked', how: 'password' }));
  assert.equal(activityLine({ action: 'something_new' }), 'something_new');
});
