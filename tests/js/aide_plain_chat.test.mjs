// aide's chat is a plain chat: the reply, "read" under the owner's newest message, and "typing"
// while it works. thinking, tool steps, plans and receipts stay out of the stream
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const { withoutThinking } = await import('../../static/js/util.js');
const chat = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');

test('thinking a model writes into its reply stays out of the words, even while still open', () => {
  assert.equal(withoutThinking('<think>plan the answer</think>here it is'), 'here it is');
  assert.equal(withoutThinking('first <thinking>a\nb</thinking>second'), 'first second');
  assert.equal(withoutThinking('the start <think>still thinking'), 'the start');
  assert.equal(withoutThinking('no thinking here'), 'no thinking here');
});

test('the typing line stays one word for the whole turn', () => {
  assert.match(chat, /progressEl\.textContent = t\('aide\.progress_typing'\)/);
  assert.doesNotMatch(chat, /setProgress|thinking_progress|bg_state_running/);
});

test('only what needs the owner shows mid reply, between the words and typing', () => {
  assert.match(chat, /attentionEl\.className = 'aide-needs-you'/);
  assert.match(chat, /attention\(\)\.appendChild\(card\)/);
  assert.match(chat, /renderAideQuestion\(attention\(\), chunk\.user_question\)/);
  assert.doesNotMatch(chat, /chunk\.todo_update\)|chunk\.tool_delta|chunk\.tool_image|ensureAgentPanel|agent-step/);
  // the steps are kept for the reply's menu only
  assert.match(chat, /addStepsAction\(actions, \[\.\.\.steps\.values\(\)\], runId\)/);
});

test('a reply with tools and no words still gets its actions row, with the steps', () => {
  assert.match(chat, /if \(wrap && \(hasWords \|\| artifacts\.length \|\| steps\.size\)\)/);
  assert.match(chat, /if \(hasWords\) \{\s*html \+= `<button class="act-btn" data-msg-act="copy">/);
  // after a reload a reply with no words has nothing to copy either, only its steps
  assert.match(sessions, /actions\.innerHTML = withoutThinking\(displayText\) \? `/);
});

test('an approval for a file change shows the change it asks about', () => {
  assert.match(chat, /agent-perm-diff[^\n]*renderDiff\(t\.diff\)/);
});

test('the steps dialog is the shared view dialog: one title, one close, no cancel', () => {
  const dialog = readFileSync(new URL('../../static/js/dialog.js', import.meta.url), 'utf8');
  const view = dialog.slice(dialog.indexOf('export function view('), dialog.indexOf('export function choose('));
  assert.equal(view.match(/<h2 class="dialog-title"/g)?.length, 1);
  assert.equal(view.match(/data-dialog-cancel/g)?.length, 1);
  assert.doesNotMatch(view, /data-dialog-confirm/);
  assert.match(sessions, /_dlgView\(title, html, \{ className: 'aide-steps-dialog'/);
});

test('read goes under the newest message the server took', () => {
  assert.match(sessions, /<span class="user-read">\$\{escHtml\(t\('aide\.read_mark'\)\)\}<\/span>/);
  assert.match(chat, /accepted = true;[\s\S]{0,400}markRead\(asked\)/);
});
