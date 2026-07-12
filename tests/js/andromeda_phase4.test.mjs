import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

globalThis.location = {
  hostname: 'localhost',
  port: '8000',
  protocol: 'http:',
};

const {
  failureSummary,
  parseSseFrames,
  validatedProjectId,
  withProjectContext,
} = await import('../../static/js/andromeda.js');

test('overview SSE parsing preserves partial frames and ordered claim events', () => {
  const first = parseSseFrames('data: {"type":"claim","claim":{"text":"one"}}\n\ndata: {"type"');
  assert.deepEqual(first.frames, ['{"type":"claim","claim":{"text":"one"}}']);
  assert.equal(first.rest, 'data: {"type"');
  const second = parseSseFrames(first.rest + ':"overview"}\n\ndata: [DONE]\n\n');
  assert.deepEqual(second.frames, ['{"type":"overview"}', '[DONE]']);
  assert.equal(second.rest, '');
});

test('SSE parser ignores non-data fields without losing later data', () => {
  const parsed = parseSseFrames('event: note\ndata: first\n\nid: 2\ndata: second\n\n');
  assert.deepEqual(parsed.frames, ['first', 'second']);
});

test('failure details name the type and bounded attempted sources', () => {
  assert.equal(
    failureSummary({ failure_type: 'provider_timeout', attempted_sources: ['managed searxng', 'external fallback'] }),
    'failure: provider timeout · tried: managed searxng, external fallback',
  );
  assert.equal(failureSummary({}), '');
});

test('Project context accepts only UUIDs and survives an Andromeda URL', () => {
  const id = '123e4567-e89b-42d3-a456-426614174000';
  assert.equal(validatedProjectId(id.toUpperCase()), id);
  assert.equal(validatedProjectId('../../private'), '');
  assert.equal(
    withProjectContext('http://localhost:8000/?app=andromeda&q=docs', id),
    `http://localhost:8000/?app=andromeda&q=docs&project_id=${id}`,
  );
  assert.equal(withProjectContext('http://localhost:8000/?app=andromeda', 'general'), 'http://localhost:8000/?app=andromeda');
});

test('Aide cross-app routes explicitly carry the selected Project into Andromeda', () => {
  const source = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  const andromeda = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(source, /crossNav\(dest, v\)/);
  assert.match(source, /withProjectContext\(base, window\._currentSession\?\.project_id\)/);
  assert.match(source, /withProjectContext\(target, window\._currentSession\?\.project_id\)/);
  assert.doesNotMatch(andromeda, /jsonRequest\(`\/api\/projects\//);
  assert.match(andromeda, /_projectId = validatedProjectId/);
  assert.match(andromeda, /project_id: _projectId/);
});
