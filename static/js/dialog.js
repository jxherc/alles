function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _overlay() {
  const el = document.createElement('div');
  el.className = 'dialog-overlay';
  return el;
}

export function confirm(msg) {
  return new Promise(resolve => {
    const ov = _overlay();
    ov.innerHTML = `<div class="dialog-card">
      <div class="dialog-msg">${_esc(msg)}</div>
      <div class="dialog-btns">
        <button class="btn" id="_dn">cancel</button>
        <button class="btn danger" id="_dy">confirm</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const done = v => { ov.remove(); resolve(v); };
    ov.querySelector('#_dy').onclick = () => done(true);
    ov.querySelector('#_dn').onclick = () => done(false);
    ov.addEventListener('click', e => { if (e.target === ov) done(false); });
    ov.querySelector('#_dn').focus();
  });
}

export function prompt(msg, def = '') {
  return new Promise(resolve => {
    const ov = _overlay();
    ov.innerHTML = `<div class="dialog-card">
      <div class="dialog-msg">${_esc(msg)}</div>
      <input class="settings-input dialog-input" id="_di" value="${_esc(String(def || ''))}">
      <div class="dialog-btns">
        <button class="btn" id="_dn">cancel</button>
        <button class="btn primary" id="_dy">ok</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const inp = ov.querySelector('#_di');
    const done = v => { ov.remove(); resolve(v); };
    ov.querySelector('#_dy').onclick = () => done(inp.value);
    ov.querySelector('#_dn').onclick = () => done(null);
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') done(inp.value);
      if (e.key === 'Escape') done(null);
    });
    ov.addEventListener('click', e => { if (e.target === ov) done(null); });
    inp.focus(); inp.select();
  });
}

// multi-field form — defs: [{id, label, value}], returns obj or null
export function fields(title, defs) {
  return new Promise(resolve => {
    const ov = _overlay();
    const inputs = defs.map(f =>
      `<input class="settings-input dialog-input" id="_df_${f.id}" placeholder="${_esc(f.label)}" value="${_esc(String(f.value || ''))}">`
    ).join('');
    ov.innerHTML = `<div class="dialog-card">
      <div class="dialog-msg">${_esc(title)}</div>
      ${inputs}
      <div class="dialog-btns">
        <button class="btn" id="_dn">cancel</button>
        <button class="btn primary" id="_dy">save</button>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const collect = () => Object.fromEntries(defs.map(f => [f.id, ov.querySelector(`#_df_${f.id}`).value]));
    const done = v => { ov.remove(); resolve(v); };
    ov.querySelector('#_dy').onclick = () => done(collect());
    ov.querySelector('#_dn').onclick = () => done(null);
    ov.addEventListener('click', e => { if (e.target === ov) done(null); });
    ov.querySelector(`#_df_${defs[0].id}`).focus();
  });
}
