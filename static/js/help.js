import { createFocusBoundary } from './kokuen.js?v=2';
import { HELP_TOPICS, findManualTopics, manualTopicForApp } from './help_content.js?v=1';

let currentManual = null;
let manualGeneration = 0;

function element(tag, className, text, attributes = {}) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}

export function closeManual() {
  if (!currentManual) return;
  const { overlay, boundary, backgrounds } = currentManual;
  currentManual = null;
  // Backgrounds must accept focus again before returning to the trigger.
  for (const [node, wasInert] of backgrounds) node.inert = wasInert;
  boundary.deactivate();
  boundary.destroy();
  overlay.remove();
}

export function openManual({ topic = manualTopicForApp(document.body.dataset), source = document.activeElement, query = '', message = '' } = {}) {
  if (currentManual) { currentManual.closeButton.focus(); return; }
  const generation = ++manualGeneration;
  let selected = HELP_TOPICS.find(item => item.id === topic) || HELP_TOPICS[0];
  let navigationPending = false;
  const overlay = element('div', 'dialog-overlay alles-help-overlay');
  const dialog = element('section', 'dialog-card alles-help-card', '', { id: 'alles-help-dialog', role: 'dialog', 'aria-labelledby': 'alles-help-title', 'data-kokuen-surface': 'manual' });
  const header = element('header', 'alles-help-header');
  const title = element('h2', '', 'help & manual', { id: 'alles-help-title' });
  const closeButton = element('button', 'btn', 'close', { type: 'button', 'data-manual-close': '', 'aria-label': 'close help & manual' });
  header.append(title, closeButton);
  const label = element('label', 'sr-only', 'search the manual', { for: 'alles-help-search' });
  const search = element('input', 'settings-input', '', { id: 'alles-help-search', type: 'search', placeholder: 'search topics and instructions', 'data-kokuen-entry': 'compact' });
  search.value = query;
  const status = element('p', 'alles-help-status', '', { id: 'alles-help-status', role: 'status', 'aria-live': 'polite' });
  const body = element('div', 'alles-help-body');
  const topics = element('nav', 'alles-help-topics', '', { 'aria-label': 'manual topics' });
  const article = element('article', 'alles-help-article', '', { id: 'alles-help-article', 'aria-labelledby': 'alles-help-topic-title', tabindex: '0' });
  body.append(topics, article);
  dialog.append(header, label, search, status, body);
  overlay.append(dialog);

  async function openAction(action) {
    if (navigationPending || currentManual?.overlay !== overlay) return;
    navigationPending = true;
    const restore = { topic: selected.id, source, query: search.value };
    closeManual();
    try {
      // App navigation owns draft guards. Never replace it with location assignment.
      if (action.view) await window._navigateTo(action.view);
      else await window._openSettings(action.pane);
    } catch {
      if (generation === manualGeneration && !currentManual) {
        openManual({ ...restore, message: 'could not open that screen. try its button again or use the app menu.' });
      }
    }
  }

  function renderArticle({ focus = false } = {}) {
    const heading = element('h3', '', selected.title, { id: 'alles-help-topic-title', tabindex: '-1' });
    article.replaceChildren(heading);
    for (const section of selected.sections) {
      if (section.title) article.append(element('h4', '', section.title));
      if (section.steps) {
        const list = element('ol');
        for (const step of section.steps) list.append(element('li', '', step));
        article.append(list);
      }
      for (const paragraph of section.text || []) article.append(element('p', '', paragraph));
      if (section.code) { const pre = element('pre'); pre.append(element('code', '', section.code)); article.append(pre); }
      for (const paragraph of section.after || []) article.append(element('p', '', paragraph));
    }
    const actions = element('div', 'alles-help-actions');
    for (const action of selected.actions || []) {
      const button = element('button', 'btn', action.label, { type: 'button', [action.view ? 'data-manual-view' : 'data-manual-pane']: action.view || action.pane });
      button.addEventListener('click', () => openAction(action));
      actions.append(button);
    }
    article.append(actions);
    article.scrollTop = 0;
    for (const button of topics.querySelectorAll('[data-manual-topic]')) {
      if (button.dataset.manualTopic === selected.id) button.setAttribute('aria-current', 'true');
      else button.removeAttribute('aria-current');
    }
    if (focus) heading.focus();
  }

  for (const item of HELP_TOPICS) {
    const button = element('button', '', item.title, { type: 'button', 'data-manual-topic': item.id });
    button.addEventListener('click', () => { selected = item; renderArticle({ focus: true }); });
    topics.append(button);
  }
  function filter() {
    const matches = findManualTopics(search.value);
    for (const button of topics.querySelectorAll('[data-manual-topic]')) button.hidden = !matches.some(item => item.id === button.dataset.manualTopic);
    status.textContent = matches.length ? '' : 'no topics match. try an app name or clear the search.';
    article.hidden = matches.length === 0;
    if (!matches.length) return;
    if (!matches.includes(selected)) selected = matches[0];
    renderArticle();
  }
  search.addEventListener('input', filter);
  filter();
  if (message) status.textContent = message;

  const boundary = createFocusBoundary(dialog, { onEscape: closeManual });
  closeButton.addEventListener('click', closeManual);
  overlay.addEventListener('click', event => { if (event.target === overlay) closeManual(); });
  overlay.addEventListener('keydown', event => event.stopPropagation());
  const backgrounds = [...document.body.children].filter(node => !['SCRIPT', 'STYLE', 'LINK'].includes(node.tagName)).map(node => [node, node.inert]);
  for (const [node] of backgrounds) node.inert = true;
  document.body.appendChild(overlay);
  currentManual = { overlay, boundary, backgrounds, closeButton };
  boundary.activate({ source, focus: closeButton });
  topics.querySelector('[aria-current="true"]')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
}
