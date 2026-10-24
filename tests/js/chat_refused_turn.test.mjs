import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const chat = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const helpers = chat.slice(chat.indexOf('let _refusedTurn = null;'), chat.indexOf('function restoreBackgroundInput'));

function row(user = false) {
  return {
    removed: false,
    previousElementSibling: null,
    querySelector: selector => (user && selector === '.user-bubble' ? {} : null),
    remove() { this.removed = true; },
  };
}

function setup() {
  const inputs = [];
  const composer = { value: '', style: {}, dispatchEvent: event => inputs.push(event.type) };
  const state = { active: 's1' };
  const context = vm.createContext({
    document: { getElementById: id => (id === 'composer-ta' ? composer : null) },
    Event: class { constructor(type) { this.type = type; } },
    getActiveId: () => state.active,
  });
  vm.runInContext(`${helpers}\nglobalThis.subject = { noteRefusedTurn, refusedRetryAccepted, dropRefusedTurn };`, context);
  return { ...context.subject, composer, inputs, state };
}

// sendMessage clears the composer, the 409 puts the words back
function refuse(h, message = 'summarize this') {
  const user = row(true);
  const reply = row();
  reply.previousElementSibling = user;
  h.noteRefusedTurn('s1', message, reply, null);
  h.composer.value = message;
  return { user, reply };
}

test('an accepted retry takes the refused words back out of the composer and its draft', () => {
  const h = setup();
  const { reply } = refuse(h);
  // retry refused once more, then accepted
  const second = row();
  h.noteRefusedTurn('s1', 'summarize this', second, reply);
  h.refusedRetryAccepted('s1', second);
  assert.equal(h.composer.value, '');
  // the input event is what saves (here: clears) the stored draft
  assert.deepEqual(h.inputs, ['input']);
});

test('an accepted retry leaves what was typed after the refusal alone', () => {
  const h = setup();
  const { reply } = refuse(h);
  h.composer.value = 'summarize this\n\nand also this';
  h.refusedRetryAccepted('s1', reply);
  assert.equal(h.composer.value, 'and also this');
  const other = setup();
  const refused = refuse(other);
  other.composer.value = 'a different question';
  other.refusedRetryAccepted('s1', refused.reply);
  assert.equal(other.composer.value, 'a different question');
  assert.deepEqual(other.inputs, []);
});

test('sending again from the composer replaces the refused bubble instead of doubling it', () => {
  const h = setup();
  const { user, reply } = refuse(h);
  h.dropRefusedTurn('s1');
  assert.equal(user.removed, true);
  assert.equal(reply.removed, true);
  // only once
  const later = refuse(h);
  h.dropRefusedTurn('s2');
  h.dropRefusedTurn('s1');
  assert.equal(later.user.removed, false);
});

test('streamReply records the refusal and clears the copy once a retry is accepted', () => {
  const stream = chat.slice(chat.indexOf('async function streamReply'), chat.indexOf('const reader = r.body.getReader();'));
  // an edit or regenerate that is refused returns earlier and never reaches this
  assert.match(stream, /if \(!r\.ok && resend\) \{[^]*?return;\s*\}\s*if \(!r\.ok\) \{/);
  assert.match(stream, /rejectedBeforeStart && !pendingDraft && getActiveId\(\) === sessionId\) noteRefusedTurn\(sessionId, request\.message, row, previousRow\)/);
  assert.match(stream, /pendingDraft\?\.accept\(\);\n\s*refusedRetryAccepted\(sessionId, previousRow\);/);
  const send = chat.slice(chat.indexOf('export async function sendMessage'), chat.indexOf('async function streamReply'));
  assert.match(send, /if \(!documentScope\) onAccepted\(sessionId\);\n\s*dropRefusedTurn\(sessionId\);/);
});
