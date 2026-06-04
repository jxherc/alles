const SENSITIVE_KEY = 'aide-sensitive-blur';
const TEXT_EMOJI_KEY = 'aide-text-only-emojis';
const WELCOME_KEY = 'aide-show-welcome';

const SENSITIVE_PATTERNS = [
  { re: /\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b/g, label: 'email' },
  { re: /\b(sk-[a-zA-Z0-9]{20,}|pk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|glpat-[a-zA-Z0-9\-_]{20,}|xox[bpras]-[a-zA-Z0-9\-]{10,}|npm_[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{12,})\b/g, label: 'key' },
  { re: /Bearer\s+[A-Za-z0-9._\-]{20,}/g, label: 'token' },
  { re: /(?:password|passwd|secret|api[_\-]?key|access[_\-]?token|auth[_\-]?token|private[_\-]?key|client[_\-]?secret)\s*[:=]\s*["']?[^\s"'<]{4,}["']?/gi, label: 'secret' },
  { re: /\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b/g, label: 'jwt' },
  { re: /\b[0-9a-f]{32,}\b/gi, label: 'hash' },
];

export function sensitiveBlurEnabled() {
  return localStorage.getItem(SENSITIVE_KEY) === 'on';
}

export function textOnlyEmojisEnabled() {
  return localStorage.getItem(TEXT_EMOJI_KEY) === 'on';
}

export function welcomeEnabled() {
  return localStorage.getItem(WELCOME_KEY) !== 'off';
}

export function setSensitiveBlur(on) {
  localStorage.setItem(SENSITIVE_KEY, on ? 'on' : 'off');
  if (!on) document.querySelectorAll('.censored-item').forEach(el => el.classList.add('revealed'));
}

export function setTextOnlyEmojis(on) {
  localStorage.setItem(TEXT_EMOJI_KEY, on ? 'on' : 'off');
}

export function setWelcomeEnabled(on) {
  localStorage.setItem(WELCOME_KEY, on ? 'on' : 'off');
}

export function stripEmojis(text = '') {
  if (!textOnlyEmojisEnabled()) return text;
  return String(text)
    .replace(/\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?/gu, '')
    .replace(/[\u{1F1E6}-\u{1F1FF}]{2}/gu, '')
    .replace(/\s{2,}/g, ' ');
}

export function applyResponsePrivacy(root) {
  if (!root) return;
  if (textOnlyEmojisEnabled()) _stripEmojiTextNodes(root);
  if (sensitiveBlurEnabled()) _censor(root);
}

export function initPrivacyHandlers() {
  if (document.body.dataset.privacyHandlersBound === '1') return;
  document.body.dataset.privacyHandlersBound = '1';
  document.addEventListener('click', e => {
    const item = e.target.closest('.censored-item');
    if (!item) return;
    item.classList.toggle('revealed');
  });
}

function _stripEmojiTextNodes(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement?.closest('pre, code')) continue;
    nodes.push(node);
  }
  nodes.forEach(n => { n.textContent = stripEmojis(n.textContent); });
}

function _censor(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement?.closest('pre, code, .censored-item')) continue;
    nodes.push(node);
  }
  nodes.forEach(_censorTextNode);
}

function _censorTextNode(textNode) {
  const text = textNode.textContent || '';
  const matches = [];
  for (const pattern of SENSITIVE_PATTERNS) {
    pattern.re.lastIndex = 0;
    let match;
    while ((match = pattern.re.exec(text))) {
      matches.push({ start: match.index, end: match.index + match[0].length, label: pattern.label });
    }
  }
  if (!matches.length) return;
  matches.sort((a, b) => a.start - b.start);
  const merged = [];
  for (const match of matches) {
    const prev = merged[merged.length - 1];
    if (prev && match.start < prev.end) prev.end = Math.max(prev.end, match.end);
    else merged.push({ ...match });
  }
  const frag = document.createDocumentFragment();
  let pos = 0;
  for (const match of merged) {
    if (match.start > pos) frag.appendChild(document.createTextNode(text.slice(pos, match.start)));
    const span = document.createElement('span');
    span.className = 'censored-item';
    span.dataset.type = match.label;
    span.title = `click to reveal ${match.label}`;
    span.textContent = text.slice(match.start, match.end);
    frag.appendChild(span);
    pos = match.end;
  }
  if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
  textNode.parentNode?.replaceChild(frag, textNode);
}
