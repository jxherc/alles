import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

globalThis.window = new EventTarget();
const { setModelRole, onModelRoles, announceModelRoles, roleOptions, MODEL_ROLES_EVENT } =
  await import('../../static/js/settings/model_roles.js');

const read = path => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');

function backend(initial, { failPatch = false } = {}) {
  const state = { roles: structuredClone(initial), patches: [] };
  globalThis.fetch = async (url, options = {}) => {
    assert.equal(url, '/api/settings');
    if (options.method === 'PATCH') {
      const body = JSON.parse(options.body);
      state.patches.push(body);
      if (failPatch) return { ok: false, json: async () => ({ detail: 'refused' }) };
      state.roles = body.model_roles;
      return { ok: true, json: async () => ({ model_roles: state.roles }) };
    }
    return { ok: true, json: async () => ({ model_roles: state.roles }) };
  };
  return state;
}

const aide = { endpoint_id: 'ep-a', model: 'chat-a', cost_class: 'paid', fallbacks: [] };
const answerA = { endpoint_id: 'ep-a', model: 'answer-a', cost_class: 'cheap', fallbacks: [{ endpoint_id: 'ep-b', model: 'backup' }] };
const answerB = { endpoint_id: 'ep-b', model: 'answer-b' };

test('setModelRole changes one role and keeps every other stored role as it is', async () => {
  const state = backend({ aide_chat: aide, andromeda_answer: answerA, andromeda_verifier: {} });
  const stored = await setModelRole('andromeda_answer', answerB, { source: 'andromeda' });
  assert.equal(state.patches.length, 1);
  assert.deepEqual(state.patches[0].model_roles.aide_chat, aide);
  assert.deepEqual(state.patches[0].model_roles.andromeda_verifier, {});
  assert.deepEqual(state.patches[0].model_roles.andromeda_answer, {
    endpoint_id: 'ep-b', model: 'answer-b', cost_class: 'cheap', fallbacks: answerA.fallbacks,
  });
  assert.equal(stored.andromeda_answer.model, 'answer-b');
});

test('automatic clears the role', async () => {
  const state = backend({ andromeda_answer: answerA });
  await setModelRole('andromeda_answer', null);
  assert.deepEqual(state.roles.andromeda_answer, {});
});

test('the andromeda section and the models section see each other\'s change', async () => {
  const state = backend({ aide_chat: aide, andromeda_answer: {} });
  const andromedaSeen = [];
  const modelsSeen = [];
  // each section ignores the events it sent itself, as the real ones do
  const offAndromeda = onModelRoles(({ roles, source }) => { if (source !== 'andromeda') andromedaSeen.push(roles.andromeda_answer.model); });
  const offModels = onModelRoles(({ roles, source }) => { if (source !== 'models') modelsSeen.push(roles.andromeda_answer.model); });

  await setModelRole('andromeda_answer', answerA, { source: 'andromeda' });
  assert.deepEqual(modelsSeen, ['answer-a']);
  assert.deepEqual(andromedaSeen, []);

  await setModelRole('andromeda_answer', answerB, { source: 'models' });
  assert.deepEqual(andromedaSeen, ['answer-b']);
  assert.deepEqual(modelsSeen, ['answer-a']);
  // one stored value: both sections show what the server holds
  assert.equal(state.roles.andromeda_answer.model, 'answer-b');
  assert.equal(state.roles.aide_chat.model, 'chat-a');
  offAndromeda();
  offModels();
});

test('a refused save throws and announces nothing', async () => {
  backend({ andromeda_answer: answerA }, { failPatch: true });
  let heard = 0;
  const off = onModelRoles(() => { heard += 1; });
  await assert.rejects(() => setModelRole('andromeda_answer', answerB), /refused/);
  assert.equal(heard, 0);
  off();
});

test('announce carries the roles and who sent them', () => {
  const heard = [];
  const off = onModelRoles(detail => heard.push(detail));
  announceModelRoles({ andromeda_answer: answerB }, 'models');
  off();
  announceModelRoles({}, 'models');
  assert.deepEqual(heard, [{ roles: { andromeda_answer: answerB }, source: 'models' }]);
  assert.equal(MODEL_ROLES_EVENT, 'alles:model-roles');
});

test('role options pick the saved model and keep one that is no longer offered', () => {
  const endpoints = [{ id: 'ep-a', name: 'A', models: ['answer-a'] }];
  const known = roleOptions(endpoints, { endpoint_id: 'ep-a', model: 'answer-a' });
  assert.equal(known.choices[known.selected].model, 'answer-a');
  const gone = roleOptions(endpoints, { endpoint_id: 'ep-z', model: 'old' });
  assert.match(gone.selected, /^unavailable-/);
  assert.equal(roleOptions(endpoints, {}).selected, '');
});

test('both sections edit the answer model through the shared role helper', () => {
  const providers = read('static/js/settings/providers.js');
  const section = read('static/js/settings/andromeda.js');
  const html = read('static/index.html');
  // models section: the role select saves at once and listens for the other section
  assert.match(providers, /const SHARED_ROLE = 'andromeda_answer'/);
  assert.match(providers, /if \(role === SHARED_ROLE\) \{ _saveSharedRole\(select\); return; \}/);
  assert.match(providers, /setModelRole\(SHARED_ROLE, choice, \{ source: 'models' \}\)/);
  assert.match(providers, /onModelRoles\(\(\{ roles, source \}\) => \{\s*if \(source === 'models'/);
  assert.match(providers, /announceModelRoles\(modelRoles, 'models'\)/);
  // andromeda section: same role, saved on change, listens too
  assert.match(section, /const ANSWER_ROLE = 'andromeda_answer'/);
  assert.match(section, /setModelRole\(ANSWER_ROLE, choice, \{ source: 'andromeda' \}\)/);
  assert.match(section, /\$\('s-andromeda-answer-model'\)\?\.addEventListener\('change', saveAnswerModel\)/);
  assert.match(section, /onModelRoles\(\(\{ roles, source \}\) => \{\s*if \(source === 'andromeda'/);
  // each section re-reads the stored value when it opens
  assert.match(section, /_roles = settings\.model_roles \|\| \{\}/);
  assert.match(providers, /_modelRoleSettings = settings\.model_roles \|\| \{\}/);
  const pane = html.slice(html.indexOf('id="s-pane-andromeda"'), html.indexOf('<!-- ── appearance pane ── -->'));
  assert.match(pane, /class="settings-input custom-select" id="s-andromeda-answer-model"/);
  assert.doesNotMatch(html.slice(html.indexOf('id="s-pane-models"'), html.indexOf('id="s-pane-ai"')), /s-andromeda-answer-model/);
});
