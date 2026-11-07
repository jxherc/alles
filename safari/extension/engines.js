// the search engines safari can use, and where each keeps the words you searched for. shared by
// the redirect rules (the popup sets them), and the page script that catches what they miss
/* exported ENGINES, searchedWords, andromedaUrl, engineRules */
const ENGINES = [
  {
    id: 'google',
    hosts: ['www.google.com', 'www.google.ca', 'www.google.co.uk', 'www.google.com.au', 'www.google.de', 'www.google.fr', 'www.google.co.jp', 'www.google.com.hk'],
    path: /^\/search$/,
    param: 'q',
    // webkit runs these rules as content blockers, whose regex has no (?:), {n,m} or |
    regex: '^https://www\\.google\\.[a-z.]*/search\\?(.*&)?q=([^&#]*)',
  },
  { id: 'bing', hosts: ['www.bing.com'], path: /^\/search$/, param: 'q', regex: '^https://www\\.bing\\.com/search\\?(.*&)?q=([^&#]*)' },
  { id: 'duckduckgo', hosts: ['duckduckgo.com'], path: /^\/$/, param: 'q', regex: '^https://duckduckgo\\.com/\\?(.*&)?q=([^&#]*)' },
  { id: 'yahoo', hosts: ['search.yahoo.com'], path: /^\/search/, param: 'p', regex: '^https://search\\.yahoo\\.com/search[^?]*\\?(.*&)?p=([^&#]*)' },
  { id: 'ecosia', hosts: ['www.ecosia.org'], path: /^\/search$/, param: 'q', regex: '^https://www\\.ecosia\\.org/search\\?(.*&)?q=([^&#]*)' },
  { id: 'baidu', hosts: ['www.baidu.com', 'm.baidu.com'], path: /^\/s$/, param: 'wd', alt: 'word', regex: '^https://www\\.baidu\\.com/s\\?(.*&)?wd=([^&#]*)' },
];

// the words a search page was opened for, or '' when it isn't a search on one of the engines
function searchedWords(url) {
  const engine = ENGINES.find(item => item.hosts.includes(url.hostname));
  if (!engine || !engine.path.test(url.pathname)) return '';
  return (url.searchParams.get(engine.param) || (engine.alt && url.searchParams.get(engine.alt)) || '').trim();
}

function andromedaUrl(origin, words) {
  return `${origin}/?app=andromeda&q=${encodeURIComponent(words)}`;
}

// one redirect rule per engine: the search never reaches the engine where safari runs them
function engineRules(origin) {
  return ENGINES.map((engine, index) => ({
    id: index + 1,
    priority: 1,
    // a search alles itself opens on an engine (a link out) stays there
    condition: { regexFilter: engine.regex, resourceTypes: ['main_frame'], excludedInitiatorDomains: [new URL(origin).hostname] },
    action: { type: 'redirect', redirect: { regexSubstitution: `${origin}/?app=andromeda&q=\\2` } },
  }));
}
