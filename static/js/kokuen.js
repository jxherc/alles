// KOKUEN v5 shared interaction runtime.
//
// Product modules keep their data and mutation authority. This module owns the
// reusable control contract: primitive identity, state exposure, busy repeat
// rejection, menu and tab keyboard models, and modal focus boundaries.

export const KOKUEN_STATES = Object.freeze([
  'resting',
  'hover',
  'pressed',
  'selected',
  'disabled',
  'busy',
  'invalid',
  'loading',
  'empty',
  'permission',
  'offline',
  'stale',
  'partial',
  'error',
]);

const CONTROL_SELECTOR = [
  'button',
  'a[href]',
  'input:not([type="hidden"]):not([type="file"])',
  'textarea',
  '.custom-select',
  '.s-switch',
  '[role="button"]',
  '[role="checkbox"]',
  '[role="combobox"]',
  '[role="menuitem"]',
  '[role="menuitemcheckbox"]',
  '[role="menuitemradio"]',
  '[role="option"]',
  '[role="radio"]',
  '[role="switch"]',
  '[role="tab"]',
].join(',');

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'textarea:not([disabled])',
  '[role="button"]:not([aria-disabled="true"])',
  '[role="combobox"]:not([aria-disabled="true"])',
  '[role="menuitem"]:not([aria-disabled="true"])',
  '[role="menuitemcheckbox"]:not([aria-disabled="true"])',
  '[role="menuitemradio"]:not([aria-disabled="true"])',
  '[role="radio"]:not([aria-disabled="true"])',
  '[role="switch"]:not([aria-disabled="true"])',
  '[role="tab"]:not([aria-disabled="true"])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

let observer = null;
let initialized = false;

function visible(element) {
  return !element.hidden && element.getAttribute('aria-hidden') !== 'true';
}

function primitiveFor(element) {
  if (element.matches('[role="switch"], .s-switch')) return 'switch';
  if (element.matches('.custom-select, [role="combobox"]')) return 'select';
  if (element.matches('[role="tab"]')) return 'tab';
  if (element.matches('[role^="menuitem"]')) return 'menu-item';
  if (element.matches('[role="option"]')) return 'option';
  if (element.matches('[role="checkbox"], [role="radio"]')) return 'choice';
  if (element.matches('textarea')) return 'textarea';
  if (element.matches('input')) return 'field';
  if (element.matches('[role="button"]')) return 'action';
  if (element.matches('.icon-btn, [aria-label]:not([aria-label=""])')) return 'icon-action';
  if (element.matches('a[href]')) return 'link';
  return 'action';
}

function decorateControl(element) {
  if (!(element instanceof HTMLElement)) return;
  if (!element.dataset.kokuenPrimitive) element.dataset.kokuenPrimitive = primitiveFor(element);
  if (!element.dataset.kokuenState) element.dataset.kokuenState = 'resting';

  if (element.classList.contains('s-switch')) {
    if (!element.hasAttribute('role')) element.setAttribute('role', 'switch');
    if (!element.hasAttribute('aria-checked')) element.setAttribute('aria-checked', 'false');
    if (!element.hasAttribute('tabindex')) element.tabIndex = 0;
  }

  syncControlState(element);
}

function syncControlState(element) {
  const current = element.dataset.kokuenState || 'resting';
  let reflected = '';
  /* A pending mutation is still busy when the native button is disabled to
     reject repeat activation. Busy is the useful owner-facing state. */
  if (element.getAttribute('aria-busy') === 'true') reflected = current === 'loading' ? 'loading' : 'busy';
  else if (element.matches('[aria-disabled="true"]') || element.matches(':disabled')) reflected = 'disabled';
  else if (element.getAttribute('aria-invalid') === 'true') reflected = 'invalid';
  else if (['error', 'offline', 'stale', 'partial', 'permission', 'empty'].includes(current)) reflected = current;
  else if (
    element.getAttribute('aria-checked') === 'true'
    || element.getAttribute('aria-selected') === 'true'
    || element.getAttribute('aria-pressed') === 'true'
  ) reflected = 'selected';
  if (reflected) element.dataset.kokuenState = reflected;
  else if (['disabled', 'busy', 'invalid', 'selected'].includes(current)) element.dataset.kokuenState = 'resting';
}

function decorateRoot(root) {
  if (root instanceof HTMLElement && root.matches(CONTROL_SELECTOR)) decorateControl(root);
  root.querySelectorAll?.(CONTROL_SELECTOR).forEach(decorateControl);
  root.querySelectorAll?.('[data-kokuen-surface]').forEach(surface => {
    surface.dataset.kokuenVersion = '5';
    if (!surface.dataset.state) surface.dataset.state = 'resting';
  });
}

function handleSyntheticControlKey(event) {
  const control = event.target.closest?.('.s-switch');
  if (!control || control.matches('button, input') || control.getAttribute('aria-disabled') === 'true') return;
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  control.click();
}

export function initKokuenPrimitives(root = document) {
  document.documentElement.dataset.kokuenVersion = '5';
  decorateRoot(root);
  if (initialized) return;
  initialized = true;
  document.addEventListener('keydown', handleSyntheticControlKey);
  observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'attributes') {
        decorateControl(record.target);
        continue;
      }
      for (const node of record.addedNodes) {
        if (node instanceof HTMLElement) decorateRoot(node);
      }
    }
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['disabled', 'aria-disabled', 'aria-busy', 'aria-invalid', 'aria-checked', 'aria-selected', 'aria-pressed'],
  });
}

export function setControlState(element, state, { message = '' } = {}) {
  if (!element || !KOKUEN_STATES.includes(state)) return false;
  decorateControl(element);
  element.dataset.kokuenState = state;
  element.toggleAttribute('aria-busy', state === 'busy' || state === 'loading');
  if (state === 'invalid') element.setAttribute('aria-invalid', 'true');
  else element.removeAttribute('aria-invalid');
  if (message) element.dataset.kokuenStateMessage = message;
  else delete element.dataset.kokuenStateMessage;
  return true;
}

export function setSurfaceState(surface, state, { message = '' } = {}) {
  if (!surface || !KOKUEN_STATES.includes(state)) return false;
  surface.dataset.state = state;
  surface.setAttribute('aria-busy', String(state === 'busy' || state === 'loading'));
  if (message) surface.dataset.stateMessage = message;
  else delete surface.dataset.stateMessage;
  return true;
}

export function beginBusy(element, label = 'working') {
  if (!element || element.getAttribute('aria-busy') === 'true') return null;
  const snapshot = {
    disabled: 'disabled' in element ? element.disabled : false,
    ariaDisabled: element.getAttribute('aria-disabled'),
    text: element.textContent,
  };
  if ('disabled' in element) element.disabled = true;
  element.setAttribute('aria-disabled', 'true');
  setControlState(element, 'busy', { message: label });
  if (label && !element.querySelector('svg, img')) element.textContent = label;
  return ({ state = 'resting', text = snapshot.text } = {}) => {
    if ('disabled' in element) element.disabled = snapshot.disabled;
    if (snapshot.ariaDisabled == null) element.removeAttribute('aria-disabled');
    else element.setAttribute('aria-disabled', snapshot.ariaDisabled);
    element.removeAttribute('aria-busy');
    element.textContent = text;
    setControlState(element, state);
  };
}

export function createFocusBoundary(dialog, { trigger = null, onEscape = null } = {}) {
  let returnFocus = trigger;
  let active = false;

  const focusable = () => [...dialog.querySelectorAll(FOCUSABLE_SELECTOR)]
    .filter(element => visible(element) && !element.closest('[hidden]'));

  const onKeydown = event => {
    if (!active) return;
    if (event.key === 'Escape' && onEscape) {
      event.preventDefault();
      event.stopPropagation();
      onEscape();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusable();
    if (!items.length) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  dialog.addEventListener('keydown', onKeydown);

  return {
    activate({ focus = null, source = null } = {}) {
      returnFocus = source || trigger || document.activeElement;
      active = true;
      dialog.setAttribute('aria-modal', 'true');
      const target = focus || focusable()[0] || dialog;
      if (!target.hasAttribute('tabindex') && target === dialog) target.tabIndex = -1;
      target.focus();
    },
    deactivate({ restoreFocus = true } = {}) {
      active = false;
      if (restoreFocus && returnFocus?.isConnected) returnFocus.focus();
      returnFocus = trigger;
    },
    destroy() {
      active = false;
      dialog.removeEventListener('keydown', onKeydown);
    },
  };
}

export function wireMenu(trigger, menu, { onClose = null } = {}) {
  if (!trigger || !menu) return null;
  const items = () => [...menu.querySelectorAll('[role^="menuitem"]')]
    .filter(element => visible(element) && element.getAttribute('aria-disabled') !== 'true');
  const close = ({ restoreFocus = true } = {}) => {
    menu.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    onClose?.();
    if (restoreFocus) trigger.focus();
  };
  const open = () => {
    menu.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    items()[0]?.focus();
  };
  trigger.addEventListener('click', event => {
    event.stopPropagation();
    if (menu.hidden) open();
    else close();
  });
  menu.addEventListener('keydown', event => {
    const options = items();
    const index = options.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    } else if (options.length && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0
        : event.key === 'End' ? options.length - 1
          : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
      options[next].focus();
    }
  });
  return { open, close };
}

export function createMenuController(menu, { onClose = null } = {}) {
  if (!menu) return null;
  let returnFocus = null;
  let outsideListening = false;
  const items = () => [...menu.querySelectorAll('[role^="menuitem"]')]
    .filter(element => visible(element) && element.getAttribute('aria-disabled') !== 'true');
  const stopOutsideListening = () => {
    if (!outsideListening) return;
    outsideListening = false;
    document.removeEventListener('pointerdown', onOutsidePointer, true);
  };
  const close = ({ restoreFocus = true } = {}) => {
    stopOutsideListening();
    menu.hidden = true;
    menu.style.display = 'none';
    onClose?.();
    if (restoreFocus && returnFocus?.isConnected) returnFocus.focus();
  };
  const onOutsidePointer = event => {
    if (!menu.contains(event.target)) close();
  };
  const open = ({ source = null, focus = true } = {}) => {
    stopOutsideListening();
    returnFocus = source || document.activeElement;
    menu.hidden = false;
    menu.style.display = 'block';
    if (focus) items()[0]?.focus();
    outsideListening = true;
    document.addEventListener('pointerdown', onOutsidePointer, true);
  };
  const onKeydown = event => {
    const options = items();
    const index = options.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    } else if (options.length && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0
        : event.key === 'End' ? options.length - 1
          : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
      options[next].focus();
    }
  };
  menu.addEventListener('keydown', onKeydown);
  return {
    open,
    close,
    destroy() {
      stopOutsideListening();
      menu.removeEventListener('keydown', onKeydown);
    },
  };
}

export function wireTabs(tablist, { activate = tab => tab.click() } = {}) {
  if (!tablist || tablist.dataset.kokuenTabsReady === '1') return null;
  tablist.dataset.kokuenTabsReady = '1';
  const tabs = () => [...tablist.querySelectorAll('[role="tab"]')]
    .filter(tab => tab.getAttribute('aria-disabled') !== 'true');
  const sync = selected => {
    for (const tab of tabs()) tab.tabIndex = tab === selected ? 0 : -1;
  };
  tablist.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    const options = tabs();
    const index = options.indexOf(event.target.closest('[role="tab"]'));
    if (index < 0 || !options.length) return;
    event.preventDefault();
    const backwards = event.key === 'ArrowLeft' || event.key === 'ArrowUp';
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? options.length - 1
        : (index + (backwards ? -1 : 1) + options.length) % options.length;
    sync(options[next]);
    options[next].focus();
    activate(options[next]);
  });
  const selected = tabs().find(tab => tab.getAttribute('aria-selected') === 'true') || tabs()[0];
  if (selected) sync(selected);
  return { sync };
}

export function wireChoiceGroup(group, { activate = choice => choice.click() } = {}) {
  if (!group || group.dataset.kokuenChoiceReady === '1') return null;
  group.dataset.kokuenChoiceReady = '1';
  if (!group.hasAttribute('role')) group.setAttribute('role', 'radiogroup');

  const choices = () => [...group.querySelectorAll('[role="radio"]')]
    .filter(choice => choice.getAttribute('aria-disabled') !== 'true' && !choice.disabled);
  const sync = selected => {
    for (const choice of choices()) {
      const active = choice === selected;
      choice.setAttribute('aria-checked', String(active));
      choice.tabIndex = active ? 0 : -1;
      setControlState(choice, active ? 'selected' : 'resting');
    }
  };

  group.addEventListener('click', event => {
    const choice = event.target.closest?.('[role="radio"]');
    if (choice && group.contains(choice)) sync(choice);
  });
  group.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    const options = choices();
    const current = event.target.closest?.('[role="radio"]');
    const index = options.indexOf(current);
    if (index < 0 || !options.length) return;
    event.preventDefault();
    const backwards = event.key === 'ArrowLeft' || event.key === 'ArrowUp';
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? options.length - 1
        : (index + (backwards ? -1 : 1) + options.length) % options.length;
    options[next].focus();
    activate(options[next]);
  });

  const selected = choices().find(choice => choice.getAttribute('aria-checked') === 'true');
  if (selected) sync(selected);
  else if (choices()[0]) choices()[0].tabIndex = 0;
  return { sync };
}
