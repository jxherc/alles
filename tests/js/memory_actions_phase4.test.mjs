import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

globalThis.window = {};

const { memoryProvenanceLabel, provenanceLabels } = await import('../../static/js/memoryactions.js');

test('response provenance names every private context source', () => {
  const labels = provenanceLabels({
    owner_instructions: true,
    project_instructions: true,
    persona: { name: 'coder' },
    memories: [{ id: 'one' }, { id: 'two' }],
    endpoint: 'local ollama',
    model: 'small-model',
  });
  assert.deepEqual(labels, [
    'owner instructions',
    'Project instructions',
    'persona: coder',
    '2 memories',
    'local ollama / small-model',
  ]);
});

test('empty provenance stays quiet', () => {
  assert.deepEqual(provenanceLabels({}), []);
});

test('each visible memory provenance label includes its id and scope', () => {
  assert.equal(memoryProvenanceLabel({ id: 'mem-123', scope: 'project' }), 'project · id mem-123');
  assert.equal(memoryProvenanceLabel({ id: 'mem-456' }), 'global · id mem-456');
  const source = readFileSync(new URL('../../static/js/memoryactions.js', import.meta.url), 'utf8');
  assert.match(source, /safe\(memoryProvenanceLabel\(memory\)\)/);
});
