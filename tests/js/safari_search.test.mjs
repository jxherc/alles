// the safari search extension (nov 7): searches on safari's engines go to andromeda
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const context = vm.createContext({ URL, encodeURIComponent });
vm.runInContext(readFileSync(new URL('../../safari/extension/engines.js', import.meta.url), 'utf8') + '\nthis.api = { ENGINES, searchedWords, andromedaUrl, engineRules };', context);
const { ENGINES, searchedWords, andromedaUrl, engineRules } = context.api;
const ORIGIN = 'https://alles.example.com';

const SEARCHES = [
  ['https://www.google.com/search?q=knee+surgery&client=safari&hl=en', 'knee surgery'],
  ['https://www.google.ca/search?client=safari&rls=en&q=%E4%BD%A0%E5%A5%BD&ie=UTF-8', '你好'],
  ['https://www.bing.com/search?q=weather%20toronto&form=APMCS1', 'weather toronto'],
  ['https://duckduckgo.com/?q=f1+standings&t=iphone', 'f1 standings'],
  ['https://search.yahoo.com/search;_ylt=abc?p=periodic+table&fr=iphone', 'periodic table'],
  ['https://www.ecosia.org/search?q=translate+hello&tts=st_asaf_iphone', 'translate hello'],
  ['https://www.baidu.com/s?wd=%E5%A4%A9%E6%B0%94&tn=iphone', '天气'],
];

test('a search page gives back the words searched for', () => {
  for (const [url, words] of SEARCHES) assert.equal(searchedWords(new URL(url)), words, url);
});

test('pages that are not searches, or empty ones, give nothing', () => {
  for (const url of [
    'https://www.google.com/maps?q=toronto',
    'https://www.google.com/url?q=https://example.com',
    'https://www.google.com/search?tbm=isch',
    'https://calendar.google.com/calendar?q=x',
    'https://example.com/search?q=x',
  ]) assert.equal(searchedWords(new URL(url)), '', url);
});

test('every redirect rule turns its engine\'s search into the same andromeda address', () => {
  const rules = engineRules(ORIGIN);
  assert.equal(rules.length, ENGINES.length);
  for (const [url, words] of SEARCHES) {
    const hits = rules.filter(rule => new RegExp(rule.condition.regexFilter).test(url));
    assert.equal(hits.length, 1, url);
    const sub = hits[0].action.redirect.regexSubstitution.replace('\\2', '$2');
    const target = new URL(url.replace(new RegExp(hits[0].condition.regexFilter + '.*'), sub));
    assert.equal(target.origin, ORIGIN);
    assert.equal(target.searchParams.get('app'), 'andromeda');
    assert.equal(target.searchParams.get('q'), words);
    assert.equal(andromedaUrl(ORIGIN, words), `${ORIGIN}/?app=andromeda&q=${encodeURIComponent(words)}`);
  }
});

test('rules stay inside webkit\'s regex and skip searches alles opens itself', () => {
  for (const rule of engineRules(ORIGIN)) {
    // content blocker regex: no non-capturing groups, counted repeats or alternation
    assert.doesNotMatch(rule.condition.regexFilter, /\(\?:|\{\d|\|/);
    // arrays from the vm sandbox compare by value only once copied out
    assert.deepEqual([...rule.condition.resourceTypes], ['main_frame']);
    assert.deepEqual([...rule.condition.excludedInitiatorDomains], ['alles.example.com']);
  }
});

test('the manifest grants exactly the engines the table names', () => {
  const manifest = JSON.parse(readFileSync(new URL('../../safari/extension/manifest.json', import.meta.url), 'utf8'));
  const granted = manifest.host_permissions.map(pattern => new URL(pattern.replace('/*', '/')).hostname).sort();
  assert.deepEqual(granted, [...ENGINES.flatMap(engine => [...engine.hosts])].sort());
  assert.deepEqual(manifest.content_scripts[0].matches, manifest.host_permissions);
  const locales = ['ar', 'en', 'es', 'fr', 'ja', 'ko', 'zh_CN', 'zh_TW'];
  const en = Object.keys(JSON.parse(readFileSync(new URL('../../safari/extension/_locales/en/messages.json', import.meta.url), 'utf8'))).sort();
  for (const id of locales) {
    const keys = Object.keys(JSON.parse(readFileSync(new URL(`../../safari/extension/_locales/${id}/messages.json`, import.meta.url), 'utf8'))).sort();
    assert.deepEqual(keys, en, id);
  }
});
