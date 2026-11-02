// units on the habit screens (track E2): a value keeps the unit it was entered in, and this names
// it in the reader's language. the choices per measure follow services/units.py, whose names are
// the stored ones ("glass", not "glasses"); a person's height is cm or ft and in, but every
// "height" a habit logs (elevation, pool length, a high point) reads in m or ft
import { currencySymbol, localizationState, t } from './i18n.js';

export const MEASURE_UNITS = {
  distance: ['km', 'mi'],
  body: ['cm', 'in'],
  weight: ['lb', 'kg'],
  height: ['m', 'ft'],
  liquid: ['ml', 'floz', 'glass'],
  temperature: ['c', 'f'],
};

const ALIASES = { glasses: 'glass', 'fl oz': 'floz', '°c': 'c', '°f': 'f' };
export const storedUnit = unit => ALIASES[String(unit ?? '').toLowerCase()] || unit;

// "fl oz", "°C", "glasses"; a unit nobody named (a count habit's own word) shows as typed
export function unitText(unit) {
  const key = `habits.unit_${storedUnit(unit)}`;
  const found = t(key);
  return found === key ? String(unit ?? '') : found;
}

// what a number field counts in, when its name alone doesn't say: minutes, beats, percent, money
const FIELD_UNITS = {
  caffeine_mg: 'mg', hr: 'bpm', hr_avg: 'bpm', hr_max: 'bpm', tempo_bpm: 'bpm', cadence: 'per_min',
  power_avg: 'w', correct_pct: 'pct', abv: 'pct', body_fat: 'pct', comprehension: 'pct',
  sleep_hours: 'h', speed: 'x', grams: 'g', sugar_g: 'g',
};
const MONEY = new Set(['cost', 'avoided', 'left', 'total', 'save.amount', 'items.amount']);

export function fieldUnit(field, kind = '') {
  if (field.type === 'minutes') return unitText('min');
  if (field.type === 'seconds') return unitText('s');
  if (MONEY.has(field.key) || MONEY.has(`${kind}.${field.key}`)) return currencySymbol(localizationState().effectiveCurrency);
  if (FIELD_UNITS[field.key]) return unitText(FIELD_UNITS[field.key]);
  return field.unit ? unitText(field.unit) : '';
}
