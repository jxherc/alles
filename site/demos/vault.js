// the vault app, as in shots/vault.webp: the vault picker and toolbar, the list of entries with copy and
// delete, a details panel, a locked screen and a new login form. labels from static/js/vault.js and
// static/index.html. every password, card number and passport number here is an obvious fake
import { h, ic, css, topbar, menu, toast } from './kit.js';

let seq = 0;
const login = (name, user, pw, url) => ({ id: ++seq, kind: 'login', name, user, pw, url });
const KIND = { login: 'login', card: 'credit card', note: 'secure note' };

const makeVaults = () => ({
  Personal: [
    { id: ++seq, kind: 'card', name: 'Visa card', holder: 'Maya Okafor', number: '4242 4242 4242 4242', expiry: '08/29' },
    { id: ++seq, kind: 'note', name: 'Passport and travel numbers', text: 'passport: DEMO-000000\nbooking ref: DEMO42\nairline member: DEMO-0000-17' },
    login('Clay Collective', 'maya.okafor@maplemail.ca', 'correct-horse-demo-17', 'claycollective.example'),
    login('Spotify', 'maya.okafor@maplemail.ca', 'demo-battery-staple-23', 'spotify.example'),
    login('Rogers', 'mokafor', 'demo-maple-river-41', 'rogers.example'),
    login('Presto', 'maya.okafor', 'demo-plum-harbour-08', 'presto.example'),
    login('Air Portugal', 'maya.okafor@maplemail.ca', 'demo-cork-oak-52', 'airportugal.example'),
    login('Maplemail', 'maya.okafor@maplemail.ca', 'demo-lantern-moss-19', 'maplemail.example'),
    login('Notion', 'maya.okafor@maplemail.ca', 'demo-fern-lake-66', 'notion.example'),
    login('GitHub', 'mokafor', 'demo-copper-wren-30', 'github.example'),
    login('Figma', 'maya.okafor@maplemail.ca', 'demo-tidal-pine-74', 'figma.example'),
    login('Fieldnote admin', 'maya@fieldnote.co', 'demo-quartz-fox-05', 'admin.fieldnote.example'),
  ],
  Family: [
    { id: ++seq, kind: 'note', name: 'Home wifi', text: 'network: okafor-home\npassword: demo-kettle-snow-12' },
    login('Netflix', 'okafor.family@maplemail.ca', 'demo-ember-owl-27', 'netflix.example'),
    login('Hydro bill', 'okafor.family', 'demo-birch-cove-90', 'hydro.example'),
    { id: ++seq, kind: 'card', name: 'Family Visa', holder: 'Okafor Family', number: '4242 4242 4242 4242', expiry: '03/28' },
  ],
});

const WORDS = ['maple', 'river', 'plum', 'harbour', 'cork', 'lantern', 'moss', 'fern', 'lake', 'copper', 'wren', 'tidal', 'pine', 'quartz', 'fox', 'birch'];
const pick = () => WORDS[Math.floor(Math.random() * WORDS.length)];
const fakePassword = () => `demo-${pick()}-${pick()}-${String(Math.floor(Math.random() * 90) + 10)}`;
const dots = '••••••••••••';

// the clipboard only when it works; false means it didn't
async function copyText(root, text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch { /* try the old way next */ }
  const box = h('textarea', { 'aria-hidden': 'true', tabindex: '-1', style: 'position:absolute;left:-9999px;top:0' });
  box.value = text;
  root.append(box);
  box.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  box.remove();
  return ok;
}

export default function build(root) {
  css('vault');
  root.classList.add('vt-app');
  const vaults = makeVaults();
  let current = 'Personal';
  let locked = false;
  let openId = null; // the entry in the panel
  let confirmId = null; // the row asking before delete
  let adding = false; // the new login form is showing

  const items = () => vaults[current];
  const secretOf = (it) => (it.kind === 'login' ? it.pw : it.kind === 'card' ? it.number : it.text);
  const copy = async (text) => toast(root, (await copyText(root, text)) ? 'copied' : 'in alles this copies it to your clipboard');

  // ---- top bar and toolbar ----
  const bar = topbar({ app: 'vault' });
  const say = (label, icon, text) => {
    const b = h('button', { type: 'button', class: 'dm-btn vt-tool', 'data-k': label.replace(/^\+ /, '') }, icon ? ic(icon) : null, label);
    b.addEventListener('click', () => toast(root, text));
    return b;
  };
  const pickLabel = h('span', { text: current });
  const picker = h('button', { type: 'button', class: 'vt-pick', 'data-k': 'picker', 'data-value': current, 'aria-label': 'vault' }, pickLabel, ic('chevron-down'));
  menu(picker, ['Personal', 'Family'], (name) => {
    if (name === current) return;
    current = name;
    picker.dataset.value = name;
    pickLabel.textContent = name;
    closePanel();
    confirmId = null;
    paintList();
  });
  const newBtn = h('button', { type: 'button', class: 'dm-btn primary vt-tool', 'data-k': 'new', text: '+ new' });
  newBtn.addEventListener('click', () => startAdd());
  const lockBtn = h('button', { type: 'button', class: 'dm-btn vt-tool', 'data-k': 'lock', text: 'lock' });
  lockBtn.addEventListener('click', () => setLocked(true));
  const tools = h('div', { class: 'vt-tools' }, picker,
    say('+ vault', null, 'in alles this makes another vault with its own password'),
    say('travel', 'plane', 'in alles travel mode hides vaults not marked travel-safe'),
    say('biometric', 'fingerprint', 'in alles this turns on touch id or windows hello for this vault'),
    newBtn,
    say('watchtower', 'shield', 'in alles watchtower checks for breached, reused and weak passwords'),
    lockBtn,
    say('settings', 'gear', 'in alles this opens the vault’s settings: second factor, browser access, export'));

  // ---- list ----
  const list = h('ul', { class: 'vt-list', 'aria-label': 'entries' });
  const empty = h('p', { class: 'vt-empty dm-muted', text: 'no entries: hit “+ new”', hidden: true });

  function paintList() {
    list.replaceChildren();
    empty.hidden = items().length > 0;
    items().forEach((it) => {
      const sub = it.kind === 'login' ? it.user : '';
      const openBtn = h('button', { type: 'button', class: 'vt-open', 'data-k': 'open:' + it.name, 'aria-pressed': String(it.id === openId) },
        h('span', { class: 'vt-name', text: it.name }),
        sub ? h('span', { class: 'vt-sub', text: '· ' + sub }) : null,
        h('span', { class: 'vt-kind', text: '· ' + KIND[it.kind] }));
      openBtn.addEventListener('click', () => (it.id === openId ? closePanel() : openEntry(it)));
      const actions = h('span', { class: 'vt-actions' });
      if (confirmId === it.id) {
        const yes = h('button', { type: 'button', class: 'vt-act danger', 'data-k': 'confirm-delete', text: 'delete' });
        const no = h('button', { type: 'button', class: 'vt-act', 'data-k': 'cancel-delete', text: 'cancel' });
        const back = () => { confirmId = null; paintList(); root.querySelector(`[data-k="del:${it.name}"]`)?.focus(); };
        yes.addEventListener('click', () => {
          const i = items().indexOf(it);
          items().splice(i, 1);
          confirmId = null;
          if (openId === it.id) closePanel();
          paintList();
          toast(root, 'deleted ' + it.name);
          (list.children[Math.min(i, list.children.length - 1)]?.querySelector('.vt-open') || newBtn).focus();
        });
        no.addEventListener('click', back);
        actions.append(h('span', { class: 'vt-ask', text: 'delete this entry?' }), yes, no);
        actions.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); back(); } });
      } else {
        const cp = h('button', { type: 'button', class: 'vt-act', 'data-k': 'copy:' + it.name, text: 'copy' });
        cp.addEventListener('click', () => copy(secretOf(it)));
        const del = h('button', { type: 'button', class: 'vt-act danger', 'data-k': 'del:' + it.name, text: 'delete' });
        del.addEventListener('click', () => { confirmId = it.id; paintList(); root.querySelector('[data-k="cancel-delete"]')?.focus(); });
        actions.append(cp, del);
      }
      list.append(h('li', { class: 'vt-row', 'data-open': String(it.id === openId) }, openBtn, actions));
    });
  }

  // ---- the panel: an entry's fields, or the new login form ----
  const panel = h('section', { class: 'vt-panel', tabindex: '-1', hidden: true });
  panel.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePanel(true); });
  const body = h('div', { class: 'vt-body' });
  let returnKey = 'new';

  function showPanel(title, kindLine, content) {
    const close = h('button', { type: 'button', class: 'dm-btn quiet icon vt-close', 'data-k': 'close', 'aria-label': 'close' }, ic('close'));
    close.addEventListener('click', () => closePanel(true));
    panel.setAttribute('aria-label', title);
    body.replaceChildren(
      h('div', { class: 'vt-phead' }, h('div', { class: 'vt-ptitle' }, h('strong', { text: title }), kindLine ? h('span', { class: 'dm-muted', text: kindLine }) : null), close),
      content);
    panel.hidden = false;
    list.classList.add('with-panel');
  }

  function closePanel(focusBack) {
    openId = null;
    adding = false;
    panel.hidden = true;
    list.classList.remove('with-panel');
    paintList();
    if (focusBack) root.querySelector(`[data-k="${CSS.escape(returnKey)}"]`)?.focus();
  }

  const field = (label, value, { secret, multiline, key } = {}) => {
    let shown = !secret;
    const val = h('span', { class: 'vt-val' + (multiline ? ' multi' : ''), 'data-k': 'val:' + key });
    const paint = () => { val.textContent = shown ? value : (key === 'number' ? '•••• ' + value.slice(-4) : dots); };
    const buttons = [];
    if (secret) {
      const eye = h('button', { type: 'button', class: 'dm-btn vt-small', 'data-k': 'toggle:' + key, 'aria-pressed': 'false', 'aria-label': `show ${label}`, text: 'show' });
      eye.addEventListener('click', () => {
        shown = !shown;
        eye.setAttribute('aria-pressed', String(shown));
        eye.setAttribute('aria-label', `${shown ? 'hide' : 'show'} ${label}`);
        eye.textContent = shown ? 'hide' : 'show';
        paint();
      });
      buttons.push(eye);
    }
    const cp = h('button', { type: 'button', class: 'dm-btn vt-small', 'data-k': 'copyfield:' + key, 'aria-label': `copy ${label}`, text: 'copy' });
    cp.addEventListener('click', () => copy(value));
    buttons.push(cp);
    paint();
    return h('div', { class: 'vt-field' + (multiline ? ' multi' : '') }, h('span', { class: 'vt-label dm-muted', text: label }), h('div', { class: 'vt-line' }, val, h('span', { class: 'vt-btns' }, buttons)));
  };

  function openEntry(it) {
    adding = false;
    openId = it.id;
    returnKey = 'open:' + it.name;
    const fields = it.kind === 'login'
      ? [field('username', it.user, { key: 'username' }), field('password', it.pw, { secret: true, key: 'password' }), field('website', it.url, { key: 'website' })]
      : it.kind === 'card'
        ? [field('cardholder name', it.holder, { key: 'holder' }), field('card number', it.number, { secret: true, key: 'number' }), field('expiry', it.expiry, { key: 'expiry' })]
        : [field('notes', it.text, { multiline: true, key: 'notes' })];
    showPanel(it.name, KIND[it.kind], h('div', { class: 'vt-fields' }, fields));
    paintList();
    panel.focus({ preventScroll: true });
  }

  function startAdd() {
    if (adding) { panel.querySelector('[data-k="f-name"]')?.focus(); return; }
    openId = null;
    adding = true;
    returnKey = 'new';
    const name = h('input', { class: 'dm-input', id: 'vt-f-name', 'data-k': 'f-name', placeholder: 'e.g. work', autocomplete: 'off' });
    const user = h('input', { class: 'dm-input', id: 'vt-f-user', 'data-k': 'f-user', autocomplete: 'off' });
    const pw = h('input', { class: 'dm-input', id: 'vt-f-pw', 'data-k': 'f-pw', autocomplete: 'off', spellcheck: 'false' });
    const gen = h('button', { type: 'button', class: 'dm-btn', 'data-k': 'generate', text: 'generate' });
    gen.addEventListener('click', () => { pw.value = fakePassword(); pw.focus(); });
    const save = h('button', { type: 'submit', class: 'dm-btn primary', 'data-k': 'save', text: 'save' });
    const cancel = h('button', { type: 'button', class: 'dm-btn', 'data-k': 'cancel', text: 'cancel' });
    cancel.addEventListener('click', () => closePanel(true));
    const lab = (text, id, el) => h('div', { class: 'vt-field' }, h('label', { class: 'vt-label dm-muted', for: id, text }), el);
    const form = h('form', { class: 'vt-form', novalidate: true },
      lab('name', 'vt-f-name', name),
      lab('username', 'vt-f-user', user),
      lab('password', 'vt-f-pw', h('div', { class: 'vt-pwline' }, pw, gen)),
      h('div', { class: 'vt-formbtns' }, save, cancel));
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const nm = name.value.trim();
      if (!nm) { name.setAttribute('aria-invalid', 'true'); name.focus(); toast(root, 'name it first'); return; }
      const entry = login(nm, user.value.trim(), pw.value || fakePassword(), nm.toLowerCase().replace(/[^a-z0-9]+/g, '') + '.example');
      const at = items().findIndex((x) => x.kind === 'login');
      items().splice(at < 0 ? items().length : at, 0, entry);
      adding = false;
      closePanel();
      toast(root, `saved ${nm} to ${current}`);
      list.querySelector(`[data-k="${CSS.escape('open:' + nm)}"]`)?.focus();
    });
    name.addEventListener('input', () => name.removeAttribute('aria-invalid'));
    showPanel('new login', null, form);
    paintList();
    name.focus();
  }

  // ---- locked screen, as the app draws it ----
  const pwIn = h('input', { type: 'password', id: 'vt-pw', class: 'dm-input', 'data-k': 'master', autocomplete: 'off', placeholder: 'type anything' });
  const unlock = h('button', { type: 'submit', class: 'dm-btn primary', 'data-k': 'unlock', text: 'unlock' });
  const lockScreen = h('form', { class: 'vt-lock', hidden: true, novalidate: true },
    ic('lock', 28),
    h('label', { for: 'vt-pw', text: 'master password' }),
    pwIn,
    h('p', { class: 'vt-help dm-muted', text: 'your vault password is separate from your alles sign-in. alles cannot reset it to recover your secrets. keep the password safe; use an enrolled biometric unlock or a backup whose vault password you still know if needed.' }),
    unlock);
  lockScreen.addEventListener('submit', (e) => { e.preventDefault(); setLocked(false); });

  function setLocked(on) {
    locked = on;
    if (on) { closePanel(); confirmId = null; paintList(); pwIn.value = ''; }
    tools.hidden = list.hidden = on;
    empty.hidden = on || items().length > 0;
    lockScreen.hidden = !on;
    (on ? pwIn : lockBtn).focus();
  }

  root.append(bar.el, h('div', { class: 'vt' }, tools, list, empty, panel, lockScreen));
  panel.append(body);
  paintList();
}
