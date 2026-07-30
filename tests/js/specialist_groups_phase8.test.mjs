import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  GROUP_DEFINITIONS,
  addDateKeyDays,
  financeActualPresentation,
  groupIdentifierFor,
  groupRouteFor,
  mailboxAddress,
  normalizeGroupSection,
  planCommitments,
  releaseSpecialistLegacyView,
} from '../../static/js/specialist_groups.js';
import { configureLocalization } from '../../static/js/i18n.js';

const specialistSource = readFileSync(
  new URL('../../static/js/specialist_groups.js', import.meta.url),
  'utf8',
);
const specialistHtml = readFileSync(
  new URL('../../static/index.html', import.meta.url),
  'utf8',
);
const kokuenCss = readFileSync(
  new URL('../../static/kokuen.css', import.meta.url),
  'utf8',
);
const appSource = readFileSync(
  new URL('../../static/js/app.js', import.meta.url),
  'utf8',
);

test('Inbox contact matching extracts mailbox addresses from display names', () => {
  assert.equal(mailboxAddress('Alice Example <ALICE@example.com>'), 'alice@example.com');
  assert.equal(mailboxAddress('plain@example.com'), 'plain@example.com');
  assert.doesNotMatch(specialistSource, /toLocaleLowerCase/);
  assert.doesNotMatch(kokuenCss, /content:\s*["']selected["']/);
});

test('Phase 12 defines exactly the nine approved specialist workbenches', () => {
  assert.deepEqual(Object.keys(GROUP_DEFINITIONS), [
    'plan', 'inbox', 'library', 'health', 'finance', 'docs', 'files', 'vault', 'server',
  ]);
  assert.deepEqual(GROUP_DEFINITIONS.plan.sections, ['overview', 'week', 'board', 'calendar', 'tasks', 'reminders', 'days']);
  assert.deepEqual(GROUP_DEFINITIONS.inbox.sections, ['overview', 'mail', 'contacts']);
  assert.deepEqual(GROUP_DEFINITIONS.library.sections, ['overview', 'books', 'read']);
  assert.deepEqual(GROUP_DEFINITIONS.health.sections, ['overview', 'health', 'habits']);
  assert.deepEqual(GROUP_DEFINITIONS.finance.sections, ['overview', 'money', 'subs', 'imports']);
  assert.deepEqual(GROUP_DEFINITIONS.docs.sections, ['notes', 'journal']);
  assert.deepEqual(GROUP_DEFINITIONS.files.sections, ['files', 'gallery']);
  assert.deepEqual(GROUP_DEFINITIONS.vault.sections, ['items']);
  assert.deepEqual(GROUP_DEFINITIONS.server.sections, ['overview', 'services', 'search', 'backups', 'updates', 'logs', 'activity', 'watch', 'policy']);
});

test('Plan seven-day boundaries use date-only UTC arithmetic', () => {
  assert.equal(addDateKeyDays('2026-12-28', 7), '2027-01-04');
  assert.equal(addDateKeyDays('2026-03-07', 7), '2026-03-14');
  assert.equal(addDateKeyDays('2026-02-30', 7), '');
  assert.match(specialistSource, /const sevenDayEndKey = addDateKeyDays\(today, 7\)/);
  assert.doesNotMatch(specialistSource, /new Date\(`\$\{today\}T12:00:00`\)/);
});

test('Plan preserves timezone-less commitment wall dates and times', () => {
  configureLocalization({ language: 'en', region: 'TW', timezone: 'America/New_York' });
  try {
    const [commitment] = planCommitments([
      { id: 'event-1', title: 'morning review', start_dt: '2026-07-23T09:00' },
    ], [], []);
    assert.equal(commitment.date, '2026-07-23');
    assert.equal(commitment.time, '09:00');
  } finally {
    configureLocalization({ language: 'en', region: 'TW', timezone: '' });
  }
});

test('specialist workbenches show one app name and use the universal shell', () => {
  const headings = {
    'plan-title': 'plan',
    'inbox-title': 'inbox',
    'library-title': 'library',
    'health-group-title': 'health',
    'finance-title': 'finance',
    'docs-workbench-title': 'docs',
    'files-workbench-title': 'files',
    'vault-workbench-title': 'vault',
    'server-workbench-title': 'server',
  };
  for (const [id, label] of Object.entries(headings)) {
    assert.match(
      specialistHtml,
      new RegExp(`<h1 class="specialist-app-name" id="${id}"[^>]*>${label}</h1>`),
      id,
    );
  }
  assert.equal((specialistHtml.match(/class="specialist-app-head"/g) || []).length, 9);
  assert.equal((specialistHtml.match(/class="specialist-app-name"/g) || []).length, 9);
  assert.doesNotMatch(specialistHtml, /specialist-group-head/);
  assert.equal((specialistHtml.match(/data-specialist-home/g) || []).length, 0);
  assert.equal((specialistHtml.match(/data-kokuen-surface="specialist"/g) || []).length, 9);
  assert.match(kokuenCss, /body:is\(\s*\[data-app="plan"\][^]*?\.main > \.topbar[^]*?display: none !important/);
  assert.doesNotMatch(appSource, /querySelectorAll\('\[data-specialist-home\]'\)/);
  assert.match(appSource, /const SHELL_GROUPS = Object\.freeze/);
});

test('all nine specialist workbenches share one persistent accessible sidebar toggle', () => {
  const toggles = [...specialistHtml.matchAll(/<button class="specialist-sidebar-toggle"[^>]+>/g)]
    .map(match => match[0]);
  assert.equal(toggles.length, 9);
  for (const toggle of toggles) {
    assert.match(toggle, /data-specialist-sidebar-toggle/);
    assert.match(toggle, /aria-expanded="true"/);
    assert.match(toggle, /aria-controls="[^"]+-tabs"/);
    assert.match(toggle, /aria-label="hide [^"]+ navigation"/);
  }
  assert.equal(new Set(toggles.map(toggle => toggle.match(/aria-controls="([^"]+)"/)?.[1])).size, 9);
  assert.match(specialistSource, /SPECIALIST_SIDEBAR_STORAGE_KEY = 'alles-specialist-sidebar-hidden'/);
  assert.match(specialistSource, /window\.localStorage\.setItem\(SPECIALIST_SIDEBAR_STORAGE_KEY/);
  assert.match(specialistSource, /root\.dataset\.sidebarCollapsed/);
  assert.match(kokuenCss, /\[data-sidebar-collapsed="true"\]/);
});

test('the shared sidebar state also collapses nested Docs and Files navigation rails', () => {
  assert.match(
    kokuenCss,
    /\[data-sidebar-collapsed="true"\] \.specialist-workbench-rail\s*\{\s*display: none;/,
  );
  assert.match(
    kokuenCss,
    /\[data-sidebar-collapsed="true"\] \.specialist-workbench\s*\{\s*grid-template-columns: minmax\(18rem, 1\.5fr\) minmax\(14rem, 0\.75fr\);/,
  );
  assert.match(
    kokuenCss,
    /#docs-workbench-view\[data-sidebar-collapsed="true"\] #wiki-view \.docs-nav-panel\s*\{\s*display: none;/,
  );
  assert.match(
    kokuenCss,
    /#files-workbench-view\[data-sidebar-collapsed="true"\] #files-view \.files-phase7-location-panel\s*\{\s*display: none;/,
  );
  assert.match(
    kokuenCss,
    /#files-workbench-view\[data-sidebar-collapsed="true"\] #files-view \.files-phase7-workbench\s*\{\s*grid-template-columns: minmax\(0, 1fr\) auto;/,
  );
});

test('specialist workbenches collapse before their fixed tracks can overflow', () => {
  assert.match(
    kokuenCss,
    /@media \(max-width: 824px\) \{\s*\.specialist-workbench \{ grid-template-columns: minmax\(0, 1fr\); \}/,
  );
  assert.match(specialistSource, /activeTab\?\.scrollIntoView\?\.\(\{ block: 'nearest', inline: 'nearest' \}\)/);
  assert.match(
    kokuenCss,
    /@media \(max-width: 760px\) \{\s*#plan-view\[data-kokuen-surface="specialist"\][^]*?\.specialist-group \{\s*grid-template-columns: minmax\(0, 1fr\);\s*grid-template-rows: var\(--k-app-header\) var\(--k-control\) minmax\(0, 1fr\);/,
  );
});

test('legacy app identifiers resolve to a group without losing their subsection', () => {
  const expected = {
    plan: ['plan', 'overview'], 'plan-week': ['plan', 'week'], 'plan-board': ['plan', 'board'], calendar: ['plan', 'calendar'], tasks: ['plan', 'tasks'], reminders: ['plan', 'reminders'],
    inbox: ['inbox', 'overview'], mail: ['inbox', 'mail'], contacts: ['inbox', 'contacts'],
    library: ['library', 'overview'], books: ['library', 'books'], read: ['library', 'read'],
    health: ['health', 'overview'], 'health-overview': ['health', 'overview'],
    'health-log': ['health', 'health'], habits: ['health', 'habits'],
    finance: ['finance', 'overview'], 'finance-overview': ['finance', 'overview'],
    money: ['finance', 'money'], subs: ['finance', 'subs'], imports: ['finance', 'imports'],
    docs: ['docs', 'notes'], wiki: ['docs', 'notes'], journal: ['docs', 'journal'],
    files: ['files', 'files'], photos: ['files', 'gallery'], 'files-gallery': ['files', 'gallery'],
    vault: ['vault', 'items'], secrets: ['vault', 'items'],
    server: ['server', 'overview'], system: ['server', 'overview'], activity: ['server', 'activity'], watch: ['server', 'watch'], days: ['plan', 'days'],
  };
  for (const [view, [group, section]] of Object.entries(expected)) {
    assert.deepEqual(groupRouteFor(view), { group, section }, view);
  }
  assert.deepEqual(groupRouteFor('days'), { group: 'plan', section: 'days' });
});

test('Aide reminders has a routable identifier while legacy reminders stay with Plan', () => {
  const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  assert.match(app, /const grouped = groupRouteFor\(v\)/);
  assert.match(app, /const dest = groupedRoute\?\.host \?\? viewToSub\(v\)/);
  assert.match(app, /AIDE_TOOL_VIEWS = new Set\(\[[^]*?'aide-reminders'/);
  assert.match(app, /v === 'aide-reminders'\) showRemindersView\(\)/);
  assert.match(app, /function renderLocalRoute\(route\) \{[^]*?return renderLocalView\(route\.view, route\)/);
  assert.match(app, /if \(route\.section \|\| singleHost\(\)\) url\.searchParams\.set\('view', identifier\)/);
  assert.doesNotMatch(app, /const aideReminder =/);
  assert.match(app, /releaseSpecialistLegacyView\('plan', 'reminders'\)/);
  assert.equal(typeof releaseSpecialistLegacyView, 'function');
  assert.deepEqual(groupRouteFor('reminders'), { group: 'plan', section: 'reminders' });
});

test('combined inbox account IDs use one stable string identity', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /account_id: String\(accounts\[index\]\?\.id \?\? ''\)/);
  assert.match(source, /value: String\(account\.id \?\? ''\)/);
});

test('new group overview links do not collide with legacy app identifiers', () => {
  assert.equal(groupIdentifierFor('finance', 'overview'), 'finance-overview');
  assert.equal(groupIdentifierFor('health', 'overview'), 'health-overview');
  assert.equal(groupIdentifierFor('health', 'health'), 'health-log');
  assert.equal(groupIdentifierFor('finance', 'money'), 'money');
  assert.equal(groupIdentifierFor('plan', 'overview'), 'plan');
  assert.equal(groupIdentifierFor('plan', 'week'), 'plan-week');
  assert.equal(groupIdentifierFor('plan', 'board'), 'plan-board');
  assert.equal(groupIdentifierFor('docs', 'notes'), 'docs');
  assert.equal(groupIdentifierFor('files', 'gallery'), 'files-gallery');
  assert.equal(groupIdentifierFor('server', 'services'), 'server-services');
  assert.equal(groupIdentifierFor('server', 'activity'), 'activity');
});

test('invalid or unavailable group subsections safely return to overview', () => {
  assert.equal(normalizeGroupSection('plan', 'tasks'), 'tasks');
  assert.equal(normalizeGroupSection('plan', ''), 'overview');
  assert.equal(normalizeGroupSection('plan', 'money'), 'overview');
  assert.equal(normalizeGroupSection('made-up', 'tasks'), 'overview');
  assert.equal(normalizeGroupSection('docs', ''), 'notes');
  assert.equal(normalizeGroupSection('files', 'unknown'), 'files');
});

test('Finance Actual status exposes only safe actions for each authority state', () => {
  const base = {
    service: { available: true, installed: true, running: true, healthy: true, version: '26.7.0' },
    ledger: { mode: 'alles', base_currency_code: 'CAD', run: null },
  };
  assert.deepEqual(financeActualPresentation({
    service: { available: true, installed: false, node_version: '22.17.0' },
    ledger: base.ledger,
  }).actions, ['install']);
  assert.deepEqual(financeActualPresentation(base).actions, ['stage', 'backup', 'stop']);
  assert.deepEqual(financeActualPresentation({
    ...base, ledger: { ...base.ledger, base_currency_code: '' },
  }).actions, ['backup', 'stop']);
  assert.deepEqual(financeActualPresentation({
    ...base, ledger: { ...base.ledger, run: { id: 'run-1', status: 'ready', links: 12 } },
  }).actions, ['cutover', 'backup', 'stop']);
  assert.deepEqual(financeActualPresentation({
    ...base, ledger: { ...base.ledger, mode: 'actual', legacy_read_only: true },
  }).actions, ['backup', 'rollback-ledger']);
  for (const [service, expected] of [
    [{ available: false, node_version: '18.0.0' }, ['rollback-ledger']],
    [{ available: true, installed: false }, ['install', 'rollback-ledger']],
    [{ available: true, installed: true, running: false, healthy: false }, ['start', 'rollback-ledger']],
    [{ available: true, installed: true, running: true, healthy: false }, ['restart', 'rollback-ledger']],
  ]) {
    assert.deepEqual(financeActualPresentation({
      service, ledger: { ...base.ledger, mode: 'actual', legacy_read_only: true },
    }).actions, expected);
  }
  assert.equal(financeActualPresentation({
    service: { available: false, node_version: '18.0.0' }, ledger: base.ledger,
  }).actions.length, 0);
  assert.doesNotMatch(specialistSource, /base_currency_code:\s*ledger\.base_currency_code\s*\|\|\s*['"]CAD['"]/);
});

test('Plan composes events, tasks, and reminders into one stable ordered agenda', () => {
  const rows = planCommitments(
    [{ id: 'e1', title: 'dentist', start_dt: '2026-07-18T09:45:00', location: 'Zhongshan' }],
    [
      { id: 't1', title: 'review', due_date: '2026-07-18T08:30:00', status: 'open' },
      { id: 't2', title: 'unscheduled', due_date: '', status: 'open' },
      { id: 't3', title: 'already done', due_date: '2026-07-18T07:30:00', done: true },
      { id: 't4', title: 'cancelled work', due_date: '2026-07-18T07:45:00', stage: 'cancelled' },
      { id: 't5', title: 'completed work', due_date: '2026-07-18T08:00:00', status: 'COMPLETED' },
    ],
    [{ id: 'r1', text: 'passport', trigger_at: '2026-07-18T21:15:00' }],
  );
  assert.deepEqual(rows.map(row => row.type), ['task', 'event', 'reminder', 'task']);
  assert.equal(rows[0].time, '08:30');
  assert.equal(rows.at(-1).date, '');
  assert.doesNotMatch(rows.map(row => row.title).join(' '), /already done|cancelled work|completed work/);
});

test('Plan derives offset timestamps in the local calendar rather than copying their prefix', () => {
  const timestamp = '2026-07-18T23:30:00-04:00';
  const local = new Date(timestamp);
  const pad = part => String(part).padStart(2, '0');
  const expectedDate = `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}`;
  const expectedTime = `${pad(local.getHours())}:${pad(local.getMinutes())}`;
  const [row] = planCommitments(
    [{ id: 'offset-event', title: 'handoff', start_dt: timestamp }],
    [],
    [],
  );
  assert.equal(row.date, expectedDate);
  assert.equal(row.time, expectedTime);
});

test('Plan buckets timestamps in the configured Alles timezone', () => {
  configureLocalization({ timezone: 'Asia/Tokyo' });
  try {
    const [row] = planCommitments(
      [{ id: 'configured-zone', title: 'handoff', start_dt: '2026-07-18T23:30:00Z' }],
      [],
      [],
    );
    assert.equal(row.date, '2026-07-19');
    assert.equal(row.time, '08:30');
  } finally {
    configureLocalization({});
  }
});

test('Plan sorts wall times and offset timestamps in one configured timezone', () => {
  configureLocalization({ timezone: 'Asia/Tokyo' });
  try {
    const rows = planCommitments([
      { id: 'offset', title: 'later', start_dt: '2026-07-18T23:30:00Z' },
      { id: 'wall', title: 'earlier', start_dt: '2026-07-19T07:00:00' },
    ], [], []);
    assert.deepEqual(rows.map(row => row.title), ['earlier', 'later']);
  } finally {
    configureLocalization({});
  }
});

test('Plan loads expanded calendar occurrences for its eight-day window', () => {
  assert.match(specialistSource, /_json\(request, '\/api\/calendar\/agenda\?days=8'\)/);
  assert.match(specialistSource, /_asArray\(agendaPayload, 'days'\)\.flatMap\(day => _asArray\(day, 'events'\)\)/);
});

test('ambiguous statement matches expose explicit duplicate and import-new decisions', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /resolve-match/);
  assert.match(source, /treat as duplicate/);
  assert.match(source, /import as new/);
  assert.match(source, /JSON\.stringify\(\{ decision \}\)/);
  assert.match(source, /if \(resolutionBusy\) return/);
  assert.match(source, /resolutionButtons\.forEach\(button => \{ button\.disabled = true; \}\)/);
});

test('interrupted Actual imports expose explicit keep, delete, and partial undo recovery', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /resolve-recovery/);
  assert.match(source, /accept edited Actual transaction as replacement/);
  assert.match(source, /delete it and retry/);
  assert.match(source, /undo applied rows/);
  assert.match(source, /confirmDialog/);
  assert.match(source, /if \(recoveryBusy\) return/);
  assert.match(source, /if \(receiptMutationBusy\) return/);
  assert.match(source, /receiptMutationButtons\.forEach\(button => \{ button\.disabled = true; \}\)/);
});

test('foreign-currency import review uses an explicit accessible evidence form', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /finance-import-conversion/);
  assert.match(source, /base_amount_text/);
  assert.match(source, /rate_text/);
  assert.match(source, /rate_date/);
  assert.match(source, /conversion rate source/);
  assert.match(source, /\/rows\/\$\{encodeURIComponent\(row\.id\)\}\/conversion/);
  assert.match(source, /save reviewed conversion/);
});

test('specialist subsection roots stay mounted so they can be revisited', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.doesNotMatch(source, /slot\.replaceChildren/);
  assert.match(source, /legacyRoot\.parentElement !== slot/);
  assert.match(source, /slot\.append\(legacyRoot\)/);
});

test('only the latest async specialist overview may replace live controls', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /const renderNonce = Symbol\(`\$\{group\}:\$\{selected\}`\)/);
  assert.match(source, /current\.renderNonce !== renderNonce \|\| current\.section !== section/);
  assert.match(source, /overview\.replaceChildren\(\.\.\.staged\.childNodes\)/);
});

test('Finance distinguishes unavailable data and gates apply until review is complete', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /subscriptions unavailable:/);
  assert.match(source, /accounts unavailable:/);
  assert.match(source, /receipt\.counts\.conflicts === 0/);
  assert.match(source, /receipt\.counts\.applying === 0/);
  assert.match(source, /import could not be applied/);
  assert.match(source, /reported \? \(ledger\.mode === 'actual' \? 'Actual' : 'Alles'\) : 'not reported'/);
  assert.match(source, /status unavailable/);
  assert.match(source, /previewMessage\.textContent = error\?\.message \|\| 'import preview could not be created'/);
  assert.match(source, /previewMessage\.setAttribute\('aria-live', 'polite'\)/);
  assert.match(source, /Array\.isArray\(profileData\?\.profiles\)/);
  assert.match(source, /import setup unavailable:/);
  assert.match(source, /retry import setup/);
  assert.match(source, /if \(!profiles\.length\)/);
  assert.match(source, /const selectedProfile = profiles\.find/);
  assert.match(source, /item\.currency_code \|\| item\.currency/);
  assert.match(source, /file\.size > 5 \* 1024 \* 1024/);
  assert.match(source, /statement files must be 5 MiB or smaller/);
  assert.match(source, /try \{ receipts = await _json\(request, '\/api\/finance\/imports'\); \}/);
  assert.match(source, /new imports still work/);
  assert.doesNotMatch(source, /profileData\.profiles\.find/);
  assert.match(source, /const generation = \+\+previewGeneration/);
  assert.match(source, /const capturedAccountId = accountId/);
  assert.match(source, /const capturedProfileId = profileId/);
  assert.match(source, /if \(generation !== previewGeneration\) return/);
});

test('specialist overviews keep partial failures distinct from honest empty states', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /partial data:/);
  assert.match(source, /calendar data could not be loaded/);
  assert.match(source, /mail accounts unavailable/);
  assert.match(source, /contacts unavailable/);
  assert.match(source, /saved reading could not be loaded/);
  assert.match(source, /measurements unavailable/);
  assert.match(source, /habit status unavailable/);
  assert.match(source, /no items were returned by available sources/);
});

test('a committed import receipt survives an independent history refresh failure', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  const showReceipt = source.slice(
    source.indexOf('const showReceipt = async receipt =>'),
    source.indexOf("preview.addEventListener('click'"),
  );
  assert.match(showReceipt, /_renderImportReceipt\(receiptTarget, receipt/);
  assert.match(showReceipt, /try \{/);
  assert.match(showReceipt, /recent receipts could not be refreshed; the receipt above is current/);
  assert.doesNotMatch(showReceipt, /throw/);
});

test('notification imports require an explicit account-suffix confirmation action', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /confirm account ending/i);
  assert.match(source, /\/confirm-account/);
  assert.match(source, /account_id: receipt\.account_id/);
  assert.match(source, /account_suffix: parsed\.account_suffix \|\| ''/);
  assert.match(source, /account suffix could not be confirmed/);
});

test('statement imports prefer the selected account currency over a profile fallback', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  const accountLookup = source.indexOf('const selectedAccount = accounts.find');
  const accountCurrency = source.indexOf('selectedAccount?.currency_code', accountLookup);
  const profileFallback = source.indexOf('selectedProfile?.default_currency_code', accountLookup);
  assert.ok(accountLookup >= 0);
  assert.ok(accountCurrency > accountLookup);
  assert.ok(profileFallback > accountCurrency);
});

test('Plan quick capture reports create and refresh failures without losing a retry', () => {
  const source = readFileSync(
    new URL('../../static/js/specialist_groups.js', import.meta.url),
    'utf8',
  );
  const capture = source.slice(source.indexOf("capture.addEventListener('submit'"), source.indexOf("const workbench =", source.indexOf("capture.addEventListener('submit'")));
  assert.match(capture, /catch \(error\)/);
  assert.match(capture, /task could not be added/);
  assert.match(capture, /task saved; plan could not refresh/);
  assert.match(capture, /input\.value = ''/);
  assert.match(capture, /input\.focus\(\)/);
});
