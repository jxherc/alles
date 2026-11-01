// the kit page (static/kit.html): every universal piece on one page, wired by the real modules.
// the theme comes from ?theme=light|dark so a check can screenshot both without the app
import { initKokuenPrimitives } from './kokuen.js?v=5';
import './motion.js';
import { initDatePickers } from './datepick.js';
import { stepperHtml, wireSteppers } from './stepper.js';

const root = document.documentElement;
root.dataset.theme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark';
const theme = document.getElementById('kit-theme');
theme.querySelector(`[data-theme-pick="${root.dataset.theme}"]`).setAttribute('aria-checked', 'true');
// the stepper in its states: a value, at the floor (minus off), empty, unknown, a time, a long
// value, off. fake labels only
const steppers = [
  ['weight', { name: 'weight', value: '60', step: 5 }],
  ['at the floor', { name: 'partial reps', value: '0' }],
  ['empty', { name: 'reps', value: '' }],
  ['unknown', { name: 'reps', value: '?' }],
  ['time', { name: 'rest after', value: '2:00', inputmode: 'numeric', auto: false }],
  ['long value', { name: 'steps', value: '12450', step: 500, inputmode: 'numeric' }],
  ['off', { name: 'glasses', value: '6', disabled: true }],
];
document.getElementById('kit-steppers').innerHTML = steppers
  .map(([title, options]) => `<div class="kit-cell"><span class="kit-name">${title}</span>${stepperHtml(options)}</div>`)
  .join('');
wireSteppers(document);
initKokuenPrimitives(document);
initDatePickers(document);
theme.addEventListener('click', event => {
  const pick = event.target.closest('[data-theme-pick]');
  if (!pick) return;
  root.dataset.theme = pick.dataset.themePick;
  const url = new URL(location.href);
  url.searchParams.set('theme', pick.dataset.themePick);
  history.replaceState(null, '', url);
});
