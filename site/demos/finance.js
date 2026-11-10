// the finance app, as in shots/finance.webp. every account, transaction and renewal is made up.
// spent this month and the category rows are summed from this month's transactions
import { h, ic, css, topbar, toast } from './kit.js';

const ACCOUNTS = [
  { name: 'Chequing', bal: 5361.25, ch: 1321.25, spark: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.9, 0.85, 0.9, 0.7, 0.6, 0.45, 0.4, 0.1, 0.2, 0.15, 0.85, 0.95] },
  { name: 'Savings', bal: 10200.0, ch: 1000.0, spark: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.45, 0.9] },
  { name: 'Visa', bal: -125.67, ch: 194.33, spark: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.12, 0.95, 0.9, 0.95, 0.9, 0.85, 0.8, 0.78, 0.75] },
];

// day = days before sunday, nov 8, 2026. nov 1 is 7 days ago
const TX = [
  { name: 'Transfer from Chequing', day: 1, acct: 'Savings', cat: 'transfer', amt: 500.0 },
  { name: 'Transfer to Savings', day: 1, acct: 'Chequing', cat: 'transfer', amt: -500.0 },
  { name: 'Loblaws', day: 1, acct: 'Visa', cat: 'food', amt: -86.45 },
  { name: 'Rosewood Cafe', day: 2, acct: 'Visa', cat: 'food', amt: -38.4 },
  { name: 'Fieldnote payroll', day: 2, acct: 'Chequing', cat: 'income', amt: 3150.0 },
  { name: 'Daily Brew Coffee', day: 3, acct: 'Visa', cat: 'food', amt: -7.25 },
  { name: 'Indigo', day: 4, acct: 'Visa', cat: 'shopping', amt: -72.0 },
  { name: 'Pizzeria Libretto', day: 4, acct: 'Visa', cat: 'food', amt: -22.8 },
  { name: 'Uber', day: 4, acct: 'Visa', cat: 'transport', amt: -52.3 },
  { name: 'Cineplex Yonge', day: 4, acct: 'Visa', cat: 'entertainment', amt: -15.99 },
  { name: 'Clay Collective', day: 5, acct: 'Chequing', cat: 'shopping', amt: -129.0 },
  { name: 'Presto reload', day: 6, acct: 'Chequing', cat: 'transport', amt: -60.0 },
  { name: 'Steam', day: 6, acct: 'Chequing', cat: 'entertainment', amt: -15.99 },
  { name: 'Maple Court rent', day: 7, acct: 'Chequing', cat: 'bills', amt: -1850.0 },
  { name: 'Daily Brew Coffee', day: 8, acct: 'Visa', cat: 'food', amt: -6.85 },
  { name: 'Fieldnote payroll', day: 16, acct: 'Chequing', cat: 'income', amt: 3150.0 },
];
const LAST_MONTH = 3344.24;

// day offset from today, days ahead
const RENEWALS = [
  { name: 'iCloud+', ahead: 1, when: 'tomorrow', price: 3.99 },
  { name: 'Netflix', ahead: 4, when: 'thu', price: 16.49 },
  { name: 'Spotify', ahead: 9, when: 'in 9 days', price: 11.99 },
  { name: 'Adobe Creative Cloud', ahead: 12, when: 'in 12 days', price: 59.99 },
  { name: 'Figma', ahead: 14, when: 'nov 22', price: 15.0 },
];

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const dateOf = (offset) => { const d = new Date(2026, 10, 8 + offset); return `${MONTHS[d.getMonth()]} ${d.getDate()}`; };
const dayDate = (offset) => { const d = new Date(2026, 10, 8 + offset); return `${DAYS[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}`; };
const txWhen = (d) => (d === 0 ? 'today' : d === 1 ? 'yesterday' : d <= 7 ? `${d} days ago` : dateOf(-d));
const money = (n) => Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = (n) => `USD ${money(n)}`;
const signed = (n) => `${n < 0 ? '−' : '+'}USD ${money(n)}`;

export default function build(root) {
  css('finance');
  root.classList.add('fn');
  const st = { acct: null, cat: null, q: '' };
  const thisMonth = () => TX.filter((t) => t.day <= 7 && t.amt < 0 && t.cat !== 'transfer');
  const spent = () => thisMonth().reduce((a, t) => a + -t.amt, 0);
  const cats = () => {
    const sums = {};
    for (const t of thisMonth()) sums[t.cat] = (sums[t.cat] || 0) + -t.amt;
    return Object.entries(sums).sort((a, b) => b[1] - a[1]).slice(0, 5);
  };

  // ---- overview
  const spentCard = h('section', { class: 'fn-card fn-spent' }, h('h4', { text: 'spent this month' }), h('div', { class: 'fn-big', text: usd(spent()) }), h('div', { class: 'fn-sub', text: `last month ${usd(LAST_MONTH)}` }));

  const spark = (vals) => {
    const w = 46;
    const hgt = 18;
    const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(hgt - 1 - v * (hgt - 3)).toFixed(1)}`).join(' ');
    return h('span', { class: 'spark', html: `<svg viewBox="0 0 ${w} ${hgt}" width="${w}" height="${hgt}" aria-hidden="true"><polyline class="fn-spk" points="${pts}"/></svg>` }).firstChild;
  };
  const accBtns = ACCOUNTS.map((a) => h('button', { type: 'button', class: 'fn-line fn-acc', 'aria-pressed': 'false', 'aria-label': `${a.name}, show its transactions`, onclick: () => { st.acct = st.acct === a.name ? null : a.name; paint(); } },
    h('span', { class: 'nm', text: a.name }),
    h('span', { class: 'nums' }, h('span', { text: a.bal < 0 ? `−${usd(a.bal)}` : usd(a.bal) }), h('span', { class: 'ch', text: `${signed(a.ch)} vs last month` })),
    spark(a.spark)));
  const accCard = h('section', { class: 'fn-card fn-mid' }, h('h4', { text: 'accounts' }), accBtns);

  const catBox = h('div');
  const catCard = h('section', { class: 'fn-card fn-mid' }, h('h4', { text: 'top categories' }), catBox);

  const txTitle = h('h4');
  const txBox = h('div');
  const txCard = h('section', { class: 'fn-card fn-low' }, txTitle, txBox);

  const renCard = h('section', { class: 'fn-card fn-low' }, h('h4', { text: 'upcoming renewals' }), RENEWALS.map((r) => h('div', { class: 'fn-line fn-ren' }, h('span', { class: 'nm', text: r.name }), h('span', { class: 'when', text: r.when }), h('span', { class: 'amt', text: usd(r.price) }))));

  const overview = h('div', { class: 'fn-view', 'data-tab': 'overview' }, h('div', { class: 'fn-ov' }, spentCard, accCard, catCard, txCard, renCard));

  const visible = () => TX.filter((t) => (!st.acct || t.acct === st.acct) && (!st.cat || t.cat === st.cat)).sort((a, b) => a.day - b.day);

  // ---- money
  const find = h('input', { type: 'text', class: 'dm-input', placeholder: 'search transactions', 'aria-label': 'search transactions', autocomplete: 'off' });
  const count = h('span', { class: 'n' });
  const table = h('div', { class: 'fn-table' });
  const money_ = h('div', { class: 'fn-view', 'data-tab': 'money', hidden: true }, h('div', { class: 'fn-money' }, h('div', { class: 'fn-find' }, find, count), table));
  find.addEventListener('input', () => { st.q = find.value.trim().toLowerCase(); paintMoney(); });
  find.addEventListener('keydown', (e) => { if (e.key === 'Escape' && find.value) { find.value = ''; st.q = ''; paintMoney(); } });

  // ---- subscriptions
  const total = RENEWALS.reduce((a, r) => a + r.price, 0);
  const subRows = RENEWALS.map((r) => {
    const btn = h('button', { type: 'button', class: 'dm-btn', 'aria-pressed': 'false', 'aria-label': `cancel reminder for ${r.name}` }, h('span', { class: 'ic-slot' }), 'cancel reminder');
    btn.addEventListener('click', () => {
      const on = btn.getAttribute('aria-pressed') !== 'true';
      btn.setAttribute('aria-pressed', String(on));
      btn.firstChild.replaceChildren(...(on ? [ic('bell')] : []));
    });
    return h('div', { class: 'fn-sr' }, h('span', { text: r.name }), h('span', { class: 'd', text: dayDate(r.ahead) }), h('span', { class: 'p', text: usd(r.price) }), btn);
  });
  const subs = h('div', { class: 'fn-view', 'data-tab': 'subscriptions', hidden: true }, h('div', { class: 'fn-subs' }, h('div', { class: 'fn-sh' }, h('strong', { text: 'renewals' }), h('span', { text: `${RENEWALS.length} · ${usd(total)} a month` })), subRows));

  // ---- imports
  const impRow = (name, sub, label, note) => {
    const b = h('button', { type: 'button', class: 'dm-btn', text: label });
    b.addEventListener('click', () => toast(root, note));
    return h('div', { class: 'fn-ir' }, h('div', {}, h('strong', { text: name }), h('span', { text: sub })), b);
  };
  const imports = h('div', { class: 'fn-view', 'data-tab': 'imports', hidden: true }, h('div', { class: 'fn-imp' },
    impRow('file', 'csv from your bank', 'import a file', 'in alles you pick the account and file, preview the rows, then apply them'),
    impRow('bank', 'simplefin or plaid', 'connect a bank', 'in alles this links your bank and syncs new transactions')));

  // ---- painting
  const lineTx = (t) => h('div', { class: 'fn-line fn-tx' }, h('span', { class: 'nm', text: t.name }), h('span', { class: 'when', text: txWhen(t.day) }), h('span', { class: 'amt', text: signed(t.amt) }));
  const paint = () => {
    accBtns.forEach((b, i) => b.setAttribute('aria-pressed', String(st.acct === ACCOUNTS[i].name)));
    catBox.replaceChildren(...cats().map(([name, sum]) => h('button', { type: 'button', class: 'fn-line fn-cat', 'aria-pressed': String(st.cat === name), 'aria-label': `${name}, show its transactions`, onclick: () => { st.cat = st.cat === name ? null : name; paint(); } }, h('span', { class: 'nm', text: name }), h('span', { class: 'amt', text: usd(sum) }))));
    const tags = [st.acct, st.cat].filter(Boolean).join(' · ');
    txTitle.replaceChildren('recent transactions', tags ? h('span', { text: tags }) : '');
    const rows = visible().slice(0, 10);
    txBox.replaceChildren(...(rows.length ? rows.map(lineTx) : [h('p', { class: 'fn-none', text: 'no transactions' })]));
  };
  const paintMoney = () => {
    const rows = TX.filter((t) => {
      if (!st.q) return true;
      return [t.name, t.acct, t.cat, signed(t.amt), txWhen(t.day)].join(' ').toLowerCase().includes(st.q);
    }).sort((a, b) => a.day - b.day);
    count.textContent = `${rows.length} transaction${rows.length === 1 ? '' : 's'}`;
    table.replaceChildren(
      h('div', { class: 'fn-th' }, h('span', { text: 'date' }), h('span', { text: 'description' }), h('span', { text: 'account' }), h('span', { text: 'category' }), h('span', { text: 'amount' })),
      ...(rows.length
        ? rows.map((t) => h('div', { class: 'fn-tr' }, h('span', { text: txWhen(t.day) }), h('span', { text: t.name }), h('span', { class: 'c2', text: t.acct }), h('span', { class: 'c2', text: t.cat }), h('span', { text: signed(t.amt) })))
        : [h('p', { class: 'fn-none', text: 'no matches' })]));
  };

  const guide = h('button', { type: 'button', class: 'dm-btn fn-guide', text: 'finance guide' });
  guide.addEventListener('click', () => toast(root, 'in alles this opens the finance guide, with steps for each tab'));
  const panels = [overview, money_, subs, imports];
  const bar = topbar({
    app: 'finance',
    tabs: ['overview', 'money', 'subscriptions', 'imports'],
    selected: 'overview',
    onTab: (name) => panels.forEach((p) => { p.hidden = p.dataset.tab !== name; }),
    right: guide,
  });
  root.append(bar.el, ...panels);
  paint();
  paintMoney();
}
