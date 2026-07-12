import assert from 'node:assert/strict';
import test from 'node:test';

const { renderAgentSteps } = await import('../../static/js/agentview.js');

test('successful steps reload collapsed with one clear control', () => {
  const html = renderAgentSteps([{ name: 'read_file', args: { path: 'a.md' }, output: 'ok' }]);
  assert.match(html, /show steps/);
  assert.match(html, /hide steps/);
  assert.doesNotMatch(html, /<details class="agent-steps" open>/);
});

test('failed steps reload open so failure stays visible', () => {
  const html = renderAgentSteps([{ name: 'web_fetch', error: true, output: 'timeout' }]);
  assert.match(html, /<details class="agent-steps" open>/);
  assert.match(html, /timeout/);
});

test('reload restores sources and revert controls from the durable run id', () => {
  const html = renderAgentSteps(
    [{ name: 'edit_file', args: { path: 'a.md' }, diff: '-old\n+new' }],
    false,
    'run-123',
  );
  assert.match(html, /data-agent-sources="run-123"/);
  assert.match(html, /data-agent-revert="run-123"/);
});

test('read-only reload has sources without a false revert action', () => {
  const html = renderAgentSteps([{ name: 'read_file', args: { path: 'a.md' } }], false, 'run-read');
  assert.match(html, /data-agent-sources="run-read"/);
  assert.doesNotMatch(html, /data-agent-revert/);
});
