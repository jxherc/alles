import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const body = source.match(/document\.getElementById\('aide-sidebar'\)\?\.addEventListener\('click', async event => \{([\s\S]*?)\n  \}\);/)[1];
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const openTool = new AsyncFunction('event', 'navigateTo', 'setAideToolsMenu', 'document', 'closeCompactAideSidebar', body);

for (const view of ['usage', 'compare']) {
  test(`cancelled ${view} navigation returns focus to a visible control`, async () => {
    let menuOpen = true, focused = null;
    const tools = { focus() { focused = this; } };
    const trigger = {
      dataset: { aideToolView: view },
      closest: selector => selector === '#aide-sidebar-menu' && view === 'usage' ? {} : null,
      focus() { if (view === 'compare' || menuOpen) focused = this; },
    };
    const event = { target: { closest: () => trigger }, stopPropagation() {} };
    await openTool(event, async () => false, open => { menuOpen = open; }, {
      getElementById: id => id === 'aide-tools-link' ? tools : null,
    }, () => { throw new Error('cancelled navigation must keep the sidebar open'); });
    assert.equal(menuOpen, false);
    assert.equal(focused, view === 'usage' ? tools : trigger);
  });
}
