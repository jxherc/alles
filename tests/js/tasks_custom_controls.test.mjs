import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tasks = readFileSync(new URL('../../static/js/tasks.js', import.meta.url), 'utf8');

test('task editor reads priority and repeat from the custom dropdown API', () => {
  assert.match(tasks, /import \{ getDropdownValue, populateDropdown \} from '\.\/dropdown\.js\?v=212'/);
  assert.match(tasks, /priority: parseInt\(getDropdownValue\(ov\.querySelector\('#te-prio'\)\)\) \|\| 0/);
  assert.match(tasks, /repeat: getDropdownValue\(ov\.querySelector\('#te-rep'\)\)/);
  assert.doesNotMatch(tasks, /querySelector\('#te-(?:prio|rep)'\)\.value/);
});

test('repeat tooltip localizes the selected cadence', () => {
  assert.match(tasks, /tr\(`tasks\.repeat\.\$\{t\.repeat\}`\)/);
});
