// a number with its change (u.05): "-1.2 lb this week" and a quiet 30 day line.
// the line is plain inline svg, hidden from a screen reader: the change is the text it reads.
// dates here are day keys (yyyy-mm-dd), so no clock or time zone gets in the way.
import { formatNumber, t } from './i18n.js';
import { addDays } from './when.js';

const DAY = 86400000;
const parts = key => String(key || '').split('-').map(Number);
const stamp = key => Date.UTC(...(([y, m, d]) => [y, m - 1, d])(parts(key)));
const valid = key => /^\d{4}-\d{2}-\d{2}$/.test(String(key || '')) && Number.isFinite(stamp(key));

// the same day a month earlier, held to the last day of a shorter month (mar 31 -> feb 28)
export function monthBefore(key) {
  const [year, month, day] = parts(key);
  const first = new Date(Date.UTC(year, month - 2, 1));
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
  return new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), Math.min(day, last))).toISOString().slice(0, 10);
}

const decimals = value => {
  const text = String(Math.abs(Number(value)));
  return text.includes('.') && !text.includes('e') ? text.split('.')[1].length : 0;
};

// a signed figure with a true minus, rounded to the places the two readings were written in
// (151.2 and 152.4 give -1.2, never -1.2000000000000455)
export function signedFigure(delta, places = 1, unit = '') {
  const factor = 10 ** places;
  const rounded = Math.round(delta * factor) / factor;
  const number = formatNumber(Math.abs(rounded), { minimumFractionDigits: places, maximumFractionDigits: places });
  const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '';
  return `${sign}${number}${unit ? ` ${unit}` : ''}`;
}

// the change of a measurement over the week before its latest reading: the last reading a
// week or more earlier (but not more than two weeks) is what it is compared with. a reading
// with no partner that close has no change to show, and so does one in another unit.
export function weekChange(series) {
  const rows = (series || []).filter(row => valid(row?.date) && Number.isFinite(Number(row.value)))
    .sort((a, b) => stamp(a.date) - stamp(b.date));
  const latest = rows.at(-1);
  if (!latest) return null;
  const newest = addDays(latest.date, -7), oldest = addDays(latest.date, -14);
  const from = rows.filter(row => row.date <= newest && row.date >= oldest).at(-1);
  if (!from || (from.unit || '') !== (latest.unit || '')) return null;
  const delta = Number(latest.value) - Number(from.value);
  const places = Math.min(2, Math.max(decimals(latest.value), decimals(from.value)));
  return { delta, places, unit: latest.unit || '', from };
}

// "−1.2 lb this week", or "no change this week". a latest reading older than a week says
// "that week", since this week has no reading yet
export function weekChangeText(change, latestDate, today) {
  if (!change) return '';
  const recent = valid(today) && valid(latestDate) && latestDate >= addDays(today, -7);
  const when = t(recent ? 'numbers.this_week' : 'numbers.that_week');
  if (Math.round(change.delta * 10 ** change.places) === 0) return t('numbers.no_change', { when });
  return t('numbers.change', { figure: signedFigure(change.delta, change.places, change.unit), when });
}

// the readings of the last 30 days as x (0..29, oldest first) and value
export function lastThirtyDays(series, today) {
  if (!valid(today)) return [];
  const start = addDays(today, -29);
  return (series || [])
    .filter(row => valid(row?.date) && row.date >= start && row.date <= today && Number.isFinite(Number(row.value)))
    .sort((a, b) => stamp(a.date) - stamp(b.date))
    .map(row => ({ x: (stamp(row.date) - stamp(start)) / DAY, y: Number(row.value) }));
}

// the svg path through the points, in a box of width x height with a little room around it.
// null when there is no shape to draw: fewer than three different values. two values make a
// flat line with one step, which says less than the change printed beside it
export function sparkPath(points, width = 72, height = 20, pad = 2) {
  if (!points || points.length < 3) return null;
  const ys = points.map(point => point.y);
  if (new Set(ys).size < 3) return null;
  const low = Math.min(...ys), high = Math.max(...ys);
  const xs = points.map(point => point.x);
  const left = Math.min(...xs), right = Math.max(...xs);
  const across = right - left || 1;
  const at = point => [
    pad + ((point.x - left) / across) * (width - 2 * pad),
    height - pad - ((point.y - low) / (high - low)) * (height - 2 * pad),
  ];
  return points.map((point, index) => `${index ? 'L' : 'M'}${at(point).map(n => Math.round(n * 10) / 10).join(' ')}`).join('');
}

// the line as svg text, or '' when there is none. it takes the text colour of its holder
export function sparkSvg(points, width = 72, height = 20) {
  const path = sparkPath(points, width, height);
  if (!path) return '';
  return `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" aria-hidden="true" focusable="false"><path d="${path}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

// a balance's line: today's balance and every move after each day back to the start of the
// window. `moves` are { date, amount } already in the balance's own currency
export function balanceSeries(balance, moves, today, days = 30) {
  if (!valid(today)) return [];
  const start = addDays(today, -(days - 1));
  const out = [];
  for (let i = 0; i < days; i += 1) {
    const day = addDays(start, i);
    const after = (moves || []).reduce((sum, move) => (move.date > day && move.date <= today ? sum + Number(move.amount || 0) : sum), 0);
    out.push({ date: day, value: Math.round((Number(balance) - after) * 100) / 100 });
  }
  return out;
}

// what a balance was on a day: today's balance less every move after that day
export function balanceOn(balance, moves, day, today) {
  const after = (moves || []).reduce((sum, move) => (move.date > day && move.date <= today ? sum + Number(move.amount || 0) : sum), 0);
  return Math.round((Number(balance) - after) * 100) / 100;
}
