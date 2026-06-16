// host parsing + the subdomain↔app map — the single source of truth for the
// "ecosystem of sites" routing. works on *.localhost today, a real domain later.

let _base = 'localhost';   // overwritten from /api/auth/me on boot
export function setBaseDomain(b) { if (b) _base = b; }

// apex ('') = the hub. every app gets its own subdomain; the AI stuff is grouped under aide.
export const SUBDOMAIN_VIEWS = {
  '':         { app: 'alles',    primary: 'home',     views: ['home'] },
  aide:       { app: 'aide',     primary: 'chat',     views: ['chat', 'memory', 'compare', 'brain', 'models', 'reminders', 'gallery', 'cookbook', 'usage', 'skills'] },
  mail:       { app: 'mail',     primary: 'mail',     views: ['mail'] },
  docs:       { app: 'docs',     primary: 'wiki',     views: ['wiki'] },
  gallery:    { app: 'gallery',  primary: 'photos',   views: ['photos'] },
  calendar:   { app: 'calendar', primary: 'calendar', views: ['calendar'] },
  tasks:      { app: 'tasks',    primary: 'tasks',    views: ['tasks'] },
  subs:       { app: 'subs',     primary: 'subs',     views: ['subs'] },
  money:      { app: 'money',    primary: 'money',    views: ['money'] },
  days:       { app: 'days',     primary: 'days',     views: ['days'] },
  journal:    { app: 'journal',  primary: 'journal',  views: ['journal'] },
  activity:   { app: 'activity', primary: 'activity', views: ['activity'] },
  system:     { app: 'system',   primary: 'system',   views: ['system'] },
  files:      { app: 'files',    primary: 'files',    views: ['files'] },
  contacts:   { app: 'contacts', primary: 'contacts', views: ['contacts'] },
  secrets:    { app: 'secrets',  primary: 'vault',    views: ['vault'] },
  notes:      { app: 'docs',     primary: 'wiki',     views: ['wiki'] },
  photos:     { app: 'gallery',  primary: 'photos',   views: ['photos'] },
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

export function currentSub() { return parseHost().sub; }

export function appForSub(sub) { return SUBDOMAIN_VIEWS[sub] || SUBDOMAIN_VIEWS['']; }

// which subdomain owns a view (settings has none — it's a global modal)
export function viewToSub(viewId) {
  for (const [sub, cfg] of Object.entries(SUBDOMAIN_VIEWS)) {
    if (cfg.views.includes(viewId)) return sub;
  }
  return '';
}

export function urlForApp(sub, hash = '') {
  const { base, port, scheme } = parseHost();
  const hostPart = (sub ? sub + '.' : '') + base + (port ? ':' + port : '');
  return `${scheme}//${hostPart}/${hash || ''}`;
}
