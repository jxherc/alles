import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../static/js/server_workbench.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');

test('Server workbench exposes the approved management sections without native choice controls', () => {
  for (const section of ['overview', 'services', 'search', 'backups', 'updates', 'logs', 'activity', 'watch', 'policy']) {
    assert.match(html, new RegExp(`data-group-section="${section}"`), section);
  }
  assert.doesNotMatch(source, /createElement\(['"]select['"]\)/);
  assert.doesNotMatch(source, /type\s*=\s*['"](?:checkbox|radio)['"]/);
  assert.match(source, /setAttribute\('role', 'radiogroup'\)/);
  assert.match(source, /setAttribute\('role', 'switch'\)/);
});

test('Server policy editor is schema-bound to the one policy API', () => {
  assert.match(source, /json\(request, '\/api\/system\/policy'/);
  assert.match(source, /json\(request, '\/api\/system\/policy\/diff'/);
  assert.match(source, /type “\$\{current\.confirmation_phrase\}”/);
  assert.doesNotMatch(source, /showOpenFilePicker|webkitdirectory|type\s*=\s*['"]file['"]/);
  assert.doesNotMatch(source, /\/api\/(?:shell|exec|command)/);
});

test('Server owns separate answer and verifier model roles and bounded controls', () => {
  assert.match(source, /'andromeda_answer', 'andromeda_verifier'/);
  assert.match(source, /andromeda_answer_max_tokens/);
  assert.match(source, /andromeda_verifier_max_tokens/);
  assert.match(source, /andromeda_verification_enabled/);
  assert.match(source, /freshness-sensitive/);
  assert.match(source, /search_result_count: Number\(value\)/);
});

test('managed companions expose native service APIs without storing the Nginx password', () => {
  for (const route of [
    '/api/system/companions/adguard-home/dashboard',
    '/api/system/companions/adguard-home/filtering',
    '/api/system/companions/adguard-home/rewrites/add',
    '/api/system/companions/nginx-proxy-manager/dashboard',
    '/api/system/companions/nginx-proxy-manager/connect',
    '/api/system/companions/nginx-proxy-manager/proxy-hosts',
  ]) assert.match(source, new RegExp(route.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(source, /The password is exchanged locally and never stored/);
  assert.match(source, /only the encrypted API token is retained/);
  assert.match(source, /DNS filtering/);
  assert.match(source, /DNS rewrites/);
  assert.match(source, /certificates/);
});

test('Server mutations recover exact recent-owner challenges and reject repeated activation', () => {
  assert.match(source, /requestWithRecentOwner\(request, url, options\)/);
  assert.match(source, /button\.setAttribute\('aria-busy', 'true'\)/);
  assert.match(source, /button\.removeAttribute\('aria-busy'\)/);
  assert.match(source, /if \(button\.disabled\) return/);
});

test('Server choices roll back failed persistence and disruptive controls confirm consequence', () => {
  assert.match(source, /const previous = buttons\.find/);
  assert.match(source, /catch \(error\) \{\s*select\(previous \|\| button\)/);
  assert.match(source, /rollbackFocus = previous \|\| button/);
  assert.match(source, /rollbackFocus\?\.focus\(\)/);
  assert.match(source, /list\.setAttribute\('aria-busy', 'true'\)/);
  assert.match(source, /function destructiveAction/);
  assert.match(source, /function serviceAction/);
  assert.match(source, /remove Alles ownership of/);
  assert.match(source, /roll back .* activation\?/);
});

test('legacy Docs, Files, Vault, System, Activity, and Watch render inside workbench shells', () => {
  assert.match(app, /group === 'docs'/);
  assert.match(app, /group === 'files' && section === 'gallery'/);
  assert.match(app, /group === 'vault'/);
  assert.match(app, /group === 'server' && section === 'overview'/);
  assert.match(app, /group === 'server' && section === 'activity'/);
  assert.match(app, /group === 'server' && section === 'watch'/);
  assert.match(app, /history\.pushState/);
  assert.match(app, /addEventListener\('popstate'/);
});
