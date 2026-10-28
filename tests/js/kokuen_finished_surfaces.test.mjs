import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');
const legacyCss = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
const dropdownJs = readFileSync(new URL('../../static/js/dropdown.js', import.meta.url), 'utf8');
const appJs = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const filesJs = readFileSync(new URL('../../static/js/filesphase7.js', import.meta.url), 'utf8');
const universalLanguageStarter = readFileSync(
  new URL('../../docs/mockups/afterlife-navigation/kokuen-universal-language.html', import.meta.url),
  'utf8',
);

const finishedSurfaces = new Map([
  ['app-drawer', 'apps'],
  ['today-view', 'home'],
  ['andromeda-view', 'andromeda'],
  ['chat', 'aide'],
  ['plan-view', 'specialist'],
  ['inbox-view', 'specialist'],
  ['library-view', 'specialist'],
  ['health-group-view', 'specialist'],
  ['finance-view', 'specialist'],
  ['brain-view', 'aide-tool'],
  ['reminders-view', 'aide-tool'],
  ['aide-scheduled-view', 'aide-tool'],
  ['skills-view', 'aide-tool'],
  ['system-view', 'system'],
  ['wiki-view', 'docs'],
  ['files-view', 'files'],
  ['settings-modal', 'settings'],
]);

const untouchedLegacyRoots = [
  'calendar-view', 'tasks-view', 'mail-view', 'contacts-view', 'photos-view',
  'vault-view', 'subs-view', 'money-view', 'days-view', 'activity-view',
  'watch-view', 'habits-view', 'read-view', 'books-view', 'health-view',
];

test('the KOKUEN runtime layer loads after the legacy stylesheet', () => {
  const legacy = html.search(/\/static\/style\.css\?v=\d+/);
  const kokuen = html.search(/\/static\/kokuen\.css\?v=\d+/);
  assert.ok(legacy >= 0);
  assert.ok(kokuen > legacy);
});

test('every finished surface opts into the runtime and legacy apps stay out', () => {
  for (const [id, surface] of finishedSurfaces) {
    const tag = html.match(new RegExp(`<[^>]+id="${id}"[^>]*>`))?.[0] || '';
    assert.ok(tag, `missing #${id}`);
    assert.match(tag, new RegExp(`data-kokuen-surface="${surface}"`), `#${id}`);
  }
  for (const id of untouchedLegacyRoots) {
    const tag = html.match(new RegExp(`<[^>]+id="${id}"[^>]*>`))?.[0] || '';
    assert.ok(tag, `missing legacy #${id}`);
    assert.doesNotMatch(tag, /data-kokuen-surface=/, `legacy #${id} was opted in`);
  }

  assert.match(css, /body\.afterlife-aide-projects\[data-space="aide"\]/);
  assert.match(css, /body\[data-app="files"\]/);
  for (const [id] of finishedSurfaces) {
    if (['chat', 'brain-view', 'reminders-view', 'aide-scheduled-view', 'skills-view', 'files-view'].includes(id)) continue;
    assert.match(css, new RegExp(`#${id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\[data-kokuen-surface`));
  }
  assert.doesNotMatch(
    css,
    /#(?:calendar|tasks|mail|contacts|photos|vault|subs|money|days|activity|watch|habits|read|books|health)-view/,
  );
});

test('finished surfaces use custom choices and portaled menus keep their surface', () => {
  assert.doesNotMatch(html, /<select\b/i);
  assert.doesNotMatch(html, /type="(?:checkbox|radio)"/i);
  assert.match(dropdownJs, /closest\('\[data-kokuen-surface\]'\)/);
  assert.match(dropdownJs, /panel\.dataset\.kokuenSurface = surface/);
});

test('semantic tokens preserve themes while keeping KOKUEN defaults', () => {
  assert.match(css, /--k-default-page:\s*#12100e/);
  assert.match(css, /--k-default-page:\s*#f8f6f3/);
  assert.match(css, /--k-page:\s*var\(--bg/);
  assert.match(css, /--k-focus:\s*var\(--focus,\s*var\(--k-soft\)\)/);
  assert.match(legacyCss, /--focus:\s*color-mix\(in srgb, var\(--faint\) 72%, var\(--text\) 28%\)/);
  assert.match(css, /--k-accent:\s*var\(--accent/);
  assert.match(css, /\[data-kokuen-surface\][\s\S]*?:focus-visible\s*\{[\s\S]*?outline:\s*2px solid var\(--k-focus\)/);
  assert.match(css, /html\[data-theme="light"\]/);
  assert.match(css, /--k-permission:\s*var\(--signal,\s*#e8b26c\)/);
  for (const stylesheet of [css, legacyCss]) {
    for (const match of stylesheet.matchAll(/([^{}]*focus(?:-visible|-within)?[^{}]*)\{([^{}]*)\}/g)) {
      assert.doesNotMatch(
        match[2],
        /var\(--(?:k-)?accent\)|#818cf8|#9298ff|purple/i,
        `focus must stay neutral: ${match[1].trim()}`,
      );
    }
  }
});

test('Aide keeps its permission colors and approved composition', () => {
  assert.match(css, /#perm-mode-btn\.perm-full/);
  assert.match(css, /#perm-mode-btn\.perm-auto/);
  assert.match(legacyCss, /\.messages[\s\S]*width:\s*min\(820px,\s*100%\)/);
  assert.match(legacyCss, /\.composer-outer[\s\S]*width:\s*min\(860px,\s*100%\)/);
  assert.match(
    css,
    /body\.afterlife-aide-projects\[data-space="aide"\] \.composer-box:focus-within\s*\{[\s\S]*?border-color:\s*var\(--k-focus\)/,
  );
  assert.match(
    css,
    /body\.afterlife-aide-projects\[data-space="aide"\] \.composer-ta:focus-visible\s*\{[\s\S]*?outline:\s*none/,
  );
});

test('the finished surfaces share the documented rhythm and safe motion', () => {
  assert.match(css, /--k-app-header:\s*52px/);
  assert.match(css, /\.main\s*>\s*\.topbar[\s\S]*height:\s*var\(--k-app-header\)/);
  assert.match(css, /@media\s*\(max-width:\s*760px\)[\s\S]*min-height:\s*var\(--k-control\)/);
  assert.match(css, /\.file-name\s*\{[\s\S]*min-width:\s*60px/);
  assert.match(css, /\.file-name-button\s*\{[^}]*min-width:\s*0[^}]*text-overflow:\s*ellipsis/);
  assert.match(css, /#settings-modal\[data-kokuen-surface="settings"\][\s\S]*\.s-nav[\s\S]*width:\s*14\.5rem/);
  assert.match(css, /#wiki-view\[data-kokuen-surface="docs"\][\s\S]*width:\s*244px/);
  assert.match(css, /#andromeda-view\[data-kokuen-surface="andromeda"\][\s\S]*box-shadow:\s*none/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.doesNotMatch(
    css,
    /\b(?:gap|padding(?:-(?:top|right|bottom|left|inline|block))?|margin(?:-(?:top|right|bottom|left|inline|block))?):\s*[^;]*(?<!\d)(?:1|2|3|5|6|7|9|10|14|18|20|34)px/,
  );
  assert.doesNotMatch(css, /translateY\s*\(/);
  assert.doesNotMatch(css, /(?:linear|radial|repeating-linear)-gradient\s*\(/);
  assert.doesNotMatch(css, /backdrop-filter|filter:\s*blur\s*\(/);
  assert.doesNotMatch(css, /opacity:\s*0(?:\.0+)?\s*[;}]/);
  assert.match(
    css,
    /#settings-modal\[data-kokuen-surface="settings"\]\s*\{[\s\S]*?animation:\s*none;[\s\S]*?opacity:\s*1;/,
  );
  assert.match(
    css,
    /@media\s*\(max-width:\s*620px\)[\s\S]*?#reminders-view\s+\.reminder-add-form[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/,
  );
  assert.doesNotMatch(
    legacyCss,
    /\.photos-person:hover\s+\.photos-person-av\s*\{[^}]*transform\s*:/,
  );
  // No decorative shadows. The only shadow is the shared text-field focus: the field's own 1px
  // edge recolored (decision 0045), never a line painted inside the box.
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const shadow = match[2].match(/box-shadow:\s*([^;]+);/)?.[1].trim().replace(/\s*!important$/, '');
    if (!shadow || shadow === 'none') continue;
    assert.match(match[1], /:focus-visible\s*$/);
    assert.match(match[1], /html\[data-kokuen-version="5"\] :where\(/);
    assert.match(match[1], /input:not\(\[type\]\)/);
    assert.match(match[1], /textarea/);
    assert.match(match[1], /\.custom-select\[role="combobox"\]/);
    assert.equal(shadow, 'inset 0 0 0 1px var(--k-field-focus, var(--muted))');
  }
});

const centralJs = readFileSync(new URL('../../static/js/aidecentral.js', import.meta.url), 'utf8');
const centralCss = readFileSync(new URL('../../static/aidecentral.css', import.meta.url), 'utf8');
function archiveHarness({ width = 1440, stored = null } = {}) {
  const extract = (source, name) => {
    const result = source.match(new RegExp(`^(?:export )?function ${name}\\([^]*?^}`, 'm'))?.[0];
    assert.ok(result, `exercise actual ${name} behavior`);
    return result.replace(/^export /, '');
  };
  const bootStart = appJs.indexOf('  const aideSidebarMedia =');
  const bootEnd = appJs.indexOf('\n  // these hit the server', bootStart);
  assert.ok(bootStart >= 0 && bootEnd > bootStart, 'exercise the actual sidebar boot/resize initialization');
  const classes = new Set(['is-aide', 'aide-central']);
  const document = { activeElement: null, body: { classList: {
    contains: name => classes.has(name),
    toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
  } }, dispatchEvent() {} };
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, {
      id, inert: false, isConnected: true, attributes: {},
      closest: selector => selector === '.sidebar' && id.startsWith('aide-sidebar') ? get('aide-sidebar') : null,
      toggleAttribute(name, on) { this[name] = on; },
      setAttribute(name, value) { this.attributes[name] = value; },
      focus() { document.activeElement = this; },
    });
    return nodes.get(id);
  };
  document.getElementById = get;
  document.querySelector = selector => selector === '.main' ? get('main') : null;
  const composer = get('composer-ta');
  Object.assign(composer, { value: '  unfinished primary question\n中文  ', selectionStart: 4, selectionEnd: 12 });
  document.activeElement = composer;
  const storage = new Map([['aide-draft-v2-primary', '{"text":"saved primary question","document_scope":null}']]);
  if (stored !== null) storage.set('aide-sidebar-hidden', stored);
  const media = { matches: width <= 700, addEventListener(type, listener) { assert.equal(type, 'change'); this.listener = listener; } };
  const window = { matchMedia: () => media, _currentSession: { id: 'primary', primary: true },
    _pendingDocumentScope: { kind: 'vault_document', path: 'primary.md', expected_hash: 'owned' }, _closeAideTools() {} };
  const location = { href: 'http://isolated.test/?view=chat#primary' };
  const context = vm.createContext({ window, document, location,
    CustomEvent: class {}, $: get, setAideToolsMenu() {}, closeContext() {},
    localStorage: { getItem: name => storage.get(name) ?? null, setItem: (name, value) => storage.set(name, value) },
  });
  vm.runInContext(`let archiveInert = []; const menu = { close() {} };
    const archiveBoundary = { activate({ focus }) { focus.focus(); }, deactivate() {} };
    ${['restoreInert', 'suspend', 'archiveVisibility'].map(name => extract(centralJs, name)).join('\n')}
    window._aideArchiveVisibility = archiveVisibility;
    ${['setAideSidebarHidden', 'closeCompactAideSidebar'].map(name => extract(appJs, name)).join('\n')}
    ${appJs.match(/^window\._setAideArchiveOpen = .*;$/m)?.[0]}
    ${appJs.slice(bootStart, bootEnd)}
    globalThis.closeArchive = closeCompactAideSidebar;
  `, context);
  return { window, document, get, classes, storage, composer, closeArchive: context.closeArchive,
    resize: nextWidth => { media.matches = nextWidth <= 700; media.listener({ matches: media.matches }); },
    snapshot: () => JSON.stringify({ session: window._currentSession, scope: window._pendingDocumentScope,
      text: composer.value, start: composer.selectionStart, end: composer.selectionEnd, storage: [...storage], href: location.href }),
  };
}

test('central Aide boots with archive closed at every size regardless of legacy sidebar preference', () => {
  for (const width of [360, 700, 820, 1440]) for (const stored of [null, '', '1']) {
    const h = archiveHarness({ width, stored });
    assert.equal(h.classes.has('sidebar-hidden'), true, `archive unexpectedly open at ${width}px with saved preference ${stored}`);
    assert.equal(h.get('aide-sidebar').inert, true);
    assert.equal(h.get('sidebar-toggle-btn').attributes['aria-expanded'], 'false');
    const before = h.snapshot();
    for (const nextWidth of [1440, 360, 820]) {
      h.resize(nextWidth);
      assert.equal(h.classes.has('sidebar-hidden'), true, 'resizing must not open an archive the user did not request');
      assert.equal(h.get('aide-sidebar').inert, true);
    }
    assert.equal(h.snapshot(), before);
  }
});

test('deliberate archive browsing preserves the primary owner, route and exact unsent draft on desktop and phone', () => {
  for (const width of [360, 1440]) {
    const h = archiveHarness({ width, stored: '' });
    const before = h.snapshot();
    h.window._setAideArchiveOpen(true);
    assert.equal(h.classes.has('sidebar-hidden'), false);
    assert.equal(h.get('aide-sidebar').inert, false);
    assert.equal(h.get('main').inert, true, 'archive is an explicit modal surface, not a second default pane');
    assert.equal(h.snapshot(), before, 'opening archive alone must not select or create a conversation');
    assert.equal(h.closeArchive({ restoreFocus: true }), true, 'central archive closes even on desktop');
    assert.equal(h.classes.has('sidebar-hidden'), true);
    assert.equal(h.get('aide-sidebar').inert, true);
    assert.equal(h.get('main').inert, false);
    assert.equal(h.document.activeElement, h.get('aide-more-btn'));
    assert.equal(h.snapshot(), before);
  }
});

test('archive remains an explicitly labelled More action and its closed presentation is not phone-only', () => {
  assert.match(html, /<button[^>]+role="menuitem"[^>]+data-aide-central-action="archive"/);
  assert.match(centralJs, /if \(value === 'archive'\) window\._setAideArchiveOpen\?\.\(true\)/);
  assert.match(html, /<aside[^>]+id="aide-sidebar"[^>]+role="dialog"[^>]+aria-modal="true"[^>]+aria-labelledby="aide-archive-title"/);
  const hiddenRule = centralCss.match(/body\.aide-central\[data-space="aide"\]\.sidebar-hidden \.sidebar\s*\{\s*display:\s*none !important;/);
  assert.ok(hiddenRule, 'the closed archive has an explicit display:none rule');
  const precedingCss = centralCss.slice(0, hiddenRule.index).replace(/\/\*[^]*?\*\//g, '');
  const nesting = [...precedingCss].reduce((depth, character) => depth + (character === '{' ? 1 : character === '}' ? -1 : 0), 0);
  assert.equal(nesting, 0, 'archive hiding applies at stylesheet root, not only inside a phone media query');
  assert.match(centralCss, /body\.aide-central\[data-space="aide"\] \.main\s*\{[^}]*width:\s*100%;[^}]*margin:\s*0;/);
});

test('current file controls use buttons and selection state rather than hover-only actions', () => {
  assert.match(filesJs, /<button class="file-name-button" type="button" data-file-open/);
  assert.match(filesJs, /<button class="files-check" type="button" role="checkbox"/);
  assert.match(filesJs, /bar\.hidden = count === 0/);
  assert.match(html, /<button[^>]+data-files-bulk="copy"[^>]+type="button"/);
  assert.doesNotMatch(filesJs, /file-row-actions/);
});

test('universal-language file options activate from the keyboard', () => {
  assert.match(universalLanguageStarter, /function selectFileRow\(row\)/);
  assert.match(universalLanguageStarter, /row\.addEventListener\('click', \(\) => selectFileRow\(row\)\)/);
  assert.match(universalLanguageStarter, /event\.key !== 'Enter' && event\.key !== ' '/);
  assert.match(universalLanguageStarter, /event\.preventDefault\(\);\s*selectFileRow\(row\)/);
});
