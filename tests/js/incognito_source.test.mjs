import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const chat = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const uploads = readFileSync(new URL('../../static/js/uploads.js', import.meta.url), 'utf8');

test('incognito session ids and drafts are not written to browser storage', () => {
  assert.match(sessions, /if \(isIncognitoMode\(\)\) return;/);
  assert.match(sessions, /if \(id && !isIncognitoMode\(\)\) location\.hash = id/);
  assert.match(sessions, /if \(!options\.incognito\) await loadSessions\(\)/);
});

test('leaving incognito deletes the temporary server session without saving its draft', () => {
  assert.match(app, /fetch\(`\/api\/sessions\/\$\{sessionId\}`.*method: 'DELETE'/s);
  assert.match(app, /newChat\(\{ skipDraft: true \}\)/);
});

test('switching privacy modes discards selected attachments', () => {
  assert.match(uploads, /export async function discardAttachments\(\)/);
  assert.equal((app.match(/await discardAttachments\(\)/g) || []).length, 2);
});

test('attachment ids are copied before the composer clears them', () => {
  const snapshot = chat.indexOf('const attachmentIds = getAttachments()');
  const clear = chat.indexOf('clearAttachments()');
  const request = chat.indexOf('file_ids: attachmentIds');
  assert.ok(snapshot >= 0 && snapshot < clear && clear < request);
});
