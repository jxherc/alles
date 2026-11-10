// the inbox app's mail view, as in shots/inbox.webp: folders, message list, reading pane.
// every message is made up
import { h, ic, css, topbar, menu, toast } from './kit.js';

const ME = { name: 'Maya Okafor', email: 'maya.okafor@maplemail.ca' };
const FOLDERS = [
  ['inbox', 'mail'], ['primary', 'user'], ['social', 'comment'], ['promotions', 'tag'], ['unread', 'bell'], ['flagged', 'bookmark'],
  ['vip', 'star'], ['muted', 'mute'], ['snoozed', 'snooze'], ['sent', 'send'], ['drafts', 'edit'],
];

const MSGS = [
  { id: 'jordan', from: 'Jordan Reyes', email: 'jordan@fieldnote.co', subject: 'Re: Q4 roadmap comments', date: 'Nov 8', when: 'Sun, Nov 8, 2026 · 1:15 AM', cat: 'primary',
    body: "Hi Maya,\n\nRead through the roadmap last night. Two thoughts:\n\n1. The onboarding goal looks right. Can we get a rough prototype in front of Marcus by Tuesday so he can scope the permissions screen?\n2. I'd like to talk about shipping shared notebooks behind a flag. Let's use our 1:1.\n\nThanks for the clear write-up.\n\nJordan",
    summary: ['wants a prototype in front of marcus by tuesday.', 'also wants to talk about shared notebooks in your 1:1.'],
    task: 'rough prototype to Marcus by Tuesday', event: 'prototype due, Tue Nov 10' },
  { id: 'priya', from: 'Priya Nair', email: 'priya@fieldnote.co', subject: 'Brunch tomorrow?', date: 'Nov 7', when: 'Sat, Nov 7, 2026 · 6:42 PM', cat: 'social', unread: true, vip: true,
    body: "Hey Maya,\n\nAre you free for brunch tomorrow? I found a place on Queen West that does a good shakshuka. 11:30 works for me, but I can do noon if you'd rather sleep in.\n\nPriya",
    summary: ['asks you to brunch tomorrow on queen west.', 'suggests 11:30, or noon if you want to sleep in.'],
    task: 'reply to Priya about brunch', event: 'brunch with Priya, Sun Nov 8, 11:30 am' },
  { id: 'clay', from: 'Clay Collective', email: 'orders@claycollective.example', subject: 'Your glaze order is ready for pickup', date: 'Nov 7', when: 'Sat, Nov 7, 2026 · 2:05 PM', cat: 'promotions', unread: true,
    body: "Hi Maya,\n\nYour glaze order (2 x celadon, 1 x tenmoku) is ready for pickup at the studio. We're open Tuesday to Saturday, 10 am to 6 pm.\n\nThe Clay Collective team",
    summary: ['your glaze order (2 celadon, 1 tenmoku) is ready.', 'pickup is tuesday to saturday, 10 am to 6 pm.'],
    task: 'pick up glaze order', event: 'glaze pickup at Clay Collective' },
  { id: 'margin', from: 'Margin Notes', email: 'hello@marginnotes.example', subject: 'Would you write for us?', date: 'Nov 7', when: 'Sat, Nov 7, 2026 · 9:30 AM', cat: 'social',
    body: "Hi Maya,\n\nWe run a small newsletter about note-taking tools and liked your post on keeping a weekly review. Would you write a short guest piece (about 600 words) for our December issue?\n\nSana\nMargin Notes",
    summary: ['wants a 600 word guest piece for december.', 'they liked your post on weekly reviews.'],
    task: 'answer Margin Notes about a guest piece', event: 'guest piece for Margin Notes, due Dec 1' },
  { id: 'air', from: 'Air Portugal', email: 'bookings@airportugal.example', subject: 'Your trip to Lisbon: booking confirmation', date: 'Nov 6', when: 'Fri, Nov 6, 2026 · 8:12 PM', cat: 'promotions', flagged: true,
    body: "Hello Maya,\n\nYour booking is confirmed. Reference: KX4P2R.\n\nToronto (YYZ) to Lisbon (LIS)\nFri, Dec 11 · departs 9:45 PM · arrives Sat, Dec 12 at 9:20 AM\n\nLisbon (LIS) to Toronto (YYZ)\nSun, Dec 20 · departs 11:10 AM\n\nOnline check-in opens 48 hours before departure.\n\nAir Portugal",
    summary: ['toronto to lisbon fri dec 11, 9:45 pm.', 'home sun dec 20, 11:10 am. ref KX4P2R.'],
    task: 'check in for the Lisbon flight', event: 'flight to Lisbon, Fri Dec 11, 9:45 pm' },
  { id: 'maple', from: 'Maple Court Apartments', email: 'office@maplecourt.example', subject: 'Parking spot update', date: 'Nov 6', when: 'Fri, Nov 6, 2026 · 11:00 AM', cat: 'primary',
    body: "Hi Maya,\n\nThe P2 garage is being resurfaced, so your spot moves from P2-14 to P2-31 until Nov 30. P2-31 is next to the elevator.\n\nPlease move your car by Monday evening.\n\nMaple Court Management",
    summary: ['your parking spot moves to P2-31 until nov 30.', 'move the car by monday evening.'],
    task: 'move car to P2-31 by Monday', event: 'move car to P2-31, Mon Nov 9' },
  { id: 'marcus', from: 'Marcus Tran', email: 'marcus@fieldnote.co', subject: 'Permissions screen: a few questions', date: 'Nov 5', when: 'Thu, Nov 5, 2026 · 4:48 PM', cat: 'primary', vip: true,
    body: "Maya,\n\nA few questions on the permissions screen before I start:\n\n1. Do viewers see the share link, or only editors?\n2. Is \"can comment\" its own role?\n3. What happens to existing notebooks on Nov 20?\n\nMarcus",
    summary: ['three questions before he starts the permissions screen.', 'share link, a comment role, and old notebooks.'],
    task: "answer Marcus's permissions questions", event: 'permissions screen sync with Marcus' },
  { id: 'bloor', from: 'Bloor Dental', email: 'reminders@bloordental.example', subject: 'Appointment reminder: Tue Nov 10, 4:30 pm', date: 'Nov 5', when: 'Thu, Nov 5, 2026 · 9:00 AM', cat: 'primary', flagged: true,
    body: "Hi Maya,\n\nThis is a reminder of your cleaning on Tuesday, Nov 10 at 4:30 PM with Dr. Silva.\n\nPlease arrive 10 minutes early. If you need to move it, call us at least 24 hours ahead.\n\nBloor Dental",
    summary: ['cleaning with dr. silva, tue nov 10 at 4:30 pm.', 'arrive 10 minutes early; call 24 hours ahead to move it.'],
    task: 'dentist, Tue Nov 10, 4:30 pm', event: 'dentist, Tue Nov 10, 4:30 pm' },
  { id: 's1', folder: 'sent', to: 'Jordan Reyes', toEmail: 'jordan@fieldnote.co', subject: 'Q4 roadmap draft', date: 'Nov 6', when: 'Fri, Nov 6, 2026 · 5:20 PM',
    body: "Hi Jordan,\n\nThe Q4 roadmap draft is in docs. The targets table is the part I'd like your eyes on.\n\nMaya",
    summary: ['you sent the q4 roadmap draft to jordan.', 'you asked him to check the targets table.'], task: 'follow up with Jordan on the roadmap', event: 'roadmap review with Jordan' },
  { id: 's2', folder: 'sent', to: 'Clay Collective', toEmail: 'orders@claycollective.example', subject: 'Glaze order question', date: 'Nov 3', when: 'Tue, Nov 3, 2026 · 12:05 PM',
    body: "Hello,\n\nCould I add one more jar of tenmoku to my glaze order? I'll pick everything up together.\n\nThanks,\nMaya",
    summary: ['you asked for one more tenmoku jar.', 'you will pick everything up together.'], task: 'check the glaze order', event: 'glaze pickup' },
  { id: 'd1', folder: 'drafts', to: 'Priya Nair', toEmail: 'priya@fieldnote.co', subject: 'Reading list', date: 'Nov 8', when: 'Sun, Nov 8, 2026 · 12:40 AM',
    body: "Hey Priya,\n\nHere is the reading list I mentioned: the two essays on weekly reviews and the one on keeping notes small.\n\n(more to add)",
    summary: ['unfinished note to priya with your reading list.', 'it still needs more links.'], task: 'finish the reading list for Priya', event: 'send reading list to Priya' },
];
for (const m of MSGS) m.folder = m.folder || 'inbox';

const letter = (n) => n.replace(/^to /, '')[0].toUpperCase();
let uid = 0;
const who = (m) => (m.folder === 'sent' || m.folder === 'drafts' ? 'to ' + m.to : m.from);

export default function build(root) {
  css('inbox');
  const st = { folder: 'inbox', q: '', sel: 'jordan', pin: null, view: 'msg', side: true, composeFrom: 'msg' };
  const get = (id) => MSGS.find((m) => m.id === id);

  // ---- mail panel pieces
  const folderBtns = FOLDERS.map(([name, icon]) => h('button', { type: 'button', class: 'ib-folder', 'data-folder': name, 'aria-current': String(name === st.folder) }, ic(icon), name));
  const side = h('nav', { class: 'ib-side', 'aria-label': 'folders' }, folderBtns);

  const menuBtn = h('button', { type: 'button', class: 'dm-btn icon quiet', 'aria-label': 'show or hide folders', 'aria-pressed': 'true' }, ic('menu'));
  const acct = h('button', { type: 'button', class: 'ib-acct', 'data-value': 'Maya', 'aria-label': 'account' }, h('span', { text: 'Maya' }), ic('chevron-down'));
  const search = h('input', { type: 'text', class: 'dm-input ib-search', placeholder: 'search mail...', 'aria-label': 'search mail', autocomplete: 'off' });
  const refresh = h('button', { type: 'button', class: 'dm-btn', text: 'refresh' });
  const compose = h('button', { type: 'button', class: 'dm-btn primary', text: 'compose' });
  const gear = h('button', { type: 'button', class: 'dm-btn icon quiet', 'aria-label': 'mail settings' }, ic('gear'));
  const tools = h('div', { class: 'ib-tools' }, menuBtn, acct, search, h('span', { class: 'dm-spacer' }), refresh, compose, gear);
  const list = h('div', { class: 'ib-list', role: 'list', 'aria-label': 'messages' });

  // reading pane, built once and filled by show()
  const rSubj = h('h4', { class: 'ib-subj' });
  const rAv = h('span', { class: 'ib-av big' });
  const rName = h('strong');
  const rMail = h('span');
  const rTo = h('div', { class: 'ib-to' });
  const bUnread = h('button', { type: 'button', class: 'ib-act' }, 'unread');
  const bVip = h('button', { type: 'button', class: 'ib-act', 'aria-pressed': 'false' });
  const bTask = h('button', { type: 'button', class: 'ib-act' }, ic('check-circle'), 'make a task');
  const bCal = h('button', { type: 'button', class: 'ib-act' }, ic('calendar'), 'add to calendar');
  const bSum = h('button', { type: 'button', class: 'ib-act', 'aria-pressed': 'false' }, 'summarize');
  const bFlag = h('button', { type: 'button', class: 'dm-btn icon', 'aria-label': 'flag', title: 'flag', 'aria-pressed': 'false' });
  const bReply = h('button', { type: 'button', class: 'dm-btn', text: 'reply' });
  const head = h('div', { class: 'ib-head' },
    h('div', { class: 'ib-acc', text: 'Maya' }), rSubj,
    h('div', { class: 'ib-from' }, rAv, rName, rMail), rTo,
    h('div', { class: 'ib-acts' }, bUnread, bVip, bTask, bCal, bSum),
    h('div', { class: 'ib-top-r' }, bFlag, bReply));
  const sumP = [h('p'), h('p')];
  const sum = h('div', { class: 'ib-sum', hidden: true }, sumP);
  const text = h('p', { class: 'ib-text' });
  const replied = h('div', { class: 'ib-replied', hidden: true }, h('b', {}, ic('check'), 'you replied'), h('p'));
  const replyTa = h('textarea', { class: 'ib-ta', placeholder: 'reply...', 'aria-label': 'reply' });
  const send = h('button', { type: 'button', class: 'dm-btn primary', text: 'send', disabled: true });
  const discard = h('button', { type: 'button', class: 'dm-btn quiet', text: 'discard' });
  const reply = h('div', { class: 'ib-reply', hidden: true }, replyTa, h('div', { class: 'ib-btns' }, discard, send));
  const msgView = h('div', { class: 'ib-msg', hidden: true }, head, h('div', { class: 'ib-scroll' }, sum, text, replied), reply);

  const empty = h('div', { class: 'ib-empty', text: 'no message selected', hidden: true });

  const cTo = h('input', { type: 'text', class: 'dm-input', 'aria-label': 'to', autocomplete: 'off' });
  const cSub = h('input', { type: 'text', class: 'dm-input', 'aria-label': 'subject', autocomplete: 'off' });
  const cBody = h('textarea', { class: 'ib-ta', 'aria-label': 'message' });
  const cSend = h('button', { type: 'button', class: 'dm-btn primary', text: 'send', disabled: true });
  const cDiscard = h('button', { type: 'button', class: 'dm-btn quiet', text: 'discard' });
  const composeView = h('div', { class: 'ib-compose', hidden: true },
    h('h4', { text: 'new message' }),
    h('div', { class: 'ib-field' }, h('label', { text: 'to' }), cTo),
    h('div', { class: 'ib-field' }, h('label', { text: 'subject' }), cSub),
    cBody, h('div', { class: 'ib-btns' }, cDiscard, cSend));

  const reader = h('div', { class: 'ib-reader' }, empty, msgView, composeView);
  const mail = h('div', { class: 'ib-panel ib-mail', 'data-tab': 'mail' }, side, h('div', { class: 'ib-main' }, tools, h('div', { class: 'ib-cols' }, list, reader)));

  // ---- overview and contacts
  const overview = h('div', { class: 'ib-panel ib-page', 'data-tab': 'overview', hidden: true });
  const contacts = h('div', { class: 'ib-panel ib-page', 'data-tab': 'contacts', hidden: true });

  const bar = topbar({
    app: 'inbox', tabs: ['overview', 'mail', 'contacts'], selected: 'mail',
    onTab: (name) => { st.tab = name; if (name === 'overview') drawOverview(); if (name === 'contacts') drawContacts(); showTab(); },
  });
  bar.el.classList.add('ib-top');
  root.append(bar.el, mail, overview, contacts);
  const showTab = () => [mail, overview, contacts].forEach((p) => { p.hidden = p.dataset.tab !== st.tab; });

  // ---- list
  const inFolder = (m) => {
    const f = st.folder;
    if (f === 'sent' || f === 'drafts') return m.folder === f;
    if (m.folder !== 'inbox') return false;
    if (f === 'inbox') return true;
    const open = m.id === st.pin;
    if (f === 'unread') return m.unread || open;
    if (f === 'flagged') return m.flagged || open;
    if (f === 'vip') return m.vip || open;
    if (f === 'primary' || f === 'social' || f === 'promotions') return m.cat === f;
    return false;
  };
  const matches = (m) => {
    const q = st.q.trim().toLowerCase();
    return !q || [m.from, m.to, m.subject, m.email].some((s) => (s || '').toLowerCase().includes(q));
  };
  const visible = () => MSGS.filter((m) => inFolder(m) && matches(m));

  function drawList() {
    const was = root.contains(document.activeElement) && document.activeElement.dataset.id;
    const rows = visible().map((m) => h('button', {
      type: 'button', role: 'listitem', class: 'ib-row' + (m.unread ? ' unread' : ''), 'data-id': m.id,
      'aria-current': String(st.view === 'msg' && m.id === st.sel),
      onclick: () => open(m.id),
    }, h('span', { class: 'ib-l1' }, h('span', { class: 'ib-av', text: letter(who(m)) }), h('span', { class: 'ib-name', text: who(m) }), h('span', { class: 'ib-date', text: m.date })),
    h('span', { class: 'ib-sub', text: m.subject })));
    list.replaceChildren(...(rows.length ? rows : [h('p', { class: 'ib-none', text: 'no messages' })]));
    if (was) list.querySelector(`[data-id="${was}"]`)?.focus({ preventScroll: true });
  }

  // ---- reading pane
  function setView(v) {
    st.view = v;
    empty.hidden = v !== 'empty';
    msgView.hidden = v !== 'msg';
    composeView.hidden = v !== 'compose';
  }
  function paintToggles(m) {
    bVip.replaceChildren(ic(m.vip ? 'check' : 'plus'), 'VIP');
    bVip.setAttribute('aria-pressed', String(!!m.vip));
    bFlag.replaceChildren(ic(m.flagged ? 'bookmark-fill' : 'bookmark'));
    bFlag.setAttribute('aria-pressed', String(!!m.flagged));
    bFlag.title = m.flagged ? 'unflag' : 'flag';
    bFlag.setAttribute('aria-label', m.flagged ? 'unflag' : 'flag');
  }
  function show(m) {
    const mine = m.folder === 'sent' || m.folder === 'drafts';
    rSubj.textContent = m.subject;
    rAv.textContent = letter(mine ? ME.name : m.from);
    rName.textContent = mine ? ME.name : m.from;
    rMail.textContent = `<${mine ? ME.email : m.email}>`;
    rTo.textContent = mine ? `to ${m.to} <${m.toEmail}> · ${m.when}` : `to ${ME.name} <${ME.email}> · ${m.when}`;
    text.textContent = m.body;
    sumP[0].textContent = m.summary[0];
    sumP[1].textContent = m.summary[1];
    sum.hidden = true;
    bSum.setAttribute('aria-pressed', 'false');
    replied.hidden = !m.replied;
    if (m.replied) replied.querySelector('p').textContent = m.replied;
    closeReply();
    paintToggles(m);
    setView('msg');
  }
  function open(id) {
    const m = get(id);
    st.sel = id;
    st.pin = id;
    m.unread = false;
    show(m);
    drawList();
  }
  const cur = () => get(st.sel);

  function openReply() {
    const m = cur();
    const to = m.folder === 'sent' || m.folder === 'drafts' ? m.to : m.from;
    replyTa.placeholder = `reply to ${to}...`;
    replyTa.setAttribute('aria-label', `reply to ${to}`);
    reply.hidden = false;
    bReply.setAttribute('aria-expanded', 'true');
    replyTa.focus({ preventScroll: true });
  }
  function closeReply(focus) {
    reply.hidden = true;
    replyTa.value = '';
    send.disabled = true;
    bReply.setAttribute('aria-expanded', 'false');
    if (focus) bReply.focus();
  }
  bReply.addEventListener('click', () => (reply.hidden ? openReply() : closeReply(true)));
  discard.addEventListener('click', () => closeReply(true));
  replyTa.addEventListener('input', () => { send.disabled = !replyTa.value.trim(); });
  replyTa.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeReply(true); } });
  send.addEventListener('click', () => {
    const m = cur();
    const body = replyTa.value.trim();
    if (!body) return;
    m.replied = body;
    const mine = m.folder === 'sent' || m.folder === 'drafts';
    MSGS.unshift({ id: 'r' + uid++, folder: 'sent', to: mine ? m.to : m.from, toEmail: mine ? m.toEmail : m.email, subject: m.subject.startsWith('Re:') ? m.subject : 'Re: ' + m.subject, date: 'Nov 8', when: 'Sun, Nov 8, 2026 · just now', body, summary: [`you replied to ${mine ? m.to : m.from}.`, body.slice(0, 70)], task: m.task, event: m.event });
    closeReply();
    replied.hidden = false;
    replied.querySelector('p').textContent = body;
    bReply.focus();
    toast(root, 'sent');
  });

  bUnread.addEventListener('click', () => {
    const m = cur();
    m.unread = true;
    setView('empty');
    drawList();
    list.querySelector(`[data-id="${m.id}"]`)?.focus({ preventScroll: true });
  });
  bVip.addEventListener('click', () => { const m = cur(); st.pin = m.id; m.vip = !m.vip; paintToggles(m); toast(root, m.vip ? `${m.from || m.to} added to vip` : `${m.from || m.to} removed from vip`); drawList(); });
  bFlag.addEventListener('click', () => { const m = cur(); st.pin = m.id; m.flagged = !m.flagged; paintToggles(m); toast(root, m.flagged ? 'flagged' : 'flag removed'); drawList(); });
  bTask.addEventListener('click', () => toast(root, `added to tasks: ${cur().task}`));
  bCal.addEventListener('click', () => toast(root, `added to calendar: ${cur().event}`));
  bSum.addEventListener('click', () => {
    sum.hidden = !sum.hidden;
    bSum.setAttribute('aria-pressed', String(!sum.hidden));
  });

  // ---- compose
  const canSend = () => { cSend.disabled = !(cTo.value.trim() && cBody.value.trim()); };
  [cTo, cSub, cBody].forEach((el) => {
    el.addEventListener('input', canSend);
    el.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeCompose(true); } });
  });
  compose.addEventListener('click', () => {
    if (st.view !== 'compose') st.composeFrom = st.view;
    cTo.value = cSub.value = cBody.value = '';
    cSend.disabled = true;
    setView('compose');
    drawList();
    cTo.focus({ preventScroll: true });
  });
  function closeCompose(focus) {
    setView(st.composeFrom === 'msg' && st.sel ? 'msg' : 'empty');
    drawList();
    if (focus) compose.focus();
  }
  cDiscard.addEventListener('click', () => closeCompose(true));
  cSend.addEventListener('click', () => {
    const to = cTo.value.trim();
    const known = MSGS.find((m) => m.from && m.from.toLowerCase() === to.toLowerCase());
    MSGS.unshift({ id: 'c' + uid++, folder: 'sent', to: known ? known.from : to, toEmail: known ? known.email : to, subject: cSub.value.trim() || '(no subject)', date: 'Nov 8', when: 'Sun, Nov 8, 2026 · just now', body: cBody.value.trim(), summary: [`you wrote to ${to}.`, cBody.value.trim().slice(0, 70)], task: cSub.value.trim() || 'follow up', event: cSub.value.trim() || 'follow up' });
    st.composeFrom = 'empty';
    closeCompose(true);
    toast(root, 'sent');
  });

  // ---- toolbar and folders
  folderBtns.forEach((b) => b.addEventListener('click', () => {
    st.folder = b.dataset.folder;
    st.pin = null;
    folderBtns.forEach((x) => x.setAttribute('aria-current', String(x === b)));
    drawList();
  }));
  search.addEventListener('input', () => { st.q = search.value; drawList(); });
  search.addEventListener('keydown', (e) => { if (e.key === 'Escape' && search.value) { e.preventDefault(); search.value = ''; st.q = ''; drawList(); } });
  refresh.addEventListener('click', () => toast(root, 'up to date'));
  gear.addEventListener('click', () => toast(root, 'in alles this opens mail settings'));
  menuBtn.addEventListener('click', () => {
    st.side = !st.side;
    side.hidden = !st.side;
    menuBtn.setAttribute('aria-pressed', String(st.side));
  });
  menu(acct, ['Maya', 'add account'], (it) => { if (it === 'add account') toast(root, 'in alles this connects another mailbox'); });

  // ---- overview and contacts content
  const goMail = (folder, q = '') => {
    st.folder = folder;
    st.pin = null;
    st.q = q;
    search.value = q;
    folderBtns.forEach((x) => x.setAttribute('aria-current', String(x.dataset.folder === folder)));
    st.tab = 'mail';
    bar.select('mail');
    drawList();
  };
  function drawOverview() {
    const inbox = MSGS.filter((m) => m.folder === 'inbox');
    const card = (n, label, folder, btn) => h('div', { class: 'dm-panel ib-card' }, h('strong', { text: String(n) }), h('span', { class: 'dm-muted', text: label }), h('button', { type: 'button', class: 'dm-btn', onclick: () => goMail(folder) }, btn));
    const soon = inbox.filter((m) => /Nov 10|Dec 11|Mon Nov 9/.test(m.event || ''));
    overview.replaceChildren(
      h('div', { class: 'ib-cards' },
        card(inbox.filter((m) => m.unread).length, 'unread', 'unread', 'open unread'),
        card(inbox.filter((m) => m.flagged).length, 'flagged', 'flagged', 'open flagged'),
        card(inbox.filter((m) => m.vip).length, 'from vip', 'vip', 'open vip')),
      h('p', { class: 'ib-sech', text: 'coming up' }),
      ...soon.map((m) => h('button', { type: 'button', class: 'ib-line', onclick: () => { goMail('inbox'); open(m.id); } }, h('span', { class: 'ib-name', text: m.event }), h('span', { class: 'ib-date', text: m.from }))));
  }
  function drawContacts() {
    const seen = new Map();
    for (const m of MSGS) if (m.folder === 'inbox' && !seen.has(m.from)) seen.set(m.from, { name: m.from, email: m.email, n: 0 });
    for (const m of MSGS) if (m.folder === 'inbox') seen.get(m.from).n++;
    contacts.replaceChildren(h('p', { class: 'ib-sech', style: 'margin-top: 0', text: 'contacts' }),
      ...[...seen.values()].map((c) => h('button', { type: 'button', class: 'ib-line', onclick: () => goMail('inbox', c.name) },
        h('span', { class: 'ib-av', text: letter(c.name) }), h('span', { class: 'ib-name', text: c.name }), h('span', { class: 'ib-mail-addr', text: c.email }), h('span', { class: 'ib-date', text: c.n + (c.n === 1 ? ' message' : ' messages') }))));
  }

  show(get('jordan'));
  drawList();
}
