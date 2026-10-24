import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const andromeda = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
const subject = andromeda.match(/^function focusFirstNewResult\([^]*?^}/m)[0];

function harness({ rows = 16, hidden = true, items = [] } = {}) {
  const focused = [];
  const body = { name: 'body' };
  const document = { activeElement: body, body, getElementById: id => (id === 'andromeda-query' ? query : null) };
  const node = name => ({ name, focus() { focused.push(name); document.activeElement = this; } });
  const query = node('query');
  const button = { ...node('more'), hidden };
  const selected = [];
  const results = Array.from({ length: rows }, (_, i) => node(`row ${i}`));
  const list = { children: items.map(name => ({ matches: () => true, ...node(name) })) };
  const context = vm.createContext({
    document,
    resultRows: () => results,
    selectResult: (index, options) => { selected.push(index); if (options.focus) results[index].focus(); },
    el: id => (id === 'andromeda-news' ? list : null),
  });
  vm.runInContext(`${subject}\nglobalThis.focusFirstNewResult = focusFirstNewResult;`, context);
  return { run: (category, index) => context.focusFirstNewResult(category, index, button), focused, selected, document };
}

test('more results that bring nothing new land on the last result, not the page', () => {
  const h = harness({ rows: 16, hidden: true });
  h.run('all', 16);
  assert.deepEqual(h.selected, [15]);
  assert.deepEqual(h.focused, ['row 15']);
});

test('new rows still take focus at the first one that arrived', () => {
  const h = harness({ rows: 24, hidden: false });
  h.run('all', 16);
  assert.deepEqual(h.focused, ['row 16']);
});

test('nothing new while more is still offered keeps focus on the button', () => {
  const h = harness({ rows: 16, hidden: false });
  h.run('all', 16);
  assert.deepEqual(h.focused, ['more']);
});

test('news falls back to its last card link, then the search field', () => {
  const news = harness({ items: ['card 0', 'card 1'], hidden: true });
  news.run('news', 2);
  assert.deepEqual(news.focused, ['card 1']);
  const empty = harness({ rows: 0, hidden: true });
  empty.run('all', 0);
  assert.deepEqual(empty.focused, ['query']);
});
