import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import { normalizeNewsTimestamp } from '../../static/js/aidenews.js';

const ui = fs.readFileSync(new URL('../../static/js/aidenews.js', import.meta.url), 'utf8');
const scheduled = fs.readFileSync(new URL('../../static/js/aidescheduled.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');

test('Scheduled owns a first-class News tab and real workbench', () => {
  assert.match(html, /data-scheduled-tab="news"/);
  assert.match(html, /id="aide-news-workbench"/);
  assert.match(scheduled, /initAideNews/);
  assert.match(scheduled, /section === 'news'/);
});

test('News uses custom accessible choices and automatic browser timezone', () => {
  assert.match(ui, /role="switch"/);
  assert.match(ui, /role="radiogroup"/);
  assert.match(ui, /role="radio"/);
  assert.match(ui, /resolvedTimeZone/);
  assert.match(ui, /formatDateTime/);
  assert.doesNotMatch(ui, /new Intl\.DateTimeFormat/);
  assert.doesNotMatch(ui, /<select|type="radio"|type="checkbox"/);
  assert.match(css, /\.news-switch::before/);
  assert.match(css, /width: 42px;[\s\S]*height: 24px;[\s\S]*border-radius: 999px/);
  for (const language of ['en', 'fr', 'es', 'zh-Hans', 'zh-Hant', 'ja', 'ko', 'ar', 'other']) {
    assert.match(ui, new RegExp(`\\['${language}',`));
  }
});

test('News tests sources before save and keeps Library explicit', () => {
  assert.match(ui, /\/api\/news\/sources\/test/);
  assert.match(ui, /test this URL before saving/);
  assert.match(ui, /Nothing was saved/);
  assert.match(ui, /\/api\/read\/save-news/);
  assert.match(ui, /save to Library/);
  assert.match(ui, /if \(save\) save\.disabled = changed/);
  assert.match(ui, /Source tested\. You can save it now\./);
  assert.match(ui, /\['http:', 'https:'\]\.includes\(parsed\.protocol\)/);
  assert.match(ui, /const url = safeNewsUrl\(link\.url\)/);
  assert.match(ui, /: `<span>\$\{esc\(link\.source\)\}<\/span>`/);
});

test('News has bounded fallback, independent source health, and gated Jarvis delivery copy', () => {
  const service = fs.readFileSync(new URL('../../services/news.py', import.meta.url), 'utf8');
  const route = fs.readFileSync(new URL('../../routes/news.py', import.meta.url), 'utf8');
  assert.match(service, /asyncio\.wait_for/);
  assert.match(service, /next_retry_at/);
  assert.match(service, /summary_pending/);
  assert.match(route, /readiness\["available"\]/);
  assert.match(ui, /pair Discord before enabling/);
});

test('Scheduled preserves timestamps that already include a numeric offset', () => {
  assert.ok(scheduled.includes('(?:Z|[+-]\\d{2}:?\\d{2})$'));
  assert.doesNotMatch(scheduled, /value\.endsWith\?\.\('Z'\) \? value : `\$\{value\}Z`/);
  assert.equal(normalizeNewsTimestamp('2026-07-23T08:00:00+08:00'), '2026-07-23T08:00:00+08:00');
  assert.equal(normalizeNewsTimestamp('2026-07-23T00:00:00'), '2026-07-23T00:00:00Z');
});

test('News restores the saved cadence when persistence fails', () => {
  const handler = ui.match(/async function handleRadio\(button\)[\s\S]*?\n}/)[0];
  assert.match(handler, /const previous = group === 'cadence' \? state\.configuration\.cadence/);
  assert.match(handler, /catch \(error\)/);
  assert.match(handler, /if \(prior\) chooseRadio\(prior\)/);
  assert.match(handler, /throw error/);
});

test('stale source tests cannot mutate a replaced or edited News form', () => {
  const handler = ui.match(/async function handleAction\(button\)[\s\S]*?\n}/)[0];
  assert.match(handler, /const actionEditor = editor/);
  assert.match(handler, /actionEditor\.testRequest = requestId/);
  assert.match(handler, /editor !== actionEditor/);
  assert.match(handler, /actionEditor\.testRequest !== requestId/);
  assert.match(handler, /currentUrl !== value/);
  assert.match(handler, /currentUrl !== value[\s\S]*?button\.disabled = false;[\s\S]*?return;/);
  assert.match(handler, /status && editor === actionEditor/);
});
