import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/mail.js', import.meta.url), 'utf8');
const block = source.slice(source.indexOf('let _photos = null;'), source.indexOf('const shortDate = d =>'));

function load(contacts, { ok = true } = {}) {
  const rerenders = [];
  const context = vm.createContext({
    console, encodeURIComponent, URIComponent: undefined,
    esc: value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
    fromName: f => { const m = /^(.*?)\s*<([^>]+)>/.exec(f || ''); return (m ? (m[1].replace(/"/g, '').trim() || m[2]) : f) || 'unknown'; },
    $: () => ({ querySelector: () => null }), _lastMsgs: [], _mailErrors: [],
    preserveMailReadFocus: () => run => run(), renderInbox: () => rerenders.push(1),
    fetch: async () => ({ ok, json: async () => contacts }),
  });
  vm.runInContext(`${block}\nglobalThis.api = { senderEmail, loadSenderPhotos, senderMark, senderLine };`, context);
  return { api: context.api, rerenders };
}

test('a sender with a contact photo shows it, matched by email in any case', async () => {
  const { api } = load([{ id: 'c1', email: 'Mia@Example.com', avatar: 'a.png', updated_at: '2026-11-01T10:00:00' }]);
  await api.loadSenderPhotos();
  const html = api.senderMark('Mia Chen <mia@example.com>');
  assert.match(html, /<img class="contact-av mail-av" src="\/api\/contacts\/c1\/avatar\?v=2026-11-01T10%3A00%3A00"/);
  assert.match(api.senderMark('mia@example.com'), /<img /, 'a bare address matches too');
});

test('without a photo the sender gets a quiet initial, not an image', async () => {
  const { api } = load([{ id: 'c2', email: 'patel@example.com', avatar: '' }]);
  await api.loadSenderPhotos();
  const html = api.senderMark('"Mr. Patel" <patel@example.com>');
  assert.match(html, /<span class="contact-av contact-av-ph mail-av" aria-hidden="true">M<\/span>/);
  assert.doesNotMatch(html, /<img/);
  assert.match(api.senderMark('<x@y.z>'), />X<\/span>/);
});

test('a contact with several addresses shows for each, and the list redraws when photos arrive', async () => {
  const { api, rerenders } = load([{ id: 'c3', email: 'a@x.com, b@x.com;c@x.com', avatar: 'p.png' }]);
  await api.loadSenderPhotos();
  for (const address of ['a@x.com', 'b@x.com', 'c@x.com']) assert.match(api.senderMark(address), /<img /);
  assert.equal(rerenders.length, 0, 'no rows on screen yet, nothing to redraw');
});

test('a failed contacts read leaves every sender on its initial', async () => {
  const { api } = load([], { ok: false });
  await api.loadSenderPhotos();
  assert.doesNotMatch(api.senderMark('mia@example.com'), /<img/);
});
