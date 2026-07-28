import assert from 'node:assert/strict';
import fs from 'node:fs';

const wizard = fs.readFileSync(new URL('../../static/js/setupwizard.js', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const settings = fs.readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');

assert.match(wizard, /const STEPS = \['basics', 'access', 'files', 'ai_search', 'protection'\]/);
assert.match(wizard, /\/api\/setup\/step/);
assert.match(wizard, /\/api\/setup\/complete/);
assert.match(wizard, /const completed = await _api\('\/api\/setup\/complete'/);
assert.match(wizard, /_state = completed\.setup/);
assert.match(wizard, /_state\.next_step === 'done' && !_state\.completed/);
assert.match(wizard, /if \(_state\.next_step === 'done'[\s\S]*?await _api\('\/api\/setup\/complete'/);
assert.match(wizard, /\/api\/setup\/dismiss/);
assert.match(wizard, /\/api\/setup\/resume/);
assert.match(wizard, /\/api\/setup\/obsidian/);
assert.match(wizard, /role="radiogroup"/);
assert.match(wizard, /role="switch"/);
assert.match(wizard, /event\.key !== 'Tab'/);
assert.match(wizard, /_returnFocus/);
assert.match(wizard, /_bindModal\(\);\s*try \{/);
assert.match(wizard, /id="sw-load-close"/);
assert.match(wizard, /id="sw-load-retry"/);
assert.match(wizard, /if \(modal\.dataset\.loadFailed\) _close\(\)/);
assert.match(wizard, /const advance = _filesSaved/);
assert.match(wizard, /const locationsChanged = _filesSaved && filesSignature !== _savedFilesSignature/);
assert.match(wizard, /const advance = _filesSaved && !locationsChanged/);
assert.doesNotMatch(wizard, /!locationsChanged \|\| _obsidian\?\.companion_installed === false/);
assert.match(wizard, /if \(!advance\) _obsidian = null/);
assert.match(wizard, /await _saveStep\('files'/);
assert.match(
  wizard,
  /_savedFilesSignature = `\$\{_state\.vault_preview\}\\n\$\{_state\.files_preview\}\\n\$\{Boolean\(_state\.keep_vault_inside_alles\)\}`/,
);
assert.match(wizard, /_filesSaved = Boolean\(_state\.files_companion_pending\)/);
assert.match(wizard, /companion_reviewed: advance/);
assert.match(wizard, /selectedSearch = \['duckduckgo', 'searxng'\]\.includes\(_state\.search_provider\)/);
assert.match(wizard, /searchFields\(selectedSearch\)/);
assert.match(wizard, /function _renderAiSearch\(body\) \{\s*_pickedModel = null/);
assert.doesNotMatch(wizard, /id="sw-region"/);
assert.match(wizard, /new Intl\.Locale\(locale\)\.region/);
assert.match(wizard, /region: defaults\.region/);
assert.doesNotMatch(wizard, /<select\b/i);
assert.doesNotMatch(wizard, /alles-firstrun-dismissed/);
assert.doesNotMatch(app, /alles-firstrun-dismissed/);
assert.match(app, /st\.setup\?\.completed \|\| st\.setup\?\.dismissed/);
const todayView = app.match(/const showTodayView[\s\S]*?\n};/)?.[0] || '';
assert.match(todayView, /_renderFirstRun\(\)/);
assert.match(html, /id="setup-wizard"[^>]+role="dialog"[^>]+aria-modal="true"/);
assert.match(html, /id="setup-resume-btn"/);
assert.match(settings, /window\._openSetupWizard/);
assert.match(css, /\.setup-actions \.btn \{ min-height: 44px/);

console.log('phase 9 setup source contracts: ok');
