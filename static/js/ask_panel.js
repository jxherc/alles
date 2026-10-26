// ask aide from any app: a panel slides in from the right, sees which app and view you're on and
// (unless you turn it off) the words on that screen, and streams aide's answer. "continue in aide"
// opens the same session in the full app. the vault never shares its screen.
import { icon } from './icons.js';
import { mdToHtml, appLabel } from './util.js';
import { loadShortcuts, matchesShortcut } from './shortcuts.js';
import { singleHost, urlForApp } from './subdomain.js?v=237';
import { t } from './i18n.js';

const SESSION_KEY = 'alles-ask-session';
const SCREEN_LIMIT = 3000;

let panel = null;
let sessionId = '';
let busy = null;          // the AbortController of the running answer
let turnToken = '';       // names the running answer, so a late stop can't end the next one
let shareScreen = true;
let opener = null;

const $ = id => document.getElementById(id);

// aide is its own chat, so it doesn't need the panel; vault content never leaves the page
function blocked() {
  const space = document.body.dataset.space;
  return space === 'aide' || appName() === 'vault';
}

function appName() {
  return ($('app-drawer-label')?.dataset.app || document.body.dataset.app || 'alles').trim();
}

function visibleRoot() {
  const views = [...document.querySelectorAll('.page-view, #today-view, #andromeda-view')]
    .filter(el => el.getClientRects().length && getComputedStyle(el).display !== 'none' && !el.closest('#ask-panel'));
  // the innermost shown view is the screen; an app group holds its sections inside
  return views.filter(el => !views.some(other => other !== el && el.contains(other))).pop() || document.querySelector('main') || document.body;
}

function viewName(root) {
  const tab = [...document.querySelectorAll('[role="tab"][aria-selected="true"]')]
    .find(el => el.getClientRects().length && !el.closest('#ask-panel'));
  return (tab?.textContent || root?.querySelector('h1, h2')?.textContent || '').trim().toLowerCase();
}

function screenText(root) {
  if (blocked() || root.querySelector('#vault-view, [data-specialist-app="vault"]')) return '';
  const text = (root.innerText || '').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  return text.length > SCREEN_LIMIT ? text.slice(0, SCREEN_LIMIT) + '…' : text;
}

function where() {
  const root = visibleRoot();
  const view = viewName(root);
  const app = appLabel(appName());
  return { root, label: view && view !== app ? `${app} · ${view}` : app };
}

function build() {
  panel = document.createElement('aside');
  panel.id = 'ask-panel';
  panel.className = 'ask-panel';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'false');
  panel.setAttribute('aria-labelledby', 'ask-panel-title');
  panel.innerHTML = `
    <header class="ask-panel-head">
      <h2 id="ask-panel-title">${t('shell.ask_aide')}</h2>
      <button type="button" class="ask-panel-action" id="ask-panel-new" hidden>${t('common.new')}</button>
      <button type="button" class="ask-panel-action" id="ask-panel-open" hidden>${t('shell.continue_in_aide')}</button>
      <button type="button" class="ask-panel-close" id="ask-panel-close" aria-label="${t('shell.close_ask_aide')}">${icon('close')}</button>
    </header>
    <div class="ask-panel-log" id="ask-panel-log" aria-live="polite"></div>
    <form class="ask-panel-composer" id="ask-panel-form">
      <div class="ask-panel-context" id="ask-panel-context">
        <span id="ask-panel-where"></span>
        <button type="button" id="ask-panel-share" aria-pressed="true"></button>
      </div>
      <div class="ask-panel-entry">
        <textarea id="ask-panel-input" rows="1" aria-label="${t('shell.ask_aide')}" placeholder="${t('shell.ask_about_screen')}"></textarea>
        <button type="submit" class="ask-panel-send" id="ask-panel-send" aria-label="${t('common.send')}">${icon('send')}</button>
      </div>
    </form>`;
  document.body.append(panel);

  $('ask-panel-close').addEventListener('click', () => close());
  $('ask-panel-new').addEventListener('click', reset);
  $('ask-panel-open').addEventListener('click', openInAide);
  $('ask-panel-share').addEventListener('click', () => { shareScreen = !shareScreen; paintContext(); });
  $('ask-panel-form').addEventListener('submit', event => { event.preventDefault(); busy ? stop() : send(); });
  const input = $('ask-panel-input');
  input.addEventListener('input', () => grow(input));
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!busy) send(); }
  });
  panel.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    if (busy) stop(); else close();
  });
}

function grow(input) {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 160) + 'px';
}

function paintContext() {
  const { label } = where();
  const share = $('ask-panel-share');
  const locked = blocked();
  $('ask-panel-where').textContent = locked || !shareScreen ? t('shell.ask_on', { label }) : t('shell.ask_sees', { label });
  share.hidden = locked;
  share.textContent = shareScreen ? t('shell.dont_share_screen') : t('shell.share_screen');
  share.setAttribute('aria-pressed', String(shareScreen));
}

function paintEmpty() {
  const log = $('ask-panel-log');
  if (log.childElementCount) return;
  const starts = [t('shell.ask_start_summarize'), t('shell.ask_start_next'), t('shell.ask_start_off')];
  log.innerHTML = `<div class="ask-panel-empty"><p>${t('shell.ask_empty')}</p>
    <div class="ask-panel-starts">${starts.map(s => `<button type="button" class="ask-panel-start">${s}</button>`).join('')}</div></div>`;
  log.querySelectorAll('.ask-panel-start').forEach(b => b.addEventListener('click', () => { $('ask-panel-input').value = b.textContent; send(); }));
}

export function isAskPanelOpen() { return !!panel && !panel.hidden; }

export function openAskPanel() {
  if (!panel) build();
  opener = document.activeElement;
  sessionId ||= sessionStorage.getItem(SESSION_KEY) || '';
  paintContext();
  paintEmpty();
  panel.hidden = false;
  document.body.classList.add('ask-panel-open');
  requestAnimationFrame(() => $('ask-panel-input')?.focus());
}

export function close() {
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  document.body.classList.remove('ask-panel-open');
  if (opener?.isConnected) opener.focus?.();
}

function toggle() { isAskPanelOpen() ? close() : openAskPanel(); }

function reset() {
  stop();
  sessionId = '';
  sessionStorage.removeItem(SESSION_KEY);
  $('ask-panel-log').innerHTML = '';
  $('ask-panel-new').hidden = true;
  $('ask-panel-open').hidden = true;
  paintEmpty();
  $('ask-panel-input').focus();
}

function row(kind, html) {
  const log = $('ask-panel-log');
  log.querySelector('.ask-panel-empty')?.remove();
  const el = document.createElement('div');
  el.className = `ask-panel-msg ask-panel-${kind}`;
  el.innerHTML = html;
  log.append(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

function setBusy(controller) {
  busy = controller;
  const sendBtn = $('ask-panel-send');
  sendBtn.innerHTML = icon(controller ? 'stop' : 'send');
  sendBtn.setAttribute('aria-label', controller ? t('common.stop') : t('common.send'));
  panel.classList.toggle('is-busy', !!controller);
}

async function ensureSession(question) {
  if (sessionId) return sessionId;
  const res = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: question.slice(0, 48) }),
  });
  if (!res.ok) throw await failure(res);
  sessionId = (await res.json()).id;
  sessionStorage.setItem(SESSION_KEY, sessionId);
  return sessionId;
}

async function failure(res) {
  let body = {};
  try { body = await res.json(); } catch { /* not json */ }
  const err = new Error(body.detail || t('shell.aide_answered', { status: res.status }));
  err.code = body.code || '';
  return err;
}

function compose(question) {
  const { root, label } = where();
  const text = shareScreen ? screenText(root) : '';
  if (!text) return `${question}\n\n(asked from ${label} in alles)`;
  return `${question}\n\n(asked from ${label} in alles. what's on that screen:)\n"""\n${text}\n"""`;
}

async function send() {
  const input = $('ask-panel-input');
  const question = input.value.trim();
  if (!question || busy) return;
  input.value = '';
  grow(input);
  row('you', `<p>${question.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))}</p>`);
  const answer = row('aide', `<p class="ask-panel-wait">${t('shell.thinking')}</p>`);
  const controller = new AbortController();
  setBusy(controller);
  turnToken = globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  let text = '';
  try {
    const id = await ensureSession(question);
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: id, message: compose(question), simple: true, turn_token: turnToken }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) throw await failure(res);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf('\n\n')) >= 0) {
        const line = buffer.slice(0, cut).trim();
        buffer = buffer.slice(cut + 2);
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (data === '[DONE]') continue;
        let chunk;
        try { chunk = JSON.parse(data); } catch { continue; }
        if (chunk.error) throw Object.assign(new Error(chunk.error), { code: '' });
        if (typeof chunk.delta === 'string') {
          text += chunk.delta;
          answer.innerHTML = mdToHtml(text);
          const log = $('ask-panel-log');
          log.scrollTop = log.scrollHeight;
        }
      }
    }
    if (!text) answer.innerHTML = `<p class="ask-panel-note">${t('shell.aide_sent_no_text')}</p>`;
    $('ask-panel-new').hidden = false;
    $('ask-panel-open').hidden = false;
  } catch (err) {
    // a stop that got there before the answer began is still just a stop
    if (err.name === 'AbortError' || err.code === 'turn_stopped') {
      if (!text) answer.innerHTML = `<p class="ask-panel-note">${t('shell.stopped')}</p>`;
    } else {
      const needsModel = /^model_/.test(err.code || '') || /model/i.test(err.message);
      answer.innerHTML = `<p class="ask-panel-error">${err.message.replace(/[&<>]/g, '')}</p>`
        + (needsModel ? `<button type="button" class="ask-panel-action" data-ask-model>${t('shell.choose_a_model')}</button>` : '');
      answer.querySelector('[data-ask-model]')?.addEventListener('click', () => window._openModelModal?.());
    }
  } finally {
    setBusy(null);
    input.focus();
  }
}

function stop() {
  if (!busy) return;
  const controller = busy;
  if (!sessionId) { controller.abort(); return; }
  // tell the server first, naming this answer, then drop the connection (at most 800ms later):
  // a stop that arrives late never ends the next answer in the task
  const told = fetch(`/api/chat/stop/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ turn_token: turnToken }),
  }).catch(() => {});
  Promise.race([told, new Promise(resolve => setTimeout(resolve, 800))]).then(() => controller.abort());
}

async function openInAide() {
  if (!sessionId) return;
  const id = sessionId;
  close();
  if (!singleHost()) { location.href = urlForApp('aide', '#' + id); return; }
  await window._navigateTo?.('chat', { preserveSession: true });
  const { selectSession } = await import('./sessions.js');
  await selectSession(id);
}

// opens with its shortcut only; on a screen it can't help with it closes
export function syncAskPanel() {
  if (blocked()) close();
  else if (isAskPanelOpen()) paintContext();
}

export function initAskPanel() {
  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || !matchesShortcut(event, loadShortcuts().ask_aide)) return;
    if (blocked() && !isAskPanelOpen()) return;
    event.preventDefault();
    toggle();
  });
}
