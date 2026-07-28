// host parsing + the subdomain↔app map — the single source of truth for the
// "ecosystem of sites" routing. works on *.localhost today, a real domain later.

let _base = 'localhost';   // overwritten from /api/auth/me on boot
export function setBaseDomain(b) { if (b) _base = b; }

// Canonical owners are kept separate from old host aliases so viewToSub() can never
// accidentally route new links back through a legacy hostname.
export const CANONICAL_SUBDOMAIN_VIEWS = {
  '':         { app: 'alles',     primary: 'home',     views: ['home', 'today'] },
  aide:       { app: 'aide',      primary: 'chat',     views: ['chat', 'memory', 'compare', 'brain', 'models', 'gallery', 'cookbook', 'usage', 'skills', 'scheduled', 'project', 'proactive', 'aide-reminders'] },
  andromeda:  { app: 'andromeda', primary: 'andromeda', views: ['andromeda'] },
  docs:       { app: 'docs',      primary: 'wiki',     views: ['docs', 'docs-notes', 'wiki', 'notes', 'journal'] },
  files:      { app: 'files',     primary: 'files',    views: ['files', 'files-list', 'files-gallery', 'photos'] },
  plan:       { app: 'plan',      primary: 'plan',     views: ['plan', 'plan-week', 'plan-board', 'calendar', 'tasks', 'reminders', 'days'] },
  inbox:      { app: 'inbox',     primary: 'inbox',    views: ['inbox', 'mail', 'contacts'] },
  library:    { app: 'library',   primary: 'library',  views: ['library', 'books', 'read'] },
  health:     { app: 'health',    primary: 'health',   views: ['health', 'health-log', 'habits'] },
  finance:    { app: 'finance',   primary: 'finance',  views: ['finance', 'money', 'subs', 'imports'] },
  passwords:  { app: 'passwords', primary: 'vault',    views: ['vault', 'vault-items'] },
  server:     { app: 'server',    primary: 'system',   views: ['server', 'system', 'server-services', 'server-search', 'server-backups', 'server-updates', 'server-logs', 'activity', 'watch', 'server-policy'] },
};

export const LEGACY_SUBDOMAIN_VIEWS = {
  home:          { app: 'alles',     primary: 'home',     views: ['home', 'today'] },
  today:         { app: 'alles',     primary: 'today',    views: ['today'] },
  system:        { app: 'server',    primary: 'system',   views: ['system'] },
  secrets:       { app: 'passwords', primary: 'vault',    views: ['vault'] },
  vault:         { app: 'passwords', primary: 'vault',    views: ['vault'] },
  money:         { app: 'finance',   primary: 'money',    views: ['money'] },
  subs:          { app: 'finance',   primary: 'subs',     views: ['subs'] },
  subscriptions: { app: 'finance',   primary: 'subs',     views: ['subs'] },
  notes:         { app: 'docs',      primary: 'wiki',     views: ['wiki', 'notes'] },
  wiki:          { app: 'docs',      primary: 'wiki',     views: ['wiki'] },
  journal:       { app: 'docs',      primary: 'journal',  views: ['journal'] },
  gallery:       { app: 'files',     primary: 'photos',   views: ['photos'] },
  photos:        { app: 'files',     primary: 'photos',   views: ['photos'] },
  activity:      { app: 'server',    primary: 'activity', views: ['activity'] },
  watch:         { app: 'server',    primary: 'watch',    views: ['watch'] },
  days:          { app: 'plan',      primary: 'plan',     views: ['days'] },
  cowork:        { app: 'aide',      primary: 'chat',     views: ['chat'] },
  jarvis:        { app: 'aide',      primary: 'chat',     views: ['chat'] },
  chat:          { app: 'aide',      primary: 'chat',     views: ['chat'] },
  calendar:      { app: 'plan',      primary: 'plan',     views: ['calendar'] },
  tasks:         { app: 'plan',      primary: 'plan',     views: ['tasks'] },
  reminders:     { app: 'plan',      primary: 'plan',     views: ['reminders'] },
  mail:          { app: 'inbox',     primary: 'inbox',    views: ['mail'] },
  contacts:      { app: 'inbox',     primary: 'inbox',    views: ['contacts'] },
  read:          { app: 'library',   primary: 'library',  views: ['read'] },
  books:         { app: 'library',   primary: 'library',  views: ['books'] },
  habits:        { app: 'health',    primary: 'health',   views: ['habits'] },
};

export const SUBDOMAIN_VIEWS = {
  ...CANONICAL_SUBDOMAIN_VIEWS,
  ...LEGACY_SUBDOMAIN_VIEWS,
};

export function parseHost() {
  const host = location.hostname, port = location.port, scheme = location.protocol;
  let base = _base, sub = '';
  if (host === 'localhost' || host === base) {
    base = host;
  } else if (host.endsWith('.localhost')) {
    base = 'localhost';
    sub = host.slice(0, -'.localhost'.length);
  } else if (host.endsWith('.' + base)) {
    sub = host.slice(0, -('.' + base).length);
  } else {
    base = host;   // unknown (ip etc.) → treat as apex
  }
  if (sub.includes('.')) sub = sub.split('.')[0];   // first label is the app
  return { sub, base, port, scheme };
}

// can this host actually do per-app subdomains? *.localhost works in browsers,
// and a real configured domain works behind the wildcard proxy. a bare IP (or any
// plain hostname) can't — so we run everything on one origin and switch in-page.
function _isIp(h) { return /^\d{1,3}(\.\d{1,3}){3}$/.test(h) || h.includes(':'); }
export function singleHost() {
  const h = location.hostname;
  if (h === 'localhost' || h.endsWith('.localhost')) return false;
  if (_base && _base !== 'localhost' && _base.includes('.') && !_isIp(_base) &&
      (h === _base || h.endsWith('.' + _base))) return false;
  return true;
}

export function currentSub() { return parseHost().sub; }

export function appForSub(sub) { return SUBDOMAIN_VIEWS[sub] || SUBDOMAIN_VIEWS['']; }

export function shouldPollModels(sub = parseHost().sub, oneHost = singleHost()) {
  return oneHost || appForSub(sub).app === 'aide';
}

// which subdomain owns a view (settings has none — it's a global modal)
export function viewToSub(viewId) {
  for (const [sub, cfg] of Object.entries(CANONICAL_SUBDOMAIN_VIEWS)) {
    if (cfg.views.includes(viewId)) return sub;
  }
  return '';
}

export function urlForApp(sub, hash = '') {
  const { base, port, scheme } = parseHost();
  const hostPart = (sub ? sub + '.' : '') + base + (port ? ':' + port : '');
  return `${scheme}//${hostPart}/${hash || ''}`;
}
