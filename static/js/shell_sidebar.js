// the desktop sidebar (decision 0041): every app in one column, and the open app's views right
// under it. the views are the apps' own tab lists, moved here on a wide screen and back into
// their header row on a narrow one, so their keys, focus and wiring stay exactly as they were.

import { appGlyph } from './icons.js';

const wide = typeof matchMedia === 'function' ? matchMedia('(min-width: 1024px)') : { matches: false, addEventListener() {} };

// each app's tab list, by the name the shell shows for it
const VIEWS = {
  aide: '.aide-mode-nav',
  plan: '#plan-tabs',
  inbox: '#inbox-tabs',
  docs: '#docs-tabs',
  files: '#files-tabs',
  library: '#library-tabs',
  health: '#health-tabs',
  finance: '#finance-tabs',
  vault: '#vault-tabs',
  server: '#server-tabs',
};

let current = '';
let host = null;

function nameFor(label) {
  return label === 'alles' ? 'home' : label;
}

function render(groups, go) {
  host = document.getElementById('shell-sidebar');
  if (!host) return;
  const list = document.createElement('div');
  list.className = 'shell-sidebar-apps';
  for (const [, destinations] of groups) {
    const group = document.createElement('div');
    group.className = 'shell-sidebar-group';
    for (const app of destinations) {
      const item = document.createElement('div');
      item.className = 'shell-sidebar-item';
      item.dataset.app = app.name;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'shell-sidebar-link';
      button.dataset.view = app.view;
      button.innerHTML = `${appGlyph(app.view)}<span>${app.name}</span>`;
      button.addEventListener('click', () => go(app.view));
      const slot = document.createElement('div');
      slot.className = 'shell-sidebar-views';
      item.append(button, slot);
      group.append(item);
    }
    list.append(group);
  }
  host.querySelector('.shell-sidebar-apps')?.remove();
  host.querySelector('.shell-sidebar-foot')?.before(list);
}

function placeViews() {
  if (!host) return;
  for (const [name, selector] of Object.entries(VIEWS)) {
    const tabs = document.querySelector(selector);
    if (!tabs) continue;
    // a placeholder keeps the list's place in its header row, for the way back (and for the
    // scroll strip a narrow screen builds around it)
    let home = document.querySelector(`.shell-views-home[data-for="${tabs.id || name}"]`);
    if (!home) {
      if (!tabs.id) tabs.id = `${name}-views`;
      home = document.createElement('span');
      home.className = 'shell-views-home';
      home.dataset.for = tabs.id;
      home.hidden = true;
      tabs.before(home);
    }
    const slot = host.querySelector(`.shell-sidebar-item[data-app="${name}"] .shell-sidebar-views`);
    if (wide.matches && slot) {
      if (tabs.parentElement !== slot) slot.append(tabs);
      tabs.setAttribute('aria-orientation', 'vertical');
    } else {
      if (home.nextSibling !== tabs) home.after(tabs);
      if (tabs.getAttribute('role') === 'tablist') tabs.setAttribute('aria-orientation', 'horizontal');
      else tabs.removeAttribute('aria-orientation');
    }
  }
}

// the title row reads "plan  tasks": the app (the switcher) and then the open view, in ink
function syncTitle() {
  const view = document.getElementById('shell-title-view');
  if (!view) return;
  const tabs = VIEWS[current] && document.querySelector(VIEWS[current]);
  const picked = tabs?.querySelector('[aria-selected="true"], [aria-pressed="true"]');
  const text = wide.matches && picked ? picked.textContent.trim() : '';
  view.textContent = text;
  view.hidden = !text;
}

export function syncShellSidebar(label) {
  if (!host) return;
  current = nameFor(label);
  syncTitle();
  for (const item of host.querySelectorAll('.shell-sidebar-item')) {
    const on = item.dataset.app === current;
    item.classList.toggle('is-open', on);
    const link = item.querySelector('.shell-sidebar-link');
    if (on) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
}

export function initShellSidebar({ groups, go, settings }) {
  render(groups, go);
  if (!host) return;
  host.hidden = false;
  const gear = host.querySelector('#shell-sidebar-settings');
  if (gear) {
    gear.innerHTML = `${appGlyph('settings')}<span>settings</span>`;
    gear.addEventListener('click', settings);
  }
  placeViews();
  wide.addEventListener('change', () => { placeViews(); syncTitle(); });
  // a view picked from the sidebar (or by a link) renames the title row
  new MutationObserver(syncTitle).observe(host, { subtree: true, attributes: true, attributeFilter: ['aria-selected', 'aria-pressed'] });
  document.body.classList.add('has-shell-sidebar');
}
