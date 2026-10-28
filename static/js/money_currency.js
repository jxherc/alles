// totals in one currency: the picker, the saved rates, and the note for what a total leaves out.
// money and subscriptions share it, so both say the same thing the same way
import { api, toast } from './util.js';
import { formatNumber, localeTag, t } from './i18n.js';
import { confirm as dlgConfirm, pick as dlgPick, prompt as dlgPrompt } from './dialog.js';

const _si = n => (globalThis.window?.icon ? globalThis.window.icon(n) : '');
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const known = code => /^[A-Z]{3}$/.test(code || '') && code !== 'XXX';

export function amountIn(currency, value) {
  const number = formatNumber(Math.abs(Number(value) || 0), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${Number(value) < 0 ? '−' : ''}${currency}\u00a0${number}`;
}

// "totals in CAD" with the rates it used. after the move to Actual the base can't change, and
// the bar says why
export function currencyBar(summary) {
  const base = summary?.base_currency;
  if (!base?.code) return '';
  if (base.fixed) return `<div class="totals-currency"><span class="totals-currency-lbl">${t('money.totals_follow_actual', { code: `<span class="totals-currency-code">${esc(base.code)}</span>` })}</span></div>`;
  const pick = `<button type="button" class="btn totals-currency-pick" data-totals-base aria-haspopup="dialog" aria-label="${t('money.totals_in_change', { code: esc(base.code) })}">${esc(base.code)}${_si('chevron-down')}</button>`;
  const rates = (summary.rates || []).map(rate =>
    `<button type="button" class="btn totals-rate" data-totals-rate="${esc(rate.from)}:${esc(rate.to)}" aria-label="${t('money.rate_edit', { from: esc(rate.from), rate: esc(rate.rate), to: esc(rate.to) })}">1 ${esc(rate.from)} = ${esc(rate.rate)} ${esc(rate.to)}</button>`).join('');
  return `<div class="totals-currency" role="group" aria-label="${t('money.totals_currency')}"><span class="totals-currency-lbl">${t('money.totals_in')}</span>${pick}${rates}</div>`;
}

// one line per currency left out: what it is, its own subtotal, and the way to bring it in.
// what(row) says what stayed out, eg "2 subscriptions in USD aren't in the total · USD 19.49/mo".
// a rate goes into `base` (the totals currency unless a caller adds up elsewhere). an amount
// with no currency at all takes extra(row) instead. only when nothing at all made it in is
// switching the base offered: then it drops nothing
export function excludedNotes(summary, what, { base = summary?.base_currency?.code, extra = () => '' } = {}) {
  const rows = summary?.excluded || [];
  if (!base || !rows.length) return '';
  const onlyOne = rows.length === 1 && known(rows[0].currency) && summary.included === false
    && base === summary.base_currency?.code && !summary.base_currency?.fixed;
  return rows.map(row => {
    const actions = known(row.currency)
      ? `<button type="button" class="btn" data-totals-rate="${esc(row.currency)}:${esc(base)}">${t('money.add_rate', { code: esc(row.currency) })}</button>`
        + (onlyOne ? `<button type="button" class="btn" data-totals-use="${esc(row.currency)}">${t('money.show_totals_in_code', { code: esc(row.currency) })}</button>` : '')
      : extra(row);
    return `<p class="totals-currency-note" role="status"><span>${esc(what(row))}</span>${actions}</p>`;
  }).join('');
}

// the picker and its notes share one wrapping row: one line on a desk, stacked on a phone
export function totalsCurrency(summary, what, options) {
  const bar = currencyBar(summary);
  return bar ? `<div class="totals-currency-wrap">${bar}${excludedNotes(summary, what, options)}</div>` : '';
}

// a rate is never in the thousands-separator shape, so a comma is its decimal point:
// "1,085" is 1.085. returns the plain decimal text, or null
export function parseRate(value) {
  const text = String(value ?? '').trim().replace(',', '.');
  return /^\d{1,9}(\.\d{1,8})?$/.test(text) && Number(text) > 0 ? text : null;
}

// a new rate far from the saved one is usually a slip (1085 for 1.085): say how far
export function rateJump(previous, next) {
  const ratio = Number(next) / Number(previous);
  if (!(Number(previous) > 0) || !(ratio > 0) || (ratio <= 10 && ratio >= 0.1)) return '';
  return ratio > 10 ? t('money.rate_jump_up', { n: Math.round(ratio) }) : t('money.rate_jump_down', { n: Math.round(1 / ratio) });
}

// "$", "€", "CA$": the sign a person reads, from the browser's own locale data
export function currencySymbol(code) {
  try {
    return new Intl.NumberFormat(localeTag(), { style: 'currency', currency: code, currencyDisplay: 'narrowSymbol' })
      .formatToParts(0).find(part => part.type === 'currency')?.value || code;
  } catch { return code; }
}

export function currencyName(code) {
  try { return new Intl.DisplayNames([localeTag()], { type: 'currency' }).of(code) || code; } catch { return code; }
}

async function chooseBase(current) {
  let codes = [];
  try { codes = (await api('/api/money/currencies')).codes || []; } catch { codes = []; }
  if (!codes.length) { toast(t('money.currency_choices_failed'), 'error'); return null; }
  // the ones already in use come first: picking a base is nearly always one of them
  const inUse = [...document.querySelectorAll('[data-totals-rate]')].flatMap(el => el.dataset.totalsRate.split(':'));
  const first = [...new Set([current, ...inUse])].filter(code => codes.includes(code));
  const options = [...first, ...codes.filter(code => !first.includes(code))]
    .map(value => ({ value, label: `${value} · ${currencyName(value)}`, hint: currencySymbol(value) }));
  return dlgPick(t('money.show_totals_in'), options, { value: current });
}

async function enterRate(from, to, current) {
  let draft = current || '';
  for (;;) {
    const asked = dlgPrompt('', draft, {
      title: t('money.rate_title', { from, to }),
      label: t('money.rate_label', { from, to }),
      hint: t(current ? 'money.rate_hint_clear' : 'money.rate_hint'),
      confirmLabel: t('money.save_rate'),
      validate: value => {
        if (!String(value || '').trim()) return current ? '' : t('money.rate_enter', { from, to });
        return parseRate(value) ? '' : t('money.rate_invalid');
      },
    });
    const field = document.querySelector?.('.dialog-overlay:last-of-type .dialog-input');
    field?.setAttribute('inputmode', 'decimal');
    // turned into a dot as it's typed, before the app's amount formatting reads 1,085 as 1085
    field?.addEventListener('input', () => {
      if (!field.value.includes(',')) return;
      const at = field.selectionStart;
      field.value = field.value.replace(/,/g, '.');
      try { field.setSelectionRange(at, at); } catch {}
    });
    const value = await asked;
    if (value == null) return null;
    if (!String(value).trim()) return '';
    const rate = parseRate(value);
    const jump = rateJump(current, rate);
    if (!jump || await dlgConfirm(t('money.rate_keep', { from, rate, to, jump, current }), { confirmLabel: t('money.keep_it'), danger: false })) return rate;
    draft = rate;
  }
}

// buttons rendered by currencyBar / excludedNotes. reload() redraws the view; focus then goes
// back to the same control, which the redraw replaced
export function wireCurrency(root, summary, reload) {
  const rates = new Map((summary?.rates || []).map(rate => [`${rate.from}:${rate.to}`, rate.rate]));
  const save = async (body, focusSelector, done, from) => {
    // a note inside a card (money's spending caps) keeps the person at that card, not the top
    const card = from?.closest?.('[data-card]')?.dataset.card;
    try { await api('/api/money/totals-currency', { method: 'PATCH', body }); }
    catch (error) { toast(error?.status === 400 ? error.message : t('money.save_failed'), 'error'); return; }
    toast(done, 'success');
    await reload();
    const place = card && document.querySelector(`[data-card="${card}"]`);
    const target = place?.querySelector(focusSelector) || place || document.querySelector(focusSelector) || document.querySelector('[data-totals-base]');
    if (target === place) place.tabIndex = -1;
    target?.focus();
  };
  root.querySelectorAll?.('[data-totals-base]').forEach(button => button.addEventListener('click', async () => {
    const current = summary.base_currency.code;
    const code = await chooseBase(current);
    if (!code || code === current) return;
    await save({ base: code }, '[data-totals-base]', t('money.totals_in_code', { code }));
  }));
  root.querySelectorAll?.('[data-totals-use]').forEach(button => button.addEventListener('click', () => {
    const code = button.dataset.totalsUse;
    save({ base: code }, '[data-totals-base]', t('money.totals_in_code', { code }));
  }));
  root.querySelectorAll?.('[data-totals-rate]').forEach(button => button.addEventListener('click', async () => {
    const [from, to] = button.dataset.totalsRate.split(':');
    const back = rates.get(`${to}:${from}`);
    const current = rates.get(`${from}:${to}`) || (back ? String(+(1 / Number(back)).toPrecision(6)) : '');
    const rate = await enterRate(from, to, current);
    if (rate == null || rate === current) return;
    await save({ rate: { from, to, rate } }, `[data-totals-rate="${from}:${to}"]`, rate ? t('money.rate_saved', { from, rate, to }) : t('money.rate_removed'), button);
  }));
}
