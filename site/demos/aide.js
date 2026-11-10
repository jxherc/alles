// aide's chat, as in shots/aide.webp and shots/aide-phone.webp: a chat window with replies, a read
// mark and a typing indicator. this copy has no model behind it, so a new message opens the install page
import { h, ic, glyph, css, topbar, menu, toast, needsInstall } from './kit.js';

const svg = (d) => {
  const wrap = document.createElement('span');
  wrap.innerHTML = `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  return wrap.firstChild;
};
// the work and call icons are the app's own
const workIcon = () => svg('<path d="M4 7h16M4 12h10M4 17h7"/><circle cx="18" cy="17" r="3"/>');
const callIcon = () => svg('<path d="M8 3H5a2 2 0 0 0-2 2c0 8.8 7.2 16 16 16a2 2 0 0 0 2-2v-3l-5-2-2 2a14 14 0 0 1-6-6l2-2-2-5Z"/>');

export default function build(root, { variant } = {}) {
  css('aide');
  const phone = variant === 'phone';
  root.classList.add('ai-root');
  if (phone) root.classList.add('ai-phone');
  const say = (text) => toast(root, text);

  // the top bar: work, call and more on the right (the phone keeps only call's word)
  const act = (name, icon, msg, bare) => h('button', { type: 'button', class: 'ai-act' + (bare && phone ? ' bare' : ''), 'aria-label': name, onclick: () => say(msg) }, icon, h('span', { class: 'ai-lab', text: name }));
  const top = topbar({
    app: 'aide',
    right: h('div', { class: 'ai-top' },
      act('work', workIcon(), 'in alles this lists what aide is doing in the background', true),
      act('call', callIcon(), 'in alles this starts a voice call with aide'),
      act('more', ic('more'), 'in alles this opens memory, archive, skills and settings for this chat', true)),
  });
  top.el.classList.add('ai-bar');

  const thread = h('div', { class: 'ai-thread' });
  const stack = h('div', { class: 'ai-stack', role: 'log', 'aria-label': 'conversation', 'aria-live': 'polite' });
  thread.append(stack);

  // what a message turns into when copied
  const plain = (body) => [...body.children].map((el) => (el.matches('ul') ? [...el.children].map((li) => '- ' + li.textContent).join('\n') : el.textContent)).join('\n\n');
  const copy = async (body) => {
    try { await navigator.clipboard.writeText(plain(body)); } catch { /* the toast says it either way */ }
    say('copied');
  };

  const userTurn = (text, read) => h('div', { class: 'ai-turn ai-me' },
    h('div', { class: 'ai-bubble', text }),
    h('div', { class: 'ai-meta' },
      h('button', { type: 'button', class: 'ai-link ai-hov', text: 'remember', onclick: () => say('in alles this saves the message to aide’s memory') }),
      h('button', { type: 'button', class: 'ai-link ai-ico ai-hov', 'aria-label': 'edit message', onclick: () => say('in alles this opens the message to edit and send again') }, ic('edit')),
      h('span', { class: 'ai-read', text: read ? 'read' : '' })));

  const botTurn = (...blocks) => {
    const body = h('div', { class: 'ai-body' }, blocks);
    const more = h('button', { type: 'button', class: 'ai-link ai-ico', 'aria-label': 'more reply actions' }, ic('more'));
    // the kit's menu finds the canvas from its button, so it is wired once the turn is on screen
    const wire = () => {
      menu(more, ['copy', 'remember', 'edit'], (item) => {
        if (item === 'copy') copy(body);
        else if (item === 'remember') say('in alles this saves the answer to aide’s memory');
        else say('in alles this opens the answer to edit it');
      });
      // the reply sits near the bottom, so its menu opens upward (this listener runs after the kit's)
      more.addEventListener('click', () => {
        const list = root.querySelector('.dm-menu');
        if (!list) return;
        const b = more.getBoundingClientRect();
        const r = root.getBoundingClientRect();
        const s = r.width / root.offsetWidth;
        list.style.top = (b.top - r.top) / s - list.offsetHeight - 4 + 'px';
      });
    };
    const turn = h('div', { class: 'ai-turn ai-bot' }, body,
      h('div', { class: 'ai-row' }, h('button', { type: 'button', class: 'ai-link', text: 'copy', onclick: () => copy(body) }), more));
    turn.wire = wire;
    return turn;
  };

  const p = (...kids) => h('p', {}, ...kids);
  const title = (text) => h('p', { class: 'ai-title' }, h('strong', { text }));
  const li = (lead, text) => h('li', {}, h('strong', { text: lead }), ' ' + text);

  stack.append(
    userTurn('can you move my 1:1 with jordan from monday to tuesday? something came up'),
    botTurn(p('Done. Your 1:1 with Jordan is now ', h('strong', { text: 'Tuesday, Nov 10 at 12:30 pm' }), ' (45 min). That slot was free, and it leaves 45 minutes before the onboarding flow review at 2:00.')),
    userTurn('thanks. summarize the q4 roadmap doc for me', true),
    botTurn(
      title('Q4 roadmap in short'),
      h('ul', {},
        li('Goal:', 'ship Fieldnote 2.0 on Nov 20, with onboarding as the focus.'),
        li('Onboarding:', 'cut time to first note from 6 minutes to under 2.'),
        phone
          ? h('li', {}, h('strong', { text: 'Next up:' }), ' ', h('span', { class: 'ai-nb', text: 'shared notebooks Dec 4,' }), ' ', h('span', { class: 'ai-nb', text: 'search Dec 11. Offline mode moved to Q1.' }))
          : li('Next up:', 'shared notebooks Dec 4, search Dec 11. Offline mode moved to Q1.'),
        li('Targets:', 'activation 38% to 55%, week-4 retention 31% to 38%.')),
      p('Only 5 of 8 planned interviews are booked, and Marcus is out Dec 21 to 31.')));
  stack.lastElementChild.previousElementSibling.classList.add('ai-last');

  // the composer
  const input = h('input', { type: 'text', class: 'ai-input', placeholder: 'message...', 'aria-label': 'message', maxlength: '160', autocomplete: 'off' });
  const sendBtn = h('button', { type: 'button', class: 'ai-btn ai-send', 'aria-label': 'send', onclick: () => send() }, ic('arrow-up'));
  input.addEventListener('input', () => sendBtn.classList.toggle('ready', input.value.trim() !== ''));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); send(); }
  });
  const composer = h('div', { class: 'ai-composer' },
    input,
    h('div', { class: 'ai-foot' },
      h('button', { type: 'button', class: 'ai-btn', 'aria-label': 'add', onclick: () => say('in alles this attaches a file or a photo') }, ic('plus')),
      h('button', { type: 'button', class: 'ai-mode', text: 'auto mode', onclick: () => say('in alles this sets what aide may do without asking') }),
      h('span', { class: 'dm-spacer' }),
      h('button', { type: 'button', class: 'ai-model', text: 'your model', onclick: () => say('in alles this picks the model that answers') }),
      h('button', { type: 'button', class: 'ai-btn', 'aria-label': 'dictate', onclick: () => say('in alles this types what you say') }, ic('mic')),
      sendBtn));

  // older messages leave from the top once the newer ones fill the screen
  const prune = () => {
    while (stack.children.length > 2 && stack.offsetHeight - stack.children[1].offsetTop >= thread.clientHeight) stack.firstElementChild.remove();
  };
  // turns cut off at the top can't be seen, so keyboard focus skips their buttons
  const cut = new IntersectionObserver((entries) => entries.forEach((e) => {
    e.target.querySelectorAll('button').forEach((b) => { b.tabIndex = e.intersectionRatio < 0.5 ? -1 : 0; });
  }), { root: thread, threshold: [0, 0.5, 1] });
  const push = (el) => { stack.append(el); el.wire?.(); cut.observe(el); prune(); };

  function send() {
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    input.value = '';
    sendBtn.classList.remove('ready');
    stack.querySelectorAll('.ai-read').forEach((el) => { el.textContent = ''; });
    stack.querySelectorAll('.ai-last').forEach((el) => el.classList.remove('ai-last'));
    const mine = userTurn(text);
    mine.classList.add('ai-last');
    push(mine);
    setTimeout(() => { mine.querySelector('.ai-read').textContent = 'read'; }, 300);
    let typing;
    setTimeout(() => {
      typing = h('div', { class: 'ai-turn ai-bot', role: 'status', 'aria-label': 'aide is typing' }, h('div', { class: 'ai-body' }, h('span', { class: 'ai-dots' }, h('i'), h('i'), h('i'))));
      push(typing);
    }, 500);
    setTimeout(() => {
      typing?.remove();
      needsInstall(root, 'in alles, aide answers with the model you add, and asks before it changes anything.');
    }, 1400);
  }

  const kids = [top.el, thread, composer];
  if (phone) {
    const tab = (app, label, current) => h('button', { type: 'button', class: 'ai-tab', 'aria-current': current ? 'page' : null, onclick: () => {
      if (!current) document.dispatchEvent(new CustomEvent('alles:open-app', { detail: app }));
    } }, glyph(app), h('span', { text: label }));
    kids.push(h('nav', { class: 'ai-tabs', 'aria-label': 'apps' },
      tab('home', 'home'), tab('aide', 'aide', true), tab('plan', 'plan'), tab('docs', 'docs'),
      h('button', { type: 'button', class: 'ai-tab', onclick: () => say('in alles this opens the rest of your apps') }, ic('more'), h('span', { text: 'more' }))));
  }
  root.append(h('div', { class: 'ai' }, kids));
  stack.querySelectorAll('.ai-bot').forEach((el) => el.wire());
  [...stack.children].forEach((el) => cut.observe(el));
}
