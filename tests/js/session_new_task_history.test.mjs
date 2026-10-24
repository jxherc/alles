import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const sessions = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const markActive = sessions.match(/^export function markActive\([^]*?^}/m)[0].replace(/^export /, '');

// main → an earlier conversation → new task → its first send: the send names the new task in
// place, so back goes straight to the main conversation instead of a dead bare-address step
test('the first send of a new task replaces the address instead of adding a history entry', () => {
  const entries = ['/?view=chat#main', '/?view=chat#earlier'];
  let at = 1;
  const pops = [];
  const location = {
    get href() { return `http://127.0.0.1:8186${entries[at]}`; },
    set hash(value) { entries.splice(++at, Infinity, `${entries[at - 1].split('#')[0]}#${value}`); pops.push(value); },
  };
  const context = vm.createContext({
    location, URL,
    document: { querySelectorAll: () => [] },
    window: {},
    isIncognitoMode: () => false,
    syncSessionRowState() {},
    replaceRouteUrl: url => { const next = new URL(url); entries[at] = next.pathname + next.search + next.hash; },
    _activeId: null,
  });
  vm.runInContext(`${markActive}\nglobalThis.markActive = markActive;`, context);
  // newChat already replaced the earlier conversation's entry with the bare address
  entries[at] = '/?view=chat';
  context.markActive('new-task');
  assert.deepEqual(entries, ['/?view=chat#main', '/?view=chat#new-task']);
  assert.equal(at, 1);
  // no hash write: that fired a popstate which cancelled the navigation the send was part of
  assert.deepEqual(pops, []);
});

test('incognito keeps its id out of the address', () => {
  const writes = [];
  const context = vm.createContext({
    location: { href: 'http://127.0.0.1:8186/?view=chat' }, URL,
    document: { querySelectorAll: () => [] }, window: {},
    isIncognitoMode: () => true, syncSessionRowState() {},
    replaceRouteUrl: url => writes.push(String(url)),
  });
  vm.runInContext(`let _activeId = null;\n${markActive}\nglobalThis.markActive = markActive;`, context);
  context.markActive('private-task');
  assert.deepEqual(writes, []);
});
