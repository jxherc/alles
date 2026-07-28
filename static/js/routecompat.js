// Pure compatibility routing for old app names, views, and subdomains.
//
// This module does not navigate. Callers can resolve a legacy destination, clean
// its URL, then use location.replace(target) when buildCompatibilityUrl returns
// a string. A null result always means "leave the current route alone".

import { CANONICAL_SUBDOMAIN_VIEWS } from './subdomain.js?v=237';

// Canonical product hosts after the Phase 3 compatibility window begins. Apps
// which did not move keep their existing specialist host there as well.
export const CANONICAL_HOSTS = CANONICAL_SUBDOMAIN_VIEWS;

const _route = (host, view, hashOwner, extra = {}) => Object.freeze({
  host,
  view,
  ...extra,
  hashOwner,
});

const HOME_TODAY = _route('', 'today', 'today');
const HOME_LEGACY = _route('', 'home', 'home');
const ANDROMEDA = _route('andromeda', 'andromeda', 'andromeda');
const ACTIVITY = _route('server', 'server', 'activity', { section: 'activity' });
const SYSTEM = _route('server', 'system', 'system');
const VAULT = _route('passwords', 'vault', 'vault');
const PLAN = _route('plan', 'plan', 'plan');
const PLAN_WEEK = _route('plan', 'plan', 'plan-week', { section: 'week' });
const PLAN_BOARD = _route('plan', 'plan', 'plan-board', { section: 'board' });
const CALENDAR = _route('plan', 'plan', 'calendar', { section: 'calendar' });
const TASKS = _route('plan', 'plan', 'tasks', { section: 'tasks' });
const REMINDERS = _route('plan', 'plan', 'reminders', { section: 'reminders' });
const DAYS = _route('plan', 'plan', 'days', { section: 'days' });
const INBOX = _route('inbox', 'inbox', 'inbox');
const MAIL = _route('inbox', 'inbox', 'mail', { section: 'mail' });
const CONTACTS = _route('inbox', 'inbox', 'contacts', { section: 'contacts' });
const LIBRARY = _route('library', 'library', 'library');
const BOOKS = _route('library', 'library', 'books', { section: 'books' });
const READ = _route('library', 'library', 'read', { section: 'read' });
const HEALTH = _route('health', 'health', 'health-overview');
const HEALTH_LOG = _route('health', 'health', 'health-log', { section: 'health' });
const HABITS = _route('health', 'health', 'habits', { section: 'habits' });
const FINANCE = _route('finance', 'finance', 'finance-overview');
const MONEY = _route('finance', 'finance', 'money', { section: 'money' });
const SUBS = _route('finance', 'finance', 'subs', { section: 'subs' });
const IMPORTS = _route('finance', 'finance', 'imports', { section: 'imports' });
const WIKI = _route('docs', 'wiki', 'wiki');
const NOTES = _route('docs', 'wiki', 'notes', { section: 'notes' });
const JOURNAL = _route('docs', 'journal', 'journal');
const FILES = _route('files', 'files', 'files');
const PHOTOS = _route('files', 'photos', 'photos');
const FILES_GALLERY = _route('files', 'files', 'files-gallery', { section: 'gallery' });
const SERVER_SECTION = section => _route('server', 'server', `server-${section}`, { section });
const WATCH = _route('server', 'server', 'watch', { section: 'watch' });
const CREATIONS = _route('aide', 'gallery', 'gallery', { section: 'creations' });
const CHAT = _route('aide', 'chat', 'session');
const JARVIS = _route('aide', 'chat', 'session', { mode: 'jarvis' });
const SCHEDULED = _route('aide', 'scheduled', 'scheduled');
const AIDE_REMINDERS = _route('aide', 'aide-reminders', 'aide-reminders');

// Host aliases are deliberately separate from query identifiers. In particular,
// gallery.localhost is the old personal-photo app, while ?app=gallery is Aide's
// AI-image gallery (now called Creations).
export const LEGACY_HOST_ALIASES = Object.freeze({
  home: HOME_TODAY,
  today: HOME_TODAY,
  activity: ACTIVITY,
  system: SYSTEM,
  secrets: VAULT,
  vault: VAULT,
  money: MONEY,
  subs: SUBS,
  subscriptions: SUBS,
  notes: NOTES,
  wiki: WIKI,
  journal: JOURNAL,
  gallery: PHOTOS,
  photos: PHOTOS,
  watch: WATCH,
  cowork: JARVIS,
  jarvis: JARVIS,
  chat: CHAT,
  calendar: CALENDAR,
  tasks: TASKS,
  reminders: REMINDERS,
  days: DAYS,
  mail: MAIL,
  contacts: CONTACTS,
  read: READ,
  books: BOOKS,
  habits: HABITS,
});

const _fixedIdentifierRoutes = Object.freeze({
  system: SYSTEM,
  server: SYSTEM,
  secrets: VAULT,
  vault: VAULT,
  passwords: VAULT,
  money: MONEY,
  finance: MONEY,
  'finance-overview': FINANCE,
  subs: SUBS,
  subscriptions: SUBS,
  notes: NOTES,
  wiki: WIKI,
  docs: WIKI,
  journal: JOURNAL,
  files: FILES,
  'files-list': FILES,
  'files-gallery': FILES_GALLERY,
  photos: PHOTOS,
  gallery: CREATIONS,
  cowork: JARVIS,
  jarvis: JARVIS,
  chat: CHAT,
  aide: CHAT,
  andromeda: ANDROMEDA,
  plan: PLAN,
  'plan-week': PLAN_WEEK,
  'plan-board': PLAN_BOARD,
  calendar: CALENDAR,
  tasks: TASKS,
  reminders: REMINDERS,
  inbox: INBOX,
  mail: MAIL,
  contacts: CONTACTS,
  library: LIBRARY,
  books: BOOKS,
  read: READ,
  health: HEALTH_LOG,
  'health-overview': HEALTH,
  'health-log': HEALTH_LOG,
  habits: HABITS,
  imports: IMPORTS,
  'docs-notes': NOTES,
  'vault-items': VAULT,
  'server-services': SERVER_SECTION('services'),
  'server-search': SERVER_SECTION('search'),
  'server-backups': SERVER_SECTION('backups'),
  'server-updates': SERVER_SECTION('updates'),
  'server-logs': SERVER_SECTION('logs'),
  'server-activity': ACTIVITY,
  'server-watch': WATCH,
  'server-policy': SERVER_SECTION('policy'),
  days: DAYS,
  watch: WATCH,
  memory: _route('aide', 'memory', 'memory'),
  compare: _route('aide', 'compare', 'compare'),
  brain: _route('aide', 'brain', 'brain'),
  models: _route('aide', 'models', 'models'),
  cookbook: _route('aide', 'cookbook', 'cookbook'),
  usage: _route('aide', 'usage', 'usage'),
  skills: _route('aide', 'skills', 'skills'),
  scheduled: SCHEDULED,
  proactive: SCHEDULED,
  'aide-reminders': AIDE_REMINDERS,
});

function _identifier(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function _hasIdentifier(value) {
  return typeof value === 'string' && value.trim() !== '';
}

function _routeForIdentifier(identifier, flags) {
  if (identifier === 'home' || identifier === 'today') {
    return flags?.afterlife_today === true ? HOME_TODAY : HOME_LEGACY;
  }
  if (identifier === 'activity') return ACTIVITY;
  return _fixedIdentifierRoutes[identifier] || null;
}

/**
 * Resolve an old host or app/view query into its canonical destination.
 *
 * Explicit query routing has priority over the host. `app` has priority over
 * `view`, matching the existing boot router. An explicit but unknown identifier
 * is a no-op instead of falling through to a different legacy host redirect.
 */
export function resolveCompatibilityRoute({ sub = '', app, view, flags = {} } = {}) {
  const sourceHost = _identifier(sub);
  const hasApp = _hasIdentifier(app);
  const hasView = _hasIdentifier(view);

  if (hasApp || hasView) {
    const identifier = _identifier(hasApp ? app : view);
    return _routeForIdentifier(identifier, flags);
  }

  if (!sourceHost || Object.hasOwn(CANONICAL_HOSTS, sourceHost)) return null;

  if (sourceHost === 'home') {
    return flags?.afterlife_today === true ? HOME_TODAY : HOME_LEGACY;
  }
  return LEGACY_HOST_ALIASES[sourceHost] || null;
}

const _CONSUMED_QUERY_KEYS = new Set(['app', 'view', '_auth', '_sso']);

function _decodedQueryKey(rawPair) {
  const rawKey = rawPair.split('=', 1)[0];
  try { return decodeURIComponent(rawKey.replace(/\+/g, ' ')); }
  catch { return rawKey; }
}

// Filter the raw query rather than round-tripping it through URLSearchParams.
// That keeps duplicate keys, their order, and the caller's original encoding.
function _cleanSearch(rawSearch) {
  if (!rawSearch || rawSearch === '?') return '';
  const kept = rawSearch.slice(1).split('&').filter(pair =>
    !_CONSUMED_QUERY_KEYS.has(_decodedQueryKey(pair)));
  return kept.length ? `?${kept.join('&')}` : '';
}

function _baseHostname(url, baseDomain) {
  const supplied = _identifier(baseDomain).replace(/^\.+|\.+$/g, '');
  if (supplied) return supplied;
  if (url.hostname === 'localhost' || url.hostname.endsWith('.localhost')) return 'localhost';
  // Custom wildcard domains should pass parseHost().base explicitly. Falling
  // back to the current hostname keeps single-host and bare-IP installs safe.
  return url.hostname;
}

function _handoffIdentifier(route) {
  if (route.mode === 'jarvis') return 'jarvis';
  if (route.section === 'notes') return 'notes';
  if (route.hashOwner === 'files-gallery' || route.hashOwner === 'vault-items' || route.hashOwner === 'docs-notes' || route.hashOwner.startsWith('server-')) {
    return route.hashOwner;
  }
  if (route.hashOwner === 'plan-week' || route.hashOwner === 'plan-board') {
    return route.hashOwner;
  }
  if (route.hashOwner === 'health-overview' || route.hashOwner === 'finance-overview') {
    return route.hashOwner;
  }
  if (route.hashOwner === 'health-log') return 'health-log';
  if (['calendar', 'tasks', 'reminders', 'days', 'mail', 'contacts', 'books', 'read', 'habits', 'money', 'subs', 'imports', 'activity', 'watch'].includes(route.section)) {
    return route.section;
  }
  return _identifier(route.view);
}

/**
 * Build an absolute canonical URL suitable for location.replace().
 *
 * `currentUrl` must be an absolute URL (normally location.href). `baseDomain`
 * is optional for localhost and single-host installs; configured wildcard
 * domains should pass the base returned by parseHost(). The result is null when
 * the route is invalid or the canonical URL is already the current URL.
 */
export function buildCompatibilityUrl({ currentUrl, route, baseDomain = '' } = {}) {
  if (!route || !Object.hasOwn(CANONICAL_HOSTS, _identifier(route.host))) return null;

  let current;
  try {
    current = new URL(typeof currentUrl === 'string' ? currentUrl : currentUrl?.href);
  } catch {
    return null;
  }

  const canonicalHost = _identifier(route.host);
  const base = _baseHostname(current, baseDomain);
  const hostname = canonicalHost ? `${canonicalHost}.${base}` : base;
  const port = current.port ? `:${current.port}` : '';
  let search = _cleanSearch(current.search);
  if (hostname !== current.hostname) {
    const handoff = _handoffIdentifier(route);
    if (handoff) search += `${search ? '&' : '?'}view=${encodeURIComponent(handoff)}`;
  }
  const target = `${current.protocol}//${hostname}${port}${current.pathname}${search}${current.hash}`;

  return target === current.href ? null : target;
}
