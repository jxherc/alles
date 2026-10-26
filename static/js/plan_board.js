import { plainError } from './util.js';
import { t } from './i18n.js';
const STAGES = Object.freeze(['backlog', 'next', 'doing', 'waiting']);
const stageLabel = stage => t(STAGES.includes(stage) ? `plan.stage_${stage}` : 'plan.stage_done');
const PLAN_TASK_MIME = 'application/x-alles-plan-task';

let selectedTaskId = '';
let disposeBoardMenu = () => {};
// a move or complete redraws the whole board; these say where focus goes in the new one and
// what the status line said, so "moved to blocked" isn't wiped by the redraw
let pendingFocus = null;
let pendingStatus = '';

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== '') node.textContent = text;
  return node;
}

async function json(request, url, options) {
  const response = await request(url, options);
  if (!response.ok) {
    let payload = null;
    try { payload = await response.json(); } catch { /* bounded fallback */ }
    const detail = payload?.detail?.message || payload?.detail || payload?.error?.message;
    throw new Error(typeof detail === 'string' ? detail : t('plan.board_request_failed', { status: response.status }));
  }
  return response.json();
}

function normalizedStage(task) {
  if (task?.done) return 'done';
  const stage = String(task?.stage || '').trim().toLowerCase();
  return STAGES.includes(stage) ? stage : 'backlog';
}

export function groupPlanBoardTasks(tasks) {
  const grouped = Object.fromEntries(STAGES.map(stage => [stage, []]));
  for (const task of tasks || []) {
    const stage = normalizedStage(task);
    if (stage !== 'done') grouped[stage].push({ ...task, stage });
  }
  for (const stage of STAGES) {
    grouped[stage].sort((left, right) => (
      Number(left.sort_order || 0) - Number(right.sort_order || 0)
      || Number(right.priority || 0) - Number(left.priority || 0)
      || String(left.due_date || '9999').localeCompare(String(right.due_date || '9999'))
      || String(left.title || '').localeCompare(String(right.title || ''))
    ));
  }
  return grouped;
}

function projectName(task) {
  return String(task?.project || '').trim() || t('plan.no_project');
}

export function localDateKey(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function dueLabel(task) {
  const due = String(task?.due_date || '').slice(0, 10);
  if (!due) return t('plan.no_date');
  const today = localDateKey();
  if (due < today) return t('plan.overdue_on', { due });
  if (due === today) return t('common.today');
  return due;
}

function cardFor(task, selectTask) {
  const card = el('li', 'plan-board-card');
  card.dataset.taskId = task.id;
  card.dataset.stage = task.stage;
  card.dataset.project = projectName(task);
  card.dataset.search = `${task.title || ''} ${task.notes || ''} ${task.tags || ''} ${projectName(task)}`.toLowerCase();
  const handle = el('button', 'plan-board-drag');
  handle.type = 'button';
  handle.draggable = true;
  handle.setAttribute('aria-label', t('plan.drag_task', { title: task.title || t('plan.task') }));
  handle.addEventListener('dragstart', event => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData(PLAN_TASK_MIME, task.id);
    card.dataset.dragging = 'true';
    card._dragOriginParent = card.parentElement;
    card._dragOriginNext = card.nextSibling;
    delete card.dataset.dropAccepted;
  });
  handle.addEventListener('dragend', () => {
    if (card.dataset.dropAccepted !== 'true' && card._dragOriginParent) {
      card._dragOriginParent.insertBefore(card, card._dragOriginNext || null);
    }
    delete card.dataset.dragging;
    delete card.dataset.dropAccepted;
    delete card._dragOriginParent;
    delete card._dragOriginNext;
  });
  const button = el('button', 'plan-board-card-main');
  button.type = 'button';
  button.append(el('strong', 'plan-board-card-title', task.title || t('plan.untitled_task')));
  const meta = el('span', 'plan-board-card-meta');
  if (Number(task.priority || 0) > 0) {
    // 1 low, 2 medium, 3 high, as tasks itself labels them
    const level = ['', 'low', 'medium', 'high'][Number(task.priority)] || 'high';
    const priority = el('span', `plan-board-priority${level === 'high' ? ' high' : ''}`);
    priority.setAttribute('aria-label', t('plan.priority_named', { level: t(`plan.priority_${level}`) }));
    meta.append(priority);
  }
  meta.append(el('span', '', projectName(task)), el('span', '', dueLabel(task)));
  button.append(meta);
  button.addEventListener('click', () => selectTask(task.id));
  card.append(handle, button);
  return card;
}

function wireRadioGroup(group, onChange) {
  const radios = [...group.querySelectorAll('[role="radio"]')];
  const choose = (radio, focus = false) => {
    radios.forEach(item => {
      const selected = item === radio;
      item.setAttribute('aria-checked', String(selected));
      item.tabIndex = selected ? 0 : -1;
    });
    onChange(radio.dataset.value);
    if (focus) radio.focus();
  };
  radios.forEach((radio, index) => {
    radio.addEventListener('click', () => choose(radio));
    radio.addEventListener('keydown', event => {
      let next = null;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = radios[(index + 1) % radios.length];
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = radios[(index - 1 + radios.length) % radios.length];
      if (event.key === 'Home') next = radios[0];
      if (event.key === 'End') next = radios.at(-1);
      if (!next) return;
      event.preventDefault();
      choose(next, true);
    });
  });
}

function projectMenu(projects, onChange) {
  const wrap = el('div', 'plan-board-filter-wrap');
  const trigger = el('button', 'plan-board-tool', t('plan.project_all'));
  trigger.type = 'button';
  trigger.setAttribute('aria-expanded', 'false');
  const menu = el('div', 'plan-board-menu');
  const menuId = `plan-board-menu-${Math.random().toString(16).slice(2)}`;
  menu.id = menuId;
  menu.hidden = true;
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', t('plan.filter_by_project'));
  trigger.setAttribute('aria-controls', menuId);
  const values = ['all', ...projects];
  const items = values.map(value => {
    const item = el('button', 'plan-board-menu-item', value === 'all' ? t('plan.all_projects') : value);
    item.type = 'button';
    item.dataset.value = value;
    item.setAttribute('role', 'menuitemradio');
    item.setAttribute('aria-checked', value === 'all' ? 'true' : 'false');
    menu.append(item);
    return item;
  });
  const close = (returnFocus = false) => {
    menu.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    if (returnFocus) trigger.focus();
  };
  // anchored to the trigger's right edge; flip when that would leave the screen
  const place = () => {
    menu.style.left = '';
    menu.style.right = '';
    if (menu.getBoundingClientRect().left < 8) {
      menu.style.right = 'auto';
      menu.style.left = '0';
    }
  };
  const choose = item => {
    items.forEach(option => option.setAttribute('aria-checked', String(option === item)));
    trigger.textContent = item.dataset.value === 'all' ? t('plan.project_all') : t('plan.project_named', { name: item.dataset.value });
    onChange(item.dataset.value);
    close(true);
  };
  trigger.addEventListener('click', () => {
    const open = trigger.getAttribute('aria-expanded') !== 'true';
    trigger.setAttribute('aria-expanded', String(open));
    menu.hidden = !open;
    if (open) place();
    if (open) items.find(item => item.getAttribute('aria-checked') === 'true')?.focus();
  });
  trigger.addEventListener('keydown', event => {
    if (event.key !== 'ArrowDown') return;
    event.preventDefault();
    trigger.setAttribute('aria-expanded', 'true');
    menu.hidden = false;
    place();
    items.find(item => item.getAttribute('aria-checked') === 'true')?.focus();
  });
  items.forEach((item, index) => {
    item.addEventListener('click', () => choose(item));
    item.addEventListener('keydown', event => {
      let next = null;
      if (event.key === 'ArrowDown') next = items[(index + 1) % items.length];
      if (event.key === 'ArrowUp') next = items[(index - 1 + items.length) % items.length];
      if (event.key === 'Home') next = items[0];
      if (event.key === 'End') next = items.at(-1);
      if (event.key === 'Escape') return close(true);
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        return choose(item);
      }
      if (!next) return;
      event.preventDefault();
      next.focus();
    });
  });
  const outside = event => {
    if (!menu.hidden && !wrap.contains(event.target)) close();
  };
  const escape = event => {
    if (event.key === 'Escape' && !menu.hidden) close(true);
  };
  document.addEventListener('click', outside);
  document.addEventListener('keydown', escape);
  const dispose = () => {
    document.removeEventListener('click', outside);
    document.removeEventListener('keydown', escape);
  };
  wrap.append(trigger, menu);
  return { node: wrap, dispose };
}

export function disposePlanBoard() {
  disposeBoardMenu();
  disposeBoardMenu = () => {};
}

export async function renderPlanBoard(target, request = fetch, refresh = async () => {}) {
  disposePlanBoard();
  const [activeResult, doneResult] = await Promise.allSettled([
    json(request, '/api/tasks'),
    json(request, '/api/tasks/done'),
  ]);
  const tasks = activeResult.status === 'fulfilled' ? activeResult.value : [];
  const completed = doneResult.status === 'fulfilled' ? doneResult.value : [];
  const grouped = groupPlanBoardTasks(tasks);
  const byId = new Map(tasks.map(task => [String(task.id), { ...task, stage: normalizedStage(task) }]));
  const root = el('section', 'plan-board-root');
  root.dataset.mobileStage = selectedTaskId && byId.has(selectedTaskId)
    ? byId.get(selectedTaskId).stage
    : 'doing';
  const status = el('p', 'plan-board-status');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  if (activeResult.status === 'rejected') status.textContent = t('plan.board_tasks_unavailable', { reason: activeResult.reason?.message || t('plan.board_refresh_failed') });
  else if (doneResult.status === 'rejected') status.textContent = t('plan.board_history_unavailable', { reason: doneResult.reason?.message || t('plan.board_refresh_failed') });
  else status.hidden = true;
  const setStatus = (message, tone = '') => {
    status.textContent = message;
    status.hidden = !message;
    status.dataset.tone = tone;
  };

  const toolbar = el('div', 'plan-board-toolbar');
  const addForm = el('form', 'plan-board-add');
  const addLabel = el('label', 'sr-only', t('plan.new_task_title'));
  const addInput = el('input');
  addInput.type = 'text';
  addInput.maxLength = 500;
  addInput.autocomplete = 'off';
  addInput.placeholder = t('plan.add_to_inbox');
  addInput.setAttribute('aria-label', t('plan.new_task_title'));
  const addButton = el('button', 'plan-board-add-button', t('common.add'));
  addButton.type = 'submit';
  addForm.append(addLabel, addInput, addButton);
  const search = el('input', 'plan-board-search');
  search.type = 'search';
  search.autocomplete = 'off';
  search.placeholder = t('plan.search_tasks');
  search.setAttribute('aria-label', t('plan.search_tasks'));
  let projectFilter = 'all';
  const projects = [...new Set(tasks.map(projectName).filter(value => value !== t('plan.no_project')))].sort();
  const filter = projectMenu(projects, value => {
    projectFilter = value;
    applyFilters();
  });
  const completedButton = el('button', 'plan-board-tool', t('plan.completed_count', { count: completed.length }));
  completedButton.type = 'button';
  toolbar.append(addForm, search, filter.node, completedButton);

  const stageStrip = el('div', 'plan-board-stage-strip');
  stageStrip.setAttribute('role', 'radiogroup');
  stageStrip.setAttribute('aria-label', t('plan.visible_stage'));
  for (const stage of STAGES) {
    const count = grouped[stage].length;
    const choice = el('button', 'plan-board-stage-choice', `${stageLabel(stage)} · ${count}`);
    choice.type = 'button';
    choice.dataset.value = stage;
    choice.setAttribute('role', 'radio');
    const selected = stage === root.dataset.mobileStage;
    choice.setAttribute('aria-checked', String(selected));
    choice.tabIndex = selected ? 0 : -1;
    stageStrip.append(choice);
  }
  wireRadioGroup(stageStrip, value => { root.dataset.mobileStage = value; });

  const layout = el('div', 'plan-board-layout');
  const columns = el('div', 'plan-board-columns');
  columns.setAttribute('aria-label', t('plan.active_stages'));
  const detail = el('aside', 'plan-board-detail');
  detail.setAttribute('aria-label', t('plan.selected_details'));
  const lists = new Map();

  function selectTask(id) {
    const task = byId.get(String(id));
    if (!task) return;
    selectedTaskId = String(id);
    root.dataset.mobileStage = task.stage;
    stageStrip.querySelectorAll('[role="radio"]').forEach(choice => {
      const active = choice.dataset.value === task.stage;
      choice.setAttribute('aria-checked', String(active));
      choice.tabIndex = active ? 0 : -1;
    });
    root.querySelectorAll('.plan-board-card').forEach(card => {
      card.setAttribute('aria-selected', String(card.dataset.taskId === String(id)));
    });
    renderTaskDetail(task);
  }

  async function patchTask(task, body, successMessage) {
    setStatus(t('common.saving'));
    try {
      await json(request, `/api/tasks/${encodeURIComponent(task.id)}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      setStatus(successMessage);
      pendingStatus = successMessage;
      const focus = pendingFocus;
      await refresh();
      // the new board is staged off-page and only attached once the refresh settles, so focus
      // goes in here, not while it renders
      const board = document.querySelector('.plan-board-root');
      if (focus && board?.isConnected) {
        const selected = board.querySelector(`.plan-board-card[data-task-id="${CSS.escape(focus.taskId)}"][aria-selected="true"]`);
        restoreBoardFocus(board, board.querySelector('.plan-board-detail'), focus, Boolean(selected));
      }
    } catch (error) {
      pendingFocus = null;
      pendingStatus = '';
      setStatus(t('plan.board_task_stayed', { reason: plainError(error.message), stage: stageLabel(task.stage) }), 'danger');
    }
  }

  // remember the action and the card after this one, so the redrawn board can put focus back
  function act(task, action, body, message) {
    const cards = [...(lists.get(task.stage)?.querySelectorAll('.plan-board-card:not([hidden])') || [])];
    const at = cards.findIndex(card => card.dataset.taskId === String(task.id));
    const next = cards[at + 1] || cards[at - 1];
    pendingFocus = { action, taskId: String(task.id), stage: task.stage, nextId: next?.dataset.taskId || '' };
    return patchTask(task, body, message);
  }

  function renderTaskDetail(task) {
    detail.replaceChildren();
    const stage = el('span', 'plan-board-detail-stage', stageLabel(task.stage));
    const title = el('h2', '', task.title || t('plan.untitled_task'));
    const facts = el('dl', 'plan-board-facts');
    for (const [label, value] of [
      [t('plan.project'), projectName(task)],
      [t('plan.due'), dueLabel(task)],
    ]) {
      const row = el('div');
      row.append(el('dt', '', label), el('dd', '', value));
      facts.append(row);
    }
    const notes = el('p', 'plan-board-notes', task.notes || t('plan.no_notes'));
    const actions = el('div', 'plan-board-detail-actions');
    const index = STAGES.indexOf(task.stage);
    const back = el('button', '', t('plan.move_back'));
    back.type = 'button';
    back.dataset.act = 'back';
    back.disabled = index <= 0;
    back.addEventListener('click', () => act(task, 'back', { stage: STAGES[index - 1] }, t('plan.moved_to', { stage: stageLabel(STAGES[index - 1]) })));
    const forward = el('button', '', t('plan.move_forward'));
    forward.type = 'button';
    forward.dataset.act = 'forward';
    forward.disabled = index >= STAGES.length - 1;
    forward.addEventListener('click', () => act(task, 'forward', { stage: STAGES[index + 1] }, t('plan.moved_to', { stage: stageLabel(STAGES[index + 1]) })));
    const complete = el('button', 'plan-board-complete', t('plan.mark_complete'));
    complete.type = 'button';
    complete.dataset.act = 'complete';
    complete.addEventListener('click', () => act(task, 'complete', { stage: 'done' }, t('plan.task_completed')));
    actions.append(back, forward, complete);
    detail.append(stage, title, facts, notes, actions);
  }

  function renderCompleted() {
    selectedTaskId = '';
    root.querySelectorAll('.plan-board-card').forEach(card => card.setAttribute('aria-selected', 'false'));
    detail.replaceChildren(el('h2', '', t('plan.completed_tasks')));
    const list = el('ul', 'plan-board-completed');
    if (!completed.length) list.append(el('li', 'plan-board-empty', t('plan.no_completed')));
    for (const task of completed) {
      const item = el('li');
      const copy = el('div');
      copy.append(el('strong', '', task.title || t('plan.untitled_task')), el('span', '', t('plan.project_completed', { project: projectName(task) })));
      const restore = el('button', '', t('plan.restore_to_inbox'));
      restore.type = 'button';
      restore.addEventListener('click', () => patchTask({ ...task, stage: 'done' }, { stage: 'backlog' }, t('plan.restored_to_inbox')));
      item.append(copy, restore);
      list.append(item);
    }
    detail.append(list);
  }
  completedButton.addEventListener('click', renderCompleted);

  function boardPayload() {
    const items = [];
    for (const stage of STAGES) {
      [...lists.get(stage).querySelectorAll('.plan-board-card')].forEach((card, index) => {
        items.push({ id: card.dataset.taskId, stage, sort_order: index });
      });
    }
    return { items };
  }

  let reorderQueue = Promise.resolve();

  async function persistOrder(task, oldStage, payload) {
    setStatus(t('plan.saving_order'));
    try {
      await json(request, '/api/tasks/reorder', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setStatus(t('plan.moved_task_to', { title: task.title, stage: stageLabel(task.stage) }));
      selectedTaskId = String(task.id);
      try {
        await refresh();
      } catch (refreshError) {
        setStatus(t('plan.move_saved_no_refresh', { reason: refreshError.message }), 'danger');
      }
    } catch (error) {
      setStatus(t('plan.move_failed_reloading', { reason: error.message }), 'danger');
      task.stage = oldStage;
      try {
        await refresh();
      } catch (refreshError) {
        setStatus(t('plan.move_failed_no_reload', { reason: refreshError.message }), 'danger');
      }
    }
  }

  for (const stage of STAGES) {
    const column = el('section', 'plan-board-column');
    column.dataset.stage = stage;
    const heading = el('header', 'plan-board-column-head');
    const titleId = `plan-board-${stage}-title`;
    const title = el('h2', '', stageLabel(stage));
    title.id = titleId;
    heading.append(title, el('span', '', String(grouped[stage].length)));
    column.setAttribute('aria-labelledby', titleId);
    const list = el('ol', 'plan-board-list');
    list.dataset.stage = stage;
    lists.set(stage, list);
    for (const task of grouped[stage]) list.append(cardFor(task, selectTask));
    if (!grouped[stage].length) list.append(el('li', 'plan-board-empty', t('plan.no_tasks_stage')));
    const inline = el('form', 'plan-board-inline-add');
    const input = el('input');
    input.type = 'text';
    input.maxLength = 500;
    input.autocomplete = 'off';
    input.placeholder = t('plan.quick_add');
    input.setAttribute('aria-label', t('plan.add_task_to', { stage: stageLabel(stage) }));
    const button = el('button', '', '+');
    button.type = 'submit';
    button.setAttribute('aria-label', t('plan.add_to_stage', { stage: stageLabel(stage) }));
    inline.append(input, button);
    inline.addEventListener('submit', async event => {
      event.preventDefault();
      const titleValue = input.value.trim();
      if (!titleValue) return input.focus();
    button.disabled = true;
    setStatus(t('plan.adding_task'));
    let created = false;
    try {
      await json(request, '/api/tasks', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title: titleValue, stage }),
      });
      created = true;
      input.value = '';
      setStatus(t('plan.added_to_stage', { stage: stageLabel(stage) }));
    } catch (error) {
      setStatus(t('plan.task_add_failed', { reason: error.message }), 'danger');
      input.focus();
    }
    if (created) {
      try {
        await refresh();
      } catch (error) {
        setStatus(t('plan.task_added_no_reload', { reason: error.message }), 'danger');
      }
    }
    button.disabled = false;
    });
    list.addEventListener('dragover', event => {
      const types = [...(event.dataTransfer?.types || [])];
      const activeCard = root.querySelector('[data-dragging="true"]');
      if (!types.includes(PLAN_TASK_MIME) || !activeCard) return;
      const targetCard = event.target.closest('.plan-board-card');
      event.preventDefault();
      if (!targetCard || targetCard.parentElement !== list) {
        list.append(activeCard);
        return;
      }
      const bounds = targetCard.getBoundingClientRect();
      list.insertBefore(activeCard, event.clientY < bounds.top + bounds.height / 2 ? targetCard : targetCard.nextSibling);
    });
    list.addEventListener('drop', event => {
      const id = event.dataTransfer?.getData(PLAN_TASK_MIME);
      const activeCard = root.querySelector('[data-dragging="true"]');
      if (!id || !activeCard || activeCard.dataset.taskId !== String(id)) return;
      event.preventDefault();
      const task = byId.get(String(id));
      const card = root.querySelector(`.plan-board-card[data-task-id="${CSS.escape(String(id))}"]`);
      if (!task || !card || card !== activeCard) return;
      const oldStage = task.stage;
      if (card.parentElement !== list) list.append(card);
      card.dataset.dropAccepted = 'true';
      task.stage = stage;
      card.dataset.stage = stage;
      const movedTask = { ...task };
      const payload = boardPayload();
      reorderQueue = reorderQueue.catch(() => {}).then(() => persistOrder(movedTask, oldStage, payload));
    });
    column.append(heading, list, inline);
    columns.append(column);
  }

  function applyFilters() {
    const query = search.value.trim().toLowerCase();
    root.querySelectorAll('.plan-board-card').forEach(card => {
      const projectMatch = projectFilter === 'all' || card.dataset.project === projectFilter;
      const searchMatch = !query || card.dataset.search.includes(query);
      card.hidden = !(projectMatch && searchMatch);
    });
    for (const stage of STAGES) {
      const count = lists.get(stage).querySelectorAll('.plan-board-card:not([hidden])').length;
      root.querySelector(`.plan-board-column[data-stage="${stage}"] .plan-board-column-head span`).textContent = String(count);
      const choice = stageStrip.querySelector(`[data-value="${stage}"]`);
      choice.textContent = `${stageLabel(stage)} · ${count}`;
    }
  }
  search.addEventListener('input', applyFilters);

  addForm.addEventListener('submit', async event => {
    event.preventDefault();
    const title = addInput.value.trim();
    if (!title) return addInput.focus();
    addButton.disabled = true;
    setStatus(t('plan.adding_task'));
    let created = false;
    try {
      const task = await json(request, '/api/tasks', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title, stage: 'backlog' }),
      });
      created = true;
      selectedTaskId = String(task.id);
      addInput.value = '';
      setStatus(t('plan.added_to_inbox'));
    } catch (error) {
      setStatus(t('plan.task_add_failed', { reason: error.message }), 'danger');
      addInput.focus();
    }
    if (created) {
      try {
        await refresh();
      } catch (error) {
        setStatus(t('plan.task_added_no_reload', { reason: error.message }), 'danger');
      }
    }
    addButton.disabled = false;
  });

  layout.append(columns, detail);
  root.append(toolbar, stageStrip, status, layout);
  target.replaceChildren(root);
  disposeBoardMenu = filter.dispose;
  if (pendingStatus && status.hidden) setStatus(pendingStatus);
  pendingStatus = '';
  const focus = pendingFocus;
  pendingFocus = null;
  // a completed task left its column; the one after it takes the detail
  if (focus?.action === 'complete' && !byId.has(focus.taskId) && byId.has(focus.nextId)) selectedTaskId = focus.nextId;
  const initial = byId.get(selectedTaskId) || byId.get(String(grouped.doing[0]?.id || '')) || byId.get(String(tasks[0]?.id || ''));
  if (initial) selectTask(initial.id);
  else renderCompleted();
}

// after move back/forward: the same button if it still works, else the other one, else the card.
// after complete: the next card in that column, else its first card, else its quick add
export function restoreBoardFocus(root, detail, focus, stillSelected) {
  const shown = node => node && !node.disabled && node.getClientRects().length ? node : null;
  const card = id => id && shown(root.querySelector(`.plan-board-card[data-task-id="${CSS.escape(id)}"]:not([hidden]) .plan-board-card-main`));
  let target = null;
  if (focus.action === 'complete') {
    target = card(focus.nextId)
      || shown(root.querySelector(`.plan-board-list[data-stage="${focus.stage}"] .plan-board-card:not([hidden]) .plan-board-card-main`))
      || shown(root.querySelector(`.plan-board-column[data-stage="${focus.stage}"] .plan-board-inline-add input`));
  } else {
    const other = focus.action === 'back' ? 'forward' : 'back';
    if (stillSelected) target = shown(detail.querySelector(`[data-act="${focus.action}"]`)) || shown(detail.querySelector(`[data-act="${other}"]`));
    target = target || card(focus.taskId);
  }
  target?.focus();
}
