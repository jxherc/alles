import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

globalThis.location = {
  hostname: 'localhost',
  port: '8000',
  protocol: 'http:',
};

const {
  answerFocusParts,
  andromedaLandingUrl,
  canReplacePageResults,
  canLoadMoreResults,
  configuredFallbackChain,
  continuationQuery,
  contextClaimsForOverview,
  failureSummary,
  formatPublishedDate,
  mediaUrl,
  mergePageResults,
  parseSseFrames,
  queryWithNoAi,
  queueSearchCredentialWrite,
  queueSearchConfigurationWrite,
  resultSnippetFocus,
  sanitizeSearchSettings,
  validatedProjectId,
  withProjectContext,
} = await import('../../static/js/andromeda.js');

test('answer focus isolates only the decisive supported substring', () => {
  assert.deepEqual(answerFocusParts('SQLite 3.50.4 is current.', '3.50.4'), {
    before: 'SQLite ',
    focus: '3.50.4',
    after: ' is current.',
  });
  assert.deepEqual(answerFocusParts('Version 4.0 is current.', 'version 4.0'), {
    before: '',
    focus: 'Version 4.0',
    after: ' is current.',
  });
  assert.equal(answerFocusParts('SQLite 3.50.4 is current.', '4.0'), null);
  assert.equal(answerFocusParts('SQLite 3.50.4 is current.', ''), null);
});

test('normal results emphasize a decisive version, date, price, or percentage', () => {
  assert.equal(
    resultSnippetFocus('latest SQLite version', 'SQLite 3.50.4 is the current stable release.'),
    '3.50.4',
  );
  assert.equal(
    resultSnippetFocus('Python 3.14 release date', 'Python 3.14 was released on 7 October 2025.'),
    '7 October 2025',
  );
  assert.equal(
    resultSnippetFocus(
      'Python 3.14 release date',
      'January 14, 2026 - Python 3.14 was officially released on October 7, 2025.',
    ),
    'October 7, 2025',
  );
  assert.equal(
    resultSnippetFocus(
      'Python 3.14 release date',
      'November 1, 2025 - November brings an overview of the Python 3.14 release.',
    ),
    '',
  );
  assert.equal(
    resultSnippetFocus(
      'Python 3.14 release date',
      'Python 3.15.0b4. Release date: July 18, 2026.',
    ),
    '',
  );
  assert.equal(
    resultSnippetFocus(
      'Python 3.14 release date',
      'Release version Release date. Python 3.14.6 June 10, 2026.',
    ),
    '',
  );
  assert.equal(resultSnippetFocus('price of the test plan', 'It costs $19.50 per month.'), '$19.50');
  assert.equal(resultSnippetFocus('current approval rate', 'The approval rate is 63.4%.'), '63.4%');
  assert.equal(resultSnippetFocus('Python 3.14 documentation', 'Python 3.14 documentation.'), '');
});

test('plaintext provider credentials are removed from long-lived settings state', () => {
  assert.deepEqual(
    sanitizeSearchSettings({
      tavily_api_key: 'redacted',
      brave_api_key: 'redacted',
      google_pse_api_key: 'redacted',
      serper_api_key: 'redacted',
      tavily_api_key_configured: true,
      search_result_count: 10,
    }),
    { tavily_api_key_configured: true, search_result_count: 10 },
  );
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const patch = source.slice(
    source.indexOf('async function patchSearchSettings'),
    source.indexOf('function updateProviderSettingsSummary'),
  );
  assert.equal((patch.match(/sanitizeSearchSettings\(/g) || []).length, 4);
  assert.doesNotMatch(patch, /\.\.\.patch/);
});

test('overview removes only the explicitly identified key-answer source claim', () => {
  const claims = [
    { text: 'first supported claim' },
    { text: 'second supported claim' },
  ];
  assert.deepEqual(
    contextClaimsForOverview({
      key_answer: { text: 'short answer', source_claim_index: 0 },
      claims,
    }),
    [claims[1]],
  );
  assert.deepEqual(
    contextClaimsForOverview({ key_answer: { text: 'legacy cached answer' }, claims }),
    claims,
  );
});

test('resetting Andromeda removes only the stale deep-link query', () => {
  assert.equal(
    andromedaLandingUrl(
      'http://localhost:8000/?app=andromeda&q=old%20search&project_id=123#results',
    ),
    '/?app=andromeda&project_id=123#results',
  );
});

test('failed pagination keeps the previously rendered results', () => {
  assert.equal(canReplacePageResults({ status: 'error', results: [] }), false);
  assert.equal(canReplacePageResults({ status: 'partial', results: [{ url: 'https://example.test' }] }), true);
  assert.equal(canReplacePageResults({ status: 'partial', results: [{ url: 'https://example.test' }] }, 2), false);
  assert.equal(canReplacePageResults({ status: 'ready', results: [] }), true);
  assert.deepEqual(
    mergePageResults(
      [{ url: 'https://one.test' }, { url: 'https://two.test' }],
      [{ url: 'https://one.test' }, { url: 'https://three.test' }],
    ).map(row => row.url),
    ['https://one.test', 'https://two.test', 'https://three.test'],
  );
});

test('normal load-more stops at twenty while media categories can continue', () => {
  assert.equal(canLoadMoreResults('all', 19, true), true);
  assert.equal(canLoadMoreResults('all', 20, true), false);
  assert.equal(canLoadMoreResults('all', 7, true, 20), false);
  assert.equal(canLoadMoreResults('all', 7, true, 15), true);
  assert.equal(canLoadMoreResults('all', 5, false), false);
  assert.equal(canLoadMoreResults('images', 30, true), true);
});

test('!ai stays attached to the current search while categories change', () => {
  assert.equal(queryWithNoAi('current software release', true), 'current software release !ai');
  assert.equal(queryWithNoAi('current software release !ai', true), 'current software release !ai');
  assert.equal(queryWithNoAi('current software release !ai', false), 'current software release');
});

test('continuations preserve the exact submitted bang query', () => {
  assert.equal(
    continuationQuery('fallback words', { query: 'repo issue !gh !ai' }, true),
    'fallback words !ai',
  );
  assert.equal(continuationQuery('', { query: 'repo issue !gh !ai' }, true), 'repo issue !gh !ai');
  assert.equal(continuationQuery('fallback words', {}, true), 'fallback words !ai');
  assert.equal(continuationQuery('', { query: 'repo issue !gh' }, true), 'repo issue !gh !ai');
});

test('unsafe or unsupported media uses the quiet fallback', () => {
  assert.equal(mediaUrl('javascript:alert(1)'), '');
  assert.equal(mediaUrl('https://cdn.example.test/icon.svg'), '');
  assert.equal(mediaUrl('https://cdn.example.test/icon.SVG?version=2'), '');
  assert.equal(
    mediaUrl('https://cdn.example.test/photo.webp'),
    '/api/andromeda/media?url=https%3A%2F%2Fcdn.example.test%2Fphoto.webp',
  );
});

test('text results never synthesize a request to each result-site favicon', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(source, /\? result\.favicon_url/);
  assert.doesNotMatch(source, /resultUrl\.origin/);
  assert.doesNotMatch(source, /favicon\.ico/);
});

test('news dates are readable instead of raw ISO timestamps', () => {
  const formatted = formatPublishedDate('2026-07-13T12:10:18+00:00');
  assert.match(formatted, /2026/);
  assert.doesNotMatch(formatted, /T12:10:18/);
  const dateOnly = formatPublishedDate('2026-07-19');
  const expectedDateOnly = new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC',
  }).format(new Date('2026-07-19T12:00:00Z'));
  assert.equal(dateOnly, expectedDateOnly);
  assert.doesNotMatch(dateOnly, /\d:\d/);
  assert.equal(formatPublishedDate('2026-02-30'), '2026-02-30');
  assert.equal(formatPublishedDate('recently'), 'recently');
});

test('overview SSE parsing preserves partial frames and ordered claim events', () => {
  const first = parseSseFrames('data: {"type":"claim","claim":{"text":"one"}}\n\ndata: {"type"');
  assert.deepEqual(first.frames, ['{"type":"claim","claim":{"text":"one"}}']);
  assert.equal(first.rest, 'data: {"type"');
  const second = parseSseFrames(first.rest + ':"overview"}\n\ndata: [DONE]\n\n');
  assert.deepEqual(second.frames, ['{"type":"overview"}', '[DONE]']);
  assert.equal(second.rest, '');
});

test('SSE parser ignores non-data fields without losing later data', () => {
  const parsed = parseSseFrames('event: note\ndata: first\n\nid: 2\ndata: second\n\n');
  assert.deepEqual(parsed.frames, ['first', 'second']);
});

test('failure details name the type and bounded attempted sources', () => {
  assert.equal(
    failureSummary({ failure_type: 'provider_timeout', attempted_sources: ['managed searxng', 'external fallback'] }),
    'failure: provider timeout · tried: managed searxng, external fallback',
  );
  assert.equal(
    failureSummary({ attempted_sources: ['ok', 'bad\u0000value', '', ...Array(9).fill('extra')] }),
    'tried: ok, badvalue, extra, extra, extra, extra, extra, extra',
  );
  assert.equal(failureSummary({}), '');
});

test('saving the one visible fallback removes hidden providers from the chain', () => {
  assert.deepEqual(configuredFallbackChain('duckduckgo', 'brave'), ['brave']);
  assert.deepEqual(configuredFallbackChain('tavily', 'brave'), ['brave']);
  assert.deepEqual(configuredFallbackChain('duckduckgo', 'none'), []);
  assert.deepEqual(
    configuredFallbackChain('tavily', 'brave', ['brave', 'serper', 'tavily', 'duckduckgo']),
    ['brave'],
  );
});

test('Project context accepts only UUIDs and survives an Andromeda URL', () => {
  const id = '123e4567-e89b-42d3-a456-426614174000';
  assert.equal(validatedProjectId(id.toUpperCase()), id);
  assert.equal(validatedProjectId('../../private'), '');
  assert.equal(
    withProjectContext('http://localhost:8000/?app=andromeda&q=docs', id),
    `http://localhost:8000/?app=andromeda&q=docs&project_id=${id}`,
  );
  assert.equal(withProjectContext('http://localhost:8000/?app=andromeda', 'general'), 'http://localhost:8000/?app=andromeda');
  assert.equal(
    withProjectContext(`http://localhost:8000/?app=andromeda&project_id=${id}`, ''),
    'http://localhost:8000/?app=andromeda',
  );
  assert.equal(withProjectContext('/aide?view=chat', id), `/aide?view=chat&project_id=${id}`);
  assert.equal(withProjectContext('/aide?view=chat#latest', ''), '/aide?view=chat#latest');
});

test('Aide cross-app routes carry a valid Project in the Andromeda URL', () => {
  const source = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  const andromeda = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(source, /await crossNav\(dest, groupedIdentifier, \{ docsPrepared: true \}\)/);
  assert.match(source, /withProjectContext\(base, window\._currentSession\?\.project_id\)/);
  assert.match(
    source,
    /withProjectContext\(\s*target,\s*projectId \|\| window\._currentSession\?\.project_id/,
  );
  assert.match(source, /const scopedProjectId = validatedProjectId\(/);
  assert.match(source, /newChat\(\{ projectId: scopedProjectId \}\)/);
  assert.match(
    source,
    /_replaceHistoryUrl\(withProjectContext\(location\.href, scopedProjectId\)\)/,
  );
  const handoff = source.match(/window\._askInChat = async[\s\S]*?\n};/)?.[0] || '';
  assert.doesNotMatch(
    handoff,
    /if \(scopedProjectId\) \{\s*_replaceHistoryUrl\(withProjectContext/,
  );
  assert.doesNotMatch(andromeda, /jsonRequest\(`\/api\/projects\//);
  assert.doesNotMatch(andromeda, /run with jarvis/i);
});

test('Andromeda results stay clean and end with a useful continuation', () => {
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /ranked links/i);
  assert.doesNotMatch(html, /ask aide about selected links/i);
  assert.doesNotMatch(source, /andromeda-result-select/);
  assert.match(html, /id="andromeda-more-results"[^>]*>more results</);
  assert.match(source, /images:\s*30/);
  assert.match(source, /news:\s*20/);
  assert.match(source, /andromeda-image-skeleton/);
  assert.match(source, /result\.has_more/);
  assert.match(source, /canLoadMoreResults/);
  assert.match(source, /key_answer\?\.text/);
  assert.match(source, /contextClaims\.forEach\(\(claim, index\) => renderContextClaim/);
  const streamedClaim = source.match(/function renderClaim\(claim, index\) \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(streamedClaim, /renderContextClaim\(claim, index\)/);
  assert.doesNotMatch(streamedClaim, /renderKeyAnswer/);
});

test('news results require an explicit save action before entering Library', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(source, /andromeda-news-save/);
  assert.match(source, /jsonRequest\('\/api\/read\/save-news'/);
  assert.match(source, /button\.addEventListener\('click'/);
  assert.doesNotMatch(source, /renderAndromedaResults[\s\S]{0,500}\/api\/read\/save-news/);
});

test('Andromeda owns the complete search and managed SearXNG settings', () => {
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  for (const id of [
    'andromeda-provider-order',
    'andromeda-primary-provider',
    'andromeda-fallback-provider',
    'andromeda-result-count',
    'andromeda-searxng-status',
    'andromeda-searxng-actions',
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(source, /jsonRequest\('\/api\/system\/searxng'\)/);
  assert.match(source, /\/api\/system\/searxng\/\$\{action\}/);
  assert.doesNotMatch(source, /andromeda-manage-engines[\s\S]{0,180}_openSettings\?\.\('search'\)/);
});

test('stored search credentials have an explicit accessible clear action', () => {
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const styles = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
  assert.equal((html.match(/data-andromeda-clear-setting=/g) || []).length, 6);
  assert.equal((html.match(/aria-label="clear [^"]+"/g) || []).length, 6);
  assert.match(source, /queueSearchCredentialWrite/);
  assert.match(source, /_credentialClearPending\.has\(input\.id\)/);
  assert.match(source, /addEventListener\('pointerdown'/);
  assert.match(styles, /\.andromeda-setting-clear[\s\S]{0,180}min-height: 44px/);
});

test('credential writes are serialized so a later clear wins', async () => {
  const events = [];
  let started;
  let release;
  const firstStarted = new Promise(resolve => { started = resolve; });
  const holdFirst = new Promise(resolve => { release = resolve; });
  const first = queueSearchCredentialWrite('test-setting', async () => {
    started();
    await holdFirst;
    events.push('save');
  });
  await firstStarted;
  const second = queueSearchCredentialWrite('test-setting', async () => {
    events.push('clear');
  });
  release();
  await Promise.all([first, second]);
  assert.deepEqual(events, ['save', 'clear']);
});

test('credential inputs are locked while a save or clear is pending', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const save = source.slice(
    source.indexOf('async function saveSearchCredential(input)'),
    source.indexOf('async function clearSearchCredential(button)'),
  );
  const clear = source.slice(
    source.indexOf('async function clearSearchCredential(button)'),
    source.indexOf('function managedSearxngState(service)'),
  );
  assert.match(save, /input\.disabled = true;[\s\S]*finally \{[\s\S]*input\.disabled = false;/);
  assert.match(clear, /input\.disabled = true;[\s\S]*finally \{[\s\S]*input\.disabled = false;/);
});

test('search configuration writes are serialized so the newest complete tuple wins', async () => {
  const events = [];
  let started;
  let release;
  const firstStarted = new Promise(resolve => { started = resolve; });
  const holdFirst = new Promise(resolve => { release = resolve; });
  const first = queueSearchConfigurationWrite(async () => {
    started();
    await holdFirst;
    events.push('older tuple');
  });
  await firstStarted;
  const second = queueSearchConfigurationWrite(async () => {
    events.push('newest tuple');
  });
  release();
  await Promise.all([first, second]);
  assert.deepEqual(events, ['older tuple', 'newest tuple']);
});

test('only the newest queued search configuration write may refresh provider choices', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const save = source.slice(
    source.indexOf('async function saveSearchConfiguration()'),
    source.indexOf('const SEARCH_CREDENTIAL_FIELDS'),
  );
  const loader = source.slice(
    source.indexOf('async function loadProviderChoices('),
    source.indexOf('async function explainResults()'),
  );
  assert.match(save, /const writeGeneration = \+\+_searchConfigurationGeneration/);
  assert.match(save, /writeGeneration !== _searchConfigurationGeneration\) return/);
  assert.match(save, /loadProviderChoices\(writeGeneration\)/);
  assert.match(loader, /requestedConfigurationGeneration !== _searchConfigurationGeneration\) return/);
});

test('automatic search keeps the configured provider fallback chain active', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const loader = source.slice(source.indexOf('async function loadProviderChoices('), source.indexOf('async function explainResults()'));
  assert.match(loader, /\{ value: '', label: 'automatic' \}/);
  assert.match(loader, /providerValue\('andromeda-provider'\)/);
  assert.match(loader, /options\.some\(option => option\.value === selectedProvider\)/);
  assert.match(loader, /populateDropdown\(control, options, preservedProvider\)/);
  assert.match(loader, /catch \(error\)[\s\S]*setSearchSettingsStatus[\s\S]*return;/);
  assert.doesNotMatch(source, /selected\s*=\s*response\.selected/);
});

test('unrelated search settings keep the loaded fallback-chain tail', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const save = source.slice(
    source.indexOf('async function saveSearchConfiguration()'),
    source.indexOf('const SEARCH_CREDENTIAL_FIELDS'),
  );
  assert.match(save, /primaryChanged[\s\S]*fallbackChanged/);
  assert.match(
    save,
    /if \(primaryChanged \|\| fallbackChanged\) patch\.search_fallback_chain = fallbackChain/,
  );
  assert.doesNotMatch(save, /search_fallback_chain:\s*fallbackChain/);
});

test('result explanation uses the opaque Aide handoff instead of a query payload', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  const explain = source.slice(source.indexOf('async function explainResults()'), source.indexOf('function bindRecovery()'));
  assert.match(explain, /validatedProjectId[\s\S]*project_id[\s\S]*await window\._askInChat\(request, false, _state\.documentScope, projectId\)/);
  assert.doesNotMatch(explain, /\?ask=/);
  assert.doesNotMatch(explain, /location\.href/);
  assert.match(app, /projectId \|\| window\._currentSession\?\.project_id/);
  assert.match(app, /withProjectContext\([\s\S]*target\.toString\(\)/);
  assert.match(app, /window\._currentSession\?\.project_id !== projectId\) newChat\(\{ projectId \}\)/);
});

test('provider choices refresh after credentials and managed SearXNG lifecycle changes', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const save = source.slice(source.indexOf('async function saveSearchCredential'), source.indexOf('async function clearSearchCredential'));
  const managed = source.slice(source.indexOf('async function manageSearxng'), source.indexOf('function openSettings()'));
  assert.match(save, /await loadProviderChoices\(\)/);
  assert.match(managed, /finally \{[\s\S]*await loadManagedSearxng\(\)[\s\S]*await loadProviderChoices\(\)/);
  assert.match(managed, /let actionMessage = ''/);
  assert.match(
    managed,
    /await loadProviderChoices\(\)[\s\S]*statusNode\.textContent = actionMessage/,
  );
  assert.match(managed, /actionState = 'error'/);
});

test('search and overview requests read the custom dropdown state', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(source, /provider: providerValue\('andromeda-provider'\)/);
  assert.match(source, /band: providerValue\('andromeda-band', 'standard'\)/);
  assert.match(source, /selectedFallback === primary \? 'none' : selectedFallback/);
  assert.match(
    source,
    /if \(primaryChanged \|\| fallbackChanged\) patch\.search_fallback_chain = fallbackChain/,
  );
  const saveConfiguration = source.slice(
    source.indexOf('async function saveSearchConfiguration'),
    source.indexOf('const SEARCH_CREDENTIAL_FIELDS'),
  );
  assert.doesNotMatch(saveConfiguration, /_settingsState\.search_fallback_chain/);
  assert.match(source, /_modelChoices\.get\(providerValue\('andromeda-exact-model'\)\)/);
  assert.doesNotMatch(source, /el\('andromeda-(?:provider|band|exact-model)'\)\?\.value/);
});

test('persisted Andromeda toggles and model band share the ordered settings queue', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const bindings = source.slice(source.indexOf('function bindOnce()'), source.indexOf('export async function initAndromeda'));
  const toggles = bindings.slice(
    bindings.indexOf("for (const id of ['andromeda-results-toggle'"),
    bindings.indexOf("for (const id of ['andromeda-primary-provider'"),
  );
  const band = bindings.slice(
    bindings.indexOf("el('andromeda-band')"),
    bindings.indexOf('for (const id of Object.keys(SEARCH_CREDENTIAL_FIELDS))'),
  );
  for (const handler of [toggles, band]) {
    assert.match(handler, /queueSearchConfigurationWrite\(/);
    assert.match(handler, /\(\) => patchSearchSettings\(/);
  }
  assert.match(
    toggles,
    /const next = !pressed\(id\)[\s\S]*\(\) => patchSearchSettings\(\{ \[setting\]: next \}\)/,
  );
  assert.match(
    band,
    /const band = providerValue\('andromeda-band', 'standard'\)[\s\S]*andromeda_model_band: band/,
  );
});

test('overview strength explains both speed and answer quality', () => {
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  assert.match(html, /light[^<]*fastest[^<]*least checking/i);
  assert.match(html, /standard[^<]*balanced/i);
  assert.match(html, /strong[^<]*slower[^<]*more checking/i);
  assert.match(html, /automatic[^<]*query[^<]*available model/i);
});

test('every real specialist app is registered for the shared app shell', () => {
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  for (const id of [
    'calendar-view', 'tasks-view', 'wiki-view', 'files-view', 'mail-view', 'photos-view',
    'contacts-view', 'vault-view', 'subs-view', 'money-view', 'days-view',
    'activity-view', 'system-view', 'watch-view', 'habits-view', 'read-view', 'books-view',
    'health-view',
  ]) {
    const tag = html.match(new RegExp(`<[^>]+id="${id}"[^>]*>`))?.[0] || '';
    assert.match(tag, /data-specialist-app/);
  }
  assert.match(html, /id="docs-journal-section"/);
});

test('remote overviews require an exact per-search owner confirmation', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(source, /await confirmDialog\(tr\('andromeda\.remote_confirm'/);
  assert.match(source, /confirmation\.confirmed_endpoint_id = preview\.endpoint_id/);
  assert.match(source, /confirmation\.confirmed_model = preview\.model/);
});

test('independent verification is separately confirmed, cancellable, and persisted', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  assert.match(source, /\/api\/andromeda\/verification\/preview/);
  assert.match(source, /model\.privacy_class === 'remote'/);
  assert.match(source, /confirmation\.confirmed_endpoint_id = model\.endpoint_id/);
  assert.match(source, /\/api\/andromeda\/verification\/\$\{encodeURIComponent\(jobId\)\}\/cancel/);
  assert.match(source, /verification: _state\.verification, verifier_model: _state\.verifierModel/);
  assert.match(source, /saved\.verification \|\| \{\}/);
  assert.match(source, /applyVerifiedCorrections\(job\.result \|\| \{\}\)/);
  assert.match(html, /id="andromeda-verification-state"/);
  assert.match(html, /id="andromeda-verification-details-toggle"/);
  assert.match(html, /id="andromeda-verification-toggle"[^>]+role="switch"/);
});

test('search requests use configured result counts and discard stale generations', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(source, /NORMAL_RESULT_COUNTS = new Set\(\[3, 5, 8, 10, 20\]\)/);
  assert.match(source, /max_results: pageSize\(currentCategory\)/);
  assert.match(source, /searchGeneration !== _searchGeneration/);
  assert.match(source, /_searchAbort\?\.abort\(\)/);
  const loadMore = source.slice(
    source.indexOf('async function loadMoreResults'),
    source.indexOf('function saveCurrentSearch'),
  );
  assert.match(loadMore, /Number\.parseInt\(_state\.request\?\.max_results, 10\)/);
  assert.match(loadMore, /Math\.min\(20, previousMax \+ increment\)/);
  assert.match(loadMore, /: previousMax \+ increment/);
  assert.match(loadMore, /currentCategory === 'all' && previousMax >= 20/);
  assert.doesNotMatch(loadMore, /_state\.results\.length \+ increment/);
});

test('reopening a saved search invalidates live work and restores only persisted pagination', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const reopen = source.match(/function reopen\(saved\) \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(reopen, /_searchAbort\?\.abort\(\)/);
  assert.match(reopen, /_overviewAbort\?\.abort\(\)/);
  assert.match(reopen, /_searchGeneration \+= 1/);
  assert.match(reopen, /hasMore: saved\.request\?\.has_more === true/);
  assert.match(reopen, /saved\.request\?\.query \|\| saved\.query \|\| ''/);
  assert.match(reopen, /const overviewPreference = pressed\('andromeda-overview-toggle'\)/);
  assert.match(reopen, /savedCategory === 'all' && !_state\.usedNoAi/);
  assert.match(reopen, /: overviewPreference/);
  assert.match(reopen, /updateMoreResults\(\)/);
  assert.doesNotMatch(reopen, /updateMoreResults\(saved\.request\?\.max_results/);
  assert.match(
    source,
    /request: \{ \.\.\._state\.request, query: _state\.rawQuery, has_more: _state\.hasMore \}/,
  );
  assert.match(source, /query: _state\.rawQuery/);
  assert.doesNotMatch(source, /_state\.query = result\.query/);
});

test('Andromeda Home actions use the authenticated shared navigator', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  assert.match(source, /window\._navigateHome\?\.\(\)/);
  assert.match(app, /window\._navigateHome = \(\) => navigateTo\(_afterlifeFlags\.afterlife_today \? 'today' : 'home'\)/);
  assert.doesNotMatch(source, /location\.assign\(urlForApp\(''\)\)/);
});

test('Andromeda localization preserves the current result state', () => {
  const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
  assert.match(source, /resultStatus:\s*'empty'/);
  assert.match(source, /_state\.resultStatus = state/);
  assert.match(source, /renderAndromedaResults\(_state\.results, _state\.resultStatus, category\(\)\)/);
});

test('the service worker cannot mix old and new JavaScript modules', () => {
  const worker = readFileSync(new URL('../../static/sw.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  const compatibility = readFileSync(new URL('../../static/js/routecompat.js', import.meta.url), 'utf8');
  assert.match(worker, /const STAMP = '300'/);
  assert.match(worker, /NETWORK_FIRST_STATIC = \['\.js', '\.mjs', '\.css'\]/);
  assert.match(worker, /NETWORK_FIRST_STATIC\.some\(ext => url\.pathname\.endsWith\(ext\)\)/);
  assert.match(worker, /Network-first code and styles/);
  const networkFirst = worker.match(/Network-first code and styles[\s\S]*?\/\/ Other static assets/)?.[0] || '';
  assert.match(networkFirst, /e\.respondWith\(networkFirstStatic\(e\.request\)\)/);
  assert.match(worker, /await c\.put\(request, resp\.clone\(\)\)/);
  assert.match(app, /from '\.\/subdomain\.js\?v=237'/);
  assert.match(compatibility, /from '\.\/subdomain\.js\?v=237'/);
});
