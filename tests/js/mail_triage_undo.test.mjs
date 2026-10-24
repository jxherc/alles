import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { harness, tick, deferred, scope, account, functionSource, mailSource, reader } from './helpers/mail_workflows_recovery.mjs';
import { plainError } from '../../static/js/util.js';

test('a confirmed send reads "checking delivery…" until the outbox answers, never "unconfirmed"', async () => {
  const h = harness();
  h.add('submitOutgoing');
  h.context.pending = { version: 1, action: 'send', request_id: '00000000-0000-4000-8000-000000000001', recovery_scope: scope, subject: 'hello', account_id: account.id, message: { to: 'a@example.invalid', subject: 'hello', body: 'hi', delay: 8 } };
  h.run('_outboxPending = pending');
  const answer = deferred(), seen = [];
  h.context.mailJson = async () => ({ ok: true });
  h.context._renderScheduled = async () => { seen.push(h.$('mail-outbox-status').textContent); await answer.promise; };
  const sending = h.run('submitOutgoing()');
  await tick();
  assert.deepEqual(seen, ['checking delivery…']);
  answer.resolve(); await sending;
  assert.equal(h.run('_outboxOperation'), null);
});

test('a refused send still says the request is unconfirmed', async () => {
  const h = harness();
  h.add('submitOutgoing');
  h.context.pending = { version: 1, action: 'send', request_id: '00000000-0000-4000-8000-000000000002', recovery_scope: scope, subject: 'hello', account_id: account.id, message: { delay: 8 } };
  h.run('_outboxPending = pending');
  h.context.mailJson = async () => { throw new Error('offline'); };
  h.context._renderScheduled = async () => {};
  await h.run('submitOutgoing()');
  assert.match(h.$('mail-outbox-status').textContent, /delivery request unconfirmed/);
});

test('a recipient chip × says which address it removes and works from the keyboard', async () => {
  const h = harness(); await h.run("compose({ body: 'synthetic', to: 'first@example.invalid, second@example.invalid' })");
  const remove = h.$('mail-main').querySelector('.mc-chip-x');
  assert.equal(remove.getAttribute('aria-label'), 'remove first@example.invalid');
  // pinned to the close icon: kokuen would draw a trash can for a "remove …" ×
  assert.equal(remove.getAttribute('data-kokuen-icon'), 'close');
  remove.focus(); await h.click(remove);
  assert.equal(h.$('mc-to').value, 'second@example.invalid');
  assert.equal(h.document.activeElement, h.$('mail-main').querySelector('.mc-chip-input'));
});

test('a triage undo bar keeps a queued send\'s bar, stays on failure, leaves on success', async () => {
  const h = harness();
  h.add('showTriageUndo');
  h.add('stackUndoBar');
  const send = h.document.createElement('div'); send.setAttribute('id', 'mail-undo-bar'); h.$('mail-view').appendChild(send);
  const results = [false, true];
  let calls = 0;
  h.context.undo = async () => { calls++; return results.shift(); };
  h.run("showTriageUndo('snoozed until tomorrow', undo)");
  const bar = h.$('mail-triage-undo');
  assert.equal(bar.getAttribute('role'), 'status');
  assert.ok(h.$('mail-undo-bar'), 'the send undo is untouched');
  await h.click(bar.querySelector('button'));
  assert.ok(bar.isConnected, 'a failed undo leaves the bar to retry');
  await h.click(bar.querySelector('button'));
  assert.equal(calls, 2);
  assert.equal(bar.isConnected, false);
});

test('a triage undo bar does not vanish under someone using it', () => {
  const h = harness();
  h.add('showTriageUndo');
  h.add('stackUndoBar');
  h.context.undo = async () => true;
  h.run("showTriageUndo('archived', undo)");
  const bar = h.$('mail-triage-undo');
  bar.querySelector('button').focus();
  h.timers.shift()();
  assert.ok(bar.isConnected);
  h.$('mail-compose-btn').focus();
  h.timers.shift()();
  assert.equal(bar.isConnected, false);
});

function restore(listContext, message, last = []) {
  const source = ['restoreMailRow', 'focusMailRow'].map(name => functionSource(name)).join('\n');
  let cache = [{ account_id: 'a', uid: '1', folder: 'INBOX', date_ts: 30 }];
  const rendered = [];
  const context = vm.createContext({
    _listContext: listContext, _lastMsgs: last, _mailErrors: [],
    readCache: () => cache, writeCache: value => { cache = value; },
    _msgTime: row => row.date_ts, renderInbox: rows => rendered.push(Array.from(rows, row => row.uid)),
    sameMail: (row, aid, uid, folder) => row.account_id === aid && row.uid === uid && row.folder === folder,
    $: id => (id === 'mail-list' ? { querySelectorAll: () => [], querySelector: () => null } : null),
  });
  vm.runInContext(source, context);
  context.restoreMailRow(message, 'inbox');
  return { cache: Array.from(cache, row => row.uid), rendered };
}

test('undoing a snooze puts the row back in the list and its cache, in date order', () => {
  const back = { account_id: 'a', uid: '2', folder: 'INBOX', date_ts: 40, snoozed_until: '' };
  const { cache, rendered } = restore('inbox', back, [{ account_id: 'a', uid: '1', folder: 'INBOX', date_ts: 30 }]);
  assert.deepEqual(cache, ['2', '1']);
  assert.deepEqual(rendered, [['1', '2']]);
});

test('a row put back into the snoozed view stays out of the inbox cache, and another view is left alone', () => {
  const snoozed = { account_id: 'a', uid: '2', folder: 'INBOX', date_ts: 40, snoozed_until: '2999-01-01T00:00:00.000Z' };
  assert.deepEqual(restore('inbox', snoozed).cache, ['1']);
  assert.deepEqual(restore('elsewhere', { ...snoozed, snoozed_until: '' }), { cache: ['1'], rendered: [] });
});

test('archive and snooze offer undo; archive undo moves the archived copy back by Message-ID', () => {
  const rows = functionSource('_wireRows');
  assert.match(rows, /showTriageUndo\('archived', undo\(result\.message_id\)\)/);
  assert.match(rows, /mailPost\(`\/api\/mail\/move\/\$\{aid\}`, \{ message_id: messageId, folder: 'Archive', dest: folder \}\)/);
  assert.match(rows, /showTriageUndo\(until \? 'snoozed until tomorrow' : 'snooze ended', undo\)/);
  assert.match(rows, /snooze\(previous\)/);
});

test('a reader that covers the list gets a history entry, and Back closes it onto its row', async () => {
  const h = harness();
  let position = 4;
  const pushes = [], backs = [];
  Object.assign(h.context, {
    pushRouteUrl: url => { pushes.push(url); position++; },
    routeHistoryPosition: () => position,
    history: { back: () => { backs.push(position); position--; } },
    location: { href: 'http://synthetic.invalid/?view=mail', pathname: '/', search: '?view=mail', hash: '' },
  });
  h.$('mail-list').innerHTML = '<div class="mail-row" data-aid="synthetic" data-uid="one" data-folder="INBOX"><button class="mail-open">one</button></div>';
  const row = h.$('mail-list').querySelector('.mail-open');
  h.$('mail-list').hidden = true;   // compact: the reader covers the list
  h.context.mailJson = async url => (url === '/api/mail/accounts' ? [account] : new Promise(() => {}));
  row.focus();
  h.run("openMessage('synthetic', 'one', 'INBOX')");
  await tick();
  assert.deepEqual(pushes, ['/?view=mail']);
  assert.equal(h.run('_readerEntry'), 5);
  // the pane's own back button walks the same entry back instead of leaving it behind
  h.$('mail-list').hidden = false;
  await h.run('backToMailList()');
  assert.deepEqual(backs, [5]);
  assert.ok(h.$('mail-main').firstElementChild, 'the shell closes it on popstate, not the button');
  h.document.activeElement = h.document.body;
  await h.run('loadMail()');
  assert.equal(h.$('mail-main').firstElementChild, null);
  assert.equal(h.run('_readerEntry'), null);
  assert.equal(h.document.activeElement, h.$('mail-list').querySelector('.mail-open'));
});

test('a reader beside the list (desktop) adds no history entry', async () => {
  const h = harness();
  const pushes = [];
  Object.assign(h.context, { pushRouteUrl: url => pushes.push(url), routeHistoryPosition: () => 0 });
  h.context.mailJson = async () => new Promise(() => {});
  h.run("openMessage('synthetic', 'one', 'INBOX')");
  await tick();
  assert.deepEqual(pushes, []);
});

test('mail source has no glyph bullet and names a missing sending account plainly', () => {
  assert.doesNotMatch(mailSource, /title="bullet list">•</);
  assert.match(mailSource, /'no sending account yet'/);
  assert.equal(readFileSync(new URL('../../static/js/mail.js', import.meta.url), 'utf8').includes('＋ sig'), false);
});

test('a message travels as a record id and comes back exact, folder names in any script included', () => {
  const context = vm.createContext({ TextEncoder, TextDecoder, btoa, atob, Uint8Array, String, JSON });
  vm.runInContext(['mailRecordId', 'mailRecordParts'].map(name => functionSource(name)).join('\n'), context);
  for (const [aid, uid, folder] of [['a1b2', '42', 'INBOX'], ['acct', '7', '收件箱/工作'], ['x', '1', '[Gmail]/All Mail']]) {
    const id = context.mailRecordId(aid, uid, folder);
    assert.match(id, /^msg-[A-Za-z0-9_-]+$/);
    assert.deepEqual({ ...context.mailRecordParts(id) }, { aid, folder, uid });
  }
  for (const bad of ['task-1', 'msg-', 'msg-!!', 'msg-' + Buffer.from('[1,2,3]').toString('base64url'), 'msg-bm9wZQ']) assert.equal(context.mailRecordParts(bad), null, bad);
});

test('search opens a message in mail, and a record link when mail lives on another host', async () => {
  const h = harness();
  h.add('openMailFromSearch');
  h.add('mailRecordId');
  const calls = [];
  Object.assign(h.context, {
    TextEncoder, btoa,
    recordTarget: () => null,
    openMessage: async (...args) => { calls.push(['open', ...args.slice(0, 3)]); },
  });
  h.context.window._navigateTo = async view => { calls.push(['nav', view]); return true; };
  assert.equal(await h.run("openMailFromSearch('acct', 9, '')"), true);
  assert.deepEqual(calls, [['nav', 'mail'], ['open', 'acct', '9', 'INBOX']]);
  calls.length = 0;
  h.context.recordTarget = (view, id) => ({ view, id });
  h.context.window._openRecord = async (view, id) => { calls.push(['record', view, id.slice(0, 4)]); return true; };
  assert.equal(await h.run("openMailFromSearch('acct', '9', 'INBOX')"), true);
  assert.deepEqual(calls, [['record', 'mail', 'msg-']]);
});

test('a failed mail read says what happened, not the server\'s words', () => {
  const lines = mailSource.split('\n');
  const one = lines.find(line => line.startsWith('function mailProblem('));
  const context = vm.createContext({ plainError: text => text });
  vm.runInContext(`${one}\n${functionSource('friendlyMailError')}`, context);
  assert.equal(context.mailProblem('[Errno 61] Connection refused'), 'the server refused the connection - check the host and port.');
  assert.equal(context.mailProblem('[Errno 8] something odd'), 'something odd');
  assert.equal(context.mailProblem('no IMAP host configured'), 'no IMAP host configured');
});

test('a send undo and a row undo share one column in either order, and neither covers the other', () => {
  for (const order of [['row', 'send'], ['send', 'row']]) {
    const h = harness();
    for (const name of ['stackUndoBar', 'showTriageUndo', '_showUndoBar']) h.add(name);
    h.context.undo = async () => true;
    h.context.row = { id: 'r1', send_at: '2999-01-01T00:00:00Z' };
    for (const kind of order) h.run(kind === 'row' ? "showTriageUndo('archived', undo)" : `_showUndoBar(row, '${scope}')`);
    const stack = h.$('mail-undo-stack');
    assert.ok(stack, order.join());
    assert.match(stack.style.cssText, /position:fixed/);
    assert.deepEqual(stack.children.map(bar => bar.id), order.map(kind => (kind === 'row' ? 'mail-triage-undo' : 'mail-undo-bar')));
    for (const bar of stack.children) assert.match(bar.style.cssText, /position:static/, 'a bar keeps no fixed spot of its own');
    h.$('mail-triage-undo').remove();
    assert.deepEqual(stack.children.map(bar => bar.id), ['mail-undo-bar'], 'the column closes up');
  }
});

test('a snoozed or archived row hands focus to the row that takes its place', () => {
  const h = harness();
  h.add('preserveMailReadFocus');
  const list = h.$('mail-list');
  const rows = uids => uids.map(uid => `<div class="mail-row" data-aid="a" data-uid="${uid}" data-folder="INBOX"><button class="mail-open">${uid}</button><button data-snooze title="snooze">z</button></div>`).join('');
  list.innerHTML = rows(['1', '2', '3']);
  list.querySelectorAll('[data-snooze]')[1].focus();
  h.context.list = list; h.context.html = rows(['1', '3']);
  h.run('preserveMailReadFocus(list)(() => { list.innerHTML = html; })');
  assert.equal(h.document.activeElement.textContent, '3');
  list.querySelectorAll('[data-snooze]')[1].focus();
  h.context.html = rows(['1']);
  h.run('preserveMailReadFocus(list)(() => { list.innerHTML = html; })');
  assert.equal(h.document.activeElement.textContent, '1', 'the last row went: the new last one');
});

test('a message opened from a record link returns to its own row, not the first', async () => {
  const h = harness();
  h.add('openMailSource');
  Object.assign(h.context, { TextEncoder, TextDecoder, btoa, atob });
  const opened = [];
  h.context.openMessage = async (...args) => { opened.push(args); };
  h.$('mail-list').innerHTML = '<div class="mail-row" data-aid="acct" data-uid="1" data-folder="INBOX"><button class="mail-open">one</button></div><div class="mail-row" data-aid="acct" data-uid="9" data-folder="INBOX"><button class="mail-open">nine</button></div>';
  h.context.mailIdentity = (aid, uid, folder) => JSON.stringify([aid, folder || 'INBOX', String(uid)]);
  const id = h.run("mailRecordId('acct', '9', 'INBOX')");
  assert.equal(await h.run(`openMailSource('${id}')`), true);
  assert.equal(opened[0][5]?.textContent, 'nine');
});

test('in the list, an app password problem points at mail settings, not a button that isn\'t there', () => {
  const context = vm.createContext({});
  vm.runInContext(functionSource('friendlyMailError'), context);
  const list = context.friendlyMailError('[AUTHENTICATIONFAILED] Application-specific password required', true);
  assert.doesNotMatch(list, /get app password|above/);
  assert.match(list, /mail settings/);
  assert.match(context.friendlyMailError('Application-specific password required'), /get app password/);
});

test('the VIP and rule summary marks are svg icons', () => {
  assert.doesNotMatch(mailSource, />\+ VIP</);
  assert.match(mailSource, /\$\{_si\('plus'\)\} VIP<\/button>/);
  assert.match(mailSource, /\$\{_si\('arrow-right'\)\}<span class="sr-only">then<\/span>/);
});

const outRow = (n, status = 'uncertain', day = 10 + n) => ({ id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`, account_id: account.id, to: 'a@example.invalid', cc: '', bcc: '', subject: `m${n}`, body: '', html: '', in_reply_to: '', references: '', send_at: `2026-10-${day}T09:00:00`, status, request_kind: 'send', request_delay: 8 });

test('the outbox strip shows the newest three and a toggle for the rest', () => {
  const h = harness();
  h.context.rows = [1, 2, 3, 4, 5].map(n => outRow(n));
  h.run('_outboxRows = rows; paintOutbox()');
  const strip = h.$('mail-scheduled');
  assert.deepEqual(strip.querySelectorAll('.mail-sched-chip').map(chip => chip.attrs['data-row'].slice(-1)), ['5', '4', '3']);
  const more = h.$('mail-outbox-more');
  assert.equal(more.textContent, '+2 more');
  assert.equal(more.getAttribute('aria-expanded'), 'false');
  h.click(more);
  assert.equal(h.$('mail-scheduled').querySelectorAll('.mail-sched-chip').length, 5);
  assert.equal(h.$('mail-outbox-more').textContent, 'show fewer');
});

test('an uncertain row offers check again and dismiss; a scheduled one only cancel', () => {
  const h = harness();
  h.context.rows = [outRow(1), outRow(2, 'scheduled')];
  h.run('_outboxRows = rows; paintOutbox()');
  const [scheduled, uncertain] = h.$('mail-scheduled').querySelectorAll('.mail-sched-chip');
  assert.deepEqual(scheduled.querySelectorAll('button').map(b => b.textContent.trim()), ['cancel']);
  assert.deepEqual(uncertain.querySelectorAll('button').map(b => b.getAttribute('aria-label')), ['check again: m1', 'dismiss m1']);
  assert.match(mailSource, /\$\{_si\('close'\)\} dismiss<\/button>/);
});

test('dismiss asks first, takes only uncertain rows off the list, and moves focus on', async () => {
  const h = harness();
  for (const name of ['dismissOutgoing', 'focusOutboxNext', 'recheckOutgoing']) h.add(name);
  const posts = [];
  h.context.mailJson = async (url, options = {}) => { posts.push([options.method || 'GET', url]); return { ok: true, status: 'dismissed' }; };
  h.context.rows = [outRow(1), outRow(2), outRow(3, 'scheduled')];
  h.run('_outboxRows = rows; paintOutbox()');
  await h.run(`dismissOutgoing('${outRow(3).id}')`);
  assert.deepEqual(posts, [], 'a scheduled send is never dismissed');
  h.confirm(false);
  await h.run(`dismissOutgoing('${outRow(2).id}')`);
  assert.deepEqual(posts, []);
  assert.match(h.confirms.at(-1), /remove from this list\? it may already have gone out\./);
  h.confirm(true);
  await h.run(`dismissOutgoing('${outRow(2).id}')`);
  assert.equal(posts.length, 1);
  assert.match(posts[0][1], /\/scheduled\/0+-0+-4000-8000-0+2\/cancel\?dismiss=true&recovery_scope=a{64}$/);
  assert.equal(posts[0][0], 'POST');
  assert.deepEqual(h.run('_outboxRows').map(row => row.subject), ['m1', 'm3']);
  // the row after it (in newest-first order) takes focus
  assert.equal(h.document.activeElement.getAttribute('aria-label'), 'check again: m1');
  await h.run(`dismissOutgoing('${outRow(1).id}')`);
  assert.equal(h.document.activeElement.textContent.trim(), 'cancel');
});

test('with nothing left to act on, focus goes to where you write mail', async () => {
  const h = harness();
  for (const name of ['dismissOutgoing', 'focusOutboxNext']) h.add(name);
  h.context.mailJson = async () => ({ ok: true, status: 'dismissed' });
  h.context.rows = [outRow(1)];
  h.run('_outboxRows = rows; paintOutbox()');
  h.confirm(true);
  await h.run(`dismissOutgoing('${outRow(1).id}')`);
  assert.equal(h.document.activeElement.id, 'mail-compose-btn');
});

test('check again reads that one row from the server and repaints it', async () => {
  const h = harness();
  for (const name of ['recheckOutgoing', 'focusOutboxNext']) h.add(name);
  const urls = [];
  h.context.mailJson = async url => { urls.push(url); return { scheduled: [] }; };
  h.context.rows = [outRow(1), outRow(2)];
  h.run('_outboxRows = rows; paintOutbox()');
  await h.run(`recheckOutgoing('${outRow(2).id}')`);
  assert.match(urls[0], /\/api\/mail\/scheduled\?request_id=0+-0+-4000-8000-0+2&recovery_scope=a{64}/);
  assert.deepEqual(h.run('_outboxRows').map(row => row.subject), ['m1']);
  assert.equal(h.notices.at(-1)[0], 'no longer in the outbox');
});

test('closing the accounts panel puts focus back on what opened it, else the mail settings cog', async () => {
  for (const opened of ['cog', 'nothing']) {
    const h = harness();
    const cog = h.document.createElement('button');
    cog.setAttribute('class', 'app-cog'); cog.setAttribute('data-app', 'mail');
    h.$('mail-view').appendChild(cog);
    h.document.activeElement = opened === 'cog' ? cog : h.document.body;
    if (opened === 'cog') { cog.focus(); }
    await h.run('accountsPanel(true)');
    await h.click(h.$('mail-accounts-close'));
    assert.equal(h.document.activeElement, cog, opened);
  }
});

test('while undo bars show, the list gets room at its bottom so its last row can scroll clear', () => {
  const h = harness();
  for (const name of ['stackUndoBar', 'showTriageUndo']) h.add(name);
  const observers = [];
  h.context.MutationObserver = class { constructor(fn) { observers.push(fn); } observe() {} };
  h.context.undo = async () => true;
  h.run("showTriageUndo('archived', undo)");
  h.$('mail-undo-stack').offsetHeight = 62;
  observers.forEach(fn => fn());
  assert.equal(h.$('mail-list').style.paddingBottom, 'calc(62px + 1.7rem)');
  h.$('mail-triage-undo').remove();
  observers.forEach(fn => fn());
  assert.equal(h.$('mail-list').style.paddingBottom, '');
});

test('the accounts panel opened from a menu that has gone starts on add, not <body>', async () => {
  const h = harness();
  h.document.activeElement = h.document.body;
  await h.run('accountsPanel()');
  assert.equal(h.document.activeElement.id, 'mail-add-acct');
});

test('a mail change that fails still says which change it was, offline included', async () => {
  const toasts = [];
  const context = vm.createContext({ plainError, toast: (...args) => toasts.push(args), _mailChanges: new Map(), paintMailChanges() {}, Error, TypeError });
  vm.runInContext(`${functionSource('failedBecause')}\n${functionSource('changeMail')}`, context);
  const fails = error => () => Promise.reject(error);
  const change = request => context.changeMail(null, 'k', request, () => true, () => {}, 'thread unmuted', 'could not confirm unmute');
  await change(fails(new TypeError('Failed to fetch')));
  await change(fails(new TypeError('Load failed')));
  await change(fails(new Error('owned rejected restore')));
  await change(fails(new TypeError("Cannot read properties of undefined (reading 'ok')")));
  await change(fails(new Error('')));
  assert.deepEqual(toasts.map(([text]) => text), [
    'could not confirm unmute. check the connection and try again',
    'could not confirm unmute. check the connection and try again',
    'could not confirm unmute. owned rejected restore',
    'could not confirm unmute. something went wrong. try again',
    'could not confirm unmute. check the mailbox before trying again',
  ]);
  assert.ok(toasts.every(([, kind]) => kind === 'error'));
  // the toast runs plainError over the whole line again; it has to come through whole
  for (const [text] of toasts) assert.equal(plainError(text), text);
});

test('the VIP button is a toggle: aria-pressed carries on and off, the name and label stay', async () => {
  const h = harness();
  Object.getPrototypeOf(h.$('mail-view')).removeAttribute ??= function (key) { delete this.attrs[key]; };
  const base = h.context.mailJson;
  let vips = [];
  h.context.mailJson = async (url, ...rest) => {
    if (url !== '/api/mail/vips') return base(url, ...rest);
    if (!vips) throw new Error('could not read VIP senders');
    return { vips };
  };
  const vipOf = async () => { const vip = (await reader(h)).querySelector('#mail-vip'); await tick(); return vip; };
  let vip = await vipOf();
  assert.equal(vip.getAttribute('aria-pressed'), 'false');
  assert.equal(vip.getAttribute('aria-label'), 'VIP sender');
  assert.equal(vip.textContent.trim(), 'VIP');
  vips = ['Sender@example.invalid'];
  vip = await vipOf();
  assert.equal(vip.getAttribute('aria-pressed'), 'true');
  assert.equal(vip.getAttribute('aria-label'), 'VIP sender');
  assert.equal(vip.textContent.trim(), 'VIP');
  // a failed read isn't a toggle yet: it's named by what it does
  vips = null;
  vip = await vipOf();
  assert.equal(vip.getAttribute('aria-pressed'), null);
  assert.equal(vip.getAttribute('aria-label'), null);
  assert.equal(vip.textContent, 'retry VIP status');
  assert.match(mailSource, /\$\{_si\(on \? 'star-fill' : 'plus'\)\} VIP/);
});
