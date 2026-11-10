import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

// english lives twice: built into i18n.js, so the first screen has words before any request
// answers, and in locales/en.json, which replaces it once fetched. a text changed in only one
// of them shows one wording at first paint and another after (vault's "delete" read "del")
const source = fs.readFileSync(new URL('../../static/js/i18n.js', import.meta.url), 'utf8');
const fetched = JSON.parse(fs.readFileSync(new URL('../../static/locales/en.json', import.meta.url), 'utf8'));

function builtin() {
  const start = source.indexOf('const BUILTIN_ENGLISH = ') + 'const BUILTIN_ENGLISH = '.length;
  const end = source.indexOf('\nconst KNOWN_LANGUAGES');
  assert.ok(start > 23 && end > start, 'i18n.js no longer declares BUILTIN_ENGLISH before KNOWN_LANGUAGES');
  return new Function(`return ${source.slice(start, end).trim().replace(/;$/, '')}`)();
}

test('the english built into the page is the english it fetches', () => {
  const built = builtin();
  const different = Object.keys({ ...built.messages, ...fetched.messages })
    .filter(key => built.messages[key] !== fetched.messages[key]);
  assert.deepEqual(different, [], 'these keys read differently in i18n.js and locales/en.json');
  assert.deepEqual(built.plurals, fetched.plurals);
  assert.equal(built.source_revision, fetched.source_revision);
});
