import assert from 'node:assert/strict';
import test from 'node:test';
import { harness, tick, deferred, reader, scope, account, proposal } from './helpers/mail_workflows_recovery.mjs';

const canceledRow = () => ({ id: '00000000-0000-4000-8000-000000000099', account_id: account.id,
  status: 'canceled', request_kind: 'schedule', send_at: '2099-01-01T09:00:00Z',
  to: 'recipient@example.invalid', cc: '', bcc: '', subject: 'retained cancellation', body: 'exact cancellation body', html: '', in_reply_to: '', references: '' });
async function beginCancel(h) {
  const gate = deferred(), row = canceledRow();
  h.context.row = row;
  h.context.mailJson = async url => { if (url === '/api/mail/vips') return { vips: [] }; assert.match(url, /\/scheduled\/.+\/cancel\?/); return gate.promise; };
  const cancel = h.run("cancelOutgoing({ ...row, status: 'scheduled' })");
  await tick();
  return { gate, cancel, row };
}
async function finishCancel(h, attempt) {
  attempt.gate.resolve({ ok: true }); await attempt.cancel;
  h.run('_outboxKnown = row');
  await h.run('finishOutgoing(_outboxPending, row)');
}

test('F1 late cancellation preserves a newer reader and explicit open restores the exact message', async () => {
  const h = harness(); await reader(h, 'original');
  const attempt = await beginCancel(h);
  const newer = await reader(h, 'newer');
  await finishCancel(h, attempt);
  assert.equal(h.$('mail-main').firstElementChild, newer);
  assert.ok(h.run('_outboxPending'));
  assert.equal(h.$('mail-outbox-open').textContent, 'open canceled message');
  await h.click(h.$('mail-outbox-open'));
  assert.equal(h.$('mc-to').value, attempt.row.to);
  assert.equal(h.$('mc-subj').value, attempt.row.subject);
  assert.equal(h.$('mc-html').innerHTML, attempt.row.body);
  assert.equal(h.run('_outboxPending'), null);
});

test('F1 automatic restoration remains available to the original pane owner', async () => {
  const h = harness(); await reader(h);
  const attempt = await beginCancel(h); await finishCancel(h, attempt);
  assert.equal(h.$('mc-subj').value, attempt.row.subject);
  assert.equal(h.run('_outboxPending'), null);
});

test('F1 a cancellation retry after navigation cannot acquire the newer pane', async () => {
  const h = harness(); await reader(h);
  const first = await beginCancel(h); first.gate.reject(new Error('synthetic lost reply')); await first.cancel;
  const newer = await reader(h, 'newer');
  h.context.mailJson = async () => ({ ok: true });
  await h.run('cancelOutgoing()'); h.run('_outboxKnown = row');
  await h.run('finishOutgoing(_outboxPending, row)');
  assert.equal(h.$('mail-main').firstElementChild, newer);
  assert.ok(h.$('mail-outbox-open'));
});

test('F1 reloaded cancellation has explicit recovery without automatic pane takeover', async () => {
  const h = harness(); const original = await reader(h);
  h.context.row = canceledRow();
  h.run(`storePendingOutgoing({ version: 1, action: 'cancel', request_id: row.id, recovery_scope: '${scope}', subject: row.subject }); _outboxKnown = row;`);
  await h.run('finishOutgoing(_outboxPending, row)');
  assert.equal(h.$('mail-main').firstElementChild, original);
  assert.ok(h.$('mail-outbox-open'));
});

test('F1 a newer unsaved composer and settings pane survive cancellation settlement', async () => {
  for (const pane of ['composer', 'rules']) {
    const h = harness(); await reader(h); const attempt = await beginCancel(h);
    if (pane === 'composer') await h.run("compose({ body: 'newer unsent text' })");
    else { h.context.mailJson = async url => url === '/api/mail/rules' ? { rules: [], recovery_scopes: [scope] } : { enabled: false, subject: '', body: '' }; await h.run('rulesPanel()'); h.$('mr-value').value = 'unsaved rule'; }
    const root = h.$('mail-main').firstElementChild;
    await finishCancel(h, attempt);
    assert.equal(h.$('mail-main').firstElementChild, root, pane);
    assert.ok(h.run('_outboxPending'), pane);
  }
});

test('F2 declined account navigation retains its registration, generation and exact input', async () => {
  const h = harness(); await h.run('accountsPanel()'); h.run('acctForm(_accounts[0])');
  const root = h.$('mail-main').firstElementChild, editor = h.context._accountEditor;
  h.$('ma-name').value = 'unsaved café 日本語'; const generation = h.generation();
  h.confirm(false); assert.equal(await h.run('prepareMailNavigation()'), false);
  assert.equal(h.generation(), generation); assert.equal(h.context._accountEditor, editor);
  assert.equal(h.$('mail-main').firstElementChild, root); assert.equal(h.$('ma-name').value, 'unsaved café 日本語');
  await h.click(h.$('ma-close')); await tick();
  assert.equal(h.confirms.length, 2); assert.equal(h.context._accountEditor, editor);
});

test('F2 accepted account departure removes old controls and reentry mounts a working close handler', async () => {
  const h = harness(); await h.run('accountsPanel()'); const old = h.$('mail-main').firstElementChild;
  assert.equal(await h.run('prepareMailNavigation()'), true);
  assert.equal(old.isConnected, false);
  h.$('mail-view').hidden = true;
  await h.run('prepareMailNavigation()'); // navigateTo checks Mail again while entering from Contacts.
  h.$('mail-view').hidden = false;
  await h.run('loadMail()');
  assert.notEqual(h.$('mail-main').firstElementChild, old);
  await h.click(h.$('mail-accounts-close'));
  assert.equal(h.$('mail-main').firstElementChild, null);
});

test('F2 rules reentry remounts live save handlers and does not add a duplicate after confirmed save', async () => {
  const h = harness(); const saved = [];
  h.context.mailJson = async (url, options = {}) => {
    if (url === '/api/mail/accounts') return [account];
    if (url === '/api/mail/vacation') return { enabled: false, subject: '', body: '' };
    assert.equal(url, '/api/mail/rules');
    if (!options.method) return { rules: saved, recovery_scopes: [scope] };
    const body = JSON.parse(options.body), row = { ...body, id: body.request_id }; saved.push(row); return row;
  };
  await h.run('rulesPanel()'); const old = h.$('mail-main').firstElementChild;
  await h.run('prepareMailNavigation()'); assert.equal(old.isConnected, false);
  h.$('mail-view').hidden = true; await h.run('prepareMailNavigation()'); h.$('mail-view').hidden = false;
  await h.run('loadMail()'); assert.notEqual(h.$('mail-main').firstElementChild, old);
  h.$('mr-value').value = 'synthetic match'; await h.click(h.$('mr-add')); await tick();
  assert.equal(saved.length, 1); assert.equal(h.$('mr-value').value, '');
  assert.match(h.$('mr-status').textContent, /rule saved/);
  await h.click(h.$('mr-add')); await tick(); assert.equal(saved.length, 1);
});

test('F2 rule and vacation edits survive a declined leave, including whitespace edits', async () => {
  for (const field of ['mr-value', 'mr-arg', 'mv-subject', 'mv-body']) {
    const h = harness(); await h.run('rulesPanel()'); h.$(field).value = field === 'mr-value' ? '  ' : 'unsaved café 日本語';
    const root = h.$('mail-main').firstElementChild, generation = h.generation(), value = h.$(field).value;
    h.confirm(false); assert.equal(await h.run('prepareMailNavigation()'), false, field);
    assert.equal(h.$('mail-main').firstElementChild, root); assert.equal(h.generation(), generation); assert.equal(h.$(field).value, value);
  }
});

test('F2 edits made during a shared leave dialog invalidate acceptance without invalidating the form', async () => {
  const h = harness(); await h.run('accountsPanel()'); h.run('acctForm(_accounts[0])'); h.$('ma-name').value = 'first';
  const gate = deferred(); h.confirm(gate.promise); const generation = h.generation();
  const first = h.run('prepareMailNavigation()'), second = h.run('prepareMailNavigation()');
  await tick(); assert.equal(h.confirms.length, 1);
  h.$('ma-name').value = 'later'; gate.resolve(true);
  assert.equal(await first, false); assert.equal(await second, false);
  assert.equal(h.generation(), generation); assert.equal(h.$('ma-name').value, 'later'); assert.ok(h.context._accountEditor);
});

test('F2 list reload of a still-mounted settings pane retains working handlers', async () => {
  const h = harness(); await h.run('accountsPanel()'); const root = h.$('mail-main').firstElementChild, generation = h.generation();
  await h.run('loadMail()'); assert.equal(h.generation(), generation); assert.equal(h.$('mail-main').firstElementChild, root);
  await h.click(h.$('mail-accounts-close')); assert.equal(root.isConnected, false);
});

test('F3 a preview response after accepted compose intent cannot open over the old reader', async () => {
  const h = harness(); await reader(h); const preview = deferred(), signature = deferred();
  h.context.fetch = async url => url === '/api/mail/make-task' ? preview.promise : signature.promise;
  const capturing = h.click(h.$('mail-to-task')); await tick();
  const composing = h.run('compose()'); await tick();
  preview.resolve({ ok: true, json: async () => proposal }); await capturing;
  assert.equal(h.document.querySelector('.capture-overlay'), null);
  signature.resolve({ json: async () => ({ mail_signature: '' }) }); await composing;
  assert.ok(h.$('mc-subj'));
});

test('F3 ownership is rechecked after the capture helper pending-store await', async () => {
  const h = harness(); await reader(h); const scopes = deferred(), signature = deferred();
  h.context.pendingStore = () => scopes.promise;
  h.context.fetch = async url => url === '/api/mail/make-task' ? { ok: true, json: async () => proposal } : signature.promise;
  const capturing = h.click(h.$('mail-to-task')); await tick();
  const composing = h.run('compose()'); await tick();
  scopes.resolve({ pending: null, clear() {}, put() {} }); await capturing;
  assert.equal(h.document.querySelector('.capture-overlay'), null); assert.equal(h.context.active, false);
  signature.resolve({ json: async () => ({ mail_signature: '' }) }); await composing;
});

test('F3 existing three-argument capture callers still open and close normally', async () => {
  const h = harness(); h.context.proposal = proposal; let saves = 0; h.context.onSaved = () => saves++;
  assert.equal(await h.run("openCaptureReview(proposal, $('mail-compose-btn'), onSaved)"), true);
  assert.ok(h.document.querySelector('.capture-overlay'));
  await h.click(h.$('capture-cancel'));
  assert.equal(h.document.querySelector('.capture-overlay'), null); assert.equal(h.context.active, false); assert.equal(saves, 0);
});

for (const action of ['save', 'send', 'schedule']) test(`F4 ${action} freezes pending To/Cc/Bcc text before payload and snapshot`, async () => {
  const h = harness(); await h.run("compose({ body: 'synthetic message' })");
  for (const role of ['to', 'cc', 'bcc']) h.$('mail-main').querySelector(`.mc-chipfield[data-role="${role}"]`).querySelector('.mc-chip-input').value = `${role}@example.invalid`;
  h.$('mc-subj').value = 'exact café 日本語';
  if (action === 'schedule') { h.$('mc-sched-wrap').style.display = ''; h.$('mc-sched-date').value = '2099-01-01'; h.$('mc-sched-time').value = '09:00'; }
  await h.click(h.$(`mc-${action}`));
  const pending = action === 'save' ? h.writes[0]?.pending : h.run('_outboxPending');
  assert.ok(pending, action); const body = action === 'save' ? pending : pending.message;
  for (const role of ['to', 'cc', 'bcc']) assert.equal(body[role], `${role}@example.invalid`);
  const snapshot = action === 'save' ? h.writes[0].snapshot : h.run('mailEditor().outgoingSnapshot');
  assert.equal(snapshot, h.run('mailEditor().snapshot()'));
  for (const timer of h.timers.splice(0)) timer();
  assert.equal(snapshot, h.run('mailEditor().snapshot()'));
});

test('F4 keyboard autocomplete clears the query before a later save commit', async () => {
  const h = harness(); await h.run("compose({ body: 'synthetic message' })");
  const input = h.$('mail-main').querySelector('.mc-chip-input'); input.focus(); input.value = 'chosen';
  await input.emit('input'); await input.emit('keydown', { key: 'ArrowDown' }); await input.emit('keydown', { key: 'Enter' });
  assert.equal(input.value, ''); assert.equal(h.$('mc-to').value, 'chosen@example.invalid');
  await h.click(h.$('mc-save')); assert.equal(h.writes[0].pending.to, 'chosen@example.invalid');
});

test('F4 retry retains the original frozen payload despite newer uncommitted recipients', async () => {
  const h = harness(); await h.run("compose({ body: 'synthetic message', to: 'first@example.invalid' })");
  await h.click(h.$('mc-save')); const pending = h.writes[0].pending;
  h.$('mail-main').querySelector('.mc-chip-input').value = 'later@example.invalid';
  h.context.sameDraftIntent = (a, b) => a === b;
  await h.click(h.$('mc-save')); assert.equal(h.writes.length, 1); assert.equal(h.context._draftPending, pending);
  assert.equal(pending.to, 'first@example.invalid'); assert.equal(h.$('mail-main').querySelector('.mc-chip-input').value, 'later@example.invalid');
});

for (const filter of ["loadCategory('work')", "loadByLabel('synthetic label')", "loadSmart('flagged')", 'loadDrafts()']) {
  for (const pane of ['composer', 'account', 'rules', 'vacation']) test(`F5 ${filter} preserves the mounted ${pane} editor and its generation`, async () => {
    const h = harness(); let field;
    if (pane === 'composer') { await h.run("compose({ body: 'synthetic body' })"); field = h.$('mc-subj'); }
    else if (pane === 'account') { await h.run('accountsPanel()'); h.run('acctForm(_accounts[0])'); field = h.$('ma-name'); }
    else { await h.run('rulesPanel()'); field = h.$(pane === 'rules' ? 'mr-value' : 'mv-body'); }
    field.value = 'exact unsaved café 日本語'; const root = h.$('mail-main').firstElementChild, generation = h.generation();
    await h.run(filter);
    assert.equal(h.$('mail-main').firstElementChild, root); assert.equal(h.generation(), generation); assert.equal(field.value, 'exact unsaved café 日本語');
  });
}

test('F5 filter changes still cancel a reader and its generation', async () => {
  const h = harness(); const root = await reader(h), generation = h.generation();
  await h.run("loadSmart('flagged')"); assert.equal(root.isConnected, false); assert.ok(h.generation() > generation);
});

for (const change of ['search', 'label', 'account', 'generation', 'same']) test(`F6 draft deletion completion respects ${change} list ownership`, async () => {
  const h = harness(), gate = deferred(); let reads = 0;
  h.context._filter = 'drafts';
  h.context.loadDraftRecovery = async () => { reads++; return { recovery_scopes: [scope], drafts: [{ id: 'draft-one', account_id: account.id, to: 'recipient@example.invalid', subject: 'synthetic draft', body: 'body', revision: 'b'.repeat(64) }] }; };
  await h.run('loadDrafts()');
  h.context.mailJson = async (url, options) => { assert.equal(options.method, 'DELETE'); return gate.promise; };
  const deleting = h.click(h.$('mail-list').querySelector('.mail-draft-del')); await tick();
  if (change === 'search') h.context._searchView = 'subject:café';
  if (change === 'label') h.context._labelFilter = 'synthetic label';
  if (change === 'account') h.context._active = 'other-synthetic';
  if (change === 'generation') h.context._listGeneration++;
  const before = reads; gate.resolve({ ok: true }); await deleting;
  assert.equal(reads, before + (change === 'same' ? 1 : 0));
  if (change === 'search') assert.equal(h.context._searchView, 'subject:café');
  if (change === 'label') assert.equal(h.context._labelFilter, 'synthetic label');
});

test('F2 declining composer departure preserves its generation and newer unsaved input', async () => {
  const h = harness(); await h.run("compose({ body: 'initial' })");
  h.$('mc-html').innerHTML = 'newer unsaved body'; const generation = h.generation(), editor = h.run('mailEditor()');
  h.confirm(false); assert.equal(await h.run('prepareMailNavigation()'), false);
  assert.equal(h.generation(), generation); assert.equal(h.run('mailEditor()'), editor);
  assert.equal(h.$('mc-html').innerHTML, 'newer unsaved body');
});

test('F2 two accepted leave intents share one dialog and only the latest commits departure', async () => {
  const h = harness(); await h.run("compose({ body: 'initial' })"); h.$('mc-html').innerHTML = 'edit';
  const gate = deferred(); h.confirm(gate.promise);
  const first = h.run('prepareMailNavigation()'), last = h.run('prepareMailNavigation()');
  await tick(); assert.equal(h.confirms.length, 1); gate.resolve(true);
  assert.equal(await first, false); assert.equal(await last, true); assert.equal(h.run('mailEditor()'), null);
});

for (const key of ['Enter', 'Tab', ',', ';', ' ', 'blur']) test(`F4 normal ${JSON.stringify(key)} recipient commit and existing chips remain exact`, async () => {
  const h = harness(); await h.run("compose({ body: 'synthetic body', to: 'first@example.invalid' })");
  const input = h.$('mail-main').querySelector('.mc-chip-input'); input.value = 'second@example.invalid';
  if (key === 'blur') { await input.emit('blur'); for (const timer of h.timers.splice(0)) timer(); }
  else await input.emit('keydown', { key });
  assert.equal(input.value, ''); assert.equal(h.$('mc-to').value, 'first@example.invalid, second@example.invalid');
  await h.click(h.$('mc-save'));
  assert.equal(h.writes[0].pending.to, 'first@example.invalid, second@example.invalid');
});

const accountData = () => ({ accounts: [account], recovery_scopes: [scope] });
const ruleData = () => ({ rules: [], recovery_scopes: [scope] });
const vacationData = () => ({ enabled: false, subject: '', body: '' });
const storeData = () => ({ pending: null, clear() {}, put() {} });

function initialLoad(h, kind) {
  const gate = deferred();
  const pane = kind.startsWith('accounts-') ? 'accounts' : 'rules';
  let reads = 0;
  if (kind === 'accounts-read') h.context.readAccountContext = async () => ++reads === 1 ? gate.promise : accountData();
  if (kind === 'rules-read' || kind === 'vacation-read') {
    const target = kind === 'rules-read' ? '/api/mail/rules' : '/api/mail/vacation';
    const normal = h.context.mailJson;
    h.context.mailJson = async url => url === target && ++reads === 1 ? gate.promise : normal(url);
  }
  if (kind.endsWith('-write')) {
    const clear = () => {
      if (kind === 'accounts-write') h.context._accountRecovery.write = null;
      else if (kind === 'rule-write') h.run('_ruleWrite = null');
      else h.context._vacationWrite = null;
    };
    h.context.earlierWrite = gate.promise.finally(clear);
    if (kind === 'accounts-write') h.context._accountRecovery.write = h.context.earlierWrite;
    else if (kind === 'rule-write') h.run('_ruleWrite = earlierWrite');
    else h.context._vacationWrite = h.context.earlierWrite;
  }
  const settle = () => gate.resolve(kind === 'accounts-read' ? accountData() : kind === 'rules-read' ? ruleData() : kind === 'vacation-read' ? vacationData() : { ok: true });
  return { pane, settle, opened: h.run(pane === 'accounts' ? 'accountsPanel()' : 'rulesPanel()') };
}

for (const kind of ['accounts-read', 'accounts-write', 'rules-read', 'vacation-read', 'rule-write', 'vacation-write']) {
  for (const returnWhen of ['before settlement', 'after settlement']) test(`MAIL-C1 ${kind}: leave and return ${returnWhen} remounts settings`, async () => {
    const h = harness();
    const opening = initialLoad(h, kind);
    await tick();
    const loading = h.$('mail-main').firstElementChild;
    assert.ok(loading?.isConnected, 'driver reached the initial settings placeholder');
    assert.match(loading.textContent, /loading (accounts|rules)/);
    assert.equal(await h.run('prepareMailNavigation()'), true);
    h.$('mail-view').hidden = true;
    if (returnWhen === 'after settlement') { opening.settle(); await opening.opened; }
    assert.equal(await h.run('prepareMailNavigation()'), true);
    h.$('mail-view').hidden = false;
    const returning = h.run('loadMail()');
    await tick();
    if (returnWhen === 'before settlement') opening.settle();
    await Promise.all([opening.opened, returning]);
    assert.equal(loading.isConnected, false, 'MAIL-C1 obsolete loading owner must be disposed');
    assert.ok(h.$(opening.pane === 'accounts' ? 'mail-accounts-close' : 'mr-add'), 'MAIL-C1 reentry must mount live settings');
    if (opening.pane === 'accounts') h.run('acctForm(_accounts[0])');
    const field = h.$(opening.pane === 'accounts' ? 'ma-name' : 'mr-value');
    field.value = 'exact reopened unsaved café 日本語';
    const root = h.$('mail-main').firstElementChild, generation = h.generation();
    h.confirm(false);
    assert.equal(await h.run('prepareMailNavigation()'), false);
    assert.equal(h.$('mail-main').firstElementChild, root);
    assert.equal(h.generation(), generation);
    assert.equal(field.value, 'exact reopened unsaved café 日本語');
  });
}

for (const kind of ['accounts-read', 'rules-read']) test(`MAIL-C1 normal ${kind} settles without navigation`, async () => {
  const h = harness(), opening = initialLoad(h, kind);
  await tick(); opening.settle(); await opening.opened;
  assert.ok(h.$(opening.pane === 'accounts' ? 'mail-accounts-close' : 'mr-add'));
});

function captureProposal(kind) {
  return kind === 'task' ? proposal : { kind: 'event', found: true,
    candidate: { title: 'synthetic event', start_dt: '2099-01-01T09:00', end_dt: '2099-01-01T10:00', all_day: false, location: '', description: '' },
    source: proposal.source };
}
function captureDoubles(h, kind, signature) {
  const preview = deferred(), scopes = deferred();
  const calls = { signature: 0, preview: 0, scope: 0 };
  h.context.editorDates = candidate => ({ start: candidate.start_dt, end: candidate.end_dt });
  h.context.pendingStore = () => { calls.scope++; return scopes.promise; };
  h.context.fetch = async url => {
    if (url === '/api/settings') { calls.signature++; return signature.promise; }
    assert.equal(url, kind === 'task' ? '/api/mail/make-task' : '/api/mail/extract-event');
    calls.preview++; return preview.promise;
  };
  return { preview, scopes, calls,
    settlePreview: () => preview.resolve({ ok: true, json: async () => captureProposal(kind) }),
    settleScope: () => scopes.resolve(storeData()),
  };
}

for (const kind of ['task', 'event']) test(`MAIL-C2 ${kind} clicked after accepted compose cannot open over its held signature read`, async () => {
  const h = harness(); const oldReader = await reader(h);
  const signature = deferred(), capture = captureDoubles(h, kind, signature);
  const composing = h.run('compose()');
  await tick();
  assert.equal(capture.calls.signature, 1, 'driver reached the accepted composer signature await');
  assert.equal(oldReader.isConnected, true, 'driver retained the stale reader during that await');
  const capturing = h.click(h.$(kind === 'task' ? 'mail-to-task' : 'mail-to-cal'));
  await tick(); capture.settlePreview(); await tick(); capture.settleScope(); await capturing;
  try {
    assert.equal(h.document.querySelector('.capture-overlay'), null, 'MAIL-C2 stale reader must not open a capture overlay');
    assert.equal(h.context.active, false);
    assert.equal(capture.calls.preview, 0, 'retired reader must not start a preview');
    assert.equal(capture.calls.scope, 0);
  } finally {
    signature.resolve({ json: async () => ({ mail_signature: '' }) });
    await composing;
  }
  assert.ok(h.$('mc-subj'));
});

for (const kind of ['task', 'event']) {
  for (const refreshWhen of ['before click', 'while preview pending']) test(`MAIL-C2 normal ${kind} capture survives preserved-reader refresh ${refreshWhen}`, async () => {
    const h = harness(); const sameReader = await reader(h);
    const signature = deferred(), capture = captureDoubles(h, kind, signature);
    if (refreshWhen === 'before click') await h.run('loadMail()');
    const capturing = h.click(h.$(kind === 'task' ? 'mail-to-task' : 'mail-to-cal'));
    await tick();
    if (refreshWhen === 'while preview pending') await h.run('loadMail()');
    assert.equal(h.$('mail-main').firstElementChild, sameReader);
    capture.settlePreview(); await tick(); capture.settleScope(); await capturing;
    assert.ok(h.document.querySelector('.capture-overlay'), 'ordinary refresh must preserve the current reader capture');
    assert.equal(capture.calls.preview, 1); assert.equal(capture.calls.scope, 1);
    assert.equal(capture.calls.signature, 0);
    await h.click(h.$('capture-cancel'));
    assert.equal(h.document.querySelector('.capture-overlay'), null); assert.equal(h.context.active, false);
  });
}

test('MAIL-C2 existing three-argument capture caller still opens and closes', async () => {
  const h = harness(); h.context.proposal = proposal; h.context.onSaved = () => assert.fail('cancel must not save');
  assert.equal(await h.run("openCaptureReview(proposal, $('mail-compose-btn'), onSaved)"), true);
  assert.ok(h.document.querySelector('.capture-overlay'));
  await h.click(h.$('capture-cancel'));
  assert.equal(h.document.querySelector('.capture-overlay'), null); assert.equal(h.context.active, false);
});

async function mailReaderReturn(h) {
  assert.equal(await h.run('prepareMailNavigation()'), true);
  h.$('mail-view').hidden = true;
  assert.equal(await h.run('prepareMailNavigation()'), true);
  h.$('mail-view').hidden = false;
  await h.run('loadMail()');
}

async function returnedReader(h, previous) {
  if (h.$('mail-main').firstElementChild === previous) return previous;
  assert.equal(previous.isConnected, false, 'a retired reader must be removed');
  assert.equal(h.$('mail-main').firstElementChild, null, 'retirement returns to the message list');
  return reader(h);
}

async function captureReturnedReader(h, kind, root) {
  const capture = captureDoubles(h, kind, deferred());
  await h.run('loadMail()');
  assert.equal(h.$('mail-main').firstElementChild, root, 'ordinary refresh retains the current reader');
  const capturing = h.click(h.$(kind === 'task' ? 'mail-to-task' : 'mail-to-cal'));
  await tick();
  await h.run('loadMail()');
  assert.equal(h.$('mail-main').firstElementChild, root, 'refresh during preview retains its reader');
  capture.settlePreview(); await tick(); capture.settleScope(); await capturing;
  assert.ok(h.document.querySelector('.capture-overlay'), 'MAIL-V2-C1 displayed or explicitly reopened reader must accept capture');
  assert.equal(capture.calls.preview, 1); assert.equal(capture.calls.scope, 1);
  await h.click(h.$('capture-cancel'));
  assert.equal(h.document.querySelector('.capture-overlay'), null); assert.equal(h.context.active, false);
}

for (const kind of ['task', 'event']) {
  test(`MAIL-V2-C1 ${kind} reader remains actionable or is retired after accepted leave and return`, async () => {
    const h = harness(), original = await reader(h);
    await h.run('loadMail()');
    assert.equal(h.$('mail-main').firstElementChild, original, 'direct refresh is not accepted departure');
    await mailReaderReturn(h);
    const current = await returnedReader(h, original);
    await captureReturnedReader(h, kind, current);

    const signature = deferred(), stale = captureDoubles(h, kind, signature);
    const button = h.$(kind === 'task' ? 'mail-to-task' : 'mail-to-cal');
    const composing = h.run('compose()');
    await tick();
    assert.equal(stale.calls.signature, 1, 'driver reached held signature after accepted compose');
    assert.equal(current.isConnected, true, 'reader still exists during the signature await');
    try {
      await h.click(button);
      assert.equal(stale.calls.preview, 0, 'accepted compose retires the old reader action');
      await h.run('loadMail()');
      await h.click(button);
      assert.equal(stale.calls.preview, 0, 'background reload must not rearm the retired action');
      assert.equal(h.document.querySelector('.capture-overlay'), null);
      assert.equal(h.context.active, false);
    } finally {
      signature.resolve({ json: async () => ({ mail_signature: '' }) });
      await composing;
    }
  });

  test(`MAIL-V2-C1 ${kind} pending capture stays retired across return while a fresh action works`, async () => {
    const h = harness(), original = await reader(h);
    const stale = captureDoubles(h, kind, deferred());
    const capturing = h.click(h.$(kind === 'task' ? 'mail-to-task' : 'mail-to-cal'));
    await tick(); assert.equal(stale.calls.preview, 1);
    await mailReaderReturn(h);
    stale.settlePreview(); await tick(); stale.settleScope(); await capturing;
    assert.equal(h.document.querySelector('.capture-overlay'), null, 'accepted departure retires the earlier capture');
    assert.equal(stale.calls.scope, 0); assert.equal(h.context.active, false);
    await captureReturnedReader(h, kind, await returnedReader(h, original));
  });
}
