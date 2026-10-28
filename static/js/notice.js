import { t } from './i18n.js';
import { icon } from './icons.js';

// a "saved" confirmation clears itself after a while, and has a close button. it waits while the
// pointer is on it or focus is inside, so nobody loses it mid-read
export function dismissAfter(host, ms = 8000) {
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'notice-close';
  close.setAttribute('aria-label', t('common.dismiss'));
  close.innerHTML = icon('close');
  host.append(close);
  let timer = 0, hovered = false;
  const owned = () => close.isConnected && close.parentNode === host;
  const clear = () => {
    clearTimeout(timer);
    if (!owned()) return;
    const hadFocus = host.contains(document.activeElement);
    host.replaceChildren();
    if (hadFocus) document.getElementById('composer-ta')?.focus({ preventScroll: true });
  };
  const arm = () => {
    clearTimeout(timer);
    if (!hovered && !host.contains(document.activeElement)) timer = setTimeout(clear, ms);
  };
  close.addEventListener('click', clear);
  host.onpointerenter = () => { hovered = true; clearTimeout(timer); };
  host.onpointerleave = () => { hovered = false; arm(); };
  host.onfocusin = () => clearTimeout(timer);
  host.onfocusout = () => setTimeout(arm);
  arm();
  return clear;
}
