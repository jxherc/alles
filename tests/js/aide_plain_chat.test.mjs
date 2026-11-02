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

test('read goes under the newest message the server took', () => {
  assert.match(sessions, /<span class="user-read">\$\{escHtml\(t\('aide\.read_mark'\)\)\}<\/span>/);
  assert.match(chat, /accepted = true;[\s\S]{0,400}markRead\(asked\)/);
});
