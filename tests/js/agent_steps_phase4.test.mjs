import assert from 'node:assert/strict';
import test from 'node:test';

const { renderAgentSteps } = await import('../../static/js/agentview.js');

test('document diffs retain their preview without offering the filesystem revert action', () => {
  const html = renderAgentSteps([{ name: 'docs_write', args: { path: 'work.md' }, diff: '-old\n+new' }], false, 'run-doc');
  assert.match(html, /agent-step-diff/);
  assert.match(html, /data-agent-sources="run-doc"/);
  assert.doesNotMatch(html, /data-agent-revert/);
});

test('successful steps reload collapsed with one clear control', () => {
  const html = renderAgentSteps([{ name: 'read_file', args: { path: 'a.md' }, output: 'ok' }]);
  assert.match(html, /1 step/);
  assert.doesNotMatch(html, /show steps|hide steps|turn \d+ \/ \d+/);
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

test('a saved doc gets a card that opens it; a failed write does not', () => {
  const html = renderAgentSteps([{ name: 'docs_write', args: { path: 'lists/groceries.md' } }]);
  assert.match(html, /data-open-doc="lists\/groceries.md"/);
  assert.match(html, /groceries/);
  assert.doesNotMatch(renderAgentSteps([{ name: 'docs_write', args: { path: 'x.md' }, error: true }]), /data-open-doc/);
});

test('docs pi saved for Aide get the same card', () => {
  const html = renderAgentSteps([{ name: 'pi_run', args: { task: 'plan' }, output: 'pi is working in Aide\n· docs write plans/guitar.md\n  saved doc: plans/guitar.md\n' }]);
  assert.match(html, /data-open-doc="plans\/guitar.md"/);
});

test('a skipped question reads as a skip, without its tool data or a failure count', () => {
  const html = renderAgentSteps([{
    name: 'ask_user', error: true,
    args: { title: 'Choose the verification', questions: [{ id: 'surface' }] },
    output: '{"cancelled": true, "answers": {}}',
  }]);
  assert.match(html, /you skipped this question/);
  assert.doesNotMatch(html, /failed|cancelled|answers|args/);
});
