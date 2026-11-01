import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { t } from '../../static/js/i18n.js';

const { itemKey } = await import('../../static/js/whatsnew.js');

const read = async path => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));
const { releases } = await read('../../static/whats-new.json');
const LOCALES = ['en', 'ar', 'es', 'fr', 'ja', 'ko', 'zh-Hans', 'zh-Hant'];
const catalogs = Object.fromEntries(await Promise.all(
  LOCALES.map(async id => [id, (await read(`../../static/locales/${id}.json`)).messages])));
const slugOf = release => release.id.replace(/-/g, '_');
// releases before this one were written before every note had translations; they stay as they are
const TRANSLATED_FROM = '2026-10-28';
const translated = releases.filter(release => release.id >= TRANSLATED_FROM);

// 2026-10-28 was already on dev when the keys came in, so it must stay exactly as shipped
const SHIPPED_1028 = [
  'bank sync you can find', 'gmail in one tap', 'copy that works', 'the whole world in settings',
  'calmer details', 'text aide on telegram', 'mail that shows up fast', 'one-click installs',
  'small tools in search', 'easier to find', 'habits with their own logs',
];

test('a release already shipped keeps its items', () => {
  const shipped = releases.find(release => release.id === '2026-10-28');
  assert.deepEqual(shipped.items.map(item => item.title), SHIPPED_1028);
  assert.ok(shipped.items.every(item => !('key' in item)));
});

test('the newest release names every item with a key', () => {
  const [newest] = releases;
  assert.ok(newest.items.length > 0);
  for (const item of newest.items) assert.match(item.key || '', /^[a-z][a-z0-9_]*$/, item.title);
});

test('an item key reads from the key, an older item from its place', () => {
  assert.equal(itemKey('2026_11_01', { key: 'vault_key' }, 4), 'whatsnew.2026_11_01.vault_key');
  assert.equal(itemKey('2026_10_28', { title: 'x' }, 4), 'whatsnew.2026_10_28.item5');
});

test('no two items in a release share a key', () => {
  for (const release of releases) {
    const keys = release.items.map(item => item.key).filter(Boolean);
    assert.equal(new Set(keys).size, keys.length, release.id);
  }
});

test('a release is either all keyed or all by position', () => {
  for (const release of releases) {
    const keyed = release.items.filter(item => item.key).length;
    assert.ok(keyed === 0 || keyed === release.items.length, release.id);
  }
});

test('every item reads its own title and body in english, built in and in en.json', () => {
  for (const release of translated) {
    const slug = slugOf(release);
    release.items.forEach((item, n) => {
      const key = itemKey(slug, item, n);
      assert.equal(t(`${key}.title`), item.title, `${release.id} built-in title ${key}`);
      assert.equal(t(`${key}.body`), item.body, `${release.id} built-in body ${key}`);
      assert.equal(catalogs.en[`${key}.title`], item.title, `${release.id} en.json title ${key}`);
      assert.equal(catalogs.en[`${key}.body`], item.body, `${release.id} en.json body ${key}`);
    });
  }
});

test('every keyed item has a title and body in all 8 languages', () => {
  for (const release of translated.filter(r => r.items.some(item => item.key))) {
    const slug = slugOf(release);
    release.items.forEach((item, n) => {
      const key = itemKey(slug, item, n);
      for (const id of LOCALES) {
        for (const part of ['title', 'body']) {
          const text = catalogs[id][`${key}.${part}`];
          assert.ok(typeof text === 'string' && text.trim(), `${id} is missing ${key}.${part}`);
        }
      }
    });
  }
});

test('a keyed release leaves no position keys behind', () => {
  for (const release of releases.filter(r => r.items.some(item => item.key))) {
    const slug = slugOf(release);
    for (const id of LOCALES) {
      const stale = Object.keys(catalogs[id]).filter(key => new RegExp(`^whatsnew\\.${slug}\\.item\\d+\\.`).test(key));
      assert.deepEqual(stale, [], `${id} ${release.id}`);
    }
  }
});

test('the date of every release is translated in all 8 languages', () => {
  for (const release of translated) {
    for (const id of LOCALES) assert.ok(catalogs[id][`whatsnew.${slugOf(release)}.date`], `${id} ${release.id}`);
  }
});
