// One owner for local History API writes and the URL of the rendered view.
const POSITION_KEY = '__allesRoutePosition';
const hasBrowserHistory = typeof window !== 'undefined'
  && typeof history !== 'undefined'
  && typeof location !== 'undefined';
const routeUrl = () => location.pathname + location.search + location.hash;
const storedPosition = state => Number.isSafeInteger(state?.[POSITION_KEY])
  ? state[POSITION_KEY] : null;
const browserPosition = () => {
  if (!hasBrowserHistory) return null;
  const index = window.navigation?.currentEntry?.index;
  return Number.isSafeInteger(index) && index >= 0 ? index : null;
};
const routeState = () => history.state && typeof history.state === 'object' ? history.state : {};

let position = hasBrowserHistory ? browserPosition() ?? storedPosition(history.state) ?? 0 : 0;
let visibleUrl = hasBrowserHistory ? routeUrl() : '';
if (hasBrowserHistory) history.replaceState({ ...routeState(), [POSITION_KEY]: position }, '', visibleUrl);

export function replaceRouteUrl(url) {
  history.replaceState(history.state, '', url);
  visibleUrl = routeUrl();
}

export function pushRouteUrl(url) {
  const next = (browserPosition() ?? position) + 1;
  history.pushState({ ...routeState(), [POSITION_KEY]: next }, '', url);
  position = next;
  visibleUrl = routeUrl();
}

export function routeHistoryPosition() { return position; }
export function visibleRouteUrl() { return visibleUrl; }
export function targetRoutePosition(state) { return browserPosition() ?? storedPosition(state); }

export function acceptRoutePosition(target) {
  if (target !== null) position = target;
  visibleUrl = routeUrl();
}

export function restoreDeniedRoute(target) {
  const delta = target === null ? 0 : position - target;
  if (delta) {
    history.go(delta);
    return true;
  }
  // An unmarked legacy entry has no reliable direction without a browser index.
  // Keep the edited view and its URL together rather than guessing Back.
  history.replaceState(history.state, '', visibleUrl);
  return false;
}
