import { t } from './i18n.js';
import { icon } from './icons.js';

// one notice rule (27.54): a confirmation ("saved") clears itself after a while; an error stays until
// it's closed, so it's never missed and never stuck. both have a close button.
// a confirmation waits while the pointer is on it or while focus is inside because the person moved it
// there (focusin after the notice appeared). focus that code put there, or that was already inside,
// never holds it: it always clears after its time
function closeButton() {
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'notice-close';
  close.setAttribute('aria-label', t('common.dismiss'));
  close.innerHTML = icon('close');
  return close;
}

// an error line at the top of host with its own close; closing it leaves the rest of host (a retry)
export function errorNotice(host, text) {
  host.querySelector(':scope > .notice-error')?.remove();
  const notice = document.createElement('div');
  notice.className = 'notice-error';
  notice.setAttribute('role', 'alert');
  const line = document.createElement('p');
  line.textContent = text;
  const close = closeButton();
  close.addEventListener('click', () => {
    const hadFocus = notice.contains(document.activeElement);
    notice.remove();
    if (hadFocus) document.getElementById('composer-ta')?.focus({ preventScroll: true });
  });
  notice.append(line, close);
  host.prepend(notice);
  return notice;
}

export function dismissAfter(host, ms = 8000) {
  const close = closeButton();
  host.append(close);
  let timer = 0, hovered = false, focusHeld = false;
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
    if (!hovered && !focusHeld) timer = setTimeout(clear, ms);
  };
  close.addEventListener('click', clear);
  host.onpointerenter = () => { hovered = true; clearTimeout(timer); };
  host.onpointerleave = () => { hovered = false; arm(); };
  host.onfocusin = () => { focusHeld = true; clearTimeout(timer); };
  host.onfocusout = () => { focusHeld = false; setTimeout(arm); };
  arm();
  return clear;
}
