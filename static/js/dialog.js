function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _overlay() {
  const el = document.createElement('div');
  el.className = 'dialog-overlay';
  return el;
}

let dialogSequence = 0;

function _wireDialog(overlay, resolve, valueFromConfirm) {
  const previousFocus = document.activeElement;
  const focusable = () => [...overlay.querySelectorAll('button, input, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(element => !element.disabled && !element.hidden);
  const done = value => {
    overlay.remove();
    previousFocus?.focus?.();
    resolve(value);
  };
  overlay.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      done(null);
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusable();
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  overlay.addEventListener('click', event => {
    if (event.target === overlay) done(null);
  });
  overlay.querySelector('[data-dialog-confirm]').addEventListener('click', () => done(valueFromConfirm()));
  overlay.querySelector('[data-dialog-cancel]').addEventListener('click', () => done(null));
  return done;
}

export function confirm(msg) {
  return new Promise(resolve => {
    const ov = _overlay();
    const labelId = `dialog-title-${++dialogSequence}`;
    ov.innerHTML = `<div class="dialog-card" role="alertdialog" aria-modal="true" aria-labelledby="${labelId}">
      <div class="dialog-msg" id="${labelId}">${_esc(msg)}</div>
      <div class="dialog-btns">
        <button class="btn" type="button" data-dialog-cancel>cancel</button>
        <button class="btn danger" type="button" data-dialog-confirm>confirm</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    _wireDialog(ov, value => resolve(Boolean(value)), () => true);
    ov.querySelector('[data-dialog-cancel]').focus();
  });
}

export function prompt(msg, def = '', options = {}) {
  return new Promise(resolve => {
    const ov = _overlay();
    const inputId = `dialog-input-${++dialogSequence}`;
    ov.innerHTML = `<div class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="${inputId}-label">
      <label class="dialog-msg" id="${inputId}-label" for="${inputId}">${_esc(msg)}</label>
      <input class="settings-input dialog-input" id="${inputId}" value="${_esc(String(def || ''))}"
        type="${options.secret ? 'password' : 'text'}"
        autocomplete="${options.secret ? 'current-password' : 'off'}">
      <div class="dialog-btns">
        <button class="btn" type="button" data-dialog-cancel>cancel</button>
        <button class="btn primary" type="button" data-dialog-confirm>ok</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const inp = ov.querySelector(`#${inputId}`);
    const done = _wireDialog(ov, resolve, () => inp.value);
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        done(inp.value);
      }
    });
    inp.focus(); inp.select();
  });
}

// multi-field form — defs: [{id, label, value}], returns obj or null
export function fields(title, defs) {
  return new Promise(resolve => {
    const ov = _overlay();
    const sequence = ++dialogSequence;
    const inputs = defs.map(f =>
      `<label class="dialog-msg" for="dialog-${sequence}-${_esc(f.id)}">${_esc(f.label)}</label>
       <input class="settings-input dialog-input" id="dialog-${sequence}-${_esc(f.id)}" value="${_esc(String(f.value || ''))}">`
    ).join('');
    const titleId = `dialog-title-${sequence}`;
    ov.innerHTML = `<div class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
      <div class="dialog-msg" id="${titleId}">${_esc(title)}</div>
      ${inputs}
      <div class="dialog-btns">
        <button class="btn" type="button" data-dialog-cancel>cancel</button>
        <button class="btn primary" type="button" data-dialog-confirm>save</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const collect = () => Object.fromEntries(defs.map(f => [f.id, ov.querySelector(`#dialog-${sequence}-${CSS.escape(f.id)}`).value]));
    _wireDialog(ov, resolve, collect);
    ov.querySelector(`#dialog-${sequence}-${CSS.escape(defs[0].id)}`).focus();
  });
}
