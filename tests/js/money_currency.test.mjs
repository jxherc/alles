import assert from 'node:assert/strict';
import test from 'node:test';

const { amountIn, currencyBar, excludedNotes, totalsCurrency, parseRate, rateJump } = await import('../../static/js/money_currency.js');

const text = html => html.replace(/<[a-z/][^>]*>/gi, ' ').replace(/\s+/g, ' ').trim();
const summary = (more = {}) => ({
  base_currency: { code: 'CAD', fixed: false },
  rates: [],
  excluded: [],
  included: true,
  ...more,
});

test('the picker names the base, and each saved rate reads as an edit button', () => {
  const html = currencyBar(summary({ rates: [{ from: 'USD', to: 'CAD', rate: '1.36', date: '2026-10-24' }] }));
  assert.match(html, /data-totals-base/);
  assert.match(html, /data-totals-rate="USD:CAD"/);
  assert.equal(text(html), 'totals in CAD 1 USD = 1.36 CAD');
  assert.equal(currencyBar({}), '');
  assert.equal(totalsCurrency({}, () => ''), '');
});

test('after the move to Actual the bar says why the base is fixed', () => {
  const fixed = currencyBar(summary({ base_currency: { code: 'SGD', fixed: true } }));
  assert.doesNotMatch(fixed, /data-totals-base|<button/);
  assert.equal(text(fixed), 'totals follow your Actual ledger in SGD');
});

test('a left-out currency gets its own line and the way to bring it in', () => {
  const rows = [{ currency: 'USD', count: 2, total: 19.49 }, { currency: 'XXX', count: 1, total: 4 }];
  const html = excludedNotes(summary({ excluded: rows }), row => `${row.count} in ${row.currency}`,
    { extra: () => '<button type="button" class="btn" data-set-currency="a">set currency</button>' });
  assert.match(html, /data-totals-rate="USD:CAD">add USD rate/);
  // no currency at all can't take a rate: it gets its own action instead
  assert.equal((html.match(/data-totals-rate/g) || []).length, 1);
  assert.match(text(html), /1 in XXX set currency$/);
  assert.doesNotMatch(html, /show totals in/);
  // a note can point its rate at another currency, like the envelope's ledger one
  assert.match(excludedNotes(summary({ excluded: rows.slice(0, 1) }), () => 'x', { base: 'EUR' }), /data-totals-rate="USD:EUR"/);
});

test('switching the base is offered only when nothing at all made it in', () => {
  const rows = [{ currency: 'GBP', count: 1, total: 10 }];
  // a USD account already converts into the totals: switching to GBP would drop it
  assert.doesNotMatch(excludedNotes(summary({ excluded: rows, included: true }), () => 'x'), /show totals in/);
  assert.match(excludedNotes(summary({ excluded: rows, included: false }), () => 'x'), /data-totals-use="GBP">show totals in GBP/);
  const fixed = summary({ base_currency: { code: 'CAD', fixed: true }, excluded: rows, included: false });
  assert.doesNotMatch(excludedNotes(fixed, () => 'x'), /show totals in/);
  assert.equal(amountIn('USD', -1234.5), '−USD 1,234.50');
});

test('a rate takes a comma as its decimal point and flags a far jump', () => {
  assert.equal(parseRate('1,085'), '1.085');
  assert.equal(parseRate(' 1.37 '), '1.37');
  for (const bad of ['1_000', '1e3', '-1', '0', '1.2.3', 'abc', '']) assert.equal(parseRate(bad), null, bad);
  assert.equal(rateJump('1.36', '1.4'), '');
  assert.equal(rateJump('', '1085'), '');
  assert.equal(rateJump('1.085', '1085'), 'about 1000 times the saved rate');
  assert.equal(rateJump('1.36', '0.0136'), 'about 1/100 of the saved rate');
});
