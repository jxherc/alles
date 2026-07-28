import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { shouldRunInBackground } from '../../static/js/aidebackgroundpolicy.js';

const chat = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const background = readFileSync(new URL('../../static/js/aidebackground.js', import.meta.url), 'utf8');
const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const serviceWorker = readFileSync(new URL('../../static/sw.js', import.meta.url), 'utf8');

test('service worker URL replay preserves literal percent paths while decoding traversal', () => {
  const source = serviceWorker.match(/function replayPolicyPathname\(url\) \{[\s\S]*?\n\}/)?.[0] || '';
  const replayPolicyPathname = Function(`${source}; return replayPolicyPathname;`)();
  assert.equal(replayPolicyPathname(new URL('https://alles.test/api/notes/100%25')), '/api/notes/100%');
  assert.equal(replayPolicyPathname(new URL('https://alles.test/safe/%252e%252e/api/auth')), '/api/auth');
});

test('explicit natural language starts background work without a mode switch', () => {
  assert.equal(shouldRunInBackground('check this in the background'), true);
  assert.equal(shouldRunInBackground('keep working on the migration while I leave'), true);
  assert.equal(shouldRunInBackground('Can Aide keep working while I close the tab?'), false);
  assert.equal(shouldRunInBackground('How does keep working while I am away work?'), false);
  assert.equal(shouldRunInBackground('/background prepare the report'), true);
  assert.equal(shouldRunInBackground('what does background processing mean?'), false);
  assert.equal(shouldRunInBackground('Which services run in the background?'), false);
  assert.equal(shouldRunInBackground('How can I check what runs in the background?'), false);
  assert.equal(shouldRunInBackground('In the background, how does this work?'), false);
  assert.equal(shouldRunInBackground('check whether the backup works in the background'), true);
  assert.equal(shouldRunInBackground('run the tests if needed in the background'), true);
  assert.equal(shouldRunInBackground('prepare a guide to apps that work in the background'), false);
  assert.equal(shouldRunInBackground('Could you run the migration in the background?'), true);
  assert.equal(shouldRunInBackground('I need you to continue this in the background.'), true);
  assert.equal(shouldRunInBackground('answer this question'), false);
});

test('normal Aide chat owns the background path and keeps the same session', () => {
  assert.match(chat, /shouldRunInBackground\(text\)/);
  assert.match(chat, /startBackgroundWork\(\{[\s\S]*sessionId[\s\S]*request: text/);
  assert.match(background, /session_id: sessionId/);
  assert.match(background, /\/api\/jarvis\/handoffs/);
  assert.doesNotMatch(background, /run with jarvis|switch to chat|jarvis mode/i);
});

test('remote background work requires owner confirmation before any request or file is sent', () => {
  const start = background.match(
    /export async function startBackgroundWork[^]*?\n}\n\nexport async function reattachBackgroundWork/,
  )?.[0] || '';
  assert.match(background, /import \{ confirm as confirmDialog \} from '.\/dialog\.js'/);
  assert.match(start, /preview\.privacy_class === 'remote'/);
  assert.match(start, /await confirmDialog\(/);
  assert.ok(start.indexOf('await confirmDialog(') < start.indexOf("fetch('/api/jarvis/handoffs'"));
  assert.match(start, /confirmation\.confirmed_endpoint_id = preview\.endpoint_id/);
  assert.match(start, /confirmation\.confirmed_model = preview\.model/);
  assert.match(start, /\.\.\.confirmation/);
  assert.doesNotMatch(start, /confirmed_endpoint_id:\s*preview\.endpoint_id/);
});

test('failed background enqueue restores the composer and keeps attachments', () => {
  const branch = chat.match(/if \(!documentScope && shouldRunInBackground[\s\S]*?\n  }\n\n  showMessages/)?.[0] || '';
  assert.match(branch, /if \(!run\)[\s\S]*restoreComposerInput\(text\)[\s\S]*return/);
  assert.match(branch, /if \(!run\)[\s\S]*return;[\s\S]*clearAttachments\(\)/);
  assert.match(branch, /const userRow = appendUserMsg\(text\)/);
  assert.match(branch, /if \(!run\)[\s\S]*userRow\.remove\(\)[\s\S]*restoreComposerInput\(text\)/);
  assert.match(chat, /function restoreComposerInput\(text\)[\s\S]*dispatchEvent\(new Event\('input'/);
});

test('a Docs-scoped image request stays on the scoped text path', () => {
  assert.match(chat, /if \(!documentScope && isImageSelected\(\)\)/);
  assert.match(chat, /if \(!documentScope && imgSlot && _looksLikeImageRequest\(text\)\)/);
});

test('a Docs-scoped request restores its scope after a transport failure', () => {
  const transportFailure = chat.match(/} catch \(e\) \{[\s\S]*?\n  } finally \{/)?.[0] || '';
  assert.match(transportFailure, /restoreDocumentScope\(documentScope\)/);
});

test('opening a conversation reattaches durable background work', () => {
  assert.match(sessions, /aidebackground\.js/);
  assert.match(sessions, /reattachBackgroundWork\(id\)/);
  assert.match(background, /\/api\/jarvis\/runs\?limit=/);
  assert.match(background, /window\._reloadActiveSession/);
  assert.match(background, /runs\.filter\(/);
  assert.match(background, /relevantRuns\.forEach\(/);
  assert.doesNotMatch(background, /runs\.find\(/);
});

test('reattaching a conversation keeps every run that still needs attention', () => {
  const reattach = background.match(/export async function reattachBackgroundWork[^]*?\n}/)?.[0] || '';
  for (const state of ['queued', 'running', 'failed', 'cancelled', 'interrupted', 'uncertain']) {
    assert.match(reattach, new RegExp(`['\"]${state}['\"]`));
  }
  assert.doesNotMatch(reattach, /['\"]succeeded['\"]/);
  assert.ok(
    reattach.indexOf("import('./bgrun.js')") > reattach.indexOf('relevantRuns.forEach'),
    'legacy reattachment must still run after durable runs render',
  );
  assert.ok(
    reattach.indexOf("import('./bgrun.js')") < reattach.indexOf('return relevantRuns.length'),
    'durable runs must not return before legacy work can reattach',
  );
});

test('a stale status poll cannot overwrite a cancel or retry response', () => {
  assert.match(background, /const pollVersion = card\.dataset\.pollVersion \|\| '0'/);
  assert.match(background, /if \(\(card\.dataset\.pollVersion \|\| '0'\) !== pollVersion\) return/);
  assert.match(background, /card\.dataset\.pollVersion = String\(Number\(card\.dataset\.pollVersion \|\| 0\) \+ 1\)/);
});

test('a pre-run background failure never renders an inert retry action', () => {
  const render = background.match(/function renderCard\(card[^]*?\n}\n\nfunction stopPolling/)?.[0] || '';
  assert.match(render, /card\.dataset\.runId\s*\?\s*actionForState\(state\)\s*:\s*''/);
});

test('background actions are never queued for a surprising later replay', () => {
  assert.match(serviceWorker, /NOQUEUE = \[[^\]]*'\/api\/jarvis'/);
});
