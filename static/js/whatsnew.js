// what's new: shows once after each update (never on a first visit), then stays shut until
// the next one. releases live in /static/whats-new.json, newest first.
import { createFocusBoundary } from './kokuen.js?v=5';
import { escapeHtml } from './util.js';
import { parseHost, singleHost } from './subdomain.js?v=238';
import { t } from './i18n.js';

// a note without a catalog entry (a release added before its translations) shows its own text
const tr = (key, fallback) => { const text = t(key); return text === key ? fallback : text; };

// an item with a key keeps its translations under that key whatever its place in the list, so
// a new item can go in front without moving the others. older items (no key) use their position
export const itemKey = (slug, item, n) => `whatsnew.${slug}.${item.key || `item${n + 1}`}`;

const SEEN = 'alles.whatsNewSeen';

// each app has its own address (aide., plan., ...), so browser storage alone would show the
// notes once per app; a cookie on the shared domain makes "seen" hold everywhere
const COOKIE = 'alles_whats_new';
function sharedDomain() {
  // only alles's own base domain when it really runs one app per subdomain; never a parent
  // domain it doesn't own (a tailnet name, an IP)
  if (singleHost()) return '';
  const base = parseHost().base || '';
  return base.includes('.') && location.hostname.endsWith('.' + base) ? base : '';
}
const read = () => {
  const cookie = document.cookie.split('; ').find(part => part.startsWith(COOKIE + '='));
  if (cookie) return decodeURIComponent(cookie.slice(COOKIE.length + 1));
  try { return localStorage.getItem(SEEN) || ''; } catch { return ''; }
};
const markHere = id => {
  const domain = sharedDomain();
  document.cookie = `${COOKIE}=${encodeURIComponent(id)}; path=/; max-age=31536000; SameSite=Lax${domain ? `; domain=${domain}` : ''}`;
  try { localStorage.setItem(SEEN, id); } catch { /* private window: the cookie still holds */ }
};

// a browser only remembers for its own address, and on an ipad every home-screen app keeps its
// own storage too, so the tailscale ip, the lan ip and the home-screen app each showed the notes
// again (nov 5). alles keeps one record for all of them in its settings
let _onServer = null;
async function seenOnServer() {
  try {
    const settings = await fetch('/api/settings', { cache: 'no-store' }).then(r => (r.ok ? r.json() : null));
    _onServer = typeof settings?.whats_new_seen === 'string' ? settings.whats_new_seen : '';
  } catch { _onServer = null; }
  return _onServer || '';
}
const mark = id => {
  markHere(id);
  if (_onServer === id) return;
  _onServer = id;
  fetch('/api/settings', {
    method: 'PATCH', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ whats_new_seen: id }),
  }).catch(() => {});
};

// the newer of two records; releases are newest first, and one the list doesn't know is oldest
export function newestSeen(list, ...ids) {
  const rank = id => { const at = list.findIndex(release => release.id === id); return at === -1 ? Infinity : at; };
  return ids.filter(Boolean).sort((a, b) => rank(a) - rank(b))[0] || '';
}

async function releases() {
  try {
    const response = await fetch('/static/whats-new.json', { cache: 'no-cache' });
    if (!response.ok) return [];
    const data = await response.json();
    return Array.isArray(data.releases) ? data.releases : [];
  } catch { return []; }
}

// which releases to show: everything newer than the last one seen. a first visit shows none:
// a fresh install opens setup, and notes only mean something after an update (u.11)
export function unseen(list, seen) {
  if (!list.length || !seen || list[0].id === seen) return [];
  const at = list.findIndex(release => release.id === seen);
  return (at === -1 ? list : list.slice(0, at)).slice(0, 3);
}

export async function maybeShowWhatsNew() {
  // a test browser or other automation never needs release notes over the screen it drives
  if (navigator.webdriver) return;
  const list = await releases();
  if (!list.length) return;
  const here = read();
  const seen = newestSeen(list, here, await seenOnServer());
  if (!seen) { mark(list[0].id); return; }
  if (seen !== here) markHere(seen);
  const show = unseen(list, seen);
  if (!show.length) return;
  // never on top of something the owner already has open
  const busy = [...document.querySelectorAll('.dialog-overlay, [role="dialog"], [role="alertdialog"]')].some(node => node.getClientRects().length);
  if (busy) { setTimeout(maybeShowWhatsNew, 4000); return; }
  // shown once is seen: switching apps or reloading before closing it never brings it back
  mark(list[0].id);
  open(show, { first: false, latest: list[0].id });
}

export async function openWhatsNew() {
  const list = await releases();
  if (list.length) open(list.slice(0, 3), { first: false, latest: list[0].id });
}

function open(show, { first, latest }) {
  if (document.getElementById('whats-new-dialog')) return;
  const source = document.activeElement;
  const overlay = document.createElement('div');
  overlay.className = 'dialog-overlay whats-new-overlay';
  let index = 0;
  overlay.innerHTML = `<section class="dialog-card whats-new-card" id="whats-new-dialog" role="dialog" aria-modal="true" aria-labelledby="whats-new-title">
    <header class="whats-new-head">
      <div><h2 id="whats-new-title">${escapeHtml(first ? t('common.whatsnew_welcome') : t('common.whatsnew_title'))}</h2><p class="whats-new-date"></p></div>
      <button type="button" class="icon-btn" data-whats-new-close aria-label="${escapeHtml(t('common.close'))}">×</button>
    </header>
    <ol class="whats-new-list"></ol>
    <footer class="whats-new-foot">
      <span class="whats-new-pages" aria-live="polite"></span>
      <button type="button" class="btn" data-whats-new-older hidden>${escapeHtml(t('common.whatsnew_older'))}</button>
      <button type="button" class="btn primary" data-whats-new-done>${escapeHtml(t('common.whatsnew_got_it'))}</button>
    </footer>
  </section>`;
  document.body.appendChild(overlay);
  const dialog = overlay.querySelector('[role="dialog"]');
  const list = overlay.querySelector('.whats-new-list');
  const older = overlay.querySelector('[data-whats-new-older]');

  const render = () => {
    const release = show[index];
    const slug = String(release.id).replace(/-/g, '_');
    overlay.querySelector('.whats-new-date').textContent = release.date ? tr(`whatsnew.${slug}.date`, release.date) : '';
    list.innerHTML = (release.items || []).map((item, n) => `
      <li class="whats-new-item" style="--n:${n}">
        <h3>${escapeHtml(tr(`${itemKey(slug, item, n)}.title`, item.title || ''))}</h3>
        <p>${escapeHtml(tr(`${itemKey(slug, item, n)}.body`, item.body || ''))}</p>
        ${item.try ? `<p class="whats-new-try">${escapeHtml(t('common.whatsnew_try'))} <kbd>${escapeHtml(item.try)}</kbd></p>` : ''}
      </li>`).join('');
    list.classList.remove('is-in'); void list.offsetWidth; list.classList.add('is-in');
    older.hidden = index >= show.length - 1;
    overlay.querySelector('.whats-new-pages').textContent = show.length > 1 ? t('common.whatsnew_page', { index: index + 1, total: show.length }) : '';
  };
  const close = () => {
    mark(latest);
    boundary.deactivate(); boundary.destroy();
    overlay.remove();
  };
  const boundary = createFocusBoundary(dialog, { onEscape: close });
  overlay.addEventListener('keydown', event => event.stopPropagation());
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  overlay.querySelector('[data-whats-new-close]').onclick = close;
  overlay.querySelector('[data-whats-new-done]').onclick = close;
  older.onclick = () => { index = Math.min(index + 1, show.length - 1); render(); };
  render();
  boundary.activate({ source, focus: overlay.querySelector('[data-whats-new-done]') });
}
