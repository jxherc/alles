// Special answer cards above Andromeda's results. The server picks the card and its data;
// this only draws it. Every value is set as text, never as markup.
import { formatDate, formatTime } from './i18n.js';

const make = (tag, className = '', text = '') => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
};

const source = text => make('p', 'andromeda-answer-source', text);

function bigLine(label, value, unit = '') {
  const wrap = make('div', 'andromeda-answer-main');
  if (label) wrap.append(make('p', 'andromeda-answer-label', label));
  const big = make('p', 'andromeda-answer-value', value);
  if (unit) big.append(make('span', 'andromeda-answer-unit', ` ${unit}`));
  wrap.append(big);
  return wrap;
}

const CATEGORY_ORDER = ['alkali-metal', 'alkaline-earth', 'transition', 'post-transition', 'metalloid', 'nonmetal', 'halogen', 'noble-gas', 'lanthanide', 'actinide'];

function elementDetail(element) {
  const box = make('div', 'andromeda-element');
  const tile = make('div', `andromeda-element-tile is-${element.category}`);
  tile.append(make('span', 'andromeda-element-number', String(element.number)), make('span', 'andromeda-element-symbol', element.symbol));
  const facts = make('div', 'andromeda-element-facts');
  facts.append(make('p', 'andromeda-answer-value', element.name));
  const list = make('dl', 'andromeda-element-list');
  for (const [term, value] of [
    ['atomic number', element.number], ['atomic mass', element.mass], ['category', element.category_label],
    ['group', element.group || (element.category === 'lanthanide' ? 'lanthanides' : 'actinides')], ['period', element.period],
  ]) list.append(make('dt', '', term), make('dd', '', String(value)));
  facts.append(list);
  box.append(tile, facts);
  return box;
}

function periodicTable(data, onPick) {
  const grid = make('div', 'andromeda-ptable');
  grid.setAttribute('role', 'grid');
  grid.setAttribute('aria-label', 'periodic table');
  let lanthanide = 0;
  let actinide = 0;
  for (const element of data.elements) {
    const cell = make('button', `andromeda-ptable-cell is-${element.category}`);
    cell.type = 'button';
    cell.setAttribute('role', 'gridcell');
    cell.setAttribute('aria-label', `${element.name}, ${element.number}`);
    cell.dataset.number = String(element.number);
    cell.append(make('span', 'andromeda-ptable-number', String(element.number)), make('span', 'andromeda-ptable-symbol', element.symbol));
    let column = element.group;
    let row = element.period;
    if (element.category === 'lanthanide') { row = 9; column = 3 + lanthanide++; }
    if (element.category === 'actinide') { row = 10; column = 3 + actinide++; }
    cell.style.gridColumn = String(column);
    cell.style.gridRow = String(row);
    if (element.number === data.selected) cell.setAttribute('aria-current', 'true');
    cell.addEventListener('click', () => onPick(element, cell));
    grid.append(cell);
  }
  const legend = make('div', 'andromeda-ptable-legend');
  for (const category of CATEGORY_ORDER) {
    const example = data.elements.find(element => element.category === category);
    const item = make('span', `andromeda-ptable-key is-${category}`);
    item.append(make('i'), document.createTextNode(example.category_label));
    legend.append(item);
  }
  return { grid, legend };
}

const RENDER = {
  calc: data => [bigLine(`${data.expression} =`, data.result)],
  units: data => [bigLine(`${data.amount} ${data.from} =`, data.result, data.to)],
  currency: data => [bigLine(`${data.amount} ${data.from} =`, data.result, data.to), source(`${data.source}, ${data.date}`)],
  time: data => {
    const zone = { timeZone: data.zone };
    const main = bigLine(`time in ${data.place}`, formatTime(data.iso, { ...zone, hour: 'numeric', minute: '2-digit' }));
    return [main, source(`${formatDate(data.iso, { ...zone, weekday: 'long', month: 'long', day: 'numeric' })} · ${data.zone.replace(/_/g, ' ')} (UTC${data.offset.slice(0, 3)}:${data.offset.slice(3)})`)];
  },
  weather: data => {
    const main = bigLine(data.place, `${Math.round(data.temperature)}°C`, data.sky);
    const detail = make('p', 'andromeda-answer-detail', [
      data.feels_like != null ? `feels like ${Math.round(data.feels_like)}°` : '',
      data.wind != null ? `wind ${Math.round(data.wind)} km/h` : '',
      data.humidity != null ? `humidity ${data.humidity}%` : '',
    ].filter(Boolean).join(' · '));
    const days = make('ol', 'andromeda-weather-days');
    for (const day of data.days || []) {
      const item = make('li');
      item.append(
        make('span', 'andromeda-weather-day', formatDate(`${day.date}T12:00:00`, { weekday: 'short' })),
        make('span', 'andromeda-weather-temps', `${Math.round(day.high)}° / ${Math.round(day.low)}°`),
        make('span', 'andromeda-weather-sky', day.sky),
      );
      days.append(item);
    }
    return [main, detail, days, source(data.source)];
  },
  define: data => {
    const head = make('div', 'andromeda-answer-main');
    const word = make('p', 'andromeda-answer-value', data.word);
    if (data.phonetic) word.append(make('span', 'andromeda-answer-unit', ` ${data.phonetic}`));
    head.append(word);
    const parts = [head];
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
    parts.push(source(data.source));
    return parts;
  },
  translate: data => {
    if (data.status === 'needs_model') {
      return [bigLine(`translate to ${data.to}`, data.text), source('add a model in settings → models to translate here')];
    }
    const language = value => String(value || '').replace(/^\w/, letter => letter.toUpperCase());
    const main = bigLine(`${language(data.from) || 'detected'} → ${language(data.to)}`, data.translation);
    const parts = [main];
    if (data.romanization) parts.push(make('p', 'andromeda-answer-detail', data.romanization));
    parts.push(source(`"${data.text}" · translated by your answer model`));
    return parts;
  },
  periodic: data => tableParts(data),
  element: data => tableParts(data),
};

function tableParts(data) {
  const selected = data.elements.find(element => element.number === data.selected);
  const detailHost = make('div', 'andromeda-element-host');
  if (selected) detailHost.append(elementDetail(selected));
  const { grid, legend } = periodicTable(data, (element, cell) => {
    grid.querySelectorAll('[aria-current="true"]').forEach(node => node.removeAttribute('aria-current'));
    cell.setAttribute('aria-current', 'true');
    detailHost.replaceChildren(elementDetail(element));
  });
  const scroller = make('div', 'andromeda-ptable-scroll');
  scroller.append(grid);
  return [detailHost, scroller, legend];
}

export function renderAnswer(host, data) {
  if (!host) return;
  const draw = data?.kind && RENDER[data.kind];
  host.replaceChildren();
  host.hidden = !draw;
  if (!draw) return;
  host.dataset.kind = data.kind;
  host.append(...draw(data));
}
