import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync('docs/mockups/afterlife-specialists/remaining.js', 'utf8');
const html = fs.readFileSync('docs/mockups/afterlife-specialists/plan-kanban-v2.html', 'utf8');

test('completed mockup tasks restore their original project and reapply filters', () => {
  assert.match(source, /restore\.dataset\.restoreProject = selectedTask\.dataset\.project/);
  assert.match(source, /item\._completedCard = former/);
  assert.match(source, /completedItem\?\._completedCard\s*\|\| makePlanCard/);
  assert.match(source, /card\.dataset\.stage = 'backlog'/);
  assert.match(source, /completedItem\?\.remove\(\);\s*refreshPlanCounts\(\);\s*applyPlanFilters\(\)/);
  assert.match(source, /if \(card\.hidden\) \{[\s\S]*?projectFilter = card\.dataset\.project;[\s\S]*?applyPlanFilters\(\)/);
  assert.match(source, /filters updated to show it/);
  assert.match(html, /data-restore-title="send Sunday dinner time" data-restore-project="personal"/);
});

test('source testing validates and stays bound to the current feed URL', () => {
  assert.match(source, /new URL\(sourceUrl\?\.value\.trim\(\) \|\| ''\)/);
  assert.match(source, /\['http:', 'https:'\]\.includes\(parsed\.protocol\)/);
  assert.match(source, /sourceUrl\?\.addEventListener\('input', resetSourceTest\)/);
  assert.match(source, /sourceUrl\?\.value\.trim\(\) !== testedSourceUrl/);
});

test('completing the final mockup task clears stale detail and exposes the empty state', () => {
  assert.match(source, /function clearTaskDetail\(boardIsEmpty = planCards\(\)\.length === 0\)/);
  assert.match(source, /remainingBody\.dataset\.boardEmpty = 'true'/);
  assert.match(source, /delete remainingBody\.dataset\.boardEmpty/);
  assert.match(source, /former\.remove\(\);\s*applyPlanFilters\(\)/);
});

test('filtering never leaves controls bound to a hidden task', () => {
  assert.match(source, /function reconcilePlanSelection\(preferred = null\)/);
  assert.match(source, /const visible = planCards\(\)\.filter\(card => !card\.hidden\)/);
  assert.match(source, /preferred && !preferred\.hidden/);
  assert.match(source, /selectedTask && !selectedTask\.hidden/);
  assert.match(source, /if \(next\) renderTaskDetail\(next\);\s*else clearTaskDetail\(planCards\(\)\.length === 0\)/);
  assert.match(source, /if \(boardIsEmpty\) remainingBody\.dataset\.boardEmpty = 'true';\s*else delete remainingBody\.dataset\.boardEmpty/);
  assert.match(source, /no matching tasks/);
  assert.match(source, /applyPlanFilters\(\);\s*reconcilePlanSelection\(card\)/);
});

test('new mockup tasks stay inside the active project filter', () => {
  const add = source.match(/function addPlanTask\(title, stage = 'backlog'\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(add, /projectFilter === 'all' \? 'personal' : projectFilter/);
  assert.match(add, /makePlanCard\(clean, stage, project\)/);
});
