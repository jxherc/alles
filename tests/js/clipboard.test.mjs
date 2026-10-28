import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const util = readFileSync(new URL('../../static/js/util.js', import.meta.url), 'utf8');
const source = util.slice(util.indexOf('export async function writeClipboard'), util.indexOf('// code block buttons arrive'))
  .replace('export ', '');

function harness({ secure, clipboard }) {
  const appended = [], focused = [];
  const context = vm.createContext({
    Blob, Promise,
    window: { isSecureContext: secure, ClipboardItem: class { constructor(items) { this.items = items; } } },
    navigator: { clipboard },
    document: {
      activeElement: { focus: () => focused.push('prior') },
      body: { append: node => appended.push(node) },
      createElement: () => ({ style: {}, setAttribute() {}, select() { this.selected = true; }, remove() { this.removed = true; } }),
      execCommand: command => command === 'copy' && appended.at(-1)?.selected === true,
    },
  });
  context.ClipboardItem = context.window.ClipboardItem;
  vm.runInContext(source + '\nglobalThis.writeClipboard = writeClipboard;', context);
  return { context, appended, focused };
}

test('plain http copies through a hidden textarea and gives focus back', async () => {
  const h = harness({ secure: false, clipboard: undefined });
  await h.context.writeClipboard('synthetic value');
  assert.equal(h.appended[0].value, 'synthetic value');
  assert.equal(h.appended[0].removed, true);
  assert.deepEqual(h.focused, ['prior']);
});

test('a secure page with a late value starts the copy at once', async () => {
  let written;
  const h = harness({ secure: true, clipboard: { write: items => { written = items; return Promise.resolve(); }, writeText() { throw new Error('not used'); } } });
  let release;
  const late = new Promise(resolve => { release = resolve; });
  const copying = h.context.writeClipboard(late);
  assert.ok(written, 'clipboard.write ran before the value arrived');
  release('late secret');
  await copying;
  const blob = await written[0].items['text/plain'];
  assert.equal(await blob.text(), 'late secret');
});

test('a refused clipboard falls back to the textarea copy', async () => {
  const h = harness({ secure: true, clipboard: { writeText: async () => { throw new Error('denied'); } } });
  await h.context.writeClipboard('value');
  assert.equal(h.appended[0].value, 'value');
});

test('when both ways fail the copy reports it', async () => {
  const h = harness({ secure: true, clipboard: { writeText: async () => { throw new Error('denied'); } } });
  h.context.document.execCommand = () => false;
  await assert.rejects(h.context.writeClipboard('value'), /copy blocked/);
});
