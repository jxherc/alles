import assert from 'node:assert/strict';
import { test } from 'node:test';

import { projectFolderMessage } from '../../static/js/projectenv.js';

test('project folder states are clear and actionable', () => {
  assert.equal(projectFolderMessage('available'), 'folder available');
  assert.match(projectFolderMessage('missing'), /folder missing/);
  assert.match(projectFolderMessage('relink_required'), /folder required/);
});
