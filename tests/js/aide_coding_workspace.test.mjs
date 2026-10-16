import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/aidecoding.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '')
  .replace(/^export /gm, '');

function fixture() {
  class Node {
    constructor() { this.children = []; this.hidden = false; this.textContent = ''; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
  }
  const nodes = new Map(['aide-coding-events', 'aide-coding-remote', 'aide-coding-remote-events', 'aide-coding-output', 'aide-coding-output-body']
    .map(id => [id, new Node()]));
  const context = vm.createContext({
    document: { getElementById: id => nodes.get(id), createElement: () => new Node() },
    formatDateTime: value => value,
  });
  vm.runInContext(source + `
    globalThis.subject = {
      choose: id => { selectedRunId = id; renderEvents(id); },
      render: renderEvents,
      local: (id, value) => eventCache.set(id, value),
      remote: (id, value) => remoteEventCache.set(id, value),
    };
  `, context);
  return {
    ...context.subject,
    visible: () => !nodes.get('aide-coding-remote').hidden,
    remoteText: () => nodes.get('aide-coding-remote-events').children.map(node => node.textContent),
    localText: () => nodes.get('aide-coding-events').children.map(node => node.textContent),
  };
}

for (const state of ['loading', 'failed']) {
  test(`selecting a ${state} run clears the previous run's remote activity immediately`, () => {
    const h = fixture();
    h.local('first', { items: [] });
    h.remote('first', [{ summary: 'First run completed.' }]);
    h.choose('first');
    assert.equal(h.visible(), true);
    assert.deepEqual(h.remoteText(), ['First run completed.']);
    if (state === 'failed') h.local('second', { error: 'Activity unavailable.' });
    h.choose('second');
    assert.equal(h.visible(), false);
    assert.deepEqual(h.remoteText(), []);
    assert.deepEqual(h.localText(), [state === 'loading' ? 'loading activity…' : 'Activity unavailable.']);
  });
}

test('local event failure keeps only the selected run’s genuine cached remote activity', () => {
  const h = fixture();
  h.local('first', { items: [] });
  h.remote('first', [{ summary: 'First run completed.' }]);
  h.choose('first');
  h.local('second', { error: 'Activity unavailable.' });
  h.remote('second', [{ summary: 'Second run started.' }]);
  h.choose('second');
  assert.equal(h.visible(), true);
  assert.deepEqual(h.remoteText(), ['Second run started.']);
  h.render('first'); // A late response must not repaint the selected run.
  assert.deepEqual(h.remoteText(), ['Second run started.']);
});

function handlerFixture() {
  const nodes = new Map();
  const document = {
    activeElement: null,
    getElementById: id => nodes.get(id),
    createElement: tag => new Node(tag),
    addEventListener() {},
  };
  class Node {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
      this.hidden = false; this.value = ''; this.textContent = ''; this.attributes = new Map();
      this.listeners = new Map(); this.classList = { add() {} };
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    setAttribute(name, value) { this.attributes.set(name, value); }
    removeAttribute(name) { this.attributes.delete(name); }
    addEventListener(type, handler) { this.listeners.set(type, handler); }
    focus() { document.activeElement = this; }
    querySelectorAll(selector) {
      if (selector === '[data-coding-view]') return [...nodes.values()].filter(node => node.dataset.codingView);
      const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      if (selector === '[data-run-id]') return descendants.filter(node => node.dataset.runId);
      return descendants;
    }
    querySelector(selector) {
      if (selector === 'button[type="submit"]') return this.children.find(node => node.type === 'submit');
      return null;
    }
    dispatch(type) {
      return this.listeners.get(type)?.({ currentTarget: this, target: this, preventDefault() {} });
    }
  }
  for (const [, id] of source.matchAll(/id="(aide-coding-[^"]+)"/g)) nodes.set(id, new Node());
  nodes.set('aide-coding-workspace', new Node());
  for (const [id, view] of [['draft', 'draft'], ['run-detail', 'run'], ['connection', 'connection']]) {
    nodes.get(`aide-coding-${id}`).dataset.codingView = view;
  }
  const followupButton = new Node('button'); followupButton.type = 'submit';
  nodes.get('aide-coding-followup').append(followupButton);
  const savedRuns = ['a', 'b'].map(id => ({ id, prompt: `run ${id}`, terminal: true, state: 'succeeded' }));
  let pendingPost = null, nextId = 0;
  const response = data => ({ ok: true, status: 200, json: async () => data });
  const context = vm.createContext({
    document, formatDateTime: value => value, clearTimeout() {},
    window: { matchMedia: () => ({ addEventListener() {} }) },
    wireAutosizeTextarea() {}, autosizeTextarea() {}, requestId: () => `request-${++nextId}`,
    fetch: async (path, init = {}) => {
      if (init.method === 'POST') {
        assert.equal(pendingPost, null);
        return new Promise(resolve => {
          pendingPost = {
            path, payload: JSON.parse(init.body),
            resolve: data => { pendingPost = null; resolve(response(data)); },
          };
        });
      }
      if (path === '/api/aide/coding/runs?limit=100') return response({ items: savedRuns });
      if (path.endsWith('/events')) return response({ items: [], remote_events: [] });
      throw new Error(`unexpected request ${path}`);
    },
  });
  vm.runInContext(source + `
    globalThis.subject = {
      prepare(items) {
        initAideCodingWorkspace();
        runs = items; selectedWorkspace = { workspace_id: 'project', path: '/owned/project' };
        setConnectionState({ configured: true }); renderRuns(); setView('draft');
        return openAideCodingWorkspace({ refresh: false });
      },
      state: () => ({ selectedRunId, currentView, hidden: host.hidden }),
      close: closeAideCodingWorkspace,
      reopen: () => openAideCodingWorkspace({ refresh: false }),
    };
  `, context);
  context.subject.prepare(savedRuns);
  const node = id => nodes.get(`aide-coding-${id}`);
  return {
    node, state: context.subject.state, close: context.subject.close, reopen: context.subject.reopen,
    focus: () => document.activeElement,
    clickRun: id => node('run-list').children.find(child => child.dataset.runId === id).dispatch('click'),
    submit: form => node(form).dispatch('submit'),
    resolvePost: ({ newRun = false } = {}) => {
      assert.ok(pendingPost);
      const run = newRun ? { id: pendingPost.payload.request_id, prompt: pendingPost.payload.prompt, terminal: true, state: 'succeeded' } : savedRuns[0];
      if (newRun) savedRuns.unshift(run);
      pendingPost.resolve(run);
      return run;
    },
  };
}

for (const destination of ['another run', 'new run']) {
  test(`a follow-up receipt preserves newer text after navigating to ${destination}`, async () => {
    const h = handlerFixture();
    await h.clickRun('a');
    h.node('followup-prompt').value = 'submitted instruction';
    const submission = h.submit('followup');
    h.node('followup-prompt').value = 'newer unsent instruction';
    if (destination === 'another run') await h.clickRun('b');
    else h.node('new').dispatch('click');
    h.resolvePost(); await submission;
    await h.clickRun('a');
    assert.equal(h.node('followup-prompt').value, 'newer unsent instruction');
  });
}

test('new run navigation preserves an unsent follow-up without a request in flight', async () => {
  const h = handlerFixture();
  await h.clickRun('a');
  h.node('followup-prompt').value = 'unsent follow-up';
  h.node('new').dispatch('click');
  await h.clickRun('a');
  assert.equal(h.node('followup-prompt').value, 'unsent follow-up');
});

test('a successful follow-up clears its submitted text from the field and cached draft', async () => {
  const h = handlerFixture();
  await h.clickRun('a');
  h.node('followup-prompt').value = 'submitted instruction';
  const submission = h.submit('followup');
  await h.clickRun('b');
  h.resolvePost(); await submission;
  await h.clickRun('a');
  assert.equal(h.node('followup-prompt').value, '');
});

for (const destination of ['another run', 'connection', 'connection and back', 'closed surface', 'closed and reopened surface', 'new draft']) {
  test(`a delayed start preserves ${destination} and its focus`, async () => {
    const h = handlerFixture();
    h.node('prompt').value = 'start this run';
    const submission = h.submit('start');
    if (destination === 'another run') await h.clickRun('b');
    if (destination.startsWith('connection')) {
      h.node('connection-toggle').dispatch('click');
      if (destination === 'connection and back') h.node('connection-back').dispatch('click');
    }
    if (destination.startsWith('closed')) {
      h.close();
      if (destination === 'closed and reopened surface') await h.reopen();
      h.node('back').focus();
    }
    if (destination === 'new draft') { h.node('new').dispatch('click'); h.node('prompt').value = 'newer start draft'; }
    const selected = h.state(), focus = h.focus();
    const run = h.resolvePost({ newRun: true }); await submission;
    assert.deepEqual(h.state(), selected);
    assert.equal(h.focus(), focus);
    assert.ok(h.node('run-list').children.some(child => child.dataset.runId === run.id), 'receipt remains available');
    if (destination === 'new draft') assert.equal(h.node('prompt').value, 'newer start draft');
  });
}

test('a start still selects and focuses its receipt when the originating draft remains open', async () => {
  const h = handlerFixture();
  h.node('prompt').value = 'start this run';
  const submission = h.submit('start');
  const run = h.resolvePost({ newRun: true }); await submission;
  assert.equal(h.state().selectedRunId, run.id);
  assert.equal(h.state().currentView, 'run');
  assert.equal(h.focus(), h.node('detail-title'));
  assert.equal(h.node('prompt').value, '');
});
