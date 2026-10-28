import { createMenuController } from './kokuen.js?v=4';
import { icon } from './icons.js';
import { t } from './i18n.js';

let sequence = 0;
let opened = null;
const controls = new WeakMap();

// Move the existing buttons, keeping their listeners and message ancestry intact.
// the "context" line (model, memories, sources) joins the reply's own action row, so one quiet
// line under each reply holds copy, more and what Aide used; it opens as a panel under the row
function tuckProvenance(actions) {
  const details = actions.closest('.ai-wrap')?.querySelector('.context-provenance');
  if (!details || details.parentElement === actions) return;
  const summary = details.querySelector('summary');
  if (summary && !summary.dataset.full) {
    const full = summary.textContent.trim();
    const model = full.split('·').pop().split('/').pop().trim();
    summary.dataset.full = full;
    summary.textContent = model ? t('aide.context_model', { model }) : full;
    if (details.dataset.onlyModel && model) {
      const plain = document.createElement('span');
      plain.className = 'context-model';
      plain.textContent = model;
      actions.append(plain);
      details.remove();
      return;
    }
  }
  details.classList.add('is-tucked');
  actions.append(details);
  // it opens in place under the actions; keep what opened in view
  details.addEventListener('toggle', () => {
    if (details.open) details.querySelector('.context-provenance-body')?.scrollIntoView({ block: 'nearest' });
  });
  details.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !details.open) return;
    event.stopPropagation();
    details.open = false;
    details.querySelector('summary')?.focus();
  });
}

export function compactResponseActions(actions) {
  if (!actions || !document.body.classList.contains('aide-central')) return;
  tuckProvenance(actions);
  let control = controls.get(actions);
  if (!control) {
    const menu = document.createElement('div');
    menu.id = `aide-response-actions-${++sequence}`;
    menu.className = 'msg-actions-menu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', t('aide.reply_actions'));
    menu.tabIndex = -1;
    menu.hidden = true;
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'act-btn msg-more-trigger';
    trigger.innerHTML = icon('more');
    trigger.title = t('aide.more_reply_actions');
    trigger.setAttribute('aria-label', t('aide.more_reply_actions'));
    trigger.setAttribute('aria-haspopup', 'menu');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', menu.id);
    actions.classList.add('msg-actions-compact');
    actions.append(trigger, menu);

    let observer = null;
    const close = options => controller.close(options);
    const onOutside = event => {
      if (!menu.contains(event.target) && !trigger.contains(event.target)) close({ restoreFocus: false });
    };
    const onScroll = event => { if (!menu.contains(event.target)) close({ restoreFocus: false }); };
    const onResize = () => close({ restoreFocus: false });
    const cleanup = () => {
      trigger.setAttribute('aria-expanded', 'false');
      document.removeEventListener('pointerdown', onOutside, true);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
      observer?.disconnect();
      observer = null;
      if (opened === control) opened = null;
    };
    const controller = createMenuController(menu, { onClose: cleanup, closeOnOutsidePointer: false });
    const items = () => [...menu.querySelectorAll('button')];
    const position = () => {
      // A previous short viewport must not bias this opening's side choice.
      menu.style.maxHeight = '';
      const anchor = trigger.getBoundingClientRect();
      const bounds = menu.getBoundingClientRect();
      const width = document.documentElement.clientWidth;
      const height = window.innerHeight;
      const tokens = getComputedStyle(actions);
      const gutter = parseFloat(tokens.getPropertyValue('--k-space-4')) || 16;
      const gap = parseFloat(tokens.getPropertyValue('--k-space-1')) || 4;
      const below = Math.max(0, height - gutter - anchor.bottom - gap);
      const above = Math.max(0, anchor.top - gap - gutter);
      const openBelow = bounds.height <= below || (bounds.height > above && below >= above);
      menu.style.maxHeight = `${openBelow ? below : above}px`;
      const top = openBelow ? anchor.bottom + gap : anchor.top - gap - menu.getBoundingClientRect().height;
      menu.style.left = `${Math.max(gutter, Math.min(anchor.left, width - bounds.width - gutter))}px`;
      menu.style.top = `${top}px`;
    };
    const open = (last = false) => {
      if (opened && opened !== control) opened.close({ restoreFocus: false });
      observer?.disconnect();
      controller.open({ source: trigger, focus: false });
      trigger.setAttribute('aria-expanded', 'true');
      opened = control;
      position();
      const enabled = items().filter(item => !item.disabled && item.getAttribute('aria-disabled') !== 'true');
      const initial = (last ? enabled.at(-1) : enabled[0]) || menu;
      initial.focus({ preventScroll: true });
      if (initial !== menu) {
        const item = initial.getBoundingClientRect();
        const top = menu.getBoundingClientRect().top + menu.clientTop;
        const bottom = top + menu.clientHeight;
        if (item.top < top) menu.scrollTop -= top - item.top;
        else if (item.bottom > bottom) menu.scrollTop += item.bottom - bottom;
      }
      document.addEventListener('pointerdown', onOutside, true);
      window.addEventListener('scroll', onScroll, true);
      window.addEventListener('resize', onResize);
      observer = new MutationObserver(() => {
        if (!actions.isConnected) close({ restoreFocus: false });
      });
      observer.observe(document.body, { childList: true, subtree: true });
    };
    trigger.addEventListener('click', () => menu.hidden ? open() : close());
    trigger.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        open(event.key === 'ArrowUp');
      }
    });
    // Close before invoking the existing callback, so its dialog or new focus wins.
    menu.addEventListener('click', event => {
      const item = event.target.closest('button');
      if (item && !item.disabled && item.getAttribute('aria-disabled') !== 'true') close();
    }, true);
    menu.addEventListener('keydown', event => {
      if (event.key === 'Tab') close();
      if (event.key === 'Escape') event.stopPropagation();
    });
    control = { menu, trigger, close };
    controls.set(actions, control);
  }

  for (const button of [...actions.children]) {
    if (button.tagName !== 'BUTTON' || button === control.trigger) continue;
    if (button.dataset.msgAct === 'copy') {
      button.classList.add('msg-copy-action');
      button.setAttribute('aria-label', t('aide.copy_reply'));
      button.type = 'button';
      continue;
    }
    button.type = 'button';
    button.setAttribute('role', 'menuitem');
    button.tabIndex = -1;
    control.menu.appendChild(button);
  }
  control.trigger.hidden = !control.menu.children.length;
}
