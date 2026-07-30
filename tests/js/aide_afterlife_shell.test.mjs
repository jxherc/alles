import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const models = readFileSync(new URL('../../static/js/models.js', import.meta.url), 'utf8');
const chat = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const rail = readFileSync(new URL('../../static/js/aideworkspace.js', import.meta.url), 'utf8');
const scheduled = readFileSync(new URL('../../static/js/aidescheduled.js', import.meta.url), 'utf8');
const settings = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
const uploads = readFileSync(new URL('../../static/js/uploads.js', import.meta.url), 'utf8');
const starter = readFileSync(
  new URL('../../docs/mockups/afterlife-navigation/aide-projects.html', import.meta.url),
  'utf8',
);
const inboxStarter = readFileSync(
  new URL('../../docs/mockups/afterlife-specialists/inbox.html', import.meta.url),
  'utf8',
);
const specialistStarterCss = readFileSync(
  new URL('../../docs/mockups/afterlife-specialists/starter.css', import.meta.url),
  'utf8',
);
const specialistStarterJs = readFileSync(
  new URL('../../docs/mockups/afterlife-specialists/starter.js', import.meta.url),
  'utf8',
);

test('starter search and custom menus preserve their accessibility contracts', () => {
  assert.match(inboxStarter, /<label class="sr-only" for="mail-search">/);
  assert.match(specialistStarterCss, /\.sr-only\s*\{[^}]*clip:/s);
  assert.match(starter, /event\.key === "Home" \|\| event\.key === "End"/);
  assert.match(starter, /items\[event\.key === "Home" \? 0 : items\.length - 1\]\.focus\(\)/);
  assert.match(starter, /id="sidebar-search-input"[^>]*disabled/);
  assert.match(starter, /searchInput\.disabled = !open/);
  assert.match(starter, /event\.key\.toLowerCase\(\) === "b"[^]*?setSidebarOpen\(false, true\)/);
  assert.doesNotMatch(starter, /event\.key\.toLowerCase\(\) === "b"[^]*?sidebarToggle\.click\(\)/);
});

test('specialist starter modals isolate the background application shell', () => {
  assert.match(specialistStarterJs, /const appShell = document\.querySelector\('\.app-shell'\)/);
  assert.match(specialistStarterJs, /appShell\.inert = true/);
  assert.match(specialistStarterJs, /appShell\.setAttribute\('aria-hidden', 'true'\)/);
  assert.match(specialistStarterJs, /appShell\.inert = false/);
  assert.match(specialistStarterJs, /appShell\.removeAttribute\('aria-hidden'\)/);
});

test('discarded in-flight uploads abort and durably cancel their known server id', () => {
  assert.match(uploads, /const _discardedUploads = new Set\(\)/);
  assert.match(uploads, /_discardedUploads\.add\(item\.id\)/);
  assert.match(uploads, /fd\.append\('upload_id', uploadId\)/);
  assert.match(uploads, /_requests\.get\(item\.id\)\?\.abort\(\)/);
  assert.match(uploads, /\?pending=true/);
  assert.match(uploads, /localStorage\.setItem\(CANCELLATION_KEY/);
  assert.doesNotMatch(uploads, /response\.status === 404/);
  assert.match(uploads, /if \(response\.ok\)/);
  assert.doesNotMatch(uploads, /if \(!item\?\.incognito\) _rememberCancellation/);
  assert.doesNotMatch(uploads, /if \(!item\?\.incognito\) _forgetCancellation/);
  assert.match(uploads, /void _resumeUploadCancellations\(\)/);
  assert.match(uploads, /const discarded = _discardedUploads\.delete\(localId\);\s*if \(discarded\) return null;\s*_markFailed\(localId\)/);
});

test('removing one in-flight upload cancels transmission before hiding it', () => {
  assert.match(
    uploads,
    /async function removeAttachment\(id\)[\s\S]*?item\?\.status === 'uploading'[\s\S]*?_requests\.get\(item\.id\)\?\.abort\(\)[\s\S]*?await _cancelUpload\(item\)[\s\S]*?return;/,
  );
});

test('Home clock follows the universal 12 or 24 hour preference', () => {
  const today = readFileSync(new URL('../../static/js/today.js', import.meta.url), 'utf8');
  assert.doesNotMatch(today, /formatDateParts\([^]*?hour12:\s*true/);
  assert.match(today, /formatDateParts\([^)]*numberingSystem:\s*'latn'/);
});

test('aide uses one safe permission control and a focused add menu', () => {
  assert.match(app, /permLabel\('full_access'\)/);
  assert.match(app, /permLabel\('approve'\)/);
  assert.match(app, /permLabel\('full_auto'\)/);
  assert.match(app, /data-tool="upload"/);
  assert.match(app, /data-tool="app"/);
  assert.match(app, /link an app/);
  assert.match(app, /insertComposerText\(`@\$\{view\} `/);
  assert.doesNotMatch(app, /data-tool="files"/);
  assert.doesNotMatch(app, /data-tool="photos"/);
  assert.doesNotMatch(app, /data-tool="connections"/);
  assert.doesNotMatch(app, /data-tool="shell"/);
  assert.match(app, /const showChatView = \(\) => \{\s*_setAfterlifeSpace\('aide'\)/);
  assert.match(app, /function _setAfterlifeSpace\(space\) \{\s*document\.body\.dataset\.space = space \|\| ''/);
});

test('full access is orange while auto mode keeps the Alles purple', () => {
  assert.match(css, /\.perm-btn\.perm-auto\s*\{\s*color:\s*var\(--accent\)/);
  assert.match(css, /\.perm-btn\.perm-full\s*\{\s*color:\s*var\(--signal\)/);
  assert.match(css, /\.perm-menu-item\.warn \.perm-menu-label\s*\{\s*color:\s*var\(--signal\)/);
  assert.match(css, /body\.afterlife-aide-projects\[data-space="aide"\] \.perm-btn\.perm-full\s*\{\s*color:\s*var\(--signal\)/);
});

test('full access warns that an unsandboxed host shell is unrestricted', () => {
  assert.match(app, /host shell is unrestricted unless sandboxed/);
});

test('effort and reasoning menu is clamped to the space around its anchor', () => {
  assert.match(app, /const availableAbove = r\.top - gap - edge/);
  assert.match(app, /const availableBelow = window\.innerHeight - r\.bottom - gap - edge/);
  assert.match(app, /menu\.style\.maxHeight = `\$\{Math\.floor\(maxHeight\)\}px`/);
  assert.match(app, /activeItem\?\.scrollIntoView\(\{ block: 'nearest' \}\)/);
});

test('permission menu removes its outside-click listener on every close path', () => {
  assert.match(app, /let _permOutsideHandler = null/);
  const close = app.match(/function closePermMenu\(focusAnchor = false\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(close, /document\.removeEventListener\('click', _permOutsideHandler\)/);
  assert.match(close, /_permOutsideHandler = null/);
  assert.match(app, /_permOutsideHandler = outside/);
  assert.match(app, /_permOutsideHandler === outside && menu\.isConnected/);
});

test('scheduled, brain, skills, and reminders share one Aide tool page shell', () => {
  for (const id of ['aide-scheduled-view', 'brain-view', 'skills-view', 'reminders-view']) {
    const tag = html.match(new RegExp(`<[^>]+id="${id}"[^>]*>`))?.[0] || '';
    assert.match(tag, /class="[^"]*aide-tool-view/);
  }
  assert.match(css, /\.aide-tool-view\s*\{/);
  assert.match(css, /\.aide-tool-head/);
  assert.match(css, /\.aide-tool-content/);
  assert.match(starter, /data-view="aide-reminders"/);
  assert.match(starter, /["']aide-reminders["']:\s*\{/);
  assert.doesNotMatch(starter, /\n\s*reminders:\s*\{/);
});

test('Aide tool pages keep the Aide sidebar on single-host installs', () => {
  assert.match(app, /function _shChrome\(v, \{ onAide = false \} = \{\}\)/);
  assert.match(app, /document\.body\.classList\.toggle\('is-aide', onAide\)/);
  assert.match(app, /_shChrome\(v, \{ onAide: staysInAide \}\)/);
  for (const view of ['models', 'compare', 'gallery', 'cookbook', 'usage']) {
    assert.match(app, new RegExp(`AIDE_TOOL_VIEWS = new Set\\(\\[[^]*?'${view}'`));
  }
});

test('thinking stays before the answer while tool details and provenance follow it', () => {
  assert.match(chat, /mode: 'agent'/);
  assert.match(chat, /function getMode\(\) \{\s*return 'agent'/);
  assert.doesNotMatch(chat, /aide-suggest-chips|\/api\/aide\/suggestions/);
  assert.match(sessions, /body\.appendChild\(content\)[\s\S]*body\.appendChild\(tb\)[\s\S]*renderAgentSteps/);
  assert.match(chat, /body\.appendChild\(contentEl\)[\s\S]*body\.insertBefore\(thinkingEl, contentEl\)/);
  assert.match(chat, /body\.appendChild\(agentEl\)/);
  assert.match(chat, /contextProvenanceElement\(chunk\.context_provenance\)/);
  assert.match(sessions, /contextProvenanceElement\(contextProvenance\)/);
  assert.match(sessions, /if \(provenance\) body\.appendChild\(provenance\)/);
});

test('legacy Aide suggestion chips keep their wrapped composer layout', () => {
  assert.match(css, /\.aide-suggest\s*\{[^}]*display:\s*flex[^}]*flex-wrap:\s*wrap[^}]*gap:\s*0\.35rem[^}]*padding:\s*0\.4rem 0\.75rem 0\.1rem/s);
});

test('latest response usage uses one bare token-fragment mark and keeps its live label', () => {
  const counter = html.match(/<span class="session-token-count"[\s\S]*?<\/span>\s*<\/span>/)?.[0] || '';
  assert.match(counter, /role="status"/);
  assert.match(counter, /aria-live="polite"/);
  assert.match(counter, /class="session-token-mark"/);
  assert.match(counter, /id="session-token-count-value"/);
  assert.doesNotMatch(counter, /style=/);
  assert.match(chat, /value\.textContent = `\$\{formatted\} tok`/);
  assert.match(chat, /tokens used in the latest response/);
  assert.match(chat, /el\.hidden = false/);
  assert.match(sessions, /tokCount\.hidden = true/);
  assert.match(sessions, /tokValue\.textContent = ''/);
  assert.match(css, /\.session-token-count\[hidden\]\s*\{\s*display:\s*none/);
});

test('the message rail scales without changing layout width', () => {
  assert.doesNotMatch(rail, /scrollScale|pointerScale|--tick-scale/);
  assert.doesNotMatch(rail, /--tick-width/);
  assert.match(css, /#aide-message-rail-track button::before[\s\S]*transform:\s*scaleX\(1\)/);
  assert.match(css, /#aide-message-rail-track button:hover::before[\s\S]*transform:\s*scaleX\(/);
  assert.match(css, /button:hover::before,[\s\S]*scaleX\(3\.5\)/);
  assert.match(css, /button:has\(\+ button:is\(:hover, :focus-visible\)\)::before/);
  assert.match(rail, /dataset\.messageKey/);
  assert.match(rail, /existing\.get\(key\) \|\| document\.createElement\('button'\)/);
  assert.doesNotMatch(css, /width: var\(--tick-width/);
});

test('the task terminal is a vendored xterm PTY instead of a fake command form', () => {
  assert.match(html, /static\/vendor\/xterm\/xterm\.css/);
  assert.match(html, /id="aide-terminal-mount"/);
  assert.doesNotMatch(html, /id="aide-terminal-(?:form|input|output|path)"/);
  assert.match(rail, /static\/vendor\/xterm\/xterm\.mjs/);
  assert.match(rail, /static\/vendor\/xterm\/addon-fit\.mjs/);
  assert.match(rail, /async function terminalSocketUrl\(\)\s*\{\s*await ensureTerminalTaskContext\(\)/);
  assert.match(rail, /const socketUrl = await terminalSocketUrl\(\)/);
  assert.match(rail, /new WebSocket\(socketUrl\)/);
  assert.doesNotMatch(rail, /searchParams\.set\('working_dir'/);
  assert.match(rail, /createSession\([^]*?workingDir: window\._pendingWorkingDir/);
  assert.match(rail, /markActive\(session\.id\)/);
  assert.match(
    rail,
    /terminalTaskContext = taskContextIdentity\(session\);\s*markActive\(session\.id\);\s*syncNewTaskContext\(session\)/,
  );
  assert.match(rail, /type: 'resize'/);
  const panel = rail.match(/function setPanelOpen\([^]*?\n}/)?.[0] || '';
  assert.match(panel, /if \(!open\) setTerminalOpen\(false\)/);
  const context = rail.match(/function syncNewTaskContext\([^]*?\n}/)?.[0] || '';
  assert.match(context, /terminalTaskContext !== nextTerminalTaskContext/);
  assert.match(context, /setTerminalOpen\(false\)/);
  assert.match(rail, /const instance = await ensureTerminal\(\);\s*if \(\$\('aide-terminal'\)\?\.hidden\) return/);
  assert.doesNotMatch(rail, /\/api\/shell\/exec/);
});

test('Aide keeps one identity and leaves global movement to the universal shell', () => {
  const head = html.indexOf('class="sidebar-head"');
  const search = html.indexOf('class="search-wrap"');
  const nav = html.indexOf('class="sidebar-nav"');
  assert.ok(head >= 0 && search > head && nav > search);
  assert.doesNotMatch(html, /id="aide-home-button"/);
  assert.match(html, /id="app-drawer-btn"[^>]*aria-controls="app-drawer"/);
  assert.match(html, /class="search-wrap">\s*<svg[^>]*aria-hidden="true"[^>]*>[\s\S]*?id="session-search"/);
  assert.doesNotMatch(html, /id="aide-search-btn"/);
  assert.doesNotMatch(html, /id="aide-home-link"/);
  assert.match(html, /id="aide-tools-link"[^>]*aria-haspopup="menu"/);
  assert.match(html, /id="aide-sidebar-menu"[^>]*role="menu"/);
  assert.match(html, /id="aide-settings-link"[^>]*role="menuitem"/);
  assert.match(html, /id="today-settings"[^>]*>settings<\/button>/);
  assert.doesNotMatch(html, /id="today-settings"[^>]*aria-haspopup/);
});

test('Aide attachments live inside and visually expand the composer', () => {
  const composer = html.match(/<div class="composer-box">[\s\S]*?<\/div>\s*<\/div>\s*<\/div>\s*<!-- hidden file input/)?.[0] || '';
  assert.match(composer, /id="attachment-chips"/);
  assert.doesNotMatch(composer, /id="attachment-preview"/);
  assert.doesNotMatch(css, /\.attach-preview(?:\b|-)/);
  assert.match(css, /body\.afterlife-aide-projects\[data-space="aide"\] #attachment-chips/);
  assert.match(css, /\.attach-retry/);
  assert.match(app, /clipboardData\?\.items/);
  assert.match(app, /item\.kind === 'file'/);
  assert.match(app, /some\(item => item\.kind === 'string'\)\) event\.preventDefault\(\)/);
  assert.match(uploads, /new XMLHttpRequest\(\)/);
  assert.match(uploads, /xhr\.upload\.addEventListener\('progress'/);
  assert.match(uploads, /URL\.createObjectURL\(file\)/);
  assert.match(uploads, /previewUrl/);
  assert.match(uploads, /hasPendingAttachments\(\).*Boolean\(a\.status\)/);
});

test('starter popover Escape handling closes only the focused popover', () => {
  const listbox = starter.slice(
    starter.indexOf('function bindListboxKeyboard'),
    starter.indexOf('bindListboxKeyboard(permissionMenu'),
  );
  const attachments = starter.slice(
    starter.indexOf('attachMenu.addEventListener("keydown"'),
    starter.indexOf('document.addEventListener("pointerdown"'),
  );
  for (const handler of [listbox, attachments]) {
    assert.match(handler, /event\.key === "Escape"[\s\S]*event\.preventDefault\(\)/);
    assert.match(handler, /event\.key === "Escape"[\s\S]*event\.stopPropagation\(\)/);
  }
  const globalEscape = starter.slice(
    starter.indexOf('document.addEventListener("keydown"'),
    starter.indexOf('document.querySelector("#composer")'),
  );
  assert.match(globalEscape, /const openPopover = [\s\S]*?find\(\(item\) => !item\.hidden\)/);
  assert.match(globalEscape, /closePopoverAndFocus\(openPopover\)/);
  const close = starter.match(/function closePopoverAndFocus\(popover\) \{[\s\S]*?\n    \}/)?.[0] || '';
  assert.match(close, /\[aria-controls=/);
  assert.match(close, /button\.focus\(\)/);
});

test('starter recomputes panel inertness when the mobile breakpoint changes', () => {
  const responsive = starter.match(/function applyResponsiveState\(event\) \{[\s\S]*?\n    \}/)?.[0] || '';
  assert.match(responsive, /setSidebarOpen\(!event\.matches\)/);
  assert.match(
    responsive,
    /aideMain\.inert = event\.matches && app\.classList\.contains\("panel-open"\)/,
  );
});

test('new tasks expose project and git branch controls without static filler', () => {
  assert.match(html, /id="aide-new-context"/);
  assert.match(html, /id="aide-project-context"[^>]*aria-haspopup="menu"/);
  assert.match(html, /id="aide-branch-context"[^>]*aria-haspopup="menu"/);
  assert.match(html, /id="aide-branch-context-menu"[^>]*role="menu"/);
  assert.doesNotMatch(html, /title="runs on this server"/);
  assert.doesNotMatch(html, /id="aide-vault-context"/);
  assert.doesNotMatch(html, /<select[^>]+aide-new-context/);
  assert.match(css, /\.aide-new-context-item\[hidden\]\s*\{\s*display:\s*none/);
  assert.match(rail, /role = 'menuitemradio'/);
  assert.match(rail, /session\?\.id[\s\S]*\/api\/sessions\/\$\{session\.id\}\/git\/branches/);
  assert.match(sessions, /project_id: options\.projectId \?\? window\._pendingProjectId \?\? ''/);
  assert.match(sessions, /_syncAideNewTaskContext/);
});

test('failed Aide task-context writes restore the last confirmed pending context', () => {
  assert.equal((rail.match(/const previousContext = capturePendingTaskContext\(\);/g) || []).length, 3);
  assert.equal((rail.match(/restorePendingTaskContext\(previousContext\);/g) || []).length, 3);
  assert.match(
    rail,
    /function restorePendingTaskContext\(context\)[^]*?_pendingProjectId = context\.projectId;[^]*?_pendingWorkingDir = context\.workingDir;[^]*?syncNewTaskContext/,
  );
  const createProject = rail.slice(
    rail.indexOf('async function createProjectFromFolder'),
    rail.indexOf('async function useTemporaryFolder'),
  );
  assert.match(
    createProject,
    /catch \(error\) \{[^]*?toast\(error\.message, 'error'\);\s*return;\s*\}/,
  );
});

test('new tasks cannot overlap the removed proactive tool and can add a project folder', () => {
  assert.doesNotMatch(html, /class="nav-item aide-tool-link" data-view="proactive"/);
  assert.doesNotMatch(html, /id="proactive-view"/);
  assert.doesNotMatch(app, /'proactive-view'/);
  assert.match(rail, /choose folder…/);
  assert.match(rail, /\/api\/project-folders/);
});

test('expected model and session fetch failures stay out of the offline console', () => {
  assert.match(models, /navigator\?\.onLine !== false\) console\.error\('loadModels'/);
  assert.match(sessions, /navigator\?\.onLine !== false\) console\.error\('loadSessions'/);
});

test('project delete stays discoverable and keeps a full pointer target', () => {
  assert.match(css, /body\.afterlife-aide-projects\[data-space="aide"\] \.project-del\s*\{[^}]*width:\s*44px[^}]*min-height:\s*44px/);
  assert.match(css, /body\.afterlife-aide-projects\[data-space="aide"\] \.project-folder-head:hover \.project-del/);
  assert.match(css, /body\.afterlife-aide-projects\[data-space="aide"\] \.project-del:focus-visible\s*\{\s*opacity:\s*1/);
  assert.match(css, /@media \(hover: none\), \(pointer: coarse\)[^]*?\.project-del\s*\{\s*opacity:\s*0\.65/);
});

test('scheduled work has a dedicated Aide screen instead of opening settings', () => {
  assert.match(html, /id="aide-scheduled-view"/);
  assert.match(app, /const showAideScheduledView/);
  assert.match(app, /else if \(v === 'scheduled' \|\| v === 'proactive'\) return showAideScheduledView\(\)/);
  assert.match(app, /aide-scheduled-link'[\s\S]*navigateTo\('scheduled'\)/);
  assert.doesNotMatch(app, /aide-scheduled-link'\)\?\.addEventListener\('click', \(\) => openSettings\('rules'\)\)/);
  assert.match(scheduled, /\/api\/jarvis\/workflows/);
  assert.match(scheduled, /workflow\.deterministic_action === 'aide_handoff'/);
  assert.match(scheduled, /workflow\.delivery_policy\?\.aide_schedule_owner === 'aide_scheduled_v1'/);
  assert.match(scheduled, /\/api\/jarvis\/runs/);
  assert.match(scheduled, /\/triggers/);
  assert.doesNotMatch(scheduled, /Run with Jarvis|Jarvis task|Jarvis workflow/);
});

test('scheduled interrupted runs keep their retry action', () => {
  const runActions = scheduled.match(/if \(\['queued', 'running'\][^]*?row\.append\(main, state, actions\)/)?.[0] || '';
  assert.match(runActions, /\['failed', 'cancelled', 'interrupted'\]/);
});

test('Aide Scheduled owns only supported handoff workflows and saves atomically', () => {
  assert.match(scheduled, /SUPPORTED_SCHEDULE_KINDS/);
  assert.match(scheduled, /workflow\.deterministic_action === 'aide_handoff'/);
  assert.match(scheduled, /triggers\.length === 1/);
  assert.match(scheduled, /SUPPORTED_SCHEDULE_KINDS\.has\(triggers\[0\]\.kind\)/);
  assert.match(scheduled, /\/api\/jarvis\/aide-schedules/);
  assert.doesNotMatch(scheduled, /await requestJson\('\/api\/jarvis\/workflows', jsonOptions\('POST'/);
});

test('Aide Scheduled ignores stale trigger loads and shows action failures outside the form', () => {
  const triggerAssignment = scheduled.indexOf('triggersByWorkflow = loadedTriggers');
  const finalSequenceCheck = scheduled.lastIndexOf('if (sequence !== loadSequence) return;', triggerAssignment);
  assert.ok(triggerAssignment > 0);
  assert.ok(finalSequenceCheck > 0);
  assert.ok(finalSequenceCheck < triggerAssignment);
  assert.match(scheduled, /toast\(safeMessage\(error\.message\), 'error'\)/);
});

test('Aide Scheduled preserves configured wall time for one-time work', () => {
  assert.match(scheduled, /function formatWallTime\(value\)/);
  assert.match(scheduled, /trigger\.kind === 'once'[\s\S]{0,140}formatWallTime\(config\.at\)/);
  assert.match(scheduled, /replace\(\/Z\$\/, ''\)[\s\S]{0,100}replace\(\/\(\\d\{2\}:\\d\{2\}\):\\d\{2\}/);
  assert.doesNotMatch(scheduled, /replace\(\/:00\(\?:\\\.000\)\?Z\?\$\/, ''\)/);
});

test('Aide Scheduled loads recent runs after filtering by owned workflow', () => {
  assert.match(scheduled, /\/api\/jarvis\/runs\?workflow_id=\$\{encodeURIComponent\(workflow\.id\)\}&limit=30/);
  assert.doesNotMatch(scheduled, /requestJson\('\/api\/jarvis\/runs\?limit=30'/);
});

test('Aide Scheduled keeps schedules usable when one run history request fails', () => {
  const loader = scheduled.match(/async function loadScheduled\(fetcher = fetch\)[\s\S]*?\n}\n\nasync function handleScheduleAction/)?.[0] || '';
  assert.match(loader, /renderSchedules\(\)[\s\S]*?Promise\.all/);
  assert.match(loader, /requestJson\([\s\S]*?\.catch\(\(\) => \{/);
  assert.match(loader, /runHistoryPartial = true/);
  assert.match(loader, /renderRuns\(runs, runHistoryPartial\)/);
});

test('Files select-all control is not hidden from assistive technology', () => {
  const header = html.match(/<div class="files-phase7-table-head"[^>]*>/)?.[0] || '';
  assert.ok(header);
  assert.doesNotMatch(header, /aria-hidden="true"/);
});

test('scheduled work uses custom controls rather than native choice controls', () => {
  const view = html.match(/<section[^>]+id="aide-scheduled-view"[\s\S]*?<\/section>/)?.[0] || '';
  assert.ok(view);
  assert.doesNotMatch(view, /<select\b/i);
  assert.doesNotMatch(view, /type="(?:checkbox|radio)"/i);
  assert.match(view, /role="radiogroup"/);
});

test('Jarvis exists only as the custom owner-scoped Discord connection', () => {
  const card = html.match(/<div class="s-card" id="jarvis-discord-card">[\s\S]*?<\/div>\s*<div class="s-card">/)?.[0] || '';
  assert.ok(card);
  assert.match(card, /Jarvis on Discord/);
  assert.match(card, /pair one owner/);
  assert.doesNotMatch(card, /<select\b/i);
  assert.doesNotMatch(card, /type="(?:checkbox|radio)"/i);
  assert.match(card, /role="switch"/);
  assert.match(settings, /\/api\/jarvis\/discord/);
  assert.doesNotMatch(settings, /jarvis:\s*\['Jarvis Discord bot'/);
  assert.doesNotMatch(html, /data-view="jarvis"|id="mode-jarvis"/);
});
