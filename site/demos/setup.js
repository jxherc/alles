// the first run setup dialog, as in shots/setup.webp and shots/setup-access.webp. titles and wording from
// static/js/setupwizard.js; the steps after access are short forms of the real ones. nothing here is sent anywhere
import { h, ic, css, menu, toast } from './kit.js';

const STEPS = ['basics', 'access', 'files', 'ai + search', 'protection'];
const REGIONS = ['Canada', 'France', 'Germany', 'Japan', 'Taiwan', 'United Kingdom', 'United States'];
const ZONES = ['America/New_York', 'America/Toronto', 'Europe/London', 'Asia/Tokyo'];
const ACCESS = [
  { value: 'device', label: 'this device', note: 'localhost only' },
  { value: 'lan', label: 'home network', note: 'other devices on your LAN' },
  { value: 'public', label: 'public domain', note: 'HTTPS reverse proxy required' },
];

let copies = 0;
export default function build(root, { variant } = {}) {
  const tid = 'su-title-' + ++copies;
  css('setup');
  root.classList.add('su-app');
  let step = variant === 'access' ? 1 : 0; // 0 to 4, 5 is the done screen
  const state = { region: 'United States', chosen: false, name: '', zone: 'America/New_York', access: 'device', docs: '~/Alles/Docs', files: '~/Alles/Files', model: 'choose a provider', search: 'DuckDuckGo', backup: false, backupDir: '~/Alles Backups' };

  const dots = h('span', { class: 'su-dots' });
  const skip = h('button', { type: 'button', class: 'su-skip', 'data-k': 'exit', text: 'exit setup' });
  skip.addEventListener('click', () => toast(root, 'in alles this pauses setup and you resume it from settings'));
  const body = h('div', { class: 'su-body' });
  const card = h('div', { class: 'su-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': tid }, h('div', { class: 'su-head' }, dots, skip), body);
  root.append(h('div', { class: 'su-back' }, card));

  const go = (next, focus = true) => { step = Math.max(0, Math.min(5, next)); paint(focus); };

  // a field's label, with the control inside it
  const field = (label, control) => h('label', { class: 'su-field' }, h('span', { text: label }), control);
  const input = (key, extra = {}) => {
    const el = h('input', { class: 'dm-input su-input', value: state[key], autocomplete: 'off', spellcheck: 'false', ...extra });
    el.addEventListener('input', () => { state[key] = el.value; });
    return el;
  };
  // the app's dropdown in the shape of a field
  const select = (key, items, label) => {
    const text = h('span', { text: state[key] });
    const b = h('button', { type: 'button', class: 'su-select', 'data-k': key, 'data-value': state[key], 'aria-label': label }, text, ic('chevron-down'));
    menu(b, items, (v) => { state[key] = v; b.dataset.value = v; text.textContent = v; });
    return b;
  };
  const actions = (back, label) => {
    const save = h('button', { type: 'button', class: 'dm-btn primary su-btn', 'data-k': 'next', text: label });
    save.addEventListener('click', () => go(step + 1));
    const prev = back ? h('button', { type: 'button', class: 'dm-btn su-btn', 'data-k': 'back', text: 'back' }) : null;
    prev?.addEventListener('click', () => go(step - 1));
    return h('div', { class: 'su-actions' }, prev, h('span', { class: 'su-status', text: 'nothing here is sent anywhere' }), save);
  };
  const title = (text, sub) => [h('div', { class: 'su-title', id: tid, text }), sub ? h('div', { class: 'su-sub', text: sub }) : null];

  function basics() {
    const status = h('span', { 'data-k': 'region-line' });
    const paintRegion = () => {
      const name = h('strong', { text: state.region });
      status.replaceChildren(...(state.chosen ? ['region is ', name, '.'] : ['region ', name, ' is detected automatically from this browser.']));
    };
    paintRegion();
    const change = h('button', { type: 'button', class: 'dm-btn su-change', 'data-k': 'change-region', text: 'change region', 'data-value': state.region });
    menu(change, REGIONS, (v) => { state.region = v; state.chosen = true; change.dataset.value = v; paintRegion(); });
    const name = input('name', { 'data-k': 'nickname', autocomplete: 'nickname' });
    return [
      ...title('make alles yours'),
      h('div', { class: 'su-sub su-region' }, status, change),
      h('div', { class: 'su-sub' }, 'check your nickname and timezone. English is the reviewed interface language for now.'),
      field('nickname', name),
      field('timezone', select('zone', ZONES, 'timezone')),
      actions(false, 'save + continue'),
    ];
  }

  function access() {
    const group = h('div', { class: 'su-choices', role: 'radiogroup', 'aria-labelledby': tid });
    const buttons = ACCESS.map((o) => h('button', { type: 'button', role: 'radio', 'data-value': o.value, 'data-k': 'access:' + o.value }, h('strong', { text: o.label }), h('small', { text: o.note })));
    const pick = (i, focus) => {
      buttons.forEach((b, n) => { b.setAttribute('aria-checked', String(n === i)); b.tabIndex = n === i ? 0 : -1; });
      state.access = ACCESS[i].value;
      if (focus) buttons[i].focus();
    };
    buttons.forEach((b, i) => {
      b.addEventListener('click', () => pick(i));
      b.addEventListener('keydown', (e) => {
        const to = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: buttons.length - 1 }[e.key];
        if (to === undefined) return;
        e.preventDefault();
        pick((to + buttons.length) % buttons.length, true);
      });
    });
    group.append(...buttons);
    pick(Math.max(0, ACCESS.findIndex((o) => o.value === state.access)), false);
    return [...title('choose where alles answers', 'device-only is the safe default. network access takes effect after the server restarts.'), group, actions(true, 'save + continue')];
  }

  function files() {
    return [...title('put your files where you can see them', 'the document folder holds Markdown files. passwords stay in the vault app.'),
      field('document folder', input('docs', { 'data-k': 'docs' })), field('files folder', input('files', { 'data-k': 'files' })), actions(true, 'save locations')];
  }

  function tools() {
    return [...title('connect the tools you want', 'a model is optional. search defaults to DuckDuckGo and needs no account.'),
      field('AI model, optional', select('model', ['Anthropic', 'DeepSeek', 'Ollama', 'OpenAI'], 'AI model')),
      field('web search for aide and andromeda', select('search', ['DuckDuckGo', 'SearXNG'], 'web search')),
      actions(true, 'save + continue')];
  }

  function protection() {
    const sw = h('button', { type: 'button', class: 'su-switch', role: 'switch', 'aria-checked': String(state.backup), 'aria-label': 'automatic encrypted backups', 'data-k': 'backup' });
    const extra = h('div', { class: 'su-extra' });
    const paintExtra = () => { extra.replaceChildren(...(state.backup ? [field('backup folder', input('backupDir', { 'data-k': 'backup-dir' }))] : [])); };
    sw.addEventListener('click', () => { state.backup = !state.backup; sw.setAttribute('aria-checked', String(state.backup)); paintExtra(); });
    paintExtra();
    return [...title('keep a way back', 'alles can make one encrypted local backup per day and keep the latest seven. store the recovery key separately.'),
      h('div', { class: 'su-switch-row' }, h('div', {}, h('strong', { text: 'automatic encrypted backups' }), h('small', { text: 'daily, with seven-backup retention' })), sw),
      extra, actions(true, 'save + continue')];
  }

  function done() {
    const open = h('button', { type: 'button', class: 'dm-btn primary su-btn', 'data-k': 'open', text: 'open alles' });
    open.addEventListener('click', () => { go(0, false); toast(root, 'in alles this closes setup and opens the app'); });
    const access = ACCESS.find((o) => o.value === state.access).label;
    return [...title('alles is ready', 'in alles your choices are saved on your own server. here nothing is saved or sent.'),
      h('div', { class: 'su-summary' },
        h('span', { text: 'access' }), h('strong', { text: access }),
        h('span', { text: 'document folder' }), h('strong', { text: state.docs || 'not connected' }),
        h('span', { text: 'backup' }), h('strong', { text: state.backup ? 'daily encrypted' : 'off' })),
      h('div', { class: 'su-actions' }, open)];
  }

  function paint(focus) {
    dots.textContent = step >= 5 ? 'setup complete' : `${step + 1} / 5 · ${STEPS[step]}`;
    skip.hidden = step >= 5;
    body.replaceChildren(...[basics, access, files, tools, protection, done][step]().filter(Boolean));
    if (!focus) return;
    // as the app does: the first field, the chosen radio or the first button
    (body.querySelector('input, [role="radio"][aria-checked="true"], .su-btn') || card).focus({ preventScroll: true });
  }
  paint(false);
}
