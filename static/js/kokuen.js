// KOKUEN v5 shared interaction runtime.
//
// Product modules keep their data and mutation authority. This module owns the
// reusable control contract: primitive identity, state exposure, busy repeat
// rejection, menu and tab keyboard models, and modal focus boundaries.

import { t } from './i18n.js';

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
let switchLabelId = 0;

const ICON_GLYPHS = Object.freeze({
  '×': 'close',
  '✕': 'close',
  '↑': 'chevron-up',
  '↓': 'chevron-down',
  '←': 'chevron-left',
  '→': 'chevron-right',
  '‹': 'chevron-left',
  '›': 'chevron-right',
});

function inferredIconName(element) {
  if (element.dataset.kokuenIcon) return element.dataset.kokuenIcon;
  if (!element.matches('button, a[href], [role="button"]')) return '';
  // Nested labels and logos belong to the product control, even while empty.
  // Only an explicit icon opt-in may replace that structure.
  if (element.childElementCount) return '';
  const glyph = (element.textContent || '').trim();
  let name = ICON_GLYPHS[glyph] || '';
  if (!name) return '';
  const semantics = [
    element.getAttribute('aria-label'),
    element.getAttribute('title'),
    element.className,
    element.dataset.act,
  ].filter(Boolean).join(' ').toLowerCase();
  if ((glyph === '×' || glyph === '✕') && /delete|remove|discard|trash|(?:^|[-_])del(?:$|[-_])/.test(semantics)) name = 'trash';
  if (glyph === '↑' && /send|save|submit/.test(semantics)) name = 'send';
  if (element.id === 'files-up-btn') name = 'chevron-up';
  return name;
}

function decorateIconControl(element) {
  const name = inferredIconName(element);
  if (!name) return;
  if (element.dataset.kokuenIcon !== name) element.dataset.kokuenIcon = name;
  if (!element.getAttribute('aria-label') && !element.getAttribute('aria-labelledby')) {
    // ‹ › page through months and years, so "previous" reads better than "back" there
    const pager = { '‹': t('common.previous'), '›': t('common.next') }[(element.textContent || '').trim()];
    const titleKey = element.dataset.i18nTitle ? t(element.dataset.i18nTitle) : '';
    // this runs before the language loads; the key lets the catalog pass relabel it
    if (titleKey) element.dataset.i18nAriaLabel = element.dataset.i18nTitle;
    const fallback = titleKey || element.getAttribute('title') || pager || {
      close: t('common.close'),
      trash: t('common.delete'),
      send: t('common.send'),
      'chevron-up': t('shell.move_up'),
      'chevron-down': t('shell.move_down'),
      'chevron-left': t('common.back'),
      'chevron-right': t('common.next'),
    }[name];
    if (fallback) element.setAttribute('aria-label', fallback);
  }
  if (element.dataset.kokuenIconReady === name && element.querySelector(':scope > svg.ic')) return;
  const makeIcon = globalThis.iconEl;
  if (typeof makeIcon !== 'function') return;
  element.replaceChildren(makeIcon(name));
  element.dataset.kokuenIconReady = name;
}

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

// 27.35, 27.51: no native title tooltips on controls (the browser's own box covers what's under it and
// can't be styled). a title that is a control's only name becomes its aria-label, then goes. a field's
// <label> is a name too: a title must never replace it (the shortcut fields lost "new aide task" to
// "press keys"), so on a named control the title stays as its description instead
function dropNativeTooltip(element) {
  const title = element.getAttribute('title');
  if (title == null) return;
  const text = title.trim();
  const label = [...(element.labels || [])].map(node => node.textContent.trim()).join(' ');
  const named = element.getAttribute('aria-label') || element.getAttribute('aria-labelledby') || label
    || (!element.matches('input, textarea') && (element.textContent || '').trim());
  if (!named && text) {
    element.setAttribute('aria-label', title);
    if (element.dataset.i18nTitle && !element.dataset.i18nAriaLabel) element.dataset.i18nAriaLabel = element.dataset.i18nTitle;
  } else if (text && text.toLowerCase() !== String(named).trim().toLowerCase()
    && !element.hasAttribute('aria-describedby')) {
    element.setAttribute('aria-description', text);
  }
  element.removeAttribute('title');
}

function decorateControl(element) {
  if (!(element instanceof HTMLElement)) return;
  decorateIconControl(element);
  if (element.matches(CONTROL_SELECTOR)) dropNativeTooltip(element);
  if (!element.dataset.kokuenPrimitive) element.dataset.kokuenPrimitive = primitiveFor(element);
  if (!element.dataset.kokuenState) element.dataset.kokuenState = 'resting';

  if (element.classList.contains('s-switch')) {
    if (!element.hasAttribute('role')) element.setAttribute('role', 'switch');
    if (!element.hasAttribute('aria-checked')) element.setAttribute('aria-checked', 'false');
    if (!element.hasAttribute('tabindex')) element.tabIndex = 0;
    if (!element.getAttribute('aria-label') && !element.getAttribute('aria-labelledby')) {
      const row = element.closest('.s-toggle-row');
      const label = row?.querySelector('.s-toggle-label');
      if (label) {
        if (!label.id) label.id = `${element.id || `kokuen-switch-${++switchLabelId}`}-label`;
        element.setAttribute('aria-labelledby', label.id);
      }
      const description = row?.querySelector('.s-toggle-desc');
      if (description && !element.hasAttribute('aria-describedby')) {
        if (!description.id) description.id = `${label?.id || `kokuen-switch-${++switchLabelId}`}-description`;
        element.setAttribute('aria-describedby', description.id);
      }
    }
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

// choice controls (decision 0050, the owner's card a): 2 or 3 options flipped often are a pill
// switch, a rating is a number row. both are radiogroups wired by wireChoiceGroup below.
function initPillSwitch(group) {
  if (group.dataset.kokuenChoiceReady === '1') return;
  for (const option of group.querySelectorAll(':scope > button')) {
    option.type = 'button';
    option.setAttribute('role', 'radio');
    if (!option.hasAttribute('aria-checked')) option.setAttribute('aria-checked', 'false');
  }
  wireChoiceGroup(group);
  // after wireChoiceGroup's own click handler, so aria-checked is already the new pick
  group.addEventListener('click', event => {
    const option = event.target.closest?.('[role="radio"]');
    if (!option || !group.contains(option)) return;
    const value = option.dataset.value ?? option.textContent.trim();
    group.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: { value } }));
  });
}

// <div data-kokuen-choice="rating" data-min="1" data-max="10" data-words="easy,,,,,,,,,max"
//   data-labels="easy,easy,easy,moderate,..." aria-label="effort">. the end words sit on the
// numbers' own grid, each centered under its number; the readout names the pick ("7, hard")
function initNumberRow(row) {
  if (row.dataset.kokuenChoiceReady === '1') return;
  const min = Number(row.dataset.min || 1);
  const max = Number(row.dataset.max || 5);
  const labels = (row.dataset.labels || '').split(',');
  const words = (row.dataset.words || '').split(',');
  const count = max - min + 1;
  const scale = document.createElement('div');
  scale.className = 'k-number-row-scale';
  scale.setAttribute('role', 'radiogroup');
  scale.setAttribute('aria-label', row.getAttribute('aria-label') || '');
  row.removeAttribute('aria-label');
  row.style.setProperty('--k-n', String(count));
  if (count > 5) row.dataset.wrap = 'true';
  for (let value = min; value <= max; value++) {
    const option = document.createElement('button');
    option.type = 'button';
    option.setAttribute('role', 'radio');
    option.setAttribute('aria-checked', String(String(value) === row.dataset.value));
    option.dataset.value = String(value);
    option.textContent = String(value);
    const label = labels[value - min];
    if (label) option.setAttribute('aria-label', `${value}, ${label}`);
    scale.append(option);
  }
  const ends = document.createElement('div');
  ends.className = 'k-number-row-words';
  ends.setAttribute('aria-hidden', 'true');
  words.forEach((word, index) => {
    if (!word) return;
    const span = document.createElement('span');
    span.textContent = word;
    span.style.gridColumn = String(index + 1);
    ends.append(span);
  });
  const readout = document.createElement('p');
  readout.className = 'k-number-row-readout';
  readout.setAttribute('aria-live', 'polite');
  row.replaceChildren(scale, ends, readout);
  const show = option => {
    if (!option) return;
    row.dataset.value = option.dataset.value;
    readout.textContent = option.getAttribute('aria-label') || option.dataset.value;
    row.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: { value: Number(option.dataset.value) } }));
  };
  scale.addEventListener('click', event => show(event.target.closest?.('[role="radio"]')));
  wireChoiceGroup(scale);
  row.dataset.kokuenChoiceReady = '1';
  const picked = scale.querySelector('[aria-checked="true"]');
  if (picked) readout.textContent = picked.getAttribute('aria-label') || picked.dataset.value;
}

function decorateRoot(root) {
  if (root instanceof HTMLElement && root.matches(CONTROL_SELECTOR)) decorateControl(root);
  root.querySelectorAll?.(CONTROL_SELECTOR).forEach(decorateControl);
  root.querySelectorAll?.('[data-kokuen-choice="switch"]').forEach(initPillSwitch);
  root.querySelectorAll?.('[data-kokuen-choice="rating"]').forEach(initNumberRow);
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
      if (record.target instanceof HTMLElement && record.target.matches(CONTROL_SELECTOR)) {
        decorateControl(record.target);
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
    attributeFilter: ['disabled', 'aria-disabled', 'aria-busy', 'aria-invalid', 'aria-checked', 'aria-selected', 'aria-pressed', 'data-kokuen-icon', 'title'],
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


export function beginBusy(element, label = t('shell.working')) {
  if (!element || element.getAttribute('aria-busy') === 'true') return null;
  const snapshot = {
    disabled: 'disabled' in element ? element.disabled : false,
    ariaDisabled: element.getAttribute('aria-disabled'),
    text: element.textContent,
    icon: element.dataset.kokuenIcon || '',
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
    if (snapshot.icon) {
      element.dataset.kokuenIcon = snapshot.icon;
      delete element.dataset.kokuenIconReady;
      decorateIconControl(element);
    } else element.textContent = text;
    setControlState(element, state);
  };
}

export function createFocusBoundary(dialog, { trigger = null, onEscape = null } = {}) {
  let returnFocus = trigger;
  let active = false;

  const focusable = () => [...dialog.querySelectorAll(FOCUSABLE_SELECTOR)]
    .filter(element => visible(element) && !element.closest('[hidden], [inert]'));

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


// keep an open menu on screen from the top: flip it above its anchor when that side has more
// room, and scroll inside it when neither side fits all the rows (a short window, big zoom)
function fitMenuHeight(menu) {
  menu.style.maxHeight = '';
  menu.style.overflowY = '';
  if (menu.dataset.fitFlip) {
    menu.style.top = menu.dataset.fitTop;
    menu.style.bottom = menu.dataset.fitBottom;
    delete menu.dataset.fitFlip;
  }
  const edge = 8;
  const rect = menu.getBoundingClientRect();
  const below = window.innerHeight - edge - rect.top;
  const full = menu.scrollHeight + (menu.offsetHeight - menu.clientHeight);
  if (full <= below) return;
  let room = below;
  const anchor = getComputedStyle(menu).position === 'absolute' ? menu.offsetParent : null;
  if (anchor && !menu.style.top) {
    const above = anchor.getBoundingClientRect().top - edge;
    if (above > below) {
      menu.dataset.fitFlip = '1';
      menu.dataset.fitTop = menu.style.top;
      menu.dataset.fitBottom = menu.style.bottom;
      menu.style.top = 'auto';
      menu.style.bottom = '100%';
      room = above;
    }
  }
  if (full > room) {
    menu.style.maxHeight = `${Math.max(room, 88)}px`;
    menu.style.overflowY = 'auto';
  }
}

export function createMenuController(menu, { onClose = null, closeOnOutsidePointer = true } = {}) {
  if (!menu) return null;
  let returnFocus = null;
  let outsideListening = false;
  const items = () => [...menu.querySelectorAll('[role^="menuitem"]')]
    .filter(element => visible(element) && !element.disabled && element.getAttribute('aria-disabled') !== 'true');
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
    fitMenuHeight(menu);
    if (focus) items()[0]?.focus();
    if (closeOnOutsidePointer) {
      outsideListening = true;
      document.addEventListener('pointerdown', onOutsidePointer, true);
    }
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


// a "more" button and its menu: opens on click or arrow down, closes on Escape, Tab, outside
// clicks or after an item runs, and nudges itself back inside the window
export function wireActionMenu(trigger, menu, { beforeOpen = null, closeOutside = true } = {}) {
  if (!trigger || !menu) return null;
  const outside = event => {
    if (!menu.contains(event.target) && !trigger.contains(event.target)) controller.close({ restoreFocus: false });
  };
  const controller = createMenuController(menu, {
    closeOnOutsidePointer: false,
    onClose: () => {
      trigger.setAttribute('aria-expanded', 'false');
      document.removeEventListener('pointerdown', outside, true);
    },
  });
  const open = () => {
    for (const item of menu.querySelectorAll('[role="menuitem"]')) item.setAttribute('aria-disabled', String(!!item.disabled));
    beforeOpen?.();
    trigger.setAttribute('aria-expanded', 'true');
    menu.style.transform = '';
    controller.open({ source: trigger });
    if (closeOutside) document.addEventListener('pointerdown', outside, true);
    const bounds = menu.getBoundingClientRect();
    const shift = Math.max(0, -bounds.left) + Math.min(0, window.innerWidth - bounds.right);
    menu.style.transform = `translateX(${shift}px)`;
  };
  trigger.addEventListener('click', () => {
    if (menu.hidden) open();
    else controller.close();
  });
  trigger.addEventListener('keydown', event => {
    if (event.key !== 'ArrowDown') return;
    event.preventDefault(); event.stopPropagation(); open();
  });
  // close before the item's own handler opens a dialog or a panel
  menu.addEventListener('click', event => {
    const item = event.target.closest('[role="menuitem"]');
    if (!item || item.disabled || item.getAttribute('aria-disabled') === 'true') return;
    controller.close();
  }, true);
  // a resize moves the trigger, so an open menu would hang where it was: close it, focus stays put
  window.addEventListener('resize', () => { if (!menu.hidden) controller.close(); });
  menu.addEventListener('keydown', event => {
    if (event.key === 'Tab') { controller.close(); return; }
    event.stopPropagation();
    if (['Enter', ' '].includes(event.key)) {
      event.preventDefault();
      const item = event.target.closest('[role="menuitem"]');
      if (item && !item.disabled && item.getAttribute('aria-disabled') !== 'true') item.click();
    }
  });
  return controller;
}

export function wireChoiceGroup(group, { activate = choice => choice.click() } = {}) {
  if (!group || group.dataset.kokuenChoiceReady === '1') return null;
  group.dataset.kokuenChoiceReady = '1';
  if (!group.hasAttribute('role')) group.setAttribute('role', 'radiogroup');

  const choices = () => [...group.querySelectorAll('[role="radio"]')]
    .filter(choice => visible(choice) && choice.getAttribute('aria-disabled') !== 'true' && !choice.disabled);
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
