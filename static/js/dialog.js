import { t } from './i18n.js';

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _overlay() {
  const el = document.createElement('div');
  el.className = 'dialog-overlay';
  return el;
}

let dialogSequence = 0;

// safari doesn't focus a clicked or tapped button, so a dialog opened from one saw <body> as the
// focus to give back. remember the last control pressed and return there instead
let _pressed = null;
globalThis.document?.addEventListener?.('pointerdown', event => {
  _pressed = event.target?.closest?.('button, a[href], input, textarea, [tabindex]') || null;
}, true);

function _wireDialog(overlay, resolve, valueFromConfirm, canSubmit = () => true) {
  const active = document.activeElement;
  const previousFocus = active && active !== document.body ? active : (_pressed?.isConnected ? _pressed : active);
  const card = overlay.querySelector('[role="dialog"], [role="alertdialog"]');
  let busy = false, closed = false;
  const focusable = () => [...overlay.querySelectorAll('button, input, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(element => !element.disabled && !element.hidden);
  const done = value => {
    if (closed) return;
    closed = true;
    overlay.remove();
    previousFocus?.focus?.();
    resolve(value);
  };
  overlay.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      if (!busy) done(null);
      return;
    }
    if (event.key !== 'Tab') return;
    // move focus ourselves every time: safari's plain tab skips buttons, so from "cancel" it left
    // the dialog for the page behind it (and escape stopped working there)
    event.preventDefault();
    const items = focusable();
    if (!items.length) return;
    const at = items.indexOf(document.activeElement);
    const step = event.shiftKey ? -1 : 1;
    const next = at < 0 ? (event.shiftKey ? items.length - 1 : 0) : (at + step + items.length) % items.length;
    items[next].focus();
  });
  overlay.addEventListener('pointerdown', event => {
    if (event.target === overlay && busy) event.preventDefault();
  });
  overlay.addEventListener('click', event => {
    if (event.target !== overlay) return;
    if (busy) card.focus();
    else done(null);
  });
  const submit = async button => {
    if (busy || closed) return;
    const value = valueFromConfirm(button);
    const accepted = canSubmit(value);
    if (!accepted || typeof accepted.then !== 'function') {
      if (accepted) done(value);
      return;
    }
    const focused = document.activeElement;
    const controls = [...overlay.querySelectorAll('button, input, textarea')].map(element => [element, element.disabled]);
    busy = true;
    card.setAttribute('aria-busy', 'true');
    controls.forEach(([element]) => { element.disabled = true; });
    card.tabIndex = -1; card.focus();
    try { if (await accepted) done(value); }
    finally {
      busy = false; card.removeAttribute('aria-busy');
      controls.forEach(([element, disabled]) => { element.disabled = disabled; });
      if (!closed) focused?.focus?.();
    }
  };
  overlay.querySelectorAll('[data-dialog-confirm]').forEach(button => button.addEventListener('click', () => submit(button)));
  overlay.querySelector('[data-dialog-cancel]').addEventListener('click', () => { if (!busy) done(null); });
  return submit;
}

export function confirm(msg, options = {}) {
  return new Promise(resolve => {
    const ov = _overlay();
    const labelId = `dialog-title-${++dialogSequence}`;
    ov.innerHTML = `<div class="dialog-card" role="alertdialog" aria-modal="true" aria-labelledby="${labelId}">
      <div class="dialog-msg" id="${labelId}">${_esc(msg)}</div>
      <div class="dialog-btns">
        <button class="btn" type="button" data-dialog-cancel>${t('common.cancel')}</button>
        <button class="btn ${options.danger === false ? 'primary' : 'danger'}" type="button" data-dialog-confirm>${_esc(options.confirmLabel || t('common.confirm'))}</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    _wireDialog(ov, value => resolve(Boolean(value)), () => true);
    ov.querySelector('[data-dialog-cancel]').focus();
  });
}

// a small form in a dialog: a title, a labeled field, an optional hint, and a button that says
// what it does. callers pass { title, label, hint, confirmLabel }; an older call with only a
// question still works (the question becomes the label). a password check titles itself
export function prompt(msg, def = '', options = {}) {
  return new Promise(resolve => {
    const ov = _overlay();
    const inputId = `dialog-input-${++dialogSequence}`;
    const errorId = `${inputId}-error`;
    const hintId = `${inputId}-hint`;
    const secretCheck = options.secret && !options.label;
    const title = options.title || (secretCheck ? t('shell.confirm_its_you') : '');
    const label = options.label || (secretCheck ? t('shell.alles_password') : String(msg || '').replace(/\s*:\s*$/, ''));
    const hint = options.hint || (secretCheck ? String(msg || '').replace(/^enter your alles password to (.*)$/is, (_, rest) => t('shell.needed_to', { rest })) : '');
    const describedBy = [hint ? hintId : '', options.validate ? errorId : ''].filter(Boolean).join(' ');
    ov.innerHTML = `<div class="dialog-card dialog-form${options.validate ? ' dialog-validated' : ''}" role="dialog" aria-modal="true" aria-labelledby="${title ? `${inputId}-title` : `${inputId}-label`}">
      ${title ? `<h2 class="dialog-title" id="${inputId}-title">${_esc(title)}</h2>` : ''}
      <label class="dialog-label" id="${inputId}-label" for="${inputId}">${_esc(label)}</label>
      <input class="settings-input dialog-input" id="${inputId}" value="${_esc(String(def || ''))}"
        type="${options.secret ? 'password' : 'text'}"
        autocomplete="${options.secret ? 'current-password' : 'off'}"${describedBy ? ` aria-describedby="${describedBy}"` : ''}>
      ${hint ? `<p class="dialog-hint" id="${hintId}">${_esc(hint)}</p>` : ''}
      ${options.validate ? `<div class="dialog-validation" id="${errorId}" role="alert"></div>` : ''}
      <div class="dialog-btns">
        <button class="btn" type="button" data-dialog-cancel>${t('common.cancel')}</button>
        <button class="btn primary" type="button" data-dialog-confirm>${_esc(options.confirmLabel || (secretCheck ? t('common.continue') : t('common.save')))}</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const inp = ov.querySelector(`#${inputId}`);
    const error = ov.querySelector(`#${errorId}`);
    const validate = value => {
      const message = options.validate?.(value) || '';
      if (error) error.textContent = message;
      if (message) {
        inp.setAttribute('aria-invalid', 'true');
        inp.focus();
        return false;
      }
      inp.removeAttribute('aria-invalid');
      return true;
    };
    const submit = _wireDialog(ov, resolve, () => inp.value, validate);
    inp.addEventListener('input', () => {
      if (error) error.textContent = '';
      inp.removeAttribute('aria-invalid');
    });
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submit();
      }
    });
    inp.focus(); inp.select();
  });
}

// Optional submit keeps the form open until its save is confirmed.
export function fields(title, defs, options = {}) {
  return new Promise(resolve => {
    const ov = _overlay();
    const sequence = ++dialogSequence;
    const inputs = defs.map(f => {
      const id = `dialog-${sequence}-${_esc(f.id)}`;
      const value = _esc(String(f.value ?? ''));
      return `<label class="dialog-msg" for="${id}">${_esc(f.label)}</label>` + (f.multiline
        ? `<textarea class="settings-input dialog-input" id="${id}" rows="5">${value}</textarea>`
        : `<input class="settings-input dialog-input" id="${id}" value="${value}">`);
    }).join('');
    const titleId = `dialog-title-${sequence}`;
    ov.innerHTML = `<div class="dialog-card${options.submit ? ' dialog-validated' : ''}" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
      <div class="dialog-msg" id="${titleId}">${_esc(title)}</div>
      ${inputs}
      ${options.submit ? '<div class="dialog-validation" role="alert"></div>' : ''}
      <div class="dialog-btns">
        <button class="btn" type="button" data-dialog-cancel>${t('common.cancel')}</button>
        <button class="btn primary" type="button" data-dialog-confirm>${t('common.save')}</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const collect = () => Object.fromEntries(defs.map(f => [f.id, ov.querySelector(`#dialog-${sequence}-${CSS.escape(f.id)}`).value]));
    const validate = options.submit ? async value => {
      const error = ov.querySelector('.dialog-validation');
      const button = ov.querySelector('[data-dialog-confirm]');
      error.textContent = ''; button.textContent = t('common.saving');
      try { await options.submit(value); return true; }
      catch (failure) { error.textContent = failure.message || t('shell.could_not_confirm_save'); return false; }
      finally { button.textContent = t('common.save'); }
    } : () => true;
    _wireDialog(ov, resolve, collect, validate);
    ov.querySelector(`#dialog-${sequence}-${CSS.escape(defs[0].id)}`).focus();
  });
}

// a dialog around the caller's own fields. collect(card) reads them; submit(value) saves and
// throws to keep the dialog open with its message. `remove` ({ label }) adds a quiet button on
// the left that resolves { remove: true }. wire(card) runs once the markup is in the page
export function form(title, html, { confirmLabel = '', collect, submit, remove = null, wire = null, className = '' } = {}) {
  return new Promise(resolve => {
    const ov = _overlay();
    const titleId = `dialog-title-${++dialogSequence}`;
    ov.innerHTML = `<div class="dialog-card dialog-form dialog-validated${className ? ` ${_esc(className)}` : ''}" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
      <h2 class="dialog-title" id="${titleId}">${_esc(title)}</h2>
      <div class="dialog-form-body">${html}</div>
      <div class="dialog-validation" role="alert"></div>
      <div class="dialog-btns">
        ${remove ? `<button class="btn dialog-remove" type="button" data-dialog-confirm data-dialog-remove>${_esc(remove.label)}</button>` : ''}
        <button class="btn" type="button" data-dialog-cancel>${t('common.cancel')}</button>
        <button class="btn primary" type="button" data-dialog-confirm>${_esc(confirmLabel || t('common.save'))}</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const card = ov.querySelector('.dialog-card');
    const error = ov.querySelector('.dialog-validation');
    const save = ov.querySelector('[data-dialog-confirm]:not([data-dialog-remove])');
    const run = async value => {
      error.textContent = '';
      if (value?.remove || !submit) return true;
      save.textContent = t('common.saving');
      try { await submit(value); return true; }
      catch (failure) { error.textContent = failure.message || t('shell.could_not_confirm_save'); return false; }
      finally { save.textContent = confirmLabel || t('common.save'); }
    };
    const valueOf = button => {
      if (button.hasAttribute('data-dialog-remove')) return { remove: true };
      try { return collect ? collect(card) : null; }
      catch (failure) { error.textContent = failure.message; return { invalid: true }; }
    };
    const submitButton = _wireDialog(ov, resolve, valueOf, value => (value?.invalid ? false : run(value)));
    card.addEventListener('keydown', event => {
      // enter in a one-line field saves, like a form would
      if (event.key !== 'Enter' || event.defaultPrevented || !event.target.matches('input')) return;
      event.preventDefault();
      submitButton(save);
    });
    wire?.(card);
    (card.querySelector('.dialog-form-body input:not([disabled]), .dialog-form-body button:not([disabled])') || save).focus();
  });
}

export function choose(title, options) {
  return new Promise(resolve => {
    const ov = _overlay();
    const titleId = `dialog-title-${++dialogSequence}`;
    ov.innerHTML = `<div class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
      <div class="dialog-msg" id="${titleId}">${_esc(title)}</div>
      <div class="dialog-choices">${options.map(option => `<button type="button" class="btn" data-dialog-confirm data-value="${_esc(option.value)}">${_esc(option.label)}</button>`).join('')}</div>
      <div class="dialog-btns"><button type="button" class="btn" data-dialog-cancel>${t('common.cancel')}</button></div>
    </div>`;
    document.body.appendChild(ov);
    _wireDialog(ov, resolve, button => button.dataset.value);
    ov.querySelector('[data-dialog-cancel]').focus();
  });
}

// a long list (regions, currencies): type to filter, arrows to move, enter to pick. options are
// { value, label, hint?, icon?, group?, words? }: icon is an emoji shown before the label, group a
// heading the option sits under while nothing is typed, words extra search terms. `action`
// ({ label }) adds a button beside cancel that resolves { action: true, query } instead of a value.
// the current value starts selected and in view
export function pick(title, options, { value = '', placeholder = '', action = null } = {}) {
  return new Promise(resolve => {
    const ov = _overlay();
    const titleId = `dialog-title-${++dialogSequence}`;
    const listId = `dialog-list-${dialogSequence}`;
    ov.innerHTML = `<div class="dialog-card dialog-pick" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
      <div class="dialog-msg" id="${titleId}">${_esc(title)}</div>
      <input class="settings-input dialog-pick-search" type="search" autocomplete="off" spellcheck="false" role="combobox" aria-expanded="true" aria-controls="${listId}" aria-autocomplete="list" placeholder="${_esc(placeholder || t('common.search'))}">
      <div class="dialog-pick-list" id="${listId}" role="listbox" aria-labelledby="${titleId}"></div>
      <p class="dialog-pick-empty" role="status" hidden>${_esc(t('common.no_results'))}</p>
      <div class="dialog-btns">${action ? `<button type="button" class="btn dialog-pick-action" data-dialog-confirm data-pick-action>${_esc(action.label)}</button>` : ''}<button type="button" class="btn" data-dialog-cancel>${t('common.cancel')}</button></div>
    </div>`;
    document.body.appendChild(ov);
    const search = ov.querySelector('.dialog-pick-search'), list = ov.querySelector('.dialog-pick-list');
    const empty = ov.querySelector('.dialog-pick-empty');
    let shown = [], active = 0;
    const submit = _wireDialog(ov, resolve, button => button.hasAttribute('data-pick-action')
      ? { action: true, query: search.value.trim() } : button.dataset.value);
    const optionHtml = (option, index) => `<button type="button" class="dialog-pick-option" role="option" id="${listId}-${index}" tabindex="-1" data-dialog-confirm data-value="${_esc(option.value)}" aria-selected="${option.value === value}"><span>${option.icon ? `<span class="dialog-pick-icon" aria-hidden="true">${_esc(option.icon)}</span>` : ''}${_esc(option.label)}</span>${option.hint ? `<small>${_esc(option.hint)}</small>` : ''}</button>`;
    const paint = () => {
      const query = search.value.trim().toLowerCase();
      shown = options.filter(option => !query || `${option.label} ${option.value} ${option.hint || ''} ${option.words || ''}`.toLowerCase().includes(query));
      // a label that starts with what was typed comes first, so "c" lands on canada
      if (query) shown.sort((a, b) => Number(!a.label.toLowerCase().startsWith(query)) - Number(!b.label.toLowerCase().startsWith(query)));
      // headings only while browsing: a search ranks across groups
      const grouped = !query && shown.some(option => option.group);
      list.innerHTML = grouped
        ? [...new Set(shown.map(option => option.group || ''))].map((group, at) => `<div class="dialog-pick-group" role="group" aria-labelledby="${listId}-g${at}"><div class="dialog-pick-heading" id="${listId}-g${at}" role="presentation">${_esc(group)}</div>${shown.map((option, index) => (option.group || '') === group ? optionHtml(option, index) : '').join('')}</div>`).join('')
        : shown.map(optionHtml).join('');
      list.querySelectorAll('[data-dialog-confirm]').forEach(button => button.addEventListener('click', () => submit(button)));
      empty.hidden = shown.length > 0;
      move(query ? 0 : Math.max(0, shown.findIndex(option => option.value === value)));
    };
    const move = index => {
      active = Math.min(Math.max(index, 0), shown.length - 1);
      list.querySelectorAll('[role="option"]').forEach((node, at) => node.toggleAttribute('data-active', at === active));
      const node = list.querySelector(`#${CSS.escape(`${listId}-${active}`)}`);
      if (node) { search.setAttribute('aria-activedescendant', node.id); node.scrollIntoView({ block: 'nearest' }); }
      else search.removeAttribute('aria-activedescendant');
    };
    search.addEventListener('input', paint);
    search.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        move(active + (event.key === 'ArrowDown' ? 1 : -1));
      } else if (event.key === 'Enter') {
        event.preventDefault();
        const node = list.querySelector(`#${CSS.escape(`${listId}-${active}`)}`);
        if (node) submit(node);
      }
    });
    paint();
    search.focus();
  });
}
