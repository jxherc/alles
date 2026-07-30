import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');
const legacyCss = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
const dropdownJs = readFileSync(new URL('../../static/js/dropdown.js', import.meta.url), 'utf8');
const appJs = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
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
  assert.match(css, /--k-default-page:\s*#090909/);
  assert.match(css, /--k-default-page:\s*#f4f3f0/);
  assert.match(css, /--k-page:\s*var\(--bg/);
  assert.match(css, /--k-focus:\s*var\(--k-line-strong\)/);
  assert.match(legacyCss, /--focus:\s*color-mix\(in srgb, var\(--faint\) 72%, var\(--text\) 28%\)/);
  assert.match(css, /--k-accent:\s*var\(--accent/);
  assert.match(css, /\[data-kokuen-surface\][\s\S]*?:focus-visible\s*\{[\s\S]*?outline:\s*2px solid var\(--k-focus\)/);
  assert.match(css, /html\[data-theme="light"\]/);
  assert.match(css, /--k-permission:\s*var\(--signal,\s*#e0a458\)/);
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
  assert.match(css, /\.file-row-actions\s*\{[\s\S]*max-width:\s*42%/);
  assert.match(css, /#settings-modal\[data-kokuen-surface="settings"\][\s\S]*\.s-nav[\s\S]*width:\s*204px/);
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
  for (const match of css.matchAll(/box-shadow:\s*([^;]+);/g)) {
    assert.equal(match[1].trim(), 'none');
  }
});

test('a fresh phone session keeps Aide to one usable pane', () => {
  assert.match(
    appJs,
    /storedAideSidebar === null && aideSidebarMedia\.matches/,
  );
  assert.match(appJs, /const aideSidebarMedia = window\.matchMedia\('\(max-width: 700px\)'\)/);
  assert.doesNotMatch(appJs, /sidebar starts open at every width/);
});

test('file row actions stay visible for keyboard and touch operation', () => {
  assert.match(legacyCss, /\.file-row:focus-within \.file-row-actions\s*\{\s*opacity:\s*1/);
  assert.match(legacyCss, /@media\s*\(hover:\s*none\),\s*\(pointer:\s*coarse\)[\s\S]*?\.file-row-actions\s*\{\s*opacity:\s*1/);
});

test('universal-language file options activate from the keyboard', () => {
  assert.match(universalLanguageStarter, /function selectFileRow\(row\)/);
  assert.match(universalLanguageStarter, /row\.addEventListener\('click', \(\) => selectFileRow\(row\)\)/);
  assert.match(universalLanguageStarter, /event\.key !== 'Enter' && event\.key !== ' '/);
  assert.match(universalLanguageStarter, /event\.preventDefault\(\);\s*selectFileRow\(row\)/);
});
