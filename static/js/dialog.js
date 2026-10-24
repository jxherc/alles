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
        <button class="btn" type="button" data-dialog-cancel>cancel</button>
        <button class="btn ${options.danger === false ? 'primary' : 'danger'}" type="button" data-dialog-confirm>${_esc(options.confirmLabel || 'confirm')}</button>
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
    const title = options.title || (secretCheck ? 'confirm it’s you' : '');
    const label = options.label || (secretCheck ? 'Alles password' : String(msg || '').replace(/\s*:\s*$/, ''));
    const hint = options.hint || (secretCheck ? String(msg || '').replace(/^enter your alles password to /i, 'needed to ') : '');
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
        <button class="btn" type="button" data-dialog-cancel>cancel</button>
        <button class="btn primary" type="button" data-dialog-confirm>${_esc(options.confirmLabel || (secretCheck ? 'continue' : 'save'))}</button>
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
        <button class="btn" type="button" data-dialog-cancel>cancel</button>
        <button class="btn primary" type="button" data-dialog-confirm>save</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const collect = () => Object.fromEntries(defs.map(f => [f.id, ov.querySelector(`#dialog-${sequence}-${CSS.escape(f.id)}`).value]));
    const validate = options.submit ? async value => {
      const error = ov.querySelector('.dialog-validation');
      const button = ov.querySelector('[data-dialog-confirm]');
      error.textContent = ''; button.textContent = 'saving…';
      try { await options.submit(value); return true; }
      catch (failure) { error.textContent = failure.message || 'could not confirm this save'; return false; }
      finally { button.textContent = 'save'; }
    } : () => true;
    _wireDialog(ov, resolve, collect, validate);
    ov.querySelector(`#dialog-${sequence}-${CSS.escape(defs[0].id)}`).focus();
  });
}

export function choose(title, options) {
  return new Promise(resolve => {
    const ov = _overlay();
    const titleId = `dialog-title-${++dialogSequence}`;
    ov.innerHTML = `<div class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
      <div class="dialog-msg" id="${titleId}">${_esc(title)}</div>
      <div class="dialog-choices">${options.map(option => `<button type="button" class="btn" data-dialog-confirm data-value="${_esc(option.value)}">${_esc(option.label)}</button>`).join('')}</div>
      <div class="dialog-btns"><button type="button" class="btn" data-dialog-cancel>cancel</button></div>
    </div>`;
    document.body.appendChild(ov);
    _wireDialog(ov, resolve, button => button.dataset.value);
    ov.querySelector('[data-dialog-cancel]').focus();
  });
}
