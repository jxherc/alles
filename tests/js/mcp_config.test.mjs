import assert from 'node:assert/strict';
import { test } from 'node:test';

import { parsePrivateLines } from '../../static/js/mcp-config.js';

test('private MCP values parse one name=value pair per line', () => {
  assert.deepEqual(
    parsePrivateLines('GITHUB_TOKEN=private\nMODE=safe\n\n'),
    { GITHUB_TOKEN: 'private', MODE: 'safe' },
  );
});

test('private MCP values may contain equals signs', () => {
  assert.deepEqual(parsePrivateLines('Authorization=Bearer abc=='), {
    Authorization: 'Bearer abc==',
  });
});

test('private MCP values reject lines without a name', () => {
  assert.throws(() => parsePrivateLines('not-a-pair'), /name=value/);
});
