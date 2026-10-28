// emoji picker for habit icons: a button that opens a small searchable grid. the emoji are user
// content (a habit's own mark), so they stay emoji; every ui icon around them is still svg.
// keywords are english and the first word is the name a screen reader says.
import { t } from './i18n.js';

const E = (glyph, words) => ({ glyph, words, name: words.split(' ')[0] });
const EMOJI = [
  E('🏃', 'running run jog cardio'),
  E('🚶', 'walking walk steps stroll'),
  E('🚴', 'cycling bike ride bicycle'),
  E('🏊', 'swimming swim pool laps'),
  E('🏋️', 'lifting weights gym workout strength'),
  E('💪', 'strength muscle flex workout'),
  E('🧘', 'yoga meditate meditation stretch calm'),
  E('🤸', 'stretching stretch gymnastics mobility'),
  E('🥾', 'hiking hike trail boots'),
  E('⛰️', 'mountain climb hike peak'),
  E('🧗', 'climbing climb bouldering'),
  E('⚽', 'soccer football sport'),
  E('🏀', 'basketball hoops sport'),
  E('🎾', 'tennis racket sport'),
  E('🏓', 'ping pong table tennis'),
  E('🥊', 'boxing fight martial punch'),
  E('🥋', 'martial arts karate judo'),
  E('⛳', 'golf'),
  E('🎿', 'skiing ski snow'),
  E('🛹', 'skateboard skating'),
  E('🏆', 'trophy win goal achieve'),
  E('🎯', 'target goal aim focus'),
  E('📚', 'books book read reading library study'),
  E('📖', 'reading read open book'),
  E('📝', 'writing write notes journal'),
  E('✍️', 'handwriting write sign pen'),
  E('📓', 'notebook journal diary'),
  E('🎓', 'study learn graduation school'),
  E('🧠', 'brain think learn memory mind'),
  E('🔬', 'science lab research microscope'),
  E('🧮', 'math abacus numbers calculate'),
  E('🌐', 'language languages web world'),
  E('🗣️', 'speaking speak talk practice language'),
  E('💻', 'coding code laptop computer programming'),
  E('⌨️', 'typing keyboard type'),
  E('🖥️', 'desktop computer work screen'),
  E('📧', 'email mail inbox'),
  E('📞', 'call phone talk'),
  E('📅', 'calendar plan schedule date'),
  E('✅', 'done check complete task tick'),
  E('⏰', 'alarm wake up clock early'),
  E('⏳', 'timer time hourglass wait'),
  E('🌅', 'sunrise morning dawn early'),
  E('🌙', 'night moon sleep bed evening'),
  E('😴', 'sleep sleeping rest nap bed'),
  E('🛏️', 'bed make bed sleep rest'),
  E('🚿', 'shower wash clean'),
  E('🛁', 'bath soak relax'),
  E('🪥', 'teeth brush toothbrush floss dental'),
  E('🧴', 'skincare lotion sunscreen moisturize'),
  E('🧼', 'soap wash hands clean'),
  E('💧', 'water drink hydrate drop'),
  E('🥤', 'drink cup soda beverage'),
  E('☕', 'coffee tea cup caffeine'),
  E('🍵', 'tea green tea cup'),
  E('🥗', 'salad healthy eat vegetables'),
  E('🥦', 'vegetables broccoli greens veggies'),
  E('🍎', 'fruit apple healthy eat'),
  E('🍌', 'banana fruit snack'),
  E('🥑', 'avocado healthy fat'),
  E('🍳', 'cooking cook breakfast egg kitchen'),
  E('🍽️', 'meal eat dinner lunch plate'),
  E('🥩', 'meat protein steak'),
  E('🍞', 'bread bake baking'),
  E('🍫', 'chocolate sweets sugar candy'),
  E('🍺', 'beer alcohol drink'),
  E('🚭', 'smoking quit cigarette no smoking'),
  E('🚫', 'quit stop no avoid ban'),
  E('📵', 'phone detox screen off no phone'),
  E('💊', 'medicine pill vitamins meds'),
  E('🩺', 'doctor health checkup'),
  E('❤️', 'heart love health'),
  E('🫀', 'heart cardio health'),
  E('🦷', 'tooth teeth dentist'),
  E('👁️', 'eyes eye vision rest'),
  E('🧹', 'cleaning clean sweep tidy chores'),
  E('🧺', 'laundry clothes wash basket'),
  E('🍴', 'dishes fork eat dishwasher'),
  E('🗑️', 'trash garbage bin declutter'),
  E('🏠', 'home house chores'),
  E('🛒', 'shopping groceries cart'),
  E('🪴', 'plants plant water garden'),
  E('🌱', 'seedling grow plant garden'),
  E('🌳', 'tree nature outside outdoors'),
  E('🌻', 'flower garden sunflower'),
  E('☀️', 'sun sunshine outside outdoors'),
  E('🌧️', 'rain weather'),
  E('🐕', 'dog walk pet'),
  E('🐈', 'cat pet'),
  E('🐟', 'fish fishing aquarium'),
  E('🐎', 'horse riding'),
  E('🚗', 'car drive driving'),
  E('✈️', 'travel plane trip flight'),
  E('🗺️', 'map explore travel'),
  E('⛺', 'camping camp tent outdoors'),
  E('🎒', 'backpack school bag pack'),
  E('💰', 'money save savings cash'),
  E('💵', 'budget money dollars spend'),
  E('🏦', 'bank finance savings'),
  E('📈', 'growth invest stocks progress chart'),
  E('🧾', 'receipt expenses track bills'),
  E('💳', 'card credit bills pay'),
  E('🎸', 'guitar music practice play'),
  E('🎹', 'piano keyboard music practice'),
  E('🎻', 'violin music practice'),
  E('🥁', 'drums music practice'),
  E('🎤', 'singing sing vocal mic'),
  E('🎧', 'listening music podcast headphones'),
  E('🎵', 'music song notes'),
  E('🎨', 'art painting paint draw creative'),
  E('✏️', 'drawing draw sketch pencil'),
  E('🖌️', 'painting paint brush art'),
  E('📷', 'photo photography camera pictures'),
  E('🎬', 'film movie video watch'),
  E('📺', 'television tv watch show'),
  E('🎮', 'gaming game games play controller'),
  E('♟️', 'chess strategy game'),
  E('🧩', 'puzzle jigsaw game'),
  E('🧶', 'knitting crochet yarn craft'),
  E('🧵', 'sewing thread craft'),
  E('🔧', 'fix tools repair wrench'),
  E('🔨', 'build hammer diy make'),
  E('🙏', 'prayer pray thanks gratitude grateful'),
  E('🕯️', 'candle calm mindful relax'),
  E('🌬️', 'breathing breathe breath air'),
  E('😊', 'smile happy mood positive'),
  E('😌', 'calm relax relief peace'),
  E('🤗', 'hug kindness care'),
  E('🥰', 'love affection gratitude'),
  E('😂', 'laugh fun joke humor'),
  E('🤝', 'friends handshake meet network social'),
  E('👪', 'family kids parents time'),
  E('👋', 'greet hello wave friends'),
  E('💌', 'letter message love write'),
  E('🎁', 'gift give kindness present'),
  E('🙌', 'celebrate cheer win praise'),
  E('⭐', 'star favorite good'),
  E('🔥', 'fire streak hot energy'),
  E('⚡', 'energy lightning power quick'),
  E('🚀', 'launch project startup rocket'),
  E('💡', 'idea lightbulb think creative'),
  E('🔔', 'reminder bell notify alert'),
  E('🔒', 'lock secure private password'),
  E('🌍', 'earth world planet global'),
  E('♻️', 'recycle recycling reuse'),
  E('🛍️', 'bags shopping buy'),
  E('🧊', 'ice cold shower cold plunge'),
  E('🔋', 'battery charge energy recharge'),
  E('📦', 'box package unpack declutter'),
];

const COLUMNS = 7;
let _open = null;
let _sequence = 0;

export function searchEmoji(query) {
  const terms = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return EMOJI;
  return EMOJI.filter(item => {
    const words = item.words.split(' ');
    return terms.every(term => words.some(word => word.startsWith(term)));
  });
}

const nameOf = glyph => EMOJI.find(item => item.glyph === glyph)?.name || '';
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const _si = name => (window.icon ? window.icon(name) : '');

// the host carries data-f="icon" and data-value, so a form reads it like any other field
export function emojiFieldHtml(value) {
  return `<div class="habit-icon-pick" data-f="icon" data-value="${esc(value)}">${_buttonHtml(value)}</div>`;
}

function _buttonHtml(value) {
  const label = value ? t('habits.icon_pick', { icon: nameOf(value) || value }) : t('habits.icon_pick_none');
  return `<button type="button" class="settings-input habit-icon-btn" aria-haspopup="dialog" aria-expanded="false" aria-label="${esc(label)}">${value ? `<span class="habit-icon-glyph" aria-hidden="true">${esc(value)}</span>` : _si('plus')}</button>`;
}

export function wireEmojiPicker(host, { disabled = () => false } = {}) {
  if (!host || host.dataset.emojiReady === '1') return;
  host.dataset.emojiReady = '1';
  host.addEventListener('click', event => {
    const button = event.target.closest('.habit-icon-btn');
    if (!button || disabled()) return;
    if (_open?.host === host) closeEmojiPicker();
    else openEmojiPicker(host);
  });
  host.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' && !disabled() && event.target.closest('.habit-icon-btn')) {
      event.preventDefault();
      if (_open?.host !== host) openEmojiPicker(host);
    }
  });
}

export function closeEmojiPicker({ restore = true } = {}) {
  if (!_open) return;
  const { host, panel } = _open;
  _open = null;
  panel.remove();
  host.querySelector('.habit-icon-btn')?.setAttribute('aria-expanded', 'false');
  document.removeEventListener('pointerdown', _outside, true);
  window.removeEventListener('resize', _place);
  window.removeEventListener('scroll', _place, true);
  if (restore) host.querySelector('.habit-icon-btn')?.focus();
}

function openEmojiPicker(host) {
  closeEmojiPicker({ restore: false });
  const id = `emoji-picker-${++_sequence}`;
  const panel = document.createElement('div');
  panel.className = 'emoji-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', t('habits.icon'));
  panel.innerHTML = `
    <div class="emoji-head">
      <input type="text" class="settings-input emoji-search" role="combobox" aria-expanded="true" aria-controls="${id}-grid" aria-autocomplete="list" autocomplete="off" spellcheck="false" aria-label="${esc(t('habits.icon_search'))}" placeholder="${esc(t('habits.icon_search'))}">
      <button type="button" class="btn emoji-none"${host.dataset.value ? '' : ' disabled'}>${esc(t('habits.icon_none'))}</button>
    </div>
    <div class="emoji-grid" id="${id}-grid" role="listbox" aria-label="${esc(t('habits.emoji'))}"></div>
    <p class="emoji-empty" role="status" hidden>${esc(t('habits.icon_empty'))}</p>`;
  document.body.appendChild(panel);
  _open = { host, panel, id, active: 0, list: EMOJI };
  host.querySelector('.habit-icon-btn').setAttribute('aria-expanded', 'true');

  const input = panel.querySelector('.emoji-search');
  const pick = glyph => {
    host.dataset.value = glyph;
    host.innerHTML = _buttonHtml(glyph);
    closeEmojiPicker();
    host.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const paint = () => {
    const state = _open;
    if (!state) return;
    state.list = searchEmoji(input.value);
    state.active = Math.max(0, state.list.findIndex(item => item.glyph === host.dataset.value));
    state.active = Math.min(state.active, Math.max(0, state.list.length - 1));
    const grid = panel.querySelector('.emoji-grid');
    grid.innerHTML = state.list.map((item, index) => `<button type="button" tabindex="-1" role="option" id="${id}-o${index}" class="emoji-opt${index === state.active ? ' active' : ''}" data-i="${index}" aria-selected="${item.glyph === host.dataset.value}" aria-label="${esc(item.name)}">${esc(item.glyph)}</button>`).join('');
    panel.querySelector('.emoji-empty').hidden = state.list.length > 0;
    if (state.list.length) input.setAttribute('aria-activedescendant', `${id}-o${state.active}`);
    else input.removeAttribute('aria-activedescendant');
    grid.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
  };
  const move = index => {
    const state = _open;
    if (!state?.list.length) return;
    state.active = Math.max(0, Math.min(state.list.length - 1, index));
    panel.querySelectorAll('.emoji-opt.active').forEach(node => node.classList.remove('active'));
    const node = panel.querySelector(`#${id}-o${state.active}`);
    node?.classList.add('active');
    input.setAttribute('aria-activedescendant', `${id}-o${state.active}`);
    node?.scrollIntoView({ block: 'nearest' });
  };

  input.addEventListener('input', () => paint());
  // options never take focus, so a click on one can't blur the search first
  panel.addEventListener('mousedown', event => { if (event.target.closest('.emoji-opt')) event.preventDefault(); });
  // one highlighted option at a time: the pointer takes it from the keyboard and back
  panel.addEventListener('mousemove', event => {
    const option = event.target.closest('.emoji-opt');
    delete panel.dataset.kb;
    if (option && Number(option.dataset.i) !== _open?.active) move(Number(option.dataset.i));
  });
  panel.addEventListener('click', event => {
    const option = event.target.closest('.emoji-opt');
    if (option) pick(_open.list[Number(option.dataset.i)].glyph);
  });
  panel.querySelector('.emoji-none').addEventListener('click', () => pick(''));
  panel.addEventListener('keydown', event => {
    const state = _open;
    if (!state) return;
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: COLUMNS, ArrowUp: -COLUMNS }[event.key];
    if (step && event.target === input) {
      event.preventDefault();
      panel.dataset.kb = '1';
      move(state.active + step);
    } else if (event.key === 'Home' && event.ctrlKey) { event.preventDefault(); move(0); }
    else if (event.key === 'End' && event.ctrlKey) { event.preventDefault(); move(state.list.length - 1); }
    else if (event.key === 'Enter' && event.target === input) {
      event.preventDefault();
      if (state.list[state.active]) pick(state.list[state.active].glyph);
    } else if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation();
      closeEmojiPicker();
    } else if (event.key === 'Tab') closeEmojiPicker();
  });

  document.addEventListener('pointerdown', _outside, true);
  window.addEventListener('resize', _place);
  window.addEventListener('scroll', _place, true);
  paint();
  _place();
  input.focus({ preventScroll: true });
}

function _outside(event) {
  if (!_open) return;
  if (_open.panel.contains(event.target) || _open.host.contains(event.target)) return;
  closeEmojiPicker({ restore: false });
}

// fixed under the button, flipped above when the space below is short, kept inside the viewport
function _place() {
  if (!_open) return;
  const { host, panel } = _open;
  const button = host.querySelector('.habit-icon-btn');
  if (!button?.isConnected) { closeEmojiPicker({ restore: false }); return; }
  const rect = button.getBoundingClientRect(), margin = 8;
  const height = panel.offsetHeight, width = panel.offsetWidth;
  const below = window.innerHeight - rect.bottom - margin, above = rect.top - margin;
  const top = height <= below || below >= above ? rect.bottom + 4 : rect.top - height - 4;
  panel.style.top = `${Math.max(margin, top)}px`;
  panel.style.left = `${Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin))}px`;
}
