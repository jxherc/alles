import { filterCommands } from './palette.js';

let _debounce = null;
let _requestSequence = 0;
let _optionSequence = 0;
let _activeIndex = -1;
let _lastQ = '';
let _searchOpener = null;

function _modal() {
  return document.getElementById('search-modal');
}

function _input() {
  return document.getElementById('search-input');
}

function _results() {
  return document.getElementById('search-results');
}

function _availableOptions() {
  return [...(_results()?.querySelectorAll('[role="option"]') || [])]
    .filter(option => option.getAttribute('aria-disabled') !== 'true');
}

function _setActive(index, scroll = true) {
  const input = _input();
  const options = _availableOptions();
  if (!input || !options.length) {
    _activeIndex = -1;
    input?.removeAttribute('aria-activedescendant');
    return;
  }
  _activeIndex = Math.max(0, Math.min(index, options.length - 1));
  options.forEach((option, optionIndex) => {
    option.setAttribute('aria-selected', String(optionIndex === _activeIndex));
  });
  const active = options[_activeIndex];
  input.setAttribute('aria-activedescendant', active.id);
  if (scroll) active.scrollIntoView({ block: 'nearest' });
}

function _renderState(kind, message) {
  const container = _results();
  if (!container) return;
  container.setAttribute('aria-busy', String(kind === 'loading'));
  container.innerHTML = `<div class="search-state search-state--${kind}" role="status">${_esc(message)}</div>`;
  _setActive(-1, false);
}

function _renderIdle() {
  _renderState('idle', 'type to search apps, docs, tasks, messages, and more');
}

export function openSearch() {
  const modal = _modal();
  const input = _input();
  if (!modal || !input) return;
  if (modal.style.display === 'none' || !modal.style.display) {
    _searchOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }
  clearTimeout(_debounce);
  _requestSequence += 1;
  _lastQ = '';
  modal.style.display = 'flex';
  input.value = '';
  input.setAttribute('aria-expanded', 'true');
  _renderIdle();
  requestAnimationFrame(() => input.focus({ preventScroll: true }));
}

export function closeSearch({ restoreFocus = true } = {}) {
  const modal = _modal();
  const input = _input();
  if (!modal) return;
  const wasOpen = modal.style.display !== 'none';
  clearTimeout(_debounce);
  _requestSequence += 1;
  modal.style.display = 'none';
  input?.setAttribute('aria-expanded', 'false');
  input?.removeAttribute('aria-activedescendant');
  _activeIndex = -1;
  if (!wasOpen) return;
  const opener = _searchOpener;
  _searchOpener = null;
  if (restoreFocus && opener?.isConnected) opener.focus({ preventScroll: true });
}

function _moveActive(key) {
  const options = _availableOptions();
  if (!options.length) return false;
  if (key === 'Home') _setActive(0);
  else if (key === 'End') _setActive(options.length - 1);
  else if (key === 'ArrowDown') _setActive((_activeIndex + 1 + options.length) % options.length);
  else if (key === 'ArrowUp') _setActive((_activeIndex - 1 + options.length) % options.length);
  else return false;
  return true;
}

function _invokeOption(option) {
  if (!option || option.getAttribute('aria-disabled') === 'true') return;
  if (option.dataset.act === 'ask') {
    closeSearch();
    window._askInChat?.(_lastQ, false);
    return;
  }
  if (option.dataset.act === 'web') {
    closeSearch();
    window._askInChat?.(_lastQ, true);
    return;
  }
  _go(option);
}

function _trapDialogFocus(event) {
  if (event.key !== 'Tab') return false;
  const modal = _modal();
  if (!modal || modal.style.display === 'none') return false;
  const focusable = [...modal.querySelectorAll('input, button, [tabindex]:not([tabindex="-1"])')]
    .filter(element => element.tabIndex >= 0
      && !element.disabled
      && !element.hidden
      && element.getAttribute('aria-disabled') !== 'true');
  if (!focusable.length) return false;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
    return true;
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
    return true;
  }
  return false;
}

export function initSearch() {
  const input = _input();
  const modal = _modal();
  const container = _results();
  if (!input || !modal || !container || modal.dataset.searchBound === 'true') return;
  modal.dataset.searchBound = 'true';

  input.addEventListener('input', () => {
    clearTimeout(_debounce);
    _requestSequence += 1;
    const query = input.value.trim();
    if (!query) {
      _lastQ = '';
      _renderIdle();
      return;
    }
    _lastQ = query;
    _renderState('loading', 'searching');
    _debounce = setTimeout(() => _runSearch(query), 150);
  });

  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeSearch();
      return;
    }
    if (_moveActive(event.key)) {
      event.preventDefault();
      return;
    }
    if (event.key === 'Enter') {
      const active = _availableOptions()[_activeIndex];
      if (active) {
        event.preventDefault();
        _invokeOption(active);
      }
    }
  });

  modal.addEventListener('keydown', event => {
    if (_trapDialogFocus(event)) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeSearch();
    }
  });
  modal.addEventListener('click', event => {
    if (event.target === modal) closeSearch();
  });
  document.getElementById('search-close')?.addEventListener('click', () => closeSearch());

  container.addEventListener('pointermove', event => {
    const option = event.target.closest('[role="option"]');
    if (!option) return;
    const index = _availableOptions().indexOf(option);
    if (index >= 0 && index !== _activeIndex) _setActive(index, false);
  });
  container.addEventListener('click', event => {
    const option = event.target.closest('[role="option"]');
    if (!option) return;
    const index = _availableOptions().indexOf(option);
    if (index >= 0) _setActive(index, false);
    _invokeOption(option);
  });
}

async function _runSearch(query) {
  const requestId = ++_requestSequence;
  try {
    const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    if (requestId !== _requestSequence) return;
    if (!response.ok) {
      const state = [401, 403].includes(response.status) ? 'permission' : response.status >= 500 ? 'unavailable' : 'error';
      const message = state === 'permission'
        ? 'search needs an unlocked Alles session'
        : state === 'unavailable'
          ? 'local search is unavailable right now'
          : 'search failed. check the query and try again';
      _renderResults({}, query, { state, message });
      return;
    }
    const data = await response.json();
    if (requestId === _requestSequence) _renderResults(data, query);
  } catch {
    if (requestId === _requestSequence) {
      _renderResults({}, query, {
        state: 'error',
        message: 'search failed. check the connection and try again',
      });
    }
  }
}

function _money(amount) {
  const number = Number(amount) || 0;
  return (number >= 0 ? '+' : '−') + Math.abs(number).toFixed(2);
}

function _option(className, attrs, content) {
  const id = `search-option-${++_optionSequence}`;
  return `<button type="button" class="${className}" id="${id}" role="option" aria-selected="false" tabindex="-1" ${attrs}>${content}</button>`;
}

function _group(label, items, render) {
  if (!items.length) return '';
  return `<div class="search-group-label" role="presentation">${_esc(label)}</div>${items.map(render).join('')}`;
}

function _row(attrs, name, snippet) {
  return _option('search-result', attrs, `
    ${name ? `<span class="search-result-name">${_esc(name)}</span>` : ''}
    ${snippet ? `<span class="search-result-snippet">${_esc(snippet)}</span>` : ''}
  `);
}

function _actionRail(query) {
  if (!query) return '';
  return `<div class="search-group-label" role="presentation">actions</div>
    <div class="search-actions" role="presentation">
      ${_option('search-act', 'data-act="ask"', `<span><b>ask aide</b> about “${_esc(query.slice(0, 40))}”</span>`)}
      ${_option('search-act', 'data-act="web"', '<span>search the current web with andromeda</span>')}
    </div>`;
}

function _renderResults(data, query, status = null) {
  const {
    chats = [], notes = [], tasks = [], calendar = [], contacts = [], memories = [], mail = [],
    money = [], subs = [], photos = [], books = [], read = [], habits = [], watch = [],
  } = data || {};
  const container = _results();
  if (!container) return;
  _optionSequence = 0;

  const navHits = query ? filterCommands(window._navCommands || [], query).slice(0, 6) : [];
  let matches = '';
  matches += _group('go to', navHits, command => _row(`data-type="nav" data-view="${_esc(command.view)}"`, command.label, command.hint));
  matches += _group('chats', chats, chat => _row(`data-type="chat" data-id="${_esc(chat.session_id)}"`, chat.session_name, chat.snippet));
  matches += _group('docs', notes, note => _row(`data-type="note" data-path="${_esc(note.path)}"`, note.name, note.snippet));
  matches += _group('mail', mail, message => _row('data-type="nav" data-view="mail"', message.subject, _fromName(message.from)));
  matches += _group('tasks', tasks, task => _row('data-type="nav" data-view="tasks"', task.title, task.done ? 'done' : ''));
  matches += _group('calendar', calendar, event => _row('data-type="nav" data-view="calendar"', event.title, event.when));
  matches += _group('books', books, book => _row('data-type="nav" data-view="books"', book.title, [book.author, book.status].filter(Boolean).join(' · ')));
  matches += _group('read', read, item => _row('data-type="nav" data-view="read"', item.title, item.site));
  matches += _group('habits', habits, habit => _row('data-type="nav" data-view="habits"', habit.name, ''));
  matches += _group('watch', watch, item => _row('data-type="nav" data-view="watch"', item.name, item.url));
  matches += _group('money', money, transaction => _row('data-type="nav" data-view="money"', transaction.payee, `${_money(transaction.amount)} · ${transaction.when}`));
  matches += _group('subs', subs, subscription => _row('data-type="nav" data-view="subs"', subscription.name, subscription.snippet));
  matches += _group('contacts', contacts, contact => _row('data-type="nav" data-view="contacts"', contact.name, contact.snippet));
  matches += _group('photos', photos, photo => _row('data-type="nav" data-view="photos"', photo.name, ''));
  matches += _group('memories', memories, memory => _row('data-type="nav" data-view="memory"', memory.text, ''));

  const state = status
    ? `<div class="search-state search-state--${status.state}" role="status">${_esc(status.message)}</div>`
    : !matches
      ? '<div class="search-state search-state--empty" role="status">no local matches. choose an action below</div>'
      : '';
  container.setAttribute('aria-busy', 'false');
  container.innerHTML = state + _actionRail(query) + matches;
  _setActive(0, false);
}

function _fromName(from) {
  const match = /^(.*?)\s*<([^>]+)>/.exec(from || '');
  return (match ? (match[1].replace(/"/g, '').trim() || match[2]) : from) || '';
}

async function _go(option) {
  closeSearch();
  const type = option.dataset.type;
  if (type === 'chat') {
    window._navigateTo?.('chat');
    const { selectSession } = await import('./sessions.js');
    selectSession(option.dataset.id);
  } else if (type === 'note') {
    window._navigateTo?.('wiki');
    const { openNote } = await import('./docs.js');
    openNote(option.dataset.path);
  } else {
    window._navigateTo?.(option.dataset.view);
  }
}

function _esc(value = '') {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
