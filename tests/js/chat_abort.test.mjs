import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const src = readFileSync(new URL('../../static/js/chat.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');

test('stopStream aborts the active browser chat request', () => {
  assert.match(src, /let _chatAbort = null/);
  assert.match(src, /new AbortController\(\)/);
  assert.match(src, /signal: ctrl\.signal/);
  assert.match(src, /_chatAbort\?\.abort\(\)/);
  assert.match(src, /e\.name !== 'AbortError'/);
});

test('stopping a document-scoped request restores its scope for the next send', () => {
  const caught = src.match(/} catch \(e\) \{[\s\S]*?\n  } finally \{/)?.[0] || '';
  assert.match(
    caught,
    /restoreDocumentScope\(documentScope\);\s*if \(e\.name !== 'AbortError'\)/,
  );
});

test('old aborted stream cleanup cannot hide a newer stream', () => {
  assert.match(src, /let _streamToken = 0/);
  assert.match(src, /const streamToken = \+\+_streamToken/);
  assert.match(src, /if \(_streamToken === streamToken\) setStreaming\(false\)/);
});

test('a rapid send keeps its draft until the current stream can accept it', () => {
  assert.match(src, /export function canSendMessage\(\) \{\s*return !_streaming && !_backgroundLaunching/);
  assert.match(
    app,
    /if \(!canSendMessage\(\)\) return;\s*ta\.value = ''; ta\.style\.height = 'auto'; clearDraft\(\);\s*sendMessage\(text\)/,
  );
});

test('background startup blocks duplicate launches until the first request settles', () => {
  assert.match(src, /let _backgroundLaunching = false/);
  assert.match(src, /if \(!text\?\.trim\(\) \|\| _streaming \|\| _backgroundLaunching\) return/);
  assert.match(src, /shouldRunInBackground[\s\S]*?_backgroundLaunching = true/);
  assert.match(src, /startBackgroundWork[\s\S]*?finally \{\s*_backgroundLaunching = false/);
});

test('saveMsgAs comment matches the supported actions', () => {
  assert.match(src, /save an assistant message as a note or task/);
  assert.doesNotMatch(src, /save an assistant message as a note \/ task \/ reminder/);
  assert.match(src, /if \(kind === 'note'\)/);
  assert.match(src, /else if \(kind === 'task'\)/);
  assert.doesNotMatch(src, /kind === 'reminder'/);
});
