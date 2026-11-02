// the phone bar (u.07, decision 0064): a phone gets a bottom bar. ipad and desktop have no rail
// (the owner rejected it), so css shows the nav at 700px and narrower only. home and aide come
// first, then the owner's pinned apps (the same list as home's pinned apps), and "more" opens the
// app sheet for the rest. the bar keeps 5 buttons so each stays a 44px target
import { appGlyph } from './icons.js';
import { t } from './i18n.js';
import { appLabel } from './util.js';

const FIXED = Object.freeze([{ view: 'today', name: 'home' }, { view: 'chat', name: 'aide' }]);
const PHONE_PINNED = 2;
let _rail = null;
let _apps = [];
let _navigate = null;
let _current = '';

function _item({ view, name }, index) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'app-rail-item';
  button.dataset.view = view;
  button.dataset.app = name;
  // the phone bar shows home, aide and the first pinned apps; the rest wait under more
  if (index >= FIXED.length + PHONE_PINNED) button.dataset.wide = '1';
  button.innerHTML = `${appGlyph(view)}<span>${appLabel(name)}</span>`;
  button.addEventListener('click', () => _navigate?.(view));
  return button;
}

function _render(pinned) {
  if (!_rail) return;
  const byView = new Map(_apps.map(app => [app.view, app]));
  const items = [...FIXED, ...pinned.map(view => byView.get(view)).filter(Boolean)];
  const more = document.createElement('button');
  more.type = 'button';
  more.className = 'app-rail-item app-rail-more';
  more.setAttribute('aria-haspopup', 'dialog');
  more.setAttribute('aria-controls', 'app-drawer');
  more.innerHTML = `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/></svg><span>${t('common.more')}</span>`;
  more.addEventListener('click', () => document.getElementById('app-drawer-btn')?.click());
  _rail.replaceChildren(...items.map(_item), more);
  syncAppRail(_current);
}

// label: the shell's name for the open app (alles is home)
export function syncAppRail(label) {
  _current = label === 'alles' ? 'home' : label;
  _rail?.querySelectorAll('.app-rail-item[data-app]').forEach(button => {
    if (button.dataset.app === _current) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
}

export async function initAppRail({ apps, navigate }) {
  _rail = document.getElementById('app-rail');
  if (!_rail || _rail.dataset.ready) return;
  _rail.dataset.ready = '1';
  _rail.setAttribute('aria-label', t('shell.apps'));
  _apps = apps;
  _navigate = navigate;
  let pinned = ['plan', 'wiki', 'files'];
  _render(pinned);
  _rail.hidden = false;
  try {
    const response = await fetch('/api/today/preferences');
    if (response.ok) pinned = (await response.json())?.shortcuts || pinned;
  } catch {}
  _render(pinned);
  window.addEventListener('alles:home-preferences-changed', event => _render(event.detail?.shortcuts || pinned));
  window.addEventListener('alles:localization-change', () => _render(pinned));
}
