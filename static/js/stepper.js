// the stepper (kit, decision 0058): one number field with minus and plus inside its own edge, for
// numbers a thumb nudges more than it types (weight, reps, glasses, minutes). 52px tall, 44px
// buttons. a stepper with data-kokuen-stepper="auto" steps itself; others (the gym logger) keep
// their own model and only borrow the markup.
import { formatDecimal } from './liveformat.js';
import { t } from './i18n.js';

const MINUS = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3.5 8h9"/></svg>';
const PLUS = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3.5 8h9M8 3.5v9"/></svg>';
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// name is what the field is ("weight, left"); attrs are extra data-* the owner reads back
// unit ("min", "g", "ml") sits right after the value inside the field, so the number never reads
// bare; the value's width follows what's typed, so the two stay together in the middle
export function stepperHtml({ name, value = '', step = 1, min = 0, max = '', inputmode = 'decimal', placeholder = '?', auto = true, attrs = '', disabled = false, unit = '' }) {
  const off = disabled ? ' disabled' : '';
  const input = `<input inputmode="${esc(inputmode)}" autocomplete="off" aria-label="${esc(unit ? `${name} (${unit})` : name)}" placeholder="${esc(placeholder)}" value="${esc(value)}"${unit ? ` style="--k-len: ${valueLength(value, placeholder)}"` : ''}${off}>`;
  return `<div class="k-stepper"${auto ? ` data-kokuen-stepper="auto" data-step="${esc(step)}" data-min="${esc(min)}"${max !== '' ? ` data-max="${esc(max)}"` : ''}` : ''}${attrs ? ` ${attrs}` : ''}>
      <button type="button" data-d="-1" aria-label="${esc(t('common.less_n', { name }))}"${off}>${MINUS}</button>
      ${unit ? `<label class="k-stepper-value">${input}<span class="k-stepper-unit" aria-hidden="true">${esc(unit)}</span></label>` : input}
      <button type="button" data-d="1" aria-label="${esc(t('common.more_n', { name }))}"${off}>${PLUS}</button>
    </div>`;
}

// the next value after one press: empty or unknown counts from min, the result stays on the step's
// decimals and inside min and max
export function stepValue(text, direction, { step = 1, min = 0, max = Infinity } = {}) {
  const current = Number(formatDecimal(String(text ?? '').trim()));
  const from = String(text ?? '').trim() && Number.isFinite(current) ? current : min;
  const places = (String(step).split('.')[1] || '').length;
  const next = Math.min(max, Math.max(min, from + step * direction));
  return Number(next.toFixed(places));
}

function limits(stepper) {
  const { step, min, max } = stepper.dataset;
  return { step: Number(step) || 1, min: min === undefined || min === '' ? 0 : Number(min), max: max === undefined || max === '' ? Infinity : Number(max) };
}

// minus is off at the floor, plus at the ceiling; an empty or unknown value can still go up
const valueLength = (value, placeholder = '') => Math.max(1, String(value ?? '').length || String(placeholder).length);

function paint(stepper) {
  const input = stepper.querySelector('input');
  if (stepper.querySelector('.k-stepper-unit')) input.style.setProperty('--k-len', String(valueLength(input.value, input.placeholder)));
  if (input.disabled) return;
  const { min, max } = limits(stepper);
  const raw = input.value.trim();
  const value = Number(formatDecimal(raw));
  const known = raw && Number.isFinite(value);
  stepper.querySelector('[data-d="-1"]').disabled = !known || value <= min;
  stepper.querySelector('[data-d="1"]').disabled = !!known && value >= max;
}

function nudge(stepper, direction) {
  const input = stepper.querySelector('input');
  input.value = String(stepValue(input.value, direction, limits(stepper)));
  paint(stepper);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  stepper.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: { value: Number(input.value) } }));
}

export function wireSteppers(root = document) {
  root.querySelectorAll('.k-stepper[data-kokuen-stepper="auto"]').forEach(stepper => {
    if (stepper.dataset.kokuenStepperReady === '1') return;
    stepper.dataset.kokuenStepperReady = '1';
    paint(stepper);
    stepper.addEventListener('click', event => {
      const button = event.target.closest('button[data-d]');
      if (button && !button.disabled) nudge(stepper, Number(button.dataset.d));
    });
    const input = stepper.querySelector('input');
    input.addEventListener('input', () => paint(stepper));
    input.addEventListener('focus', () => input.select());
    // arrow keys step like a spin field, so the keyboard needs no trip to the buttons
    input.addEventListener('keydown', event => {
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
      event.preventDefault();
      const button = stepper.querySelector(`[data-d="${event.key === 'ArrowUp' ? 1 : -1}"]`);
      if (!button.disabled) nudge(stepper, event.key === 'ArrowUp' ? 1 : -1);
    });
  });
}
