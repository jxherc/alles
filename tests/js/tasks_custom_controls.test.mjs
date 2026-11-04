import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tasks = readFileSync(new URL('../../static/js/tasks.js', import.meta.url), 'utf8');

test('task editor reads priority and repeat from the custom dropdown API', () => {
  assert.match(tasks, /import \{ getDropdownValue, populateDropdown \} from '\.\/dropdown\.js\?v=217'/);
  assert.match(tasks, /priority: parseInt\(getDropdownValue\(ov\.querySelector\('#te-prio'\)\)\) \|\| 0/);
  assert.match(tasks, /repeat: getDropdownValue\(ov\.querySelector\('#te-rep'\)\)/);
  assert.doesNotMatch(tasks, /querySelector\('#te-(?:prio|rep)'\)\.value/);
});

test('repeat tooltip localizes the selected cadence', () => {
  assert.match(tasks, /tr\(`tasks\.repeat\.\$\{t\.repeat\}`\)/);
});

test('populated task rows expose named keyboard controls and repeat-safe mutations', () => {
  assert.match(tasks, /class="task-check[^`]+aria-label="\$\{checkLabel\}"/s);
  assert.match(tasks, /class="task-title[^`]+aria-label="\$\{esc\(tr\('tasks\.open_named'/s);
  // delete sits in the row's more menu, named by the task (u.10)
  assert.match(tasks, /class="icon-btn task-more"[^`]+tasks\.more_named/s);
  assert.match(tasks, /class="ctx-item danger task-del" role="menuitem"/);
  assert.match(tasks, /if \(btn\.getAttribute\('aria-busy'\) === 'true'\) return/);
  assert.match(tasks, /setControlState\(button, 'error'/);
});

test('task editor is a labelled modal focus boundary with failure recovery', () => {
  assert.match(tasks, /role="dialog" aria-modal="true" aria-labelledby="task-editor-title"/);
  assert.match(tasks, /createFocusBoundary\(dialog, \{ trigger: source, onEscape: close \}\)/);
  assert.match(tasks, /focusBoundary\.activate\(\{ focus: ov\.querySelector\('#te-title'\), source \}\)/);
  assert.match(tasks, /document\.querySelector\(`\.task-item\[data-id="\$\{id\}"\] \.task-title`\)\?\.focus\(\)/);
});
