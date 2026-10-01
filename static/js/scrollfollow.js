const BOTTOM_GAP = 96;

let _chat = null;
let _jump = null;
let _following = true;
let _wired = false;

export function distanceFromBottom(element) {
  if (!element) return 0;
  return Math.max(0, element.scrollHeight - element.scrollTop - element.clientHeight);
}

export function shouldAutoFollow({ following, distance, typing = false, selecting = false }) {
  return Boolean(following && distance <= BOTTOM_GAP && !typing && !selecting);
}

function selectionInsideChat() {
  const selection = document.getSelection?.();
  if (!selection || selection.isCollapsed || !_chat) return false;
  return _chat.contains(selection.anchorNode) || _chat.contains(selection.focusNode);
}

function typingDraft() {
  const input = document.getElementById('composer-ta');
  return document.activeElement === input && Boolean(input?.value.trim());
}

function renderJump() {
  if (_jump) _jump.hidden = _following && distanceFromBottom(_chat) <= BOTTOM_GAP;
}

export function pauseScrollFollow() {
  _following = false;
  renderJump();
}

export function resumeScrollFollow() {
  _following = true;
  scrollToLatest({ force: true });
}

export function scrollToLatest({ force = false } = {}) {
  _chat ||= document.getElementById('chat');
  _jump ||= document.getElementById('jump-latest');
  if (!_chat) return false;
  const canFollow = shouldAutoFollow({
    following: _following,
    distance: distanceFromBottom(_chat),
    typing: typingDraft(),
    selecting: selectionInsideChat(),
  });
  if (!force && !canFollow) {
    pauseScrollFollow();
    return false;
  }
  _chat.scrollTop = _chat.scrollHeight;
  _following = true;
  renderJump();
  return true;
}

export function initScrollFollow() {
  if (_wired) return;
  _wired = true;
  _chat = document.getElementById('chat');
  _jump = document.getElementById('jump-latest');
  if (!_chat) return;
  _chat.addEventListener('scroll', () => {
    _following = distanceFromBottom(_chat) <= BOTTOM_GAP;
    renderJump();
  }, { passive: true });
  _chat.addEventListener('wheel', event => {
    if (event.deltaY < 0) pauseScrollFollow();
  }, { passive: true });
  document.addEventListener('selectionchange', () => {
    if (selectionInsideChat()) pauseScrollFollow();
  });
  const input = document.getElementById('composer-ta');
  input?.addEventListener('input', () => {
    if (input.value.trim()) pauseScrollFollow();
    else if (distanceFromBottom(_chat) <= BOTTOM_GAP) _following = true;
  });
  _jump?.addEventListener('click', resumeScrollFollow);
  renderJump();
}
