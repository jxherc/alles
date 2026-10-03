import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.location = { hostname: 'localhost', port: '8000', protocol: 'http:' };
const { buildAideSearchContext, savedSearchUrl } = await import('../../static/js/andromeda.js');
const decode = request => JSON.parse(request.slice(request.indexOf('\n\n') + 2));
const id = '12345678-1234-4234-8234-123456789abc';
const query = 'compare the two saved accounts';
const url = 'http://127.0.0.1:8000/source?value=%26&other=%3C';
const state = () => ({
  rawQuery: query, category: 'all',
  results: [{ title: 'first account', url, snippet: 'the exact result excerpt', publisher: 'owned fixture' }],
  overview: { status: 'ready', claims: [{ text: 'the accounts differ', citations: [{ url, source_id: 's1', quote: 'first exact passage' }] }] },
  evidence: [{ id: 's1', url, title: 'first account', passages: ['first exact passage', 'second exact passage'] }],
  verification: { status: 'uncertain', changes: [], summary: 'the supplied accounts disagree' },
  model: { model: 'overview-fixture', endpoint: 'owned overview' },
  verifierModel: { model: 'verifier-fixture', endpoint: 'owned verifier' },
});

test('complete continuation retains query, snippets, quotes, machine output and saved origin', () => {
  const input = state();
  const origin = { saved_search_id: id, url: savedSearchUrl(id, 'http://127.0.0.1:8000/?q=old'), checked_at: '2026-10-03T12:00:00' };
  const before = JSON.stringify(input);
  const built = buildAideSearchContext(input, origin);
  const data = decode(built.request);
  assert.equal(built.partial, false);
  assert.equal(data.query, query);
  assert.deepEqual(data.origin, origin);
  assert.equal(data.results[0].snippet, input.results[0].snippet);
  assert.equal(data.results[0].url, url);
  assert.deepEqual(data.overview, input.overview);
  assert.deepEqual(data.evidence, input.evidence);
  assert.deepEqual(data.verification, input.verification);
  assert.deepEqual(data.overview_model, { model: 'overview-fixture', endpoint: 'owned overview' });
  assert.deepEqual(data.verifier_model, { model: 'verifier-fixture', endpoint: 'owned verifier' });
  assert.equal(data.coverage.passages_included, 2);
  assert.equal(JSON.stringify(input), before);
});

test('600 supported results remain unchanged and any bounded handoff counts whole records', () => {
  const input = state();
  input.results = Array.from({ length: 600 }, (_, i) => ({ title: `result ${i}`, url: `${url}&row=${i}`, snippet: `whole source ${i}: ` + 'exact unicode 🌱 text '.repeat(20) }));
  const before = JSON.stringify(input);
  const built = buildAideSearchContext(input);
  const data = decode(built.request);
  assert.equal(built.partial, true);
  assert.ok(built.request.length <= 20_000);
  assert.equal(data.coverage.results_total, 600);
  assert.equal(data.coverage.results_included, data.results.length);
  assert.ok(data.results.length > 0 && data.results.length < 600);
  for (const result of data.results) assert.equal(result.snippet, input.results[result.rank - 1].snippet);
  assert.equal(data.origin, null);
  assert.equal(JSON.stringify(input), before);
});

test('large evidence preserves complete passages and reports exactly how much is omitted', () => {
  const input = state();
  input.evidence = Array.from({ length: 6 }, (_, i) => ({ id: `s${i + 1}`, url, title: `source ${i}`, passages: [`passage ${i} ` + 'α🌱quoted text '.repeat(300)] }));
  const original = structuredClone(input);
  const built = buildAideSearchContext(input);
  const data = decode(built.request);
  assert.equal(built.partial, true);
  assert.ok(built.request.length <= 20_000);
  assert.equal(data.coverage.passages_total, 6);
  assert.ok(data.coverage.passages_included > 0 && data.coverage.passages_included < 6);
  assert.equal(data.coverage.passages_included, data.evidence.reduce((count, source) => count + source.passages.length, 0));
  for (const source of data.evidence) {
    const originalSource = input.evidence.find(value => value.id === source.id);
    for (const passage of source.passages) assert.ok(originalSource.passages.includes(passage));
  }
  assert.deepEqual(input, original);
});

test('no usable excerpt fitting the transport limit yields an actionable error', () => {
  assert.throws(() => buildAideSearchContext({ query, results: [{ title: 'oversized', url, snippet: 'x'.repeat(20_001) }] }), /too large.*narrower search/);
});

test('unsafe source URLs cannot become citations and malformed passages are not invented', () => {
  const input = state();
  input.results[0].url = 'javascript:fixture';
  input.evidence[0].url = 'data:text/plain,fixture';
  input.evidence[0].passages = null;
  const data = decode(buildAideSearchContext(input).request);
  assert.equal(data.results[0].url, null);
  assert.equal(data.evidence[0].url, null);
  assert.deepEqual(data.evidence[0].passages, []);
  assert.equal(data.results[0].snippet, input.results[0].snippet);
});

test('saved origin opens one exact record, keeps only valid project context and never copies handoff codes', () => {
  const target = new URL(savedSearchUrl(id, `http://andromeda.localhost:8000/?q=old&ctx=private&doc=old.md&project_id=${id}#fragment`));
  assert.equal(target.origin, 'http://andromeda.localhost:8000');
  assert.equal(target.pathname, '/');
  assert.equal(target.searchParams.get('app'), 'andromeda');
  assert.equal(target.searchParams.get('saved'), id);
  assert.equal(target.searchParams.get('project_id'), id);
  assert.equal(target.searchParams.size, 3);
  assert.equal(target.hash, '');
  assert.equal(savedSearchUrl('invalid', target.href), '');
  assert.equal(new URL(savedSearchUrl(id, 'http://localhost:8000/?project_id=invalid')).searchParams.has('project_id'), false);
});


test('bounded context rejects link-only results and blank passages when actual evidence does not fit', () => {
  for (const passages of [['x'.repeat(40_000)], [' ', 'x'.repeat(40_000)]]) {
    const input = state();
    input.results[0].snippet = '  ';
    input.evidence[0].passages = passages;
    assert.throws(() => buildAideSearchContext(input), /source excerpts are too large/);
  }
});

test('large machine overview cannot crowd out a source excerpt that fits the handoff', () => {
  const input = state();
  input.evidence = [];
  input.overview = { summary: 'machine text '.repeat(1400) };
  input.results[0].snippet = 'source text '.repeat(340);
  const before = JSON.stringify(input);
  const built = buildAideSearchContext(input);
  const data = decode(built.request);
  assert.equal(built.partial, true);
  assert.equal(data.results.length, 1);
  assert.equal(data.results[0].snippet, input.results[0].snippet);
  assert.equal(data.coverage.overview_included, false);
  assert.equal(JSON.stringify(input), before);
});

for (const placeholders of ['results', 'evidence', 'passages']) {
  test(`blank ${placeholders} cannot crowd out usable source excerpts`, () => {
    const input = state();
    input.overview = {}; input.verification = {}; input.evidence = [];
    const excerpt = { title: 'usable source', url, snippet: 'source text '.repeat(340) };
    if (placeholders === 'results') {
      input.results = [...Array.from({ length: 599 }, (_, i) => ({ title: `result ${i}`, url, snippet: '  ' })), excerpt];
    } else {
      input.results = [excerpt];
      input.evidence = placeholders === 'evidence'
        ? Array.from({ length: 200 }, (_, i) => ({ id: `empty-${i}`, title: `source ${i}`, url, passages: [] }))
        : [{ id: 'blank-passages', url, passages: [' '.repeat(18_000), 'whole source passage'] }];
    }
    const before = JSON.stringify(input);
    const built = buildAideSearchContext(input);
    const data = decode(built.request);
    assert.equal(built.partial, true);
    assert.ok(built.request.length <= 20_000);
    assert.ok(data.results.some(result => result.snippet === excerpt.snippet), placeholders);
    assert.equal(data.coverage.results_included, data.results.length);
    assert.equal(data.coverage.passages_included, data.evidence.reduce((count, source) => count + source.passages.length, 0));
    assert.equal(JSON.stringify(input), before);
  });
}

test('empty machine sections do not reject whole excerpts at the transport boundary', () => {
  for (const remaining of [0, 1, 2, 3, 4]) {
    const input = { query, results: [{ title: 'fits', url, snippet: 'x' }, { title: 'oversized', url, snippet: 'x'.repeat(40_000) }], overview: {}, verification: {} };
    const full = buildAideSearchContext(input, null, 100_000).request;
    const prefix = full.slice(0, full.indexOf('\n\n') + 2);
    const expected = decode(full);
    expected.results.pop(); expected.coverage.results_included = 1;
    input.results[0].snippet = 'x'.repeat(1 + 20_000 - remaining - (prefix + JSON.stringify(expected)).length);
    const before = JSON.stringify(input);
    const built = buildAideSearchContext(input);
    const data = decode(built.request);
    assert.equal(built.request.length, 20_000 - remaining);
    assert.equal(data.results.length, 1);
    assert.equal(data.results[0].snippet, input.results[0].snippet);
    assert.deepEqual(data.overview, {});
    assert.deepEqual(data.verification, {});
    assert.equal(JSON.stringify(input), before);
  }
});

test('small contexts without source excerpts stop before requesting an explanation', () => {
  for (const input of [
    { query, results: [], evidence: [{ id: 'empty', url, passages: [] }] },
    { query, results: [], evidence: [{ id: 'blank', url, passages: [' ', '\n'] }] },
    { query, results: [{ title: 'link without an excerpt', url, snippet: '' }] },
  ]) {
    assert.throws(() => buildAideSearchContext(input), /no source excerpts/);
  }
});
