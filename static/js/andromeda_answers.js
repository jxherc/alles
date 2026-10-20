// Answer cards and tools above Andromeda's results. The server picks the card and its data;
// this draws it and runs it in place. Every value is set as text, never as markup.
// A tool asked for by name opens empty; a query that carries its input answers right away.
import { formatCalendarDate, formatDate, formatNumber, formatTime } from './i18n.js';
import { wireAutosizeTextarea } from './text_entry.js';
import {
  ICON_COPY, ICON_SPEAK, ICON_SWAP, button, calcTool, canSpeak, choices, clockTool, colorTool, copyText,
  heading, iconButton, lookup, make, note, picker, randomTool, speak, statusLine, timeTool, timerTool, unitsTool,
} from './andromeda_tools.js';

function bigLine(label, value, unit = '') {
  const wrap = make('div', 'andromeda-answer-main');
  if (label) wrap.append(make('p', 'andromeda-answer-label', label));
  const big = make('p', 'andromeda-answer-value', value);
  if (unit) big.append(make('span', 'andromeda-answer-unit', ` ${unit}`));
  wrap.append(big);
  return wrap;
}

// one place to say a source didn't answer, with a way to ask again
function unavailable(title, message, retry) {
  const parts = [heading(title), make('p', 'andromeda-answer-detail', message)];
  if (retry) {
    const actions = make('div', 'andromeda-tool-actions');
    actions.append(button('try again', { onClick: retry }));
    parts.push(actions);
  }
  return parts;
}

const LANG_CODES = {
  arabic: 'ar', chinese: 'zh', dutch: 'nl', english: 'en', french: 'fr', german: 'de', greek: 'el', hebrew: 'he',
  hindi: 'hi', indonesian: 'id', italian: 'it', japanese: 'ja', korean: 'ko', latin: 'la', polish: 'pl',
  portuguese: 'pt', russian: 'ru', spanish: 'es', swedish: 'sv', thai: 'th', turkish: 'tr', ukrainian: 'uk',
  vietnamese: 'vi', cantonese: 'yue', persian: 'fa',
};

// ── translate ──
// libretranslate answers in a fraction of a second, so the translation follows the typing
function translateTool(data, ctx) {
  const languages = data.languages?.length ? data.languages : Object.keys(LANG_CODES).filter(name => name !== 'cantonese' && name !== 'latin');
  let from = data.from_detected ? '' : data.from || '';
  let to = data.to || 'english';
  let detected = '';
  const fromPicker = picker('translate from', [{ value: '', label: 'detect language' }, ...languages.map(value => ({ value, label: value }))], from, value => { from = value; detected = ''; syncSwap(); void run(); });
  const toPicker = picker('translate to', languages.map(value => ({ value, label: value })), to, value => { to = value; syncSwap(); void run(); });
  const swap = iconButton('swap languages', ICON_SWAP, () => {
    const source = from || detected;
    if (!source) return;
    const moved = output.textContent;
    from = to;
    to = source;
    fromPicker.value = from;
    toPicker.value = to;
    if (moved) { input.value = moved; output.textContent = ''; outputActions.hidden = true; }
    syncSwap();
    input.focus();
    void run();
  });
  const syncSwap = () => {
    const blocked = !(from || detected);
    swap.disabled = blocked;
    swap.title = blocked ? 'pick the source language to swap' : 'swap languages';
  };
  const bar = make('div', 'andromeda-translate-bar');
  bar.append(fromPicker, swap, toPicker);

  const panes = make('div', 'andromeda-translate-panes');
  const inputWrap = make('label', 'andromeda-translate-input');
  inputWrap.append(make('span', 'sr-only', 'text to translate'));
  const input = make('textarea');
  input.rows = 1;
  input.maxLength = 5000;
  input.placeholder = 'type to translate';
  input.dataset.kokuenEntry = 'autogrow';
  input.value = data.text || '';
  inputWrap.append(input);
  const out = make('div', 'andromeda-translate-output');
  out.setAttribute('aria-live', 'polite');
  const output = make('p', 'andromeda-translate-text', '');
  output.dataset.placeholder = 'translation';
  const outputActions = make('div', 'andromeda-translate-tools');
  const status = statusLine();
  if (canSpeak()) outputActions.append(iconButton('listen', ICON_SPEAK, () => speak(output.textContent, LANG_CODES[to] || 'en')));
  outputActions.append(iconButton('copy translation', ICON_COPY, () => copyText(output.textContent, status)));
  outputActions.hidden = true;
  out.append(output, outputActions);
  panes.append(inputWrap, out);
  const credit = note('');
  const creditFor = language => `${language ? `detected ${language} · ` : ''}libretranslate on your server`;
  credit.textContent = creditFor('');
  let seq = 0;
  let timer = 0;
  async function run() {
    clearTimeout(timer);
    const text = input.value.trim();
    const mine = ++seq;
    if (!text) { output.textContent = ''; outputActions.hidden = true; status.textContent = ''; return; }
    out.setAttribute('aria-busy', 'true');
    try {
      const done = await ctx.translate({ text, from, to });
      if (mine !== seq) return;
      output.textContent = done.translation;
      output.lang = LANG_CODES[to] || '';
      detected = from ? '' : done.from || '';
      outputActions.hidden = !done.translation;
      status.textContent = '';
      credit.textContent = creditFor(detected);
      syncSwap();
    } catch (error) {
      if (mine !== seq) return;
      status.textContent = error.message || 'translation failed';
    } finally {
      if (mine === seq) out.removeAttribute('aria-busy');
    }
  }
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 250); });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void run(); }
  });
  ctx.onStop(() => clearTimeout(timer));
  queueMicrotask(() => wireAutosizeTextarea(input));
  if (data.engine === 'unavailable') status.textContent = 'the translator (libretranslate) isn\'t running on your server';
  else if (data.text) queueMicrotask(run);
  syncSwap();
  return [heading('translate'), bar, panes, status, credit];
}

// ── dictionary ──
function wordList(label, words, onPick) {
  const block = make('div', 'andromeda-define-related');
  block.append(make('p', 'andromeda-answer-label', label));
  const row = make('div', 'andromeda-define-words');
  for (const word of words) row.append(button(word, { className: 'andromeda-word', onClick: () => onPick(word) }));
  block.append(row);
  return block;
}

function defineTool(data, ctx) {
  const look = word => ctx.swap(() => ctx.ask(`define ${word}`, 'define'));
  const again = lookup('word to look up', 'define', look, { placeholder: data.status === 'ok' ? 'look up another word' : 'look up a word' });
  if (data.status === 'empty') return [heading('dictionary'), again.form];
  if (data.status === 'unavailable') return [...unavailable('dictionary', `the dictionary (${data.source || 'wiktionary'}) isn't answering right now.`, () => look(data.word)), again.form];
  if (data.status === 'not_found') {
    const parts = [heading('dictionary'), make('p', 'andromeda-answer-detail', `no definition found for "${data.word}".`)];
    if (data.suggestions?.length) parts.push(wordList('did you mean', data.suggestions, look));
    again.input.value = data.word;
    return [...parts, again.form];
  }
  const head = make('div', 'andromeda-define-head');
  const word = make('p', 'andromeda-answer-value', data.word);
  word.lang = 'en';
  head.append(word);
  if (data.phonetic) head.append(make('span', `andromeda-answer-unit${data.focus === 'pronunciation' ? ' is-focus' : ''}`, data.phonetic));
  if (canSpeak()) head.append(iconButton(`say ${data.word}`, ICON_SPEAK, () => speak(data.word, 'en')));
  const parts = [heading('dictionary'), head];
  const related = [];
  if (data.synonyms?.length) related.push(wordList('similar', data.synonyms, look));
  if (data.antonyms?.length) related.push(wordList('opposite', data.antonyms, look));
  if (data.focus === 'synonyms' || data.focus === 'antonyms') parts.push(...related);
  for (const meaning of data.meanings || []) {
    const block = make('div', 'andromeda-define-part');
    block.append(make('p', 'andromeda-answer-label', meaning.part));
    const list = make('ol', 'andromeda-define-list');
    for (const definition of meaning.definitions) {
      const item = make('li', '', definition.text);
      if (definition.example) item.append(make('span', 'andromeda-define-example', definition.example));
      list.append(item);
    }
    block.append(list);
    parts.push(block);
  }
  if (data.focus !== 'synonyms' && data.focus !== 'antonyms') parts.push(...related);
  parts.push(note(data.source), again.form);
  return parts;
}

function spellTool(data, ctx) {
  const check = word => ctx.swap(() => ctx.ask(`spell ${word}`, 'spell'));
  const again = lookup('word to check', 'check', check, { placeholder: 'check a spelling' });
  if (data.status === 'empty') return [heading('spelling'), again.form];
  if (data.status === 'unavailable') return [...unavailable('spelling', 'the spelling sources (wiktionary, datamuse) aren\'t answering right now.', () => check(data.word)), again.form];
  const parts = [heading('spelling')];
  if (data.correct) {
    parts.push(bigLine('', data.word, 'is spelled correctly'));
  } else if (data.suggestions?.length) {
    parts.push(bigLine(`"${data.word}" is usually spelled`, data.suggestions[0]));
    if (data.suggestions.length > 1) parts.push(make('p', 'andromeda-answer-detail', `or ${data.suggestions.slice(1).join(', ')}`));
  } else {
    parts.push(make('p', 'andromeda-answer-detail', `"${data.word}" isn't in the dictionary and nothing close came up.`));
  }
  const word = data.correct ? data.word : data.suggestions?.[0];
  const actions = make('div', 'andromeda-tool-actions');
  if (word) actions.append(button(`define ${word}`, { onClick: () => ctx.swap(() => ctx.ask(`define ${word}`, 'define')) }));
  if (word && canSpeak()) actions.append(button('say it', { onClick: () => speak(word, 'en') }));
  if (actions.childElementCount) parts.push(actions);
  parts.push(note(data.source), again.form);
  return parts;
}

// ── currency ──
function currencyTool(data, ctx) {
  const codes = (data.currencies || []).map(row => ({ value: row.code, label: `${row.code} · ${row.name}` }));
  let rate = data.rate;
  let from = data.from;
  let to = data.to;
  const box = make('div', 'andromeda-convert');
  const side = (which, code) => {
    const row = make('div', 'andromeda-convert-side');
    const wrap = make('label', 'andromeda-tool-field');
    wrap.append(make('span', 'sr-only', `amount in ${which} currency`));
    const input = make('input');
    input.type = 'text';
    input.inputMode = 'decimal';
    input.autocomplete = 'off';
    wrap.append(input);
    const choose = picker(`${which} currency`, codes, code, value => refetch(which, value));
    row.append(wrap, choose);
    return { row, input, choose };
  };
  const left = side('from', from);
  const right = side('to', to);
  const swap = iconButton('swap currencies', ICON_SWAP, () => refetch('swap'));
  const rateLine = note('');
  const status = statusLine();
  const show = () => {
    if (!rate) { right.input.value = ''; rateLine.textContent = ''; return; }
    rateLine.textContent = `1 ${from} = ${formatNumber(rate, { maximumFractionDigits: 6 })} ${to} · ${data.source}${data.date ? `, ${data.date}` : ''}`;
  };
  const update = source => {
    if (!rate) return;
    const [give, take, factor] = source === 'left' ? [left, right, rate] : [right, left, 1 / rate];
    const value = Number(give.input.value.replace(/,/g, ''));
    take.input.value = give.input.value.trim() && Number.isFinite(value) ? (value * factor).toFixed(2) : '';
  };
  async function refetch(which, value) {
    if (which === 'swap') [from, to] = [to, from];
    else if (which === 'from') from = value;
    else to = value;
    left.choose.value = from;
    right.choose.value = to;
    if (from === to) { rate = 1; status.textContent = ''; show(); update('left'); return; }
    status.textContent = 'getting the rate…';
    try {
      const next = await ctx.ask(`1 ${from} to ${to}`, 'currency');
      if (next?.status !== 'ok') throw new Error('unavailable');
      rate = next.rate;
      data.date = next.date;
      status.textContent = '';
    } catch {
      rate = 0;
      status.textContent = 'exchange rates are unavailable right now (frankfurter)';
    }
    show();
    update('left');
  }
  left.input.value = String(data.amount_value ?? 1);
  left.input.addEventListener('input', () => update('left'));
  right.input.addEventListener('input', () => update('right'));
  box.append(left.row, swap, right.row);
  if (data.status !== 'ok') status.textContent = 'exchange rates are unavailable right now (frankfurter)';
  show();
  update('left');
  const parts = [heading('currency converter'), box, rateLine, status];
  if (data.status !== 'ok') {
    const actions = make('div', 'andromeda-tool-actions');
    actions.append(button('try again', { onClick: () => refetch('from', from) }));
    parts.push(actions);
  }
  return parts;
}

// ── weather ──
const toF = celsius => celsius * 9 / 5 + 32;

function weatherTool(data, ctx) {
  const look = place => ctx.swap(() => ctx.ask(`weather ${place}`, 'weather'));
  const again = lookup('place for the weather', 'show weather', look, { placeholder: data.status === 'ok' ? 'another place' : 'a city or town' });
  if (data.status === 'empty') return [heading('weather'), again.form];
  if (data.status === 'unavailable') {
    again.input.value = data.place || '';
    return [...unavailable('weather', 'open-meteo, the weather source, isn\'t answering right now.', () => look(data.place)), again.form];
  }
  if (data.status === 'not_found') {
    again.input.value = data.place;
    return [heading('weather'), make('p', 'andromeda-answer-detail', `no place called "${data.place}" came up.`), again.form];
  }
  let unit = ctx.prefs.get('andromeda-temp-unit') === 'f' ? 'f' : 'c';
  const host = make('div', 'andromeda-weather');
  const draw = () => {
    const degrees = value => (value == null ? '–' : `${Math.round(unit === 'f' ? toF(value) : value)}°`);
    const main = bigLine(data.place, `${degrees(data.temperature)}${unit.toUpperCase()}`, data.sky);
    const head = make('div', 'andromeda-weather-head');
    head.append(main, units);
    const detail = make('p', 'andromeda-answer-detail', [
      data.feels_like != null ? `feels like ${degrees(data.feels_like)}` : '',
      data.wind != null ? `wind ${Math.round(unit === 'f' ? data.wind / 1.609 : data.wind)} ${unit === 'f' ? 'mph' : 'km/h'}` : '',
      data.humidity != null ? `humidity ${data.humidity}%` : '',
    ].filter(Boolean).join(' · '));
    const days = make('ol', 'andromeda-weather-days');
    for (const day of data.days || []) {
      const item = make('li');
      item.append(
        make('span', 'andromeda-weather-day', formatCalendarDate(day.date, { weekday: 'short' })),
        make('span', 'andromeda-weather-temps', `${degrees(day.high)} / ${degrees(day.low)}`),
        make('span', 'andromeda-weather-sky', [day.sky, day.rain != null && day.rain >= 20 ? `${day.rain}% rain` : ''].filter(Boolean).join(' · ')),
      );
      days.append(item);
    }
    host.replaceChildren(head, detail, days);
  };
  const units = choices('temperature unit', [{ value: 'c', label: '°C' }, { value: 'f', label: '°F' }], unit, value => {
    unit = value;
    ctx.prefs.set('andromeda-temp-unit', unit);
    draw();
  });
  draw();
  return [heading('weather'), host, note(data.source), again.form];
}

// ── periodic table ──
const CATEGORY_ORDER = ['alkali-metal', 'alkaline-earth', 'transition', 'post-transition', 'metalloid', 'nonmetal', 'halogen', 'noble-gas', 'lanthanide', 'actinide'];
const FACT_LABELS = { mass: 'atomic mass', number: 'atomic number', symbol: 'symbol', group: 'group', period: 'period', category: 'category' };

function factValue(element, fact) {
  if (fact === 'mass') return { value: element.mass, unit: 'u' };
  if (fact === 'number') return { value: String(element.number) };
  if (fact === 'symbol') return { value: element.symbol };
  if (fact === 'group') return { value: element.group ? String(element.group) : `${element.category_label} row` };
  if (fact === 'period') return { value: String(element.period) };
  return { value: element.category_label };
}

function elementDetail(element) {
  const box = make('div', 'andromeda-element');
  const tile = make('div', `andromeda-element-tile is-${element.category}`);
  tile.append(make('span', 'andromeda-element-number', String(element.number)), make('span', 'andromeda-element-symbol', element.symbol));
  const facts = make('div', 'andromeda-element-facts');
  facts.append(make('p', 'andromeda-element-name', element.name));
  const list = make('dl', 'andromeda-element-list');
  for (const [term, value] of [
    ['atomic number', element.number], ['atomic mass', `${element.mass} u`], ['category', element.category_label],
    ['group', element.group || (element.category === 'lanthanide' ? 'lanthanides' : 'actinides')], ['period', element.period],
  ]) list.append(make('dt', '', term), make('dd', '', String(value)));
  facts.append(list);
  box.append(tile, facts);
  return box;
}

function periodicTable(data, onPick) {
  const grid = make('div', 'andromeda-ptable');
  grid.setAttribute('role', 'grid');
  grid.setAttribute('aria-label', 'periodic table, arrow keys move between elements');
  let lanthanide = 0;
  let actinide = 0;
  const cells = [];
  for (const element of data.elements) {
    const cell = make('button', `andromeda-ptable-cell is-${element.category}`);
    cell.type = 'button';
    cell.setAttribute('role', 'gridcell');
    cell.setAttribute('aria-label', `${element.name}, ${element.number}, ${element.category_label}`);
    cell.dataset.number = String(element.number);
    cell.dataset.category = element.category;
    cell.append(make('span', 'andromeda-ptable-number', String(element.number)), make('span', 'andromeda-ptable-symbol', element.symbol));
    let column = element.group;
    let row = element.period;
    if (element.category === 'lanthanide') { row = 9; column = 3 + lanthanide++; }
    if (element.category === 'actinide') { row = 10; column = 3 + actinide++; }
    cell.style.gridColumn = String(column);
    cell.style.gridRow = String(row);
    cell.dataset.row = String(row);
    cell.dataset.column = String(column);
    cell.tabIndex = -1;
    if (element.number === data.selected) cell.setAttribute('aria-current', 'true');
    cell.addEventListener('click', () => onPick(element, cell));
    cells.push(cell);
    grid.append(cell);
  }
  (cells.find(cell => cell.getAttribute('aria-current') === 'true') || cells[0]).tabIndex = 0;
  // arrows move to the nearest element in that direction; the table has gaps, so steps aren't fixed
  grid.addEventListener('keydown', event => {
    const at = cells.indexOf(event.target);
    if (at < 0) return;
    const here = cells[at];
    const row = Number(here.dataset.row);
    const column = Number(here.dataset.column);
    const moves = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] };
    let next = null;
    if (event.key in moves) {
      const [dr, dc] = moves[event.key];
      const ahead = cells.filter(cell => {
        const r = Number(cell.dataset.row);
        const c = Number(cell.dataset.column);
        return dr ? Math.sign(r - row) === dr : r === row && Math.sign(c - column) === dc;
      });
      ahead.sort((a, b) => {
        const score = cell => Math.abs(Number(cell.dataset.row) - row) * 30 + Math.abs(Number(cell.dataset.column) - column);
        return score(a) - score(b);
      });
      next = ahead[0];
    } else if (event.key === 'Home') next = cells[0];
    else if (event.key === 'End') next = cells[cells.length - 1];
    if (!next && !(event.key in moves)) return;
    event.preventDefault();
    if (!next) return;
    here.tabIndex = -1;
    next.tabIndex = 0;
    next.focus();
  });
  const legend = make('div', 'andromeda-ptable-legend');
  legend.setAttribute('role', 'group');
  legend.setAttribute('aria-label', 'highlight a family');
  for (const category of CATEGORY_ORDER) {
    const example = data.elements.find(element => element.category === category);
    const item = make('button', `andromeda-ptable-key is-${category}`);
    item.type = 'button';
    item.setAttribute('aria-pressed', 'false');
    item.append(make('i'), document.createTextNode(example.category_label));
    item.addEventListener('click', () => {
      const on = item.getAttribute('aria-pressed') !== 'true';
      legend.querySelectorAll('button').forEach(node => node.setAttribute('aria-pressed', String(node === item && on)));
      grid.dataset.highlight = on ? category : '';
      cells.forEach(cell => cell.classList.toggle('is-dim', on && cell.dataset.category !== category));
    });
    legend.append(item);
  }
  const scroller = make('div', 'andromeda-ptable-scroll');
  scroller.append(grid);
  return { grid, legend, scroller };
}

function tableBlock(data, detailHost) {
  const { grid, legend, scroller } = periodicTable(data, (element, cell) => {
    grid.querySelectorAll('[aria-current="true"]').forEach(node => node.removeAttribute('aria-current'));
    cell.setAttribute('aria-current', 'true');
    detailHost.replaceChildren(elementDetail(element));
  });
  return [scroller, legend];
}

function periodicTool(data) {
  const detailHost = make('div', 'andromeda-element-host');
  detailHost.setAttribute('aria-live', 'polite');
  detailHost.append(make('p', 'andromeda-answer-detail', 'pick an element to see its details.'));
  return [heading('periodic table'), detailHost, ...tableBlock({ ...data, selected: 0 }, detailHost)];
}

function elementTool(data) {
  const element = data.elements.find(row => row.number === data.selected);
  const parts = [heading('element')];
  if (data.fact) {
    const fact = factValue(element, data.fact);
    parts.push(bigLine(`${FACT_LABELS[data.fact]} of ${element.name.toLowerCase()}`, fact.value, fact.unit || ''));
  }
  const detailHost = make('div', 'andromeda-element-host');
  detailHost.setAttribute('aria-live', 'polite');
  detailHost.append(elementDetail(element));
  const tableHost = make('div', 'andromeda-ptable-host');
  tableHost.hidden = true;
  const toggle = button('show the periodic table');
  toggle.setAttribute('aria-expanded', 'false');
  toggle.addEventListener('click', () => {
    const open = tableHost.hidden;
    if (open && !tableHost.childElementCount) tableHost.append(...tableBlock(data, detailHost));
    tableHost.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open ? 'hide the periodic table' : 'show the periodic table';
  });
  const actions = make('div', 'andromeda-tool-actions');
  actions.append(toggle);
  parts.push(detailHost, actions, tableHost);
  return parts;
}

// ── formula 1 ──
function countdownText(ms) {
  if (ms <= 0) return 'under way';
  const days = Math.floor(ms / 86400000);
  const hours = Math.floor((ms % 86400000) / 3600000);
  const minutes = Math.floor((ms % 3600000) / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${days ? `${days}d ` : ''}${String(hours).padStart(2, '0')}h ${String(minutes).padStart(2, '0')}m ${String(seconds).padStart(2, '0')}s`;
}

const raceTime = iso => `${formatDate(iso, { weekday: 'short', month: 'short', day: 'numeric' })}, ${formatTime(iso, { hour: 'numeric', minute: '2-digit' })}`;

function table(caption, columns, rows) {
  const node = make('table', 'andromeda-f1-table');
  node.append(make('caption', 'sr-only', caption));
  const head = make('thead');
  const headRow = make('tr');
  for (const column of columns) {
    const th = make('th', column.className || '', column.label);
    th.scope = 'col';
    headRow.append(th);
  }
  head.append(headRow);
  const body = make('tbody');
  for (const row of rows) {
    const tr = make('tr');
    columns.forEach((column, index) => {
      const cell = make(index === 1 ? 'th' : 'td', column.className || '', String(row[column.key] ?? ''));
      if (index === 1) cell.scope = 'row';
      tr.append(cell);
    });
    body.append(tr);
  }
  node.append(head, body);
  const scroll = make('div', 'andromeda-f1-scroll');
  scroll.append(node);
  return scroll;
}

function f1Tool(data, ctx) {
  if (data.status !== 'ok') return unavailable('formula 1', 'jolpica-f1, the f1 data source, isn\'t answering right now.', () => ctx.swap(() => ctx.ask('f1', 'f1')));
  const now = Date.now();
  const schedule = data.schedule || [];
  const next = schedule.find(race => Date.parse(race.start) + 2 * 3600000 > now);
  const missing = view => make('p', 'andromeda-answer-detail', `${view} aren't available right now; the rest of the card is.`);
  let stopView = [];
  const viewStop = stop => { stopView.push(stop); ctx.onStop(stop); };
  const views = {
    next: () => {
      if (!schedule.length) return [missing('the calendar and next race')];
      if (!next) return [make('p', 'andromeda-answer-detail', `the ${data.season} season is over.`)];
      const clock = make('p', 'andromeda-answer-value andromeda-f1-countdown', countdownText(Date.parse(next.start) - Date.now()));
      clock.setAttribute('aria-label', `starts in ${countdownText(Date.parse(next.start) - Date.now())}`);
      const tick = setInterval(() => { clock.textContent = countdownText(Date.parse(next.start) - Date.now()); }, 1000);
      viewStop(() => clearInterval(tick));
      const sessions = make('dl', 'andromeda-f1-sessions');
      for (const session of [...next.sessions, { name: 'race', start: next.start }]) {
        sessions.append(make('dt', '', session.name), make('dd', '', raceTime(session.start)));
      }
      return [
        make('p', 'andromeda-answer-label', `round ${next.round} · ${next.place}`),
        make('p', 'andromeda-f1-race', next.name),
        clock,
        make('p', 'andromeda-answer-detail', `${next.circuit} · lights out ${raceTime(next.start)}, your time`),
        sessions,
      ];
    },
    drivers: () => (data.drivers ? [table(`driver standings after round ${data.after_round}`, [
      { key: 'position', label: 'pos', className: 'is-num' }, { key: 'name', label: 'driver' }, { key: 'team', label: 'team', className: 'is-team' },
      { key: 'wins', label: 'wins', className: 'is-num' }, { key: 'points', label: 'pts', className: 'is-num' },
    ], data.drivers)] : [missing('driver standings')]),
    teams: () => (data.teams ? [table('constructor standings', [
      { key: 'position', label: 'pos', className: 'is-num' }, { key: 'name', label: 'team' },
      { key: 'wins', label: 'wins', className: 'is-num' }, { key: 'points', label: 'pts', className: 'is-num' },
    ], data.teams)] : [missing('constructor standings')]),
    results: () => (data.last?.results ? [
      make('p', 'andromeda-answer-label', `round ${data.last.round} · ${formatDate(data.last.start, { month: 'long', day: 'numeric' })}`),
      make('p', 'andromeda-f1-race', data.last.name),
      table(`${data.last.name} results`, [
        { key: 'position', label: 'pos', className: 'is-num' }, { key: 'name', label: 'driver' }, { key: 'team', label: 'team', className: 'is-team' },
        { key: 'time', label: 'time' }, { key: 'points', label: 'pts', className: 'is-num' },
      ], data.last.results),
    ] : [missing('the last results')]),
    schedule: () => {
      if (!schedule.length) return [missing('the calendar')];
      const list = make('ol', 'andromeda-f1-schedule');
      for (const race of schedule) {
        const item = make('li');
        const done = Date.parse(race.start) + 2 * 3600000 <= now;
        if (done) item.dataset.state = 'done';
        if (race === next) item.dataset.state = 'next';
        item.append(
          make('span', 'andromeda-f1-round', String(race.round)),
          make('span', 'andromeda-f1-name', race.name),
          make('span', 'andromeda-f1-date', race === next ? `next · ${formatDate(race.start, { month: 'short', day: 'numeric' })}` : formatDate(race.start, { month: 'short', day: 'numeric' })),
        );
        list.append(item);
      }
      return [list];
    },
  };
  const labels = { next: 'next race', drivers: 'drivers', teams: 'teams', results: 'last race', schedule: 'calendar' };
  const tabs = make('div', 'andromeda-f1-tabs');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'formula 1 views');
  const panel = make('div', 'andromeda-f1-panel');
  panel.setAttribute('role', 'tabpanel');
  panel.tabIndex = 0;
  const id = `andromeda-f1-${Math.random().toString(36).slice(2, 8)}`;
  panel.id = `${id}-panel`;
  const pick = (view, focus = false) => {
    stopView.forEach(stop => stop());
    stopView = [];
    tabs.querySelectorAll('[role="tab"]').forEach(tab => {
      const on = tab.dataset.view === view;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      if (on) { panel.setAttribute('aria-labelledby', tab.id); if (focus) tab.focus(); }
    });
    panel.replaceChildren(...views[view]());
  };
  for (const view of Object.keys(labels)) {
    const tab = make('button', 'andromeda-f1-tab', labels[view]);
    tab.type = 'button';
    tab.id = `${id}-${view}`;
    tab.dataset.view = view;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', panel.id);
    tab.addEventListener('click', () => pick(view));
    tabs.append(tab);
  }
  tabs.addEventListener('keydown', event => {
    const all = [...tabs.querySelectorAll('[role="tab"]')];
    const at = all.indexOf(document.activeElement);
    if (at < 0) return;
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: all.length - 1 }[event.key];
    if (to == null) return;
    event.preventDefault();
    pick(all[(to + all.length) % all.length].dataset.view, true);
  });
  pick(views[data.view] ? data.view : 'next');
  const parts = [heading(`formula 1 · ${data.season} season`), tabs, panel];
  parts.push(note(`${data.source}, the free successor to the ergast api${data.after_round ? ` · standings after round ${data.after_round}` : ''}`));
  return parts;
}

// ── dates ──
const longDay = iso => formatCalendarDate(iso, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
const dayWord = days => `${formatNumber(Math.abs(days))} ${Math.abs(days) === 1 ? 'day' : 'days'}`;

// the answer first, big; what it is measured from underneath
function dateLine(value, detail) {
  const wrap = make('div', 'andromeda-answer-main');
  wrap.append(make('p', 'andromeda-answer-value', value), make('p', 'andromeda-answer-detail', detail));
  return wrap;
}

function dateTool(data, ctx) {
  const parts = [heading('date')];
  const name = data.name && !['today', 'tomorrow', 'yesterday'].includes(data.name) ? `${data.name}, ` : '';
  if (data.mode === 'today') parts.push(dateLine(longDay(data.date), 'today'));
  else if (data.mode === 'offset') parts.push(dateLine(longDay(data.date), data.days < 0 ? `${dayWord(data.days)} ago` : `${dayWord(data.days)} from today`));
  else if (data.mode === 'weekday') parts.push(dateLine(formatCalendarDate(data.date, { weekday: 'long' }), `${name}${formatCalendarDate(data.date, { year: 'numeric', month: 'long', day: 'numeric' })}`));
  else if (data.mode === 'between') parts.push(dateLine(dayWord(data.days), `from ${longDay(data.date)} to ${longDay(data.other)}`));
  else if (data.mode === 'since') parts.push(dateLine(dayWord(data.days), `since ${name}${longDay(data.date)}`));
  else {
    const detail = data.days < 0 ? `ago: ${name}${longDay(data.date)}` : data.days === 0 ? `${name}${longDay(data.date)}` : `until ${name}${longDay(data.date)}`;
    parts.push(dateLine(data.days === 0 ? 'today' : dayWord(data.days), detail));
    if (data.live && data.days >= 0) {
      const [year, month, day] = data.date.split('-').map(Number);
      const target = new Date(year, month - 1, day).getTime();
      const clock = make('p', 'andromeda-answer-detail andromeda-f1-countdown', countdownText(target - Date.now()));
      const tick = setInterval(() => { clock.textContent = countdownText(target - Date.now()); }, 1000);
      ctx.onStop(() => clearInterval(tick));
      parts.push(clock);
    }
  }
  return parts;
}

const RENDER = {
  calc: calcTool,
  units: unitsTool,
  currency: currencyTool,
  time: timeTool,
  clock: clockTool,
  weather: weatherTool,
  define: defineTool,
  spell: spellTool,
  translate: translateTool,
  periodic: periodicTool,
  element: elementTool,
  f1: f1Tool,
  date: dateTool,
  timer: timerTool,
  random: randomTool,
  color: colorTool,
};

const PREFS = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch {} },
};

// whether a card fully answers the query, so the ai overview can wait to be asked
export function answerCovers(data) {
  return Boolean(data?.kind && RENDER[data.kind] && data.engine !== 'unavailable' && !['unavailable', 'not_found', 'failed', 'needs_model', 'invalid'].includes(data.status));
}

export function renderAnswer(host, data, options = {}) {
  if (!host) return;
  host._stopAnswer?.();
  const stops = [];
  host._stopAnswer = () => { stops.splice(0).forEach(stop => { try { stop(); } catch {} }); };
  const draw = data?.kind && RENDER[data.kind];
  host.replaceChildren();
  host.hidden = !draw;
  if (!draw) { delete host.dataset.kind; return; }
  host.dataset.kind = data.kind;
  const ctx = {
    ask: options.ask || (async () => ({ kind: null })),
    translate: options.translate || (async () => { throw new Error('translation is unavailable'); }),
    prefs: PREFS,
    onStop: stop => stops.push(stop),
    // replace this card with a fresh lookup, keeping the old one until the answer arrives
    swap: async load => {
      host.setAttribute('aria-busy', 'true');
      try {
        const next = await load();
        if (next?.kind) {
          const focusTitle = host.contains(document.activeElement);
          renderAnswer(host, next, options);
          if (focusTitle) host.querySelector('input, textarea, button')?.focus({ preventScroll: true });
        }
      } catch {
        const status = host.querySelector('.andromeda-tool-status') || host.appendChild(statusLine());
        status.textContent = 'could not reach alles; try again';
      } finally {
        host.removeAttribute('aria-busy');
      }
    },
  };
  host.append(...draw(data, ctx));
}
