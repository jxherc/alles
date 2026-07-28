import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const reminders = readFileSync(new URL('../../static/js/reminders.js', import.meta.url), 'utf8');
const skills = readFileSync(new URL('../../static/js/skills.js', import.meta.url), 'utf8');
const scheduled = readFileSync(new URL('../../static/js/aidescheduled.js', import.meta.url), 'utf8');
const brain = readFileSync(new URL('../../static/js/brain.js', import.meta.url), 'utf8');
const slash = readFileSync(new URL('../../static/js/slash.js', import.meta.url), 'utf8');
const voice = readFileSync(new URL('../../static/js/voice.js', import.meta.url), 'utf8');
const specialistSources = Object.fromEntries(
  ['tasks', 'calendar', 'docs', 'vault', 'contacts', 'subs', 'money', 'days', 'activity',
    'system', 'watch', 'habits', 'read', 'books', 'health', 'mail', 'photos']
    .map(name => [name, readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8')]),
);

test('global Escape leaves the Files preview to its own cleanup handler', () => {
  const previewCheck = app.indexOf("document.getElementById('files-preview-modal')");
  const previewReturn = app.indexOf("if (filesPreview?.style.display !== 'none') return", previewCheck);
  const globalClose = app.indexOf('closeAllModals(); closeSettings()', previewCheck);
  assert.ok(previewCheck >= 0);
  assert.ok(previewReturn > previewCheck);
  assert.ok(globalClose > previewReturn);
});

test('only Aide-owned routes retain the Aide shell on a single host', () => {
  assert.match(app, /const AIDE_TOOL_VIEWS = new Set\([^;]+\);/);
  assert.match(app, /AIDE_TOOL_VIEWS\.has\(v\)/);
  assert.doesNotMatch(
    app,
    /document\.body\.dataset\.space === 'aide' && !\['home', 'today', 'andromeda'\]\.includes\(v\)/,
  );
});

test('boot canonicalizes grouped app links without losing their subsection', () => {
  const boot = app.match(/async function _boot\([^]*?\n}/)?.[0] || '';
  assert.match(boot, /const groupedIdentifier = groupedRoute[\s\S]*?groupIdentifierFor/);
  assert.match(boot, /const groupedRoute = groupRouteFor\(initialRoute\.hashOwner\)/);
  assert.match(boot, /_syncSpecialistGroupUrl\(initialRoute, groupedIdentifier\)/);
  assert.match(boot, /_consumeParams\(groupRouteFor\(_v\) \? \['app'\] : \['app', 'view'\]\)/);
});

test('generic modal dismissal excludes the Files preview lifecycle', () => {
  assert.match(app, /\.modal-overlay:not\(#settings-modal\):not\(#files-preview-modal\)/);
});

test('the Apps home action returns to Home before closing the drawer', () => {
  assert.match(
    app,
    /app-drawer-close'\)\?\.addEventListener\('click', returnHomeFromAppDrawer\)/,
  );
  const action = app.match(/async function returnHomeFromAppDrawer\(\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(action, /navigateTo\(_afterlifeFlags\.afterlife_today \? 'today' : 'home'\)/);
  assert.match(action, /if \(navigated\) closeAppDrawer\(\)/);
});

test('Apps drawer destinations close only after guarded navigation succeeds', () => {
  const drawer = app.match(/function _renderAppDrawer\(\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(drawer, /\['everyday', \['plan', 'inbox', 'wiki'\]\]/);
  assert.match(drawer, /\['personal', \['files', 'library', 'health'\]\]/);
  assert.match(drawer, /\['manage', \['finance', 'vault', 'system'\]\]/);
  assert.match(drawer, /\['system', \{ name: 'server', desc: 'services, backups, and updates' \}\]/);
  assert.match(drawer, /addEventListener\('click', async \(\) =>/);
  assert.match(drawer, /const navigated = await navigateTo\(tile\.view\)/);
  assert.match(drawer, /if \(staysOnPage && navigated\) closeAppDrawer\(\)/);
});

test('voice recording owns Escape before asynchronous cancellation work', () => {
  const listener = app.match(
    /document\.addEventListener\('keydown', event => \{[\s\S]*?cancelVoiceRecording\(\);\s*\}\);/,
  )?.[0] || '';
  assert.match(listener, /event\.stopImmediatePropagation\(\)/);
  assert.ok(listener.indexOf('event.stopImmediatePropagation()') < listener.indexOf('cancelVoiceRecording()'));
  assert.doesNotMatch(listener, /await\s+import/);
});

test('the stop action cancels a microphone take that is still starting', () => {
  const stop = voice.match(/export function stopRecording\(\) \{[\s\S]*?\n}/)?.[0] || '';
  assert.match(stop, /if \(_starting \|\| _settling\) cancelRecording\(\)/);
});

test('voice cancellation isolates recorder data and aborts active transcription', () => {
  assert.match(voice, /ondataavailable = e => \{ if \(take === _take\) chunks\.push\(e\.data\); \}/);
  assert.match(voice, /_whisperDone\(take, chunks\)/);
  assert.match(voice, /signal: controller\.signal/);
  assert.match(voice, /_transcriptionAbort\?\.abort\(\)/);
  assert.match(voice, /e\?\.name !== 'AbortError' && take === _take/);
  assert.match(voice, /try \{ _sr\.start\(\); \} catch \{[^]*?_settling = false/);
  assert.match(voice, /_settling = Boolean\(_sr\)/);
  assert.match(voice, /setTimeout\(\(\) => \{\s*timedOut = true;\s*controller\.abort\(\);\s*}, 60_000\)/);
  assert.match(voice, /clearTimeout\(timeout\)/);
  assert.match(voice, /const msg = await r\.text\(\)\.catch\(\(\) => ''\);\s*if \(take !== _take\) return;/);
  assert.match(voice, /toast\('transcription timed out', 'error'\)/);
});

test('voice cancellation stops before requesting the fallback microphone', () => {
  const start = voice.match(/export async function startRecording\(\)[\s\S]*?\n}\n/)?.[0] || '';
  const fallback = start.indexOf("getUserMedia({ audio: true })");
  assert.ok(fallback > 0);
  assert.ok(start.lastIndexOf('if (take !== _take) return;', fallback) >= 0);
});

test('voice permission denial never requests the default microphone a second time', () => {
  const start = voice.match(/export async function startRecording\(\)[\s\S]*?\n}\n/)?.[0] || '';
  const fallback = start.indexOf("getUserMedia({ audio: true })");
  assert.ok(fallback > 0);
  assert.match(start.slice(0, fallback), /retryDefault = Boolean\(micId/);
  assert.match(start.slice(0, fallback), /'NotAllowedError', 'SecurityError'/);
  assert.match(start.slice(0, fallback), /if \(!retryDefault\)/);
});

test('voice setup failure releases the microphone and resets recording state', () => {
  const start = voice.match(/export async function startRecording\(\)[\s\S]*?\n}\n/)?.[0] || '';
  assert.match(start, /catch \(error\) \{/);
  assert.match(start, /_recording = false;/);
  assert.match(start, /_stream\?\.getTracks\(\)\.forEach\(track => track\.stop\(\)\)/);
  assert.match(start, /_stream = null;/);
  assert.match(start, /voice recording could not start/);
});

test('specialist request accounting is explicitly scoped without a global fetch override', () => {
  const showView = app.match(/function showView\(viewId,[\s\S]*?\n}\n\s*\nconst showChatView/)?.[0] || '';
  assert.doesNotMatch(app, /window\.fetch\s*=/);
  assert.doesNotMatch(app, /let _specialistRun\b/);
  assert.match(showView, /const request = \(\.\.\.args\) => _trackSpecialistRequest\(run, \.\.\.args\)/);
  assert.match(showView, /const track = callback => callback\(\)/);
  assert.match(showView, /result = track\(\(\) => onShow\?\.\(track, request\)\)/);
  assert.match(app, /async function trackedImport\(track, request, load, initialize\)[\s\S]*?return track\(\(\) => initialize\(module, request\)\)/);
  assert.match(app, /const showSystemView[\s\S]{0,220}trackedImport\(track, request/);
});

test('non-specialist loaders receive safe passthrough helpers during boot', () => {
  const showView = app.match(/function showView\(viewId,[\s\S]*?\n}\n\s*\nasync function trackedImport/)?.[0] || '';
  assert.match(
    showView,
    /if \(!root\.dataset\.specialistApp[\s\S]*?onShow\?\.\(callback => callback\(\), _specialistFetch\)/,
  );
});

test('specialist request accounting propagates through awaits and ignores stale generations', () => {
  const showView = app.match(/function showView\(viewId,[\s\S]*?\n}\n\s*\nasync function trackedImport/)?.[0] || '';
  assert.match(showView, /const request = \(\.\.\.args\) => _trackSpecialistRequest\(run, \.\.\.args\)/);
  assert.match(showView, /onShow\?\.\(track, request\)/);
  assert.match(showView, /stateRoot\.dataset\.specialistRun/);
  assert.match(showView, /if \(stateRoot\.dataset\.specialistRun !== run\.id\) return/);
  assert.match(app, /const showFilesView[\s\S]{0,280}Promise\.all\(\[initFiles\(request\), loadFiles\(undefined, request\)\]\)/);
});

test('single-host chat transitions always restore Aide chrome', () => {
  const showChatView = app.match(/const showChatView = \(\) => \{[\s\S]*?\n};/)?.[0] || '';
  assert.match(showChatView, /if \(singleHost\(\)\) _shChrome\('chat', \{ onAide: true \}\)/);
});

test('slash memories reuses the exact Settings module instance loaded by the app', () => {
  assert.match(app, /from '\.\/slash\.js\?v=283'/);
  assert.match(app, /from '\.\/settings\.js\?v=289'/);
  assert.match(slash, /import\('\.\/settings\.js\?v=289'\)/);
  assert.doesNotMatch(slash, /settings\.js\?v=236/);
});

test('specialist request accounting treats every non-ok response as a failure', () => {
  const wrapper = app.match(/async function _trackSpecialistRequest\(run, \.\.\.args\) \{[\s\S]*?\n}/)?.[0] || '';
  assert.match(wrapper, /if \(!response\.ok\) run\.failures \+= 1/);
  assert.doesNotMatch(wrapper, /response\.status >= 500/);
});

test('all four Aide tool pages report their initial API failures to showView', () => {
  assert.match(app, /showBrainView[\s\S]{0,180}loadBrainPanel\(request\)/);
  assert.match(app, /showRemindersView[\s\S]{0,220}initReminderPanel\(request\)/);
  assert.match(app, /showSkillsView[\s\S]{0,260}module\.initSkills\(request\)/);
  assert.match(app, /showAideScheduledView[\s\S]{0,320}module\.initAideScheduled\(request\)/);
  assert.match(reminders, /loadReminders\(fetcher = fetch\)/);
  assert.match(reminders, /await fetcher\('\/api\/reminders'\)/);
  assert.match(skills, /initSkills\(fetcher = fetch\)/);
  assert.match(skills, /throw error/);
  assert.match(scheduled, /initAideScheduled\(fetcher = fetch\)/);
  assert.match(scheduled, /throw error/);
  assert.match(brain, /loadBrainPanel\(fetcher = fetch\)/);
  assert.match(brain, /fetcher\('\/api\/memories'\)/);
  assert.match(brain, /_loadCurrentHistory\(fetcher\)/);
});

test('every real specialist app reports its initial requests through the scoped fetcher', () => {
  const wiring = {
    tasks: /showTasksView[\s\S]{0,180}loadTasks\(request\)/,
    calendar: /showCalendarView[\s\S]{0,200}loadCalendar\(request\)/,
    docs: /showWikiView[\s\S]{0,300}initDocs\(section, request\)/,
    vault: /showVaultView[\s\S]{0,200}loadVaultView\(request\)/,
    contacts: /showContactsView[\s\S]{0,220}loadContacts\('', request\)/,
    subs: /showSubsView[\s\S]{0,260}initSubsPanel\(request\)/,
    money: /showMoneyView[\s\S]{0,280}initMoneyPanel\(request\)/,
    days: /showDaysView[\s\S]{0,260}initDaysPanel\(request\)/,
    activity: /showActivityView[\s\S]{0,280}initActivity\(request\)/,
    system: /showSystemView[\s\S]{0,280}initSystem\(request\)/,
    watch: /showWatchView[\s\S]{0,260}initWatch\(request\)/,
    habits: /showHabitsView[\s\S]{0,260}initHabits\(request\)/,
    read: /showReadView[\s\S]{0,240}initRead\(request\)/,
    books: /showBooksView[\s\S]{0,240}initBooks\(request\)/,
    health: /showHealthView[\s\S]{0,250}initHealth\(request\)/,
    mail: /showMailView[\s\S]{0,200}loadMail\(request\)/,
    photos: /showPhotosView[\s\S]{0,220}loadPhotos\(request\)/,
  };
  for (const [name, pattern] of Object.entries(wiring)) {
    assert.match(app, pattern, `${name} must receive the scoped request`);
    assert.match(
      specialistSources[name],
      /(?:load|init)[A-Za-z]+\([^)]*fetcher\s*=\s*fetch/,
      `${name} must accept a scoped fetcher`,
    );
  }
});

test('System polling starts even while the first stats or settings request is pending', () => {
  const system = specialistSources.system;
  const init = system.match(/export async function initSystem\(fetcher = fetch\) \{[^]*?\n}/)?.[0] || '';
  assert.match(init, /void tick\(fetcher\)/);
  assert.match(init, /_timer = setInterval\(\(\) => tick\(_systemFetcher\), 1500\)/);
  assert.ok(init.indexOf('void tick(fetcher)') < init.indexOf('_timer = setInterval'));
  assert.doesNotMatch(init, /await tick\(fetcher\)/);
});

test('Today capture uses atomic unique creation and preserves refresh warnings', () => {
  const today = specialistSources.today || readFileSync(new URL('../../static/js/today.js', import.meta.url), 'utf8');
  assert.doesNotMatch(today, /\/api\/vault-md\/names/);
  assert.match(today, /body: \{ path: title, content: `\$\{text\.trim\(\)\}\\n`, unique: true \}/);
  assert.match(today, /toast\(asTask \? t\('home\.task_added'\) : t\('home\.note_saved'\), 'success'\);\s*await load\(\)/);
  assert.doesNotMatch(today, /if \(refreshed\) showStatus/);
  assert.match(today, /partial\.length[\s\S]*?return false/);
});

test('Read keeps its scoped fetcher for feeds and later actions', () => {
  const read = specialistSources.read;
  assert.match(read, /let _fetcher = fetch/);
  assert.match(read, /initRead\(fetcher = fetch\)[^]*_fetcher = fetcher/);
  assert.match(read, /loadFeeds\(\)[^]*?_fetcher\('\/api\/read\/feeds'/);
  assert.doesNotMatch(read, /\bfetch\(`?\/api\/read/);
});

test('cross-subdomain document asks use an opaque one-time context code', () => {
  assert.match(app, /fetch\('\/api\/auth\/context-handoff'/);
  assert.match(app, /target\.searchParams\.set\('ctx',\s*code\)/);
  assert.doesNotMatch(app, /target\.searchParams\.set\('(ask|doc|doc_hash)'/);
  assert.doesNotMatch(app, /bootParams\.get\('(doc|doc_hash)'\)/);
  assert.doesNotMatch(app, /kind:\s*'vault_document',[^]*bootParams/);
});

test('Andromeda handoffs await guarded navigation and initialized search', () => {
  const handoff = app.match(/window\._askInChat = async[\s\S]*?\n};/)?.[0] || '';
  assert.match(handoff, /canOpenAndromedaInline[\s\S]*?await navigateTo\('andromeda'\)/);
  assert.match(handoff, /urlForApp\('andromeda'\)/);
  assert.match(handoff, /const scopedProjectId = validatedProjectId\(/);
  assert.match(handoff, /newChat\(\{ projectId: scopedProjectId \}\)/);
  assert.match(handoff, /_replaceHistoryUrl\(withProjectContext\(location\.href, scopedProjectId\)\)/);
  assert.ok(
    handoff.indexOf('newChat({ projectId: scopedProjectId })')
      < handoff.indexOf('await module.runAndromedaSearch(q, { documentScope })'),
  );
  assert.match(handoff, /await module\.runAndromedaSearch\(q, \{ documentScope \}\)/);
  assert.match(handoff, /await _navigateWithHandoff\(/);
  assert.doesNotMatch(handoff, /location\.href\s*=/);
  assert.match(app, /await renderLocalView\(v\)/);
  assert.match(app, /return Promise\.resolve\(result\)\.then/);
});

test('scoped web searches use one-time handoff state and retain scope for Aide follow-up', () => {
  const handoff = app.match(/window\._askInChat = async[\s\S]*?\n};/)?.[0] || '';
  const andromeda = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(handoff, /web && documentScope && !contextHandoffRedeemed/);
  assert.match(
    handoff,
    /body: JSON\.stringify\(\{ ask: q, web: true, document_scope: documentScope \}\)/,
  );
  assert.ok(handoff.indexOf('context-handoff') < handoff.indexOf('encodeURIComponent(q)'));
  assert.match(andromeda, /documentScope: options\.documentScope \|\| null/);
  assert.match(andromeda, /_askInChat\(request, false, _state\.documentScope, projectId\)/);
});

test('boot-time Aide handoffs preserve a validated selected project', () => {
  assert.match(app, /const handoffProjectId = validatedProjectId\(bootParams\.get\('project_id'\)\)/);
  assert.match(app, /_askInChat\(\s*_ask,\s*handoffWeb,\s*handoffDocumentScope,\s*handoffProjectId/);
  assert.match(app, /projectId \|\| window\._currentSession\?\.project_id/);
});

test('mail polling settings cannot block the specialist state from settling', () => {
  assert.match(
    specialistSources.mail,
    /export async function loadMail\(fetcher = fetch\)[\s\S]{0,100}startMailPoll\(fetcher\)\.catch/,
  );
  assert.doesNotMatch(specialistSources.mail, /await startMailPoll\(fetcher\)/);
});

test('Activity waits for its summary request before specialist state settles', () => {
  assert.match(
    specialistSources.activity,
    /render\(d\.events \|\| \[\]\);\s*await loadSummary\(want, fetcher\)/,
  );
});

test('closing Aide menus with Escape does not bubble into response cancellation', () => {
  const escapeBranches = [...app.matchAll(/if \(event\.key === 'Escape'\) \{([\s\S]{0,180}?)\}/g)];
  const menuBranches = escapeBranches.filter(match => /close(?:PermMenu|\(true\))/.test(match[1]));
  assert.ok(menuBranches.length >= 2);
  for (const branch of menuBranches) assert.match(branch[1], /event\.stopPropagation\(\)/);
});

test('Gallery and Compare return their asynchronous loading work to showView', () => {
  assert.match(
    app,
    /const showGalleryView\s*=\s*\(\) => showView\([^\n]+return loadGallery\(\)/,
  );
  assert.match(
    app,
    /const showCompareView\s*=\s*\(\) => showView\([^\n]+return Promise\.all\(\[loadCompareModels\(\), loadCompareLeaderboard\(\)\]\)/,
  );
});
