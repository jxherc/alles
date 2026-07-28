const one = selector => document.querySelector(selector);
const all = selector => [...document.querySelectorAll(selector)];
const status = message => { one('#global-status').textContent = message; };

let returnFocus = null;

function selectSurface(name, { focus = false } = {}) {
  all('[data-surface]').forEach(button => {
    const selected = button.dataset.surface === name;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    button.id = `tab-${button.dataset.surface}`;
    if (selected && focus) button.focus();
  });
  all('.surface').forEach(panel => { panel.hidden = panel.id !== `surface-${name}`; });
  status(`${name.replace('-', ' ')} starter · fake data`);
}

function selectExclusive(group, selected) {
  all('[role="radio"]', group);
  const choices = [...group.querySelectorAll('[role="radio"]')];
  choices.forEach(choice => {
    const active = choice === selected;
    choice.setAttribute('aria-checked', String(active));
    choice.tabIndex = active ? 0 : -1;
  });
}

function openDialog(id, trigger) {
  const dialog = document.getElementById(id);
  if (!dialog) return;
  returnFocus = trigger instanceof HTMLElement ? trigger : document.activeElement;
  if (id === 'provider-dialog' && trigger?.dataset.provider) {
    one('#provider-title').textContent = `connect ${trigger.dataset.provider}`;
  }
  dialog.hidden = false;
  const first = dialog.querySelector('[data-close-dialog], button, input, textarea');
  first?.focus();
}

function closeDialog(dialog, message = '') {
  if (!dialog) return;
  dialog.hidden = true;
  const target = returnFocus;
  returnFocus = null;
  if (target?.isConnected) target.focus();
  if (message) status(message);
}

function trapDialog(event) {
  const dialog = event.currentTarget;
  if (event.key === 'Escape') {
    event.preventDefault();
    closeDialog(dialog, 'dialog closed');
    return;
  }
  if (event.key !== 'Tab') return;
  const focusable = all('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')
    .filter(element => dialog.contains(element) && !element.hidden && element.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

function setFilesState(stateName) {
  all('[data-preview-state]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.previewState === stateName)));
  const list = one('#file-list');
  const message = one('#files-state-message');
  if (stateName === 'ready') {
    list.hidden = false;
    message.hidden = true;
  } else {
    list.hidden = true;
    message.hidden = false;
    message.innerHTML = stateName === 'loading'
      ? '<strong>loading approved locations…</strong><br>Existing controls stay visible while metadata refreshes.'
      : stateName === 'offline'
        ? '<strong>connected locations are offline.</strong><br>Verified offline copies remain available; no live path is implied.'
        : '<strong>this scope could not be loaded.</strong><br><button class="quiet-action" type="button" data-action="retry-files">retry</button>';
  }
  status(`Files preview: ${stateName}`);
}

document.addEventListener('click', event => {
  const surface = event.target.closest('[data-surface]');
  if (surface) { selectSurface(surface.dataset.surface); return; }

  const opener = event.target.closest('[data-open-dialog]');
  if (opener) { openDialog(opener.dataset.openDialog, opener); return; }

  const closer = event.target.closest('[data-close-dialog]');
  if (closer) { closeDialog(closer.closest('.dialog-layer'), 'dialog closed'); return; }

  const preview = event.target.closest('[data-preview-state]');
  if (preview) { setFilesState(preview.dataset.previewState); return; }

  const scope = event.target.closest('[data-scope]');
  if (scope) {
    all('[data-scope]').forEach(button => button.classList.toggle('active', button === scope));
    const labels = {
      alles: ['Alles', '4 approved locations · managed'],
      connected: ['Connected', '3 owner-approved locations · mixed access'],
      all: ['All locations', 'metadata search only · 7 approved locations'],
    };
    one('#scope-title').textContent = labels[scope.dataset.scope][0];
    one('#scope-meta').textContent = labels[scope.dataset.scope][1];
    status(`Files scope: ${labels[scope.dataset.scope][0]}`);
    return;
  }

  const choice = event.target.closest('[role="radio"]');
  if (choice) { selectExclusive(choice.closest('[role="radiogroup"]'), choice); return; }

  const check = event.target.closest('[role="checkbox"]');
  if (check) {
    const checked = check.getAttribute('aria-checked') === 'true';
    check.setAttribute('aria-checked', String(!checked));
    if (check.matches('[data-consent-check]')) {
      one('[data-consent-submit]').disabled = checked;
    }
    return;
  }

  const action = event.target.closest('[data-action]')?.dataset.action;
  if (!action) {
    if (event.target.closest('.file-row')) status(`opened ${event.target.closest('.file-row').querySelector('strong').textContent}`);
    return;
  }
  if (action === 'home') status('Home would open in the real application');
  else if (action === 'cancel-question') one('#question-status').textContent = 'run cancelled locally';
  else if (action === 'refresh-providers') status('provider health refreshed · fake data');
  else if (action === 'disconnect') { event.target.textContent = 'connect'; status('provider disconnected · fake data'); }
  else if (action === 'sync-bank') status('bank sync complete · 0 new transactions');
  else if (action === 'review-import') status('statement review opened · fake data');
  else if (action === 'run-preflight') status('preflights complete · activation remains blocked');
  else if (action === 'retry-docker') status('Docker remains unavailable · core Alles unaffected');
  else if (action === 'retry-files') setFilesState('ready');
});

document.addEventListener('keydown', event => {
  const tab = event.target.closest('[data-surface]');
  if (tab && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const tabs = all('[data-surface]');
    const index = tabs.indexOf(tab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    selectSurface(tabs[next].dataset.surface, { focus: true });
    return;
  }
  const choice = event.target.closest('[role="radio"]');
  if (choice && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
    event.preventDefault();
    const group = choice.closest('[role="radiogroup"]');
    const choices = [...group.querySelectorAll('[role="radio"]')];
    const direction = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
    const next = choices[(choices.indexOf(choice) + direction + choices.length) % choices.length];
    selectExclusive(group, next);
    next.focus();
    return;
  }
  const check = event.target.closest('[role="checkbox"]');
  if (check && (event.key === ' ' || event.key === 'Enter')) {
    event.preventDefault();
    check.click();
  }
});

all('.dialog-layer').forEach(dialog => {
  dialog.addEventListener('keydown', trapDialog);
  dialog.addEventListener('click', event => { if (event.target === dialog) closeDialog(dialog, 'dialog closed'); });
  dialog.querySelector('form')?.addEventListener('submit', event => {
    event.preventDefault();
    closeDialog(dialog, `${dialog.querySelector('h2')?.textContent || 'flow'} completed · fake data`);
  });
});

one('#question-form').addEventListener('submit', event => {
  event.preventDefault();
  const answers = all('#question-form [aria-checked="true"]').map(element => element.dataset.value || element.textContent.trim());
  one('#question-status').textContent = `answers saved locally: ${answers.join(', ')}`;
});

one('#nav-toggle').addEventListener('click', event => {
  const collapsed = document.body.dataset.navCollapsed !== 'true';
  document.body.dataset.navCollapsed = String(collapsed);
  event.currentTarget.setAttribute('aria-expanded', String(!collapsed));
  event.currentTarget.setAttribute('aria-label', `${collapsed ? 'show' : 'hide'} completion navigation`);
});

one('#theme-toggle').addEventListener('click', event => {
  const light = document.documentElement.dataset.theme !== 'light';
  document.documentElement.dataset.theme = light ? 'light' : 'dark';
  event.currentTarget.textContent = `appearance: ${light ? 'paper' : 'graphite'}`;
});

selectSurface('files');
