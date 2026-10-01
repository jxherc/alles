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
  assert.match(source, /<button type="button" class="project-folder-toggle" aria-expanded=/);
  assert.match(source, /toggleButton\.addEventListener\('click', toggle\)/);
  assert.doesNotMatch(source, /class="project-folder-head"[^>]*role="button"/);
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

test('afterlife sidebar keeps unfiled tasks separate from expandable Project folders', () => {
  const source = readFileSync(new URL('../../static/js/projects.js', import.meta.url), 'utf8');
  assert.match(source, /aide-session-section/);
  assert.doesNotMatch(source, /id: 'general', name: 'General'/);
  assert.match(source, /display:\$\{afterlife \? 'flex'/);
  assert.doesNotMatch(source, /class="aide-runs"/);
  assert.doesNotMatch(source, /folder\.dataset\.id === 'general'/);
  assert.match(source, /project-folder-open/);
  assert.match(source, /class="project-folder\$\{afterlife \? ' open' : ''\}"/);
  assert.match(source, /aria-expanded="\$\{String\(afterlife\)\}"/);
  assert.match(source, /data-session-drop="unassigned"/);
  assert.match(source, /await unassignSession\(session\.project_id, sessionId\)/);
  assert.match(source, /if \(!response\.ok\) throw new Error\('project unassignment failed'\)/);
  assert.match(source, /toast\('could not move to tasks', 'error'\)/);
});
