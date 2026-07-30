import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const docs = fs.readFileSync(new URL('../../static/js/docs.js', import.meta.url), 'utf8');
const notes = fs.readFileSync(new URL('../../static/js/notes.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const chat = fs.readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
const vaultRoutes = fs.readFileSync(new URL('../../routes/vault_md.py', import.meta.url), 'utf8');
const journal = fs.readFileSync(new URL('../../static/js/journal.js', import.meta.url), 'utf8');
const docsStarter = fs.readFileSync(new URL('../../docs/mockups/afterlife-navigation/docs.html', import.meta.url), 'utf8');

test('Docs starter keeps tablet header actions and can reopen responsive context', () => {
  assert.match(docsStarter, /\.topbar \{ grid-template-columns: 220px minmax\(0, 1fr\) auto; \}/);
  assert.match(docsStarter, /\.side-panel\.open \{[\s\S]*?display: block/);
  assert.match(docsStarter, /window\.matchMedia\('\(max-width: 1020px\)'\)\.matches/);
  assert.match(docsStarter, /contextPanel\.classList\.toggle\('open', open\)/);
  assert.match(docsStarter, /aria-controls="context-panel" aria-expanded="true"/);
});

test('Docs reserves its details column only while the panel is visible', () => {
  assert.match(css, /@media \(min-width: 1051px\) \{[\s\S]*?\.docs-workspace/);
  assert.doesNotMatch(css, /@media \(min-width: 1041px\) \{[\s\S]*?\.docs-workspace/);
});

test('Docs home columns can shrink inside the workspace without clipping', () => {
  assert.match(css, /\.wiki-empty-state\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 0\.85fr\) minmax\(0, 1\.15fr\)/);
  assert.doesNotMatch(css, /\.wiki-empty-state\s*\{[\s\S]*?grid-template-columns:\s*minmax\(260px/);
  assert.match(css, /@media \(max-width: 900px\) \{[\s\S]*?#wiki-view\.no-note \.wiki-empty-state \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/);
});

test('Docs preserves and restores legacy document deep links without reviving URL handoffs', () => {
  assert.match(app, /_consumeParams\(\['ask', 'web'\]\)/);
  assert.doesNotMatch(app, /_consumeParams\([^\n]*(?:'doc'|'doc_hash')/);
  assert.match(docs, /new URLSearchParams\(location\.search\)\.get\('doc'\)/);
  const legacyOpen = docs.match(/async function openLegacyDocumentDeepLink\(path\) \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(legacyOpen, /await openNote\(path\)/);
  assert.match(legacyOpen, /searchParams\.delete\('doc'\)/);
  assert.match(legacyOpen, /searchParams\.delete\('doc_hash'\)/);
});

test('Docs commits only the latest fully loaded document and draft', () => {
  const open = docs.match(/export async function openNote\([^)]*\)[\s\S]*?\n}\n\nfunction updateActiveRows/)?.[0] || '';
  assert.match(docs, /let _openGeneration = 0/);
  assert.match(open, /const requestGeneration = \+\+_openGeneration/);
  assert.match(open, /const departureRevision = _editRevision/);
  assert.match(open, /const openedDoc = await api/);
  assert.match(open, /const serverDraft = \([\s\S]*?await api\('\/api\/vault-md\/safety\/draft/);
  assert.match(open, /serverDraft\?\.content === openedDoc\.content[\s\S]*?expected_hash: serverDraft\.draft_hash[\s\S]*?method: 'DELETE'/);
  assert.match(open, /method: 'DELETE'[\s\S]*?catch \{/);
  assert.ok(open.indexOf("method: 'DELETE'") < open.indexOf('const backlinksState'));
  assert.match(open, /let openedDraft = emergencyDraft[\s\S]*?: serverDraft/);
  assert.match(open, /const backlinksState = await fetchBacklinks\(openedPath\)/);
  assert.match(open, /if \(requestGeneration !== _openGeneration\) return false/);
  assert.match(open, /_editRevision !== departureRevision && !\(await flushDraft\(\)\)/);
  assert.ok(open.indexOf('const backlinksState = await fetchBacklinks') < open.indexOf('_cur = openedPath'));
  assert.ok(open.indexOf('_cur = openedPath') < open.indexOf('_draft = openedDraft'));
});

test('Docs abandons delayed editor setup after another document opens', () => {
  const enter = docs.match(/async function enterEdit\([^)]*\)[\s\S]*?\n}/)?.[0] || '';
  const ensure = docs.match(/async function ensureEditor\([^)]*\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(enter, /const editPath = _cur/);
  assert.match(enter, /const editGeneration = _openGeneration/);
  assert.match(enter, /ensureEditor\(value, \{ path: editPath, generation: editGeneration \}\)/);
  assert.match(ensure, /guard\.path !== _cur/);
  assert.match(ensure, /guard\.generation !== _openGeneration/);
});

test('Docs treats an intentionally empty draft as authoritative content', () => {
  const current = docs.match(/function currentContent\(\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(current, /_draft\?\.content \?\? _doc\?\.content \?\? ''/);
  assert.doesNotMatch(current, /_draft\?\.content \|\|/);
});

test('Docs preserves the recovered draft base hash through editing and save', () => {
  const enter = docs.match(/async function enterEdit\([^)]*\)[\s\S]*?\n}/)?.[0] || '';
  const draftBody = docs.match(/function draftWriteBody\(\)[\s\S]*?\n}/)?.[0] || '';
  const save = docs.match(/async function saveCurrent\(\)[\s\S]*?\n}\n\nasync function discardDraft/)?.[0] || '';
  assert.match(docs, /let _editBaseHash = ''/);
  assert.match(docs, /_editBaseHash = openedDraft\?\.base_hash \|\| openedDoc\.hash/);
  assert.match(enter, /_editBaseHash = _draft\?\.base_hash \|\| _doc\.hash/);
  assert.match(draftBody, /base_hash: _editBaseHash \|\| _doc\.hash/);
  assert.match(save, /const expectedHash = _editBaseHash \|\| _doc\.hash/);
});

test('Docs serializes deletion of a persisted draft after edits return to disk content', () => {
  const editor = docs.match(/function editorChanged\(value\)[\s\S]*?\n}/)?.[0] || '';
  const source = docs.match(/function sourceChanged\(\)[\s\S]*?\n}/)?.[0] || '';
  const cleanup = docs.match(/function queueRevertedDraftDeletion\([^)]*\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(editor, /wasDirty && !_dirty[\s\S]*?queueRevertedDraftDeletion/);
  assert.match(source, /wasDirty && !_dirty[\s\S]*?queueRevertedDraftDeletion/);
  assert.match(cleanup, /queueDocumentWrite/);
  assert.match(cleanup, /_editRevision !== revision \|\| _dirty/);
  assert.match(cleanup, /expected_hash: expectedHash/);
  assert.match(cleanup, /method: 'DELETE'/);
  assert.match(docs, /return cleanup\.promise \|\| queueRevertedDraftDeletion/);
});

test('Docs is viewer-first and loads CodeMirror only after Edit', () => {
  assert.match(html, /id="wiki-preview"/);
  assert.match(html, /id="wiki-edit-btn"/);
  assert.match(html, /open in Obsidian/);
  assert.match(docs, /import\('\.\.\/vendor\/cm6\.bundle\.js'\)/);
  assert.doesNotMatch(docs, /\bprompt\s*\(/);
  assert.doesNotMatch(docs, /\bconfirm\s*\(/);
  assert.match(docs, /function previewBody/);
});

test('safe editing uses drafts, expected hashes, compare, and revisions', () => {
  assert.match(docs, /\/api\/vault-md\/safety\/draft/);
  assert.match(docs, /\/api\/vault-md\/safety\/save/);
  assert.match(docs, /expected_hash/);
  assert.match(docs, /\/api\/vault-md\/safety\/compare/);
  assert.match(docs, /\/api\/vault-md\/safety\/revisions/);
});

test('Docs keeps the active editor when draft persistence fails', () => {
  const home = docs.match(/async function openDocsHome\(\)[\s\S]*?\n}\n\nexport function showSection/)?.[0] || '';
  const flush = docs.match(/async function flushDraft\(\)[\s\S]*?\n}\n\nasync function saveCurrent/)?.[0] || '';
  const note = docs.match(/export async function openNote\([^)]*\)[\s\S]*?\n}\n\nfunction updateActiveRows/)?.[0] || '';
  assert.match(home, /const draftSaved = await flushDraft\(\)/);
  assert.ok(home.indexOf('if (!draftSaved) return false') < home.indexOf('_cur = null'));
  assert.match(flush, /return true/);
  assert.match(flush, /catch \(error\)[\s\S]*?return false/);
  assert.match(note, /if \(_dirty && !draftFlushed && !\(await flushDraft\(\)\)\) return false/);
});

test('Docs saves dirty content before renaming a document', () => {
  const save = docs.match(/async function saveCurrent\(\)[\s\S]*?\n}\n\nasync function discardDraft/)?.[0] || '';
  const rename = docs.match(/async function renameCurrent\(\)[\s\S]*?\n}\n\nasync function deleteCurrent/)?.[0] || '';
  assert.match(save, /if \(!_cur \|\| !_doc\?\.editable \|\| !_dirty\) return true/);
  assert.match(save, /setSaveState\('saved'\)[\s\S]*?return true/);
  assert.match(save, /catch \(error\)[\s\S]*?return false/);
  assert.match(rename, /if \(_dirty && !\(await saveCurrent\(\)\)\) return/);
  assert.match(rename, /if \(_draft && !_dirty\)[\s\S]*?resume or discard the saved draft before renaming/);
});

test('Docs refuses to delete a document while a saved draft is unresolved', () => {
  const deletion = docs.match(/async function deleteCurrent\(\)[\s\S]*?\n}\n\nasync function openTrash/)?.[0] || '';
  assert.match(deletion, /if \(_draft && !_dirty\)[\s\S]*?resume or discard the saved draft before deleting/);
  assert.ok(deletion.indexOf('if (_draft && !_dirty)') < deletion.indexOf("method: 'DELETE'"));
});

test('Docs flushes a draft before switching its inner document section', () => {
  const switcher = docs.match(/async function switchDocsSection\(section\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(switcher, /if \(!\(await flushDraft\(\)\)\) return false/);
  assert.match(switcher, /showSection\(section\)/);
  assert.match(docs, /#docs-sections \[data-section\]/);
  assert.match(docs, /await switchDocsSection\(button\.dataset\.section\)/);
});

test('Docs serializes draft and save writes so stale requests cannot win', () => {
  const flush = docs.match(/async function flushDraft\(\)[\s\S]*?\n}\n\nasync function saveCurrent/)?.[0] || '';
  const save = docs.match(/async function saveCurrent\(\)[\s\S]*?\n}\n\nasync function discardDraft/)?.[0] || '';
  assert.match(docs, /let _documentWrites = Promise\.resolve\(\)/);
  assert.match(docs, /function queueDocumentWrite\(operation\)/);
  assert.match(flush, /queueDocumentWrite/);
  assert.match(save, /queueDocumentWrite/);
  assert.match(save, /const revision = _editRevision/);
  assert.match(save, /if \(_editRevision === revision\)/);
  assert.match(docs, /globalThis\.crypto\?\.randomUUID/);
  assert.match(docs, /globalThis\.crypto\?\.getRandomValues/);
  assert.doesNotMatch(docs, /const DRAFT_WRITE_SESSION = crypto\.randomUUID\(\)/);
  assert.match(docs, /write_session: DRAFT_WRITE_SESSION/);
  assert.match(docs, /write_generation: DRAFT_WRITE_GENERATION/);
  assert.match(docs, /write_revision: revision/);
});

test('Docs does not navigate or delete while newer editor revisions are still unsaved', () => {
  const flush = docs.match(/async function flushDraft\(\)[\s\S]*?\n}\n\nasync function saveCurrent/)?.[0] || '';
  const save = docs.match(/async function saveCurrent\(\)[\s\S]*?\n}\n\nasync function discardDraft/)?.[0] || '';
  assert.match(flush, /_editRevision !== revision[\s\S]*?return (?:await )?flushDraft\(\)/);
  assert.match(save, /_editRevision !== revision[\s\S]*?return (?:await )?saveCurrent\(\)/);
});

test('Notes initial loading is awaited and uses the Docs scoped fetcher', () => {
  const notesBranch = docs.match(/if \(_section === 'notes'\) \{[\s\S]*?\n  }/)?.[0] || '';
  assert.match(notesBranch, /return loadNotes\(_fetcher\)/);
  assert.match(notes, /export async function loadNotes\(fetcher = _fetcher\)/);
  assert.match(notes, /_fetcher = fetcher/);
  assert.match(notes, /await _fetcher\('\/api\/notes'/);
});

test('Notes keeps an active editor mounted across vault watcher refreshes', () => {
  const render = notes.match(/function renderNotes\(\) \{[\s\S]*?\n}/)?.[0] || '';
  assert.match(render, /if \(!list \|\| _editing\) return/);
  assert.match(docs, /if \(_section === 'notes'\) \{ window\._reloadNotes\?\.\(\); return; \}/);
});

test('Docs home clears stale document hashes and delete resolves dirty work first', () => {
  const home = docs.match(/async function openDocsHome\(\)[\s\S]*?\n}\n\nexport function showSection/)?.[0] || '';
  const remove = docs.match(/async function deleteCurrent\(\)[\s\S]*?\n}\n\nasync function openTrash/)?.[0] || '';
  assert.match(home, /history\.replaceState\(null, '', location\.pathname \+ location\.search\)/);
  assert.match(remove, /if \(_dirty && !\(await saveCurrent\(\)\)\) return/);
  assert.match(remove, /await openDocsHome\(\)/);
});

test('Docs has no duplicate global Home route and only edits a newly opened document', () => {
  const open = docs.match(/export async function openNote\([^)]*\)[\s\S]*?\n}\n\nfunction updateActiveRows/)?.[0] || '';
  const create = docs.match(/async function newDoc\(\)[\s\S]*?\n}\n\nasync function newFolder/)?.[0] || '';
  assert.doesNotMatch(html, /data-docs-route="home"|docs-home-link/);
  assert.doesNotMatch(docs, /navigateDocsRoute|_navigateHome/);
  assert.match(html, /id="app-drawer-btn"/);
  assert.match(open, /return true/);
  assert.match(open, /catch \(error\)[\s\S]*?return false/);
  assert.ok(create.indexOf('await flushDraft()') < create.indexOf("'/api/vault-md/file'"));
  assert.match(create, /const opened = await openNote\([^;]+\);[\s\S]*?if \(!opened\) return/);
  assert.ok(create.indexOf('if (!opened) return') < create.indexOf("await enterEdit('')"));
});

test('all app navigation awaits the Docs draft guard and pagehide keeps a final draft', () => {
  const navigate = app.match(/async function navigateTo\(v\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(docs, /window\._prepareDocsNavigation\s*=\s*prepareDocsNavigation/);
  assert.match(docs, /addEventListener\('pagehide', persistDraftOnPageHide\)/);
  assert.match(docs, /keepalive:\s*true/);
  const pagehide = docs.match(/function persistDraftOnPageHide\(\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(pagehide, /const body = draftWriteBody\(\)/);
  const draftBody = docs.match(/function draftWriteBody\(\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(draftBody, /write_session: DRAFT_WRITE_SESSION/);
  assert.match(draftBody, /write_revision: _editRevision/);
  assert.match(docs, /DRAFT_KEEPALIVE_BYTES\s*=\s*48\s*\*\s*1024/);
  assert.match(docs, /DRAFT_RECOVERY_KEY\s*=\s*'alles\.docs\.draft\.recovery\.v1'/);
  assert.match(docs, /function persistEmergencyDraft\(body\)/);
  assert.match(docs, /localStorage\?\.setItem\(`\$\{DRAFT_RECOVERY_KEY\}:\$\{encodeURIComponent\(body\.path\)\}`/);
  assert.match(docs, /function readEmergencyDraft\(path = ''\)/);
  assert.match(docs, /localStorage\?\.getItem\(`\$\{DRAFT_RECOVERY_KEY\}:\$\{encodeURIComponent\(path\)\}`/);
  assert.match(docs, /const emergencyDraft = readEmergencyDraft\(openedPath\)/);
  assert.doesNotMatch(docs, /emergencyTime|serverTime/);
  assert.match(docs, /sameWriteSession && emergencyRevision > serverRevision/);
  assert.match(docs, /sameWriteSession && serverRevision > emergencyRevision/);
  assert.match(docs, /draftsNeedOwnerChoice/);
  assert.match(docs, /A browser recovery copy and a server draft both exist/);
  assert.match(docs, /label: 'resume browser copy'/);
  assert.match(docs, /label: 'use server draft'/);
  assert.match(docs, /clearEmergencyDraft\(path, DRAFT_WRITE_SESSION, revision\)/);
  assert.match(docs, /byteLength > DRAFT_KEEPALIVE_BYTES[\s\S]*?startLargeDraftFlush\(\)/);
  assert.match(docs, /addEventListener\('beforeunload', guardLargeDraftDeparture\)/);
  const departureGuard = docs.match(
    /function guardLargeDraftDeparture\(event\)[\s\S]*?\n}/,
  )?.[0] || '';
  assert.match(departureGuard, /_persistedDraftRevision === _editRevision/);
  assert.match(departureGuard, /emergency\?\.write_revision === _editRevision/);
  assert.match(departureGuard, /startLargeDraftFlush\(\)/);
  assert.match(departureGuard, /event\.preventDefault\(\)/);
  assert.match(departureGuard, /event\.returnValue = ''/);
  const flush = docs.match(/async function flushDraft\(\)[\s\S]*?\n}\n\nasync function saveCurrent/)?.[0] || '';
  assert.match(flush, /_persistedDraftPath = path/);
  assert.match(flush, /_persistedDraftRevision = revision/);
  assert.match(navigate, /await window\._prepareDocsNavigation\(\)/);
  assert.ok(navigate.indexOf('await window._prepareDocsNavigation()') < navigate.indexOf('crossNav'));
  assert.ok(navigate.indexOf('await window._prepareDocsNavigation()') < navigate.indexOf('renderLocalView'));
  assert.match(navigate, /crossNav\(dest, groupedIdentifier, \{ docsPrepared: true \}\)/);
  assert.match(app, /!docsPrepared && typeof window\._prepareDocsNavigation/);
});

test('discard and external-copy deletion are serialized after pending draft writes', () => {
  const deletion = docs.match(/async function deleteDraftSafely\([^)]*\)[\s\S]*?\n}/)?.[0] || '';
  const discard = docs.match(/async function discardDraft\(\)[\s\S]*?\n}\n\nasync function compareExternal/)?.[0] || '';
  const external = docs.match(/async function useExternalCopy\(\)[\s\S]*?\n}\n\nasync function replaceExternalWithDraft/)?.[0] || '';
  assert.match(deletion, /clearTimeout\(_draftTimer\)/);
  assert.match(deletion, /queueDocumentWrite\(async \(\) =>/);
  assert.match(deletion, /draft_hash/);
  assert.match(deletion, /expected_hash/);
  assert.match(deletion, /method:\s*'DELETE'/);
  assert.match(discard, /await deleteDraftSafely\(_cur\)/);
  assert.match(external, /await deleteDraftSafely\(_cur\)/);
});

test('conflict replacement saves against the revision that was actually compared', () => {
  const compare = docs.match(/async function compareExternal\(\)[\s\S]*?\n}\n\nasync function useExternalCopy/)?.[0] || '';
  const replace = docs.match(/async function replaceExternalWithDraft\([^)]*\)[\s\S]*?\n}\n\nfunction updateStats/)?.[0] || '';
  assert.match(compare, /const local = _draft\?\.content \?\? currentContent\(\)/);
  assert.match(compare, /replaceExternalWithDraft\(local,\s*comparison\.current_hash\)/);
  assert.match(replace, /expected_hash:\s*reviewedHash/);
  assert.doesNotMatch(replace, /\/api\/vault-md\/file/);
});

test('conflict replacement waits for pending draft writes and stops the draft timer', () => {
  const replace = docs.match(/async function replaceExternalWithDraft\([^)]*\)[\s\S]*?\n}\n\nfunction updateStats/)?.[0] || '';
  assert.match(replace, /clearTimeout\(_draftTimer\)/);
  assert.match(replace, /_draftTimer\s*=\s*0/);
  assert.match(replace, /queueDocumentWrite\(\(\)\s*=>\s*api\([\s\S]*?\/api\/vault-md\/safety\/save/);
});

test('Aide receives one visible exact note scope', () => {
  assert.match(docs, /kind: 'vault_document'/);
  assert.match(chat, /context_scope: documentScope/);
  assert.match(html, /id="aide-document-scope"/);
});

test('Docs saves the visible draft before handing its exact revision to Aide', () => {
  const handoff = docs.match(/async function askAideAboutCurrent\(\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(handoff, /if \(_dirty && !\(await saveCurrent\(\)\)\) return/);
  assert.ok(handoff.indexOf('await saveCurrent()') < handoff.indexOf('window._askInChat'));
  assert.match(handoff, /expected_hash:\s*_doc\.hash/);
  const inline = app.match(/window\._askInChat = async[\s\S]*?\n};/)?.[0] || '';
  assert.match(inline, /if \(!\(await navigateTo\('chat'\)\)\) return/);
  assert.doesNotMatch(inline, /canOpenAideInline[^]*?showChatView\(\)/);
});

test('Docs and Journal use semantic svg icons, not generic rectangle marks', () => {
  assert.match(html, /class="docs-nav-icon"/);
  assert.doesNotMatch(html, /class="(?:file|folder)-mark"/);
  assert.match(html, /id="jrnl-heatmap"|id="journal-body"/);
  assert.match(css, /grid-template-columns:\s*16px\s+minmax\(0,\s*1fr\)/);
  assert.match(journal, /grid-template-columns:repeat\(\$\{weeks\},minmax\(0,1fr\)\)/);
  assert.equal(
    (journal.match(/grid-template-columns:repeat\(\$\{weeks\},minmax\(0,1fr\)\)/g) || []).length,
    2,
  );
  assert.match(journal, /m === 11 \? `\$\{wk \+ 1\} \/ -1` : wk \+ 1/);
  assert.match(css, /\.jrnl-hm:last-child\s*\{\s*justify-self:\s*end;/);
  assert.match(css, /\.jrnl-toolbar \.btn \{ height: var\(--ui-control-height, 44px\); min-height: var\(--ui-control-height, 44px\);/);
  assert.match(css, /\.jrnl-toolbar \.jrnl-search \{ flex: 1 0 100%; \}/);
});

test('Docs home hides document-only chrome and editor controls share an aligned action group', () => {
  assert.match(css, /#wiki-view\.no-note \.docs-reader-head\s*\{\s*display:\s*none;/);
  assert.match(html, /class="docs-editor-actions"/);
  assert.match(docs, /class="docs-home-card-copy"/);
  assert.match(css, /\.docs-editor-actions\s*\{[^}]*gap:\s*(?:0\.75rem|var\(--k-space-3\))/s);
  assert.match(css, /#wiki-done-btn\s*\{[^}]*padding:\s*0\s+0\.65rem/s);
  assert.match(css, /\.docs-home-card\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+16px/s);
  assert.match(css, /\.docs-home-card-copy\s*\{[^}]*grid-column:\s*1/s);
  assert.match(css, /\.docs-home-card \.docs-nav-icon\s*\{[^}]*grid-column:\s*2/s);
});

test('Docs library groups are independently collapsible and remember their state', () => {
  for (const name of ['library', 'recent', 'vault']) {
    assert.match(html, new RegExp(`data-docs-collapse="${name}"`));
  }
  assert.match(docs, /DOCS_NAV_STATE_KEY/);
  assert.match(docs, /localStorage\.setItem\(DOCS_NAV_STATE_KEY/);
  assert.match(docs, /aria-expanded/);
  assert.match(css, /\.docs-nav-group-content\[hidden\]\s*\{\s*display:\s*none\s*!important;/);
});

test('Journal is a section of the shared Docs shell instead of a second page view', () => {
  assert.match(html, /id="docs-journal-section"/);
  assert.doesNotMatch(html, /id="journal-view"/);
  assert.match(html, /id="docs-tabs"[\s\S]*?data-group-section="journal"/);
  assert.doesNotMatch(html, /data-docs-route="journal"/);
  assert.match(app, /showJournalView\s*=\s*\(\)\s*=>\s*showWikiView\('journal'\)/);
});

test('Journal rechecks its lock before reusing hydrated private content', () => {
  const init = journal.match(/export async function initJournal\(\)[^]*?\n}/)?.[0] || '';
  assert.ok(init.indexOf("jget('/api/journal/lock/status')") >= 0);
  assert.ok(init.indexOf("jget('/api/journal/lock/status')") < init.indexOf('_lastHydratedAt < 30_000'));
});

test('the Markdown watcher checks often enough for live vault updates', () => {
  const match = vaultRoutes.match(/VAULT_WATCH_INTERVAL\s*=\s*([0-9.]+)/);
  assert.ok(match, 'watch interval should be explicit');
  assert.ok(Number(match[1]) <= 0.75, `watch interval is too slow: ${match[1]}s`);
});

test('the Markdown watcher reconciles the tree when its stream becomes ready', () => {
  assert.match(docs, /if \(data\.hello\) \{/);
  assert.match(docs, /if \(data\.hello\) \{[\s\S]*?await loadTree\(\);[\s\S]*?return;/);
});

test('the Docs library scrolls without covering its bottom action', () => {
  assert.match(css, /\.docs-nav-panel\s*\{[^}]*overflow-y:\s*hidden;/s);
  assert.match(css, /\.docs-folders\s*\{[^}]*flex:\s*1;[^}]*overflow:\s*hidden;/s);
  assert.match(
    css,
    /\.docs-vault-content\s*\{[^}]*flex:\s*1 1 auto;[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;/s,
  );
  assert.match(css, /\.docs-nav-text-action\s*\{[^}]*flex-shrink:\s*0;/s);
});

test('mobile Docs keeps its navigation closed on the empty landing until requested', () => {
  const docsCss = css.slice(css.indexOf('Afterlife Phase 6 Docs'));
  const mobile = docsCss.match(/@media \(max-width: 760px\) \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(mobile, /#wiki-view\.no-note \.docs-nav-panel\s*\{\s*display:\s*none;/);
  assert.match(
    mobile,
    /#wiki-view\.no-note\.docs-nav-open \.docs-nav-panel\s*\{\s*display:\s*flex;/,
  );
});
