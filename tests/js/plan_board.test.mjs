import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { groupPlanBoardTasks, localDateKey } from '../../static/js/plan_board.js';

const source = readFileSync(new URL('../../static/js/plan_board.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');

test('Plan board groups existing Task stages and leaves completed work out of active columns', () => {
  const grouped = groupPlanBoardTasks([
    { id: 'late', title: 'later', stage: 'next', sort_order: 3 },
    { id: 'first', title: 'first', stage: 'next', sort_order: 0 },
    { id: 'legacy', title: 'legacy', stage: 'unknown', sort_order: 0 },
    { id: 'done', title: 'done', stage: 'doing', done: true },
  ]);

  assert.deepEqual(Object.keys(grouped), ['backlog', 'next', 'doing', 'waiting']);
  assert.deepEqual(grouped.backlog.map(task => task.id), ['legacy']);
  assert.deepEqual(grouped.next.map(task => task.id), ['first', 'late']);
  assert.equal(Object.values(grouped).flat().some(task => task.id === 'done'), false);
});

test('Plan board compares due dates against the viewer local calendar day', () => {
  const localMidnight = new Date(2026, 6, 22, 0, 15, 0);
  assert.equal(localDateKey(localMidnight), '2026-07-22');
  assert.doesNotMatch(source, /new Date\(\)\.toISOString\(\)\.slice\(0, 10\)/);
});

test('Plan board uses custom accessible controls and atomic stage ordering', () => {
  assert.match(source, /setAttribute\('role', 'radiogroup'\)/);
  assert.match(source, /setAttribute\('role', 'menuitemradio'\)/);
  assert.match(source, /ArrowRight[^]*?ArrowLeft[^]*?Home[^]*?End/);
  assert.match(source, /\/api\/tasks\/reorder/);
  assert.match(source, /let reorderQueue = Promise\.resolve\(\)/);
  assert.match(source, /reorderQueue = reorderQueue\.catch\(\(\) => \{\}\)\.then\(\(\) => persistOrder/);
  assert.match(source, /JSON\.stringify\(payload\)/);
  assert.doesNotMatch(source, /createElement\(['"]select['"]\)/);
  assert.doesNotMatch(source, /type\s*=\s*['"](?:checkbox|radio)['"]/);
  assert.match(css, /\.plan-board-stage-choice\s*\{[^]*?min-height:\s*44px/);
  assert.match(css, /\.plan-board-root\[data-mobile-stage="doing"\][^]*?data-stage="doing"/);
  assert.match(css, /\.plan-board-toolbar\s*\{[^]*?gap:\s*var\(--k-space-3/);
  assert.match(css, /\.plan-board-columns\s*\{[^]*?gap:\s*var\(--k-space-4/);
  assert.match(css, /\.plan-board-columns\s*\{[^]*?grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\)/);
  assert.match(css, /\.plan-board-list\s*\{[^]*?gap:\s*var\(--k-space-3/);
  assert.match(css, /\.plan-board-card\s*\{[^]*?padding:\s*var\(--k-space-3/);
  assert.match(css, /\.plan-board-inline-add\s*\{[^]*?min-width:\s*0/);
});

test('Plan board distinguishes a successful create from a failed refresh', () => {
  assert.equal((source.match(/let created = false;/g) || []).length, 2);
  assert.equal((source.match(/task was added, but the board could not reload/g) || []).length, 2);
  assert.match(source, /created = true;[\s\S]*?if \(created\) \{[\s\S]*?await refresh\(\)/);
});

test('Plan board accepts reorder drags only from its active internal card', () => {
  assert.match(source, /application\/x-alles-plan-task/);
  assert.match(source, /dataTransfer\?\.types/);
  assert.match(source, /activeCard\.dataset\.taskId !== String\(id\)/);
  assert.doesNotMatch(source, /setData\('text\/plain', task\.id\)/);
  assert.match(source, /if \(!targetCard \|\| targetCard\.parentElement !== list\) \{\s*list\.append\(activeCard\)/);
});
