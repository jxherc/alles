import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { projectFolderMessage } from '../../static/js/projectenv.js';

test('project folder states are clear and actionable', () => {
  assert.equal(projectFolderMessage('available'), 'folder available');
  assert.match(projectFolderMessage('missing'), /folder missing/);
  assert.match(projectFolderMessage('relink_required'), /folder required/);
});

test('project folders open from the keyboard', () => {
  const source = readFileSync(new URL('../../static/js/projects.js', import.meta.url), 'utf8');
  assert.match(source, /class="project-folder-head" role="button" tabindex="0"/);
  assert.match(source, /e\.key !== 'Enter' && e\.key !== ' '/);
});

test('switching views hides the project workspace', () => {
  const source = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  assert.match(source, /'project-view',\s*\n\];/);
});

test('projects still render before the first chat exists', () => {
  const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
  assert.match(
    source,
    /if \(!src\.length\) \{[\s\S]*?renderProjectFolders\(_allSessions,[\s\S]*?return;/,
  );
});
