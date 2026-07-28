import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const html = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const sessions = fs.readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const uploads = fs.readFileSync(new URL('../../static/js/uploads.js', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
const ghostPath = 'M5 21v-9a7 7 0 0 1 14 0v9l-2.4-1.5L14.2 21l-2.2-1.5L9.8 21l-2.4-1.5L5 21z';

test('normal, active-bar, and hero incognito states use the same ghost', () => {
  assert.equal((html.match(new RegExp(ghostPath, 'g')) || []).length, 2);
  assert.equal((sessions.match(new RegExp(ghostPath, 'g')) || []).length, 1);
  assert.match(html, /id="incognito-btn"[\s\S]*class="incognito-ghost"/);
  assert.match(html, /id="incognito-bar"[\s\S]*class="incognito-ghost"/);
  assert.match(sessions, /incognito-hero-mark incognito-ghost/);
});

test('incognito state has no glow frame, drop-shadow, or pulse animation', () => {
  assert.doesNotMatch(css, /body\.is-incognito::after/);
  assert.doesNotMatch(css, /incog-pulse/);
  assert.doesNotMatch(css, /\.incognito-btn\.active svg[\s\S]{0,160}drop-shadow/);
  assert.doesNotMatch(css, /\.incognito-hero[^}]*animation/);
});

test('incognito consumers share one modes module instance', () => {
  const version = app.match(/from ['"]\.\/modes\.js\?v=(\d+)['"]/)?.[1];
  assert.ok(version);
  assert.match(sessions, new RegExp(`from ['"]\\./modes\\.js\\?v=${version}['"]`));
  assert.match(uploads, new RegExp(`from ['"]\\./modes\\.js\\?v=${version}['"]`));
});
