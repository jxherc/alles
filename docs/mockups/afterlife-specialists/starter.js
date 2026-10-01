const body = document.body;
const root = document.documentElement;
const byId = id => document.getElementById(id);

const groupStrip = document.querySelector('.group-strip');
const currentGroup = groupStrip?.querySelector('[aria-current="page"]');
if (groupStrip && currentGroup && groupStrip.scrollWidth > groupStrip.clientWidth) {
  currentGroup.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function announce(message) {
  const node = byId('starter-toast');
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
  clearTimeout(announce.timer);
  announce.timer = setTimeout(() => { node.hidden = true; }, 2600);
}

function setSwitch(control, next) {
  if (control.getAttribute('aria-disabled') === 'true') return;
  control.setAttribute('aria-checked', String(next));
  const key = control.dataset.switch;
  if (key === 'theme') {
    const theme = next ? 'light' : 'dark';
    root.dataset.theme = theme;
    control.setAttribute('aria-label', next ? 'use dark theme' : 'use light theme');
  }
  if (key === 'density') body.dataset.density = next ? 'compact' : 'comfortable';
  const status = control.dataset.status;
  if (status) announce(`${status}: ${next ? 'on' : 'off'}`);
}

document.querySelectorAll('[role="switch"]').forEach(control => {
  control.addEventListener('click', () => setSwitch(control, control.getAttribute('aria-checked') !== 'true'));
});

document.querySelectorAll('[role="checkbox"]').forEach(control => {
  const toggle = () => {
    const next = control.getAttribute('aria-checked') !== 'true';
    control.setAttribute('aria-checked', String(next));
    announce(next ? 'marked complete in this starter' : 'returned to open');
  };
  control.addEventListener('click', toggle);
});

document.querySelectorAll('[role="tablist"]').forEach(tablist => {
  const tabs = [...tablist.querySelectorAll('[role="tab"]')];
  const choose = tab => {
    tabs.forEach(item => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      const panel = byId(item.getAttribute('aria-controls'));
      if (panel) panel.hidden = !selected;
    });
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => choose(tab));
    tab.addEventListener('keydown', event => {
      let next = null;
      if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
      if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
      if (event.key === 'Home') next = tabs[0];
      if (event.key === 'End') next = tabs.at(-1);
      if (!next) return;
      event.preventDefault();
      choose(next);
      next.focus();
    });
  });
});

const stateTrigger = document.querySelector('[data-state-trigger]');
const stateMenu = byId('state-menu');
const stateOptions = stateMenu ? [...stateMenu.querySelectorAll('[role="option"]')] : [];

function closeStateMenu(focus = false) {
  if (!stateTrigger || !stateMenu) return;
  stateTrigger.setAttribute('aria-expanded', 'false');
  stateMenu.hidden = true;
  if (focus) stateTrigger.focus();
}

function renderState(value, focusTrigger = false) {
  body.dataset.demoState = value;
  stateOptions.forEach(option => {
    const selected = option.dataset.state === value;
    option.setAttribute('aria-selected', String(selected));
    option.tabIndex = selected ? 0 : -1;
  });
  const banner = byId('demo-state');
  const messages = {
    ready: ['Ready', 'All fake sources are available.', 'info'],
    loading: ['Loading', 'The workbench stays visible while fresh records arrive.', 'info'],
    empty: ['Empty', 'This view has no records yet. Other sections remain available.', 'info'],
    partial: ['Partial', 'One source is delayed. Verified local records remain usable.', 'warning'],
    error: ['Needs attention', 'The latest refresh failed. No existing record was changed.', 'danger'],
    offline: ['Offline', 'Last confirmed local data stays visible. New changes wait for a connection.', 'warning'],
    disabled: ['Disabled', 'Configuration remains available, but this workflow will not run.', 'warning'],
    permission: ['Permission needed', 'The unavailable destination stays off until its connection is approved.', 'warning'],
    interrupted: ['Interrupted', 'The unfinished draft and current selection remain available.', 'warning'],
  };
  const [title, copy, tone] = messages[value] || messages.ready;
  if (banner) {
    banner.hidden = value === 'ready';
    banner.dataset.tone = tone;
    banner.innerHTML = `<strong>${title}.</strong> ${copy}`;
  }
  closeStateMenu(focusTrigger);
}

stateTrigger?.addEventListener('click', () => {
  const open = stateTrigger.getAttribute('aria-expanded') !== 'true';
  stateTrigger.setAttribute('aria-expanded', String(open));
  stateMenu.hidden = !open;
  if (open) stateOptions.find(option => option.getAttribute('aria-selected') === 'true')?.focus();
});

stateTrigger?.addEventListener('keydown', event => {
  if (event.key !== 'ArrowDown') return;
  event.preventDefault();
  stateTrigger.setAttribute('aria-expanded', 'true');
  stateMenu.hidden = false;
  const selected = stateOptions.find(option => option.getAttribute('aria-selected') === 'true') || stateOptions[0];
  selected?.focus();
});

stateOptions.forEach((option, index) => {
  option.addEventListener('click', () => renderState(option.dataset.state, true));
  option.addEventListener('keydown', event => {
    let next = null;
    if (event.key === 'ArrowDown') next = stateOptions[(index + 1) % stateOptions.length];
    if (event.key === 'ArrowUp') next = stateOptions[(index - 1 + stateOptions.length) % stateOptions.length];
    if (event.key === 'Home') next = stateOptions[0];
    if (event.key === 'End') next = stateOptions.at(-1);
    if (event.key === 'Escape') return closeStateMenu(true);
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      return renderState(option.dataset.state, true);
    }
    if (!next) return;
    event.preventDefault();
    stateOptions.forEach(item => { item.tabIndex = item === next ? 0 : -1; });
    next.focus();
  });
});

document.addEventListener('click', event => {
  if (!stateMenu || stateMenu.hidden || stateMenu.contains(event.target) || stateTrigger?.contains(event.target)) return;
  closeStateMenu();
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && stateMenu && !stateMenu.hidden) closeStateMenu(true);
});

document.querySelectorAll('[data-toast]').forEach(control => {
  control.addEventListener('click', () => announce(control.dataset.toast));
});

const modal = byId('starter-modal');
const appShell = document.querySelector('.app-shell');
let modalOpener = null;
function closeModal() {
  if (!modal) return;
  modal.hidden = true;
  if (appShell) {
    appShell.inert = false;
    appShell.removeAttribute('aria-hidden');
  }
  modalOpener?.focus();
}

document.querySelectorAll('[data-open-modal]').forEach(control => {
  control.addEventListener('click', () => {
    if (!modal) return;
    modalOpener = control;
    if (appShell) {
      appShell.inert = true;
      appShell.setAttribute('aria-hidden', 'true');
    }
    modal.hidden = false;
    modal.querySelector('[data-close-modal], button')?.focus();
  });
});
document.querySelectorAll('[data-close-modal]').forEach(control => control.addEventListener('click', closeModal));
modal?.addEventListener('click', event => { if (event.target === modal) closeModal(); });
modal?.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    event.preventDefault();
    closeModal();
    return;
  }
  if (event.key !== 'Tab') return;
  const focusable = [...new Set(modal.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]',
  ))].filter(node => node.tabIndex >= 0 && !node.closest('[hidden]'));
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});

byId('starter-approve-import')?.addEventListener('click', () => {
  closeModal();
  announce('starter only: 3 new rows staged, 1 duplicate skipped');
  const receipt = byId('import-receipt');
  if (receipt) receipt.hidden = false;
});
byId('starter-undo-import')?.addEventListener('click', () => {
  const receipt = byId('import-receipt');
  if (receipt) receipt.hidden = true;
  announce('starter only: import receipt undone');
});

renderState('ready');
