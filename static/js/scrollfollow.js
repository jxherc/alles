// aide follows a growing reply while the owner sits at the end of the chat. whether they left the
// end comes only from where the view is (scrollTop, scrollHeight, clientHeight), the way
// use-stick-to-bottom does it (hermes' web chat, on this machine): the view moving up is the
// owner leaving, being at the end is them back. the app's own growth never counts as leaving: a
// tool step or a code block can add more than BOTTOM_GAP between two scroll events, and judging
// "still at the end?" right after that growth is what used to drop the follow mid reply.
const BOTTOM_GAP = 96;

let _chat = null;
let _jump = null;
let _following = true;
let _touching = false;
let _wired = false;
// where the view was at the last scroll event or pin, to tell "moved up" from "content grew"
let _lastTop = 0;
// a jump to the end asked for while the chat was hidden (no height yet); done once it shows
let _pendingEnd = false;

export function distanceFromBottom(element) {
  if (!element) return 0;
  return Math.max(0, element.scrollHeight - element.scrollTop - element.clientHeight);
}

// what one scroll event says about following, from the position alone
export function followAfterScroll({ following, top, lastTop, distance }) {
  if (distance <= 1) return true;               // at the end, however it got there
  if (top < lastTop - 1) return false;          // the view moved up: only the owner does that
  if (top > lastTop + 1 && distance <= BOTTOM_GAP) return true;  // came back down to the end
  return following;                             // content grew under a still view
}

function selectionInsideChat() {
  const selection = document.getSelection?.();
  if (!selection || selection.isCollapsed || !_chat) return false;
  return _chat.contains(selection.anchorNode) || _chat.contains(selection.focusNode);
}

export function refreshScrollFollow() {
  if (_jump) _jump.hidden = !(_chat?.getClientRects().length
    && _chat.querySelector('#messages .msg-row') && distanceFromBottom(_chat) > BOTTOM_GAP);
}

export function pauseScrollFollow() {
  _following = false;
  refreshScrollFollow();
}

export function resumeScrollFollow() {
  _following = true;
  scrollToLatest({ force: true });
}

function pin() {
  if (!_chat.clientHeight) { _pendingEnd = true; return; }
  _pendingEnd = false;
  _chat.scrollTop = _chat.scrollHeight;
  _lastTop = _chat.scrollTop;
}

// keeps the newest line in view while following. a caller never turns following off: only the
// owner moving the view does. a finger on the chat or a selection in it holds the view still
export function scrollToLatest({ force = false } = {}) {
  _chat ||= document.getElementById('chat');
  _jump ||= document.getElementById('jump-latest');
  if (!_chat) return false;
  if (force) _following = true;
  else if (!_following || _touching || selectionInsideChat()) {
    refreshScrollFollow();
    return false;
  }
  pin();
  refreshScrollFollow();
  return true;
}

export function initScrollFollow() {
  if (_wired) return;
  _wired = true;
  _chat = document.getElementById('chat');
  _jump = document.getElementById('jump-latest');
  if (!_chat) return;
  _lastTop = _chat.scrollTop;
  _chat.addEventListener('scroll', () => {
    const top = _chat.scrollTop;
    _following = followAfterScroll({ following: _following, top, lastTop: _lastTop, distance: distanceFromBottom(_chat) });
    _lastTop = top;
    refreshScrollFollow();
  }, { passive: true });
  // a wheel or key up is the owner leaving even before the view moves: a pin landing mid
  // animation would otherwise cancel the scroll they asked for
  const canScroll = () => _chat.scrollHeight > _chat.clientHeight;
  _chat.addEventListener('wheel', event => {
    if (event.deltaY < 0 && canScroll()) pauseScrollFollow();
  }, { passive: true });
  _chat.addEventListener('keydown', event => {
    if (['ArrowUp', 'PageUp', 'Home'].includes(event.key) && canScroll()) pauseScrollFollow();
  });
  // nothing moves the view while a finger is down (that would also stop safari's momentum).
  // the drag itself scrolls, so the scroll events above decide whether it left the end
  _chat.addEventListener('touchstart', () => { _touching = true; }, { passive: true });
  const lift = () => {
    _touching = false;
    // a reply that grew under a resting finger catches up once it lifts
    if (_following) scrollToLatest();
  };
  _chat.addEventListener('touchend', lift, { passive: true });
  _chat.addEventListener('touchcancel', lift, { passive: true });
  document.addEventListener('selectionchange', () => {
    if (selectionInsideChat()) pauseScrollFollow();
  });
  _jump?.addEventListener('click', resumeScrollFollow);
  // the chat shows (from hidden), the window resizes or a reply grows (words, a picture that
  // loads, a code block, the typing line going, the actions row coming): stay on the newest line
  // while following. this is the one place growth is followed; it needs no scroll event
  if (typeof ResizeObserver === 'function') {
    const messages = document.getElementById('messages');
    const stick = () => {
      if (!_chat.clientHeight || _touching || !(_pendingEnd || _following) || selectionInsideChat()) {
        refreshScrollFollow();
        return;
      }
      if (_pendingEnd || distanceFromBottom(_chat) > 1) pin();
      refreshScrollFollow();
    };
    const observer = new ResizeObserver(stick);
    observer.observe(_chat);
    if (messages) observer.observe(messages);
  }
  refreshScrollFollow();
}
