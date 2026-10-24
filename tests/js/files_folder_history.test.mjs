import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/filesphase7.js', import.meta.url), 'utf8');
const writeUrl = source.match(/^function writeUrl\(push = false\) \{[\s\S]*?^}/m)?.[0];
const listener = source.match(/^if \(typeof window !== 'undefined'\) window\.addEventListener\('popstate', \(\) => \{[\s\S]*?^}\);/m)?.[0];
assert.ok(writeUrl && listener);

function files(href, state) {
  let pop = null;
  const calls = [];
  const context = vm.createContext({
    URL, URLSearchParams, initialized: true, state,
    location: new URL(href),
    window: { addEventListener: (type, fn) => { if (type === 'popstate') pop = fn; } },
    pushRouteUrl: url => calls.push(['push', String(url)]),
    replaceRouteUrl: url => calls.push(['replace', String(url)]),
    renderLocations: () => calls.push(['locations']), renderLocationStatus() {},
  });
  vm.runInContext(`${writeUrl}\n${listener}`, context);
  return { context, calls, pop: () => pop() };
}
const here = (cwd, extra = {}) => ({ cwd, locationId: 'home', locations: [{ id: 'home' }, { id: 'nas' }], selected: new Map(), returnPath: '', popFocus: false, ...extra });

test('an opened folder is its own history entry; a reload of the same folder is not', () => {
  const opened = files('http://files.test/?location=home&p=trips', here('trips/japan'));
  opened.context.writeUrl(true);
  assert.deepEqual(opened.calls, [['push', 'http://files.test/?location=home&p=trips%2Fjapan']]);
  const same = files('http://files.test/?location=home&p=trips', here('trips'));
  same.context.writeUrl(true);
  same.context.writeUrl();
  assert.deepEqual(same.calls.map(call => call[0]), ['replace', 'replace']);
});

test('Back takes the folder from the entry and lands on the folder it came out of', () => {
  for (const [from, to, focus] of [['trips/japan', 'trips', 'trips/japan'], ['trips/japan/day1', '', 'trips'], ['work', 'trips', '']]) {
    const state = here(from);
    files(`http://files.test/?location=home${to ? `&p=${encodeURIComponent(to)}` : ''}`, state).pop();
    assert.equal(state.cwd, to);
    assert.equal(state.returnPath, focus);
  }
});

test('an entry from another app, or a location that is gone, leaves files alone', () => {
  const state = here('trips');
  files('http://files.test/?view=mail', state).pop();
  files('http://files.test/?location=removed&p=x', state).pop();
  assert.equal(state.cwd, 'trips');
  assert.equal(state.locationId, 'home');
});

test('an entry on another location switches to it', () => {
  const state = here('trips');
  const nas = files('http://files.test/?location=nas&p=photos', state);
  nas.pop();
  assert.deepEqual([state.locationId, state.cwd, state.returnPath], ['nas', 'photos', '']);
  assert.deepEqual(nas.calls, [['locations']]);
});

test('Forward into a subfolder also asks for focus, so it lands on the first row', () => {
  const state = here('trips');
  files('http://files.test/?location=home&p=trips%2Fjapan', state).pop();
  assert.deepEqual([state.cwd, state.returnPath, state.popFocus], ['trips/japan', '', true]);
  const load = source.match(/const back = state\.returnPath, popped = state\.popFocus;[\s\S]*?\n    }\n/)?.[0];
  assert.match(load, /if \(\(push \|\| back \|\| popped\) && \(!document\.activeElement \|\| document\.activeElement === document\.body\)\)/);
});
