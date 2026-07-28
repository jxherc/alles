const STAGES = Object.freeze(['backlog', 'next', 'doing', 'waiting']);
const STAGE_LABELS = Object.freeze({
  backlog: 'inbox',
  next: 'planned',
  doing: 'in progress',
  waiting: 'blocked',
});
const PLAN_TASK_MIME = 'application/x-alles-plan-task';

let selectedTaskId = '';
let disposeBoardMenu = () => {};

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
    throw new Error(typeof detail === 'string' ? detail : `request failed: ${response.status}`);
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
  return String(task?.project || '').trim() || 'no project';
}

export function localDateKey(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function dueLabel(task) {
  const due = String(task?.due_date || '').slice(0, 10);
  if (!due) return 'no date';
  const today = localDateKey();
  if (due < today) return `overdue · ${due}`;
  if (due === today) return 'today';
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
  handle.setAttribute('aria-label', `drag ${task.title || 'task'}`);
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
  button.append(el('strong', 'plan-board-card-title', task.title || 'untitled task'));
  const meta = el('span', 'plan-board-card-meta');
  if (Number(task.priority || 0) > 0) {
    const priority = el('span', `plan-board-priority${Number(task.priority) >= 2 ? ' high' : ''}`);
    priority.setAttribute('aria-label', Number(task.priority) >= 2 ? 'high priority' : 'priority');
    meta.append(priority);
  }
  meta.append(el('span', '', projectName(task)), el('span', dueLabel(task)));
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
  const trigger = el('button', 'plan-board-tool', 'project: all');
  trigger.type = 'button';
  trigger.setAttribute('aria-expanded', 'false');
  const menu = el('div', 'plan-board-menu');
  const menuId = `plan-board-menu-${Math.random().toString(16).slice(2)}`;
  menu.id = menuId;
  menu.hidden = true;
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', 'filter tasks by project');
  trigger.setAttribute('aria-controls', menuId);
  const values = ['all', ...projects];
  const items = values.map(value => {
    const item = el('button', 'plan-board-menu-item', value === 'all' ? 'all projects' : value);
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
  const choose = item => {
    items.forEach(option => option.setAttribute('aria-checked', String(option === item)));
    trigger.textContent = item.dataset.value === 'all' ? 'project: all' : `project: ${item.dataset.value}`;
    onChange(item.dataset.value);
    close(true);
  };
  trigger.addEventListener('click', () => {
    const open = trigger.getAttribute('aria-expanded') !== 'true';
    trigger.setAttribute('aria-expanded', String(open));
    menu.hidden = !open;
    if (open) items.find(item => item.getAttribute('aria-checked') === 'true')?.focus();
  });
  trigger.addEventListener('keydown', event => {
    if (event.key !== 'ArrowDown') return;
    event.preventDefault();
    trigger.setAttribute('aria-expanded', 'true');
    menu.hidden = false;
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
  if (activeResult.status === 'rejected') status.textContent = `tasks unavailable: ${activeResult.reason?.message || 'refresh failed'}`;
  else if (doneResult.status === 'rejected') status.textContent = `active tasks ready; completed history unavailable: ${doneResult.reason?.message || 'refresh failed'}`;
  else status.hidden = true;
  const setStatus = (message, tone = '') => {
    status.textContent = message;
    status.hidden = !message;
    status.dataset.tone = tone;
  };

  const toolbar = el('div', 'plan-board-toolbar');
  const addForm = el('form', 'plan-board-add');
  const addLabel = el('label', 'sr-only', 'new task title');
  const addInput = el('input');
  addInput.type = 'text';
  addInput.maxLength = 500;
  addInput.autocomplete = 'off';
  addInput.placeholder = 'add a task to inbox';
  addInput.setAttribute('aria-label', 'new task title');
  const addButton = el('button', 'plan-board-add-button', 'add');
  addButton.type = 'submit';
  addForm.append(addLabel, addInput, addButton);
  const search = el('input', 'plan-board-search');
  search.type = 'search';
  search.autocomplete = 'off';
  search.placeholder = 'search tasks';
  search.setAttribute('aria-label', 'search tasks');
  let projectFilter = 'all';
  const projects = [...new Set(tasks.map(projectName).filter(value => value !== 'no project'))].sort();
  const filter = projectMenu(projects, value => {
    projectFilter = value;
    applyFilters();
  });
  const completedButton = el('button', 'plan-board-tool', `completed · ${completed.length}`);
  completedButton.type = 'button';
  toolbar.append(addForm, search, filter.node, completedButton);

  const stageStrip = el('div', 'plan-board-stage-strip');
  stageStrip.setAttribute('role', 'radiogroup');
  stageStrip.setAttribute('aria-label', 'visible task stage');
  for (const stage of STAGES) {
    const count = grouped[stage].length;
    const choice = el('button', 'plan-board-stage-choice', `${STAGE_LABELS[stage]} · ${count}`);
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
  columns.setAttribute('aria-label', 'active task stages');
  const detail = el('aside', 'plan-board-detail');
  detail.setAttribute('aria-label', 'selected task details');
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
    setStatus('saving…');
    try {
      await json(request, `/api/tasks/${encodeURIComponent(task.id)}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      setStatus(successMessage);
      await refresh();
    } catch (error) {
      setStatus(`${error.message}. The task stayed in ${STAGE_LABELS[task.stage] || 'completed'}.`, 'danger');
    }
  }

  function renderTaskDetail(task) {
    detail.replaceChildren();
    const stage = el('span', 'plan-board-detail-stage', STAGE_LABELS[task.stage]);
    const title = el('h2', '', task.title || 'untitled task');
    const facts = el('dl', 'plan-board-facts');
    for (const [label, value] of [
      ['project', projectName(task)],
      ['due', dueLabel(task)],
      ['record', 'existing Task'],
    ]) {
      const row = el('div');
      row.append(el('dt', '', label), el('dd', '', value));
      facts.append(row);
    }
    const notes = el('p', 'plan-board-notes', task.notes || 'No notes.');
    const actions = el('div', 'plan-board-detail-actions');
    const index = STAGES.indexOf(task.stage);
    const back = el('button', '', 'move back');
    back.type = 'button';
    back.disabled = index <= 0;
    back.addEventListener('click', () => patchTask(task, { stage: STAGES[index - 1] }, `moved to ${STAGE_LABELS[STAGES[index - 1]]}`));
    const forward = el('button', '', 'move forward');
    forward.type = 'button';
    forward.disabled = index >= STAGES.length - 1;
    forward.addEventListener('click', () => patchTask(task, { stage: STAGES[index + 1] }, `moved to ${STAGE_LABELS[STAGES[index + 1]]}`));
    const complete = el('button', 'plan-board-complete', 'mark complete');
    complete.type = 'button';
    complete.addEventListener('click', () => patchTask(task, { stage: 'done' }, 'task completed'));
    actions.append(back, forward, complete);
    detail.append(stage, title, facts, notes, actions);
  }

  function renderCompleted() {
    selectedTaskId = '';
    root.querySelectorAll('.plan-board-card').forEach(card => card.setAttribute('aria-selected', 'false'));
    detail.replaceChildren(el('h2', '', 'completed tasks'));
    const list = el('ul', 'plan-board-completed');
    if (!completed.length) list.append(el('li', 'plan-board-empty', 'No completed tasks.'));
    for (const task of completed) {
      const item = el('li');
      const copy = el('div');
      copy.append(el('strong', '', task.title || 'untitled task'), el('span', '', `${projectName(task)} · completed`));
      const restore = el('button', '', 'restore to inbox');
      restore.type = 'button';
      restore.addEventListener('click', () => patchTask({ ...task, stage: 'done' }, { stage: 'backlog' }, 'restored to inbox'));
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
    setStatus('saving board order…');
    try {
      await json(request, '/api/tasks/reorder', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setStatus(`moved ${task.title} to ${STAGE_LABELS[task.stage]}`);
      selectedTaskId = String(task.id);
      try {
        await refresh();
      } catch (refreshError) {
        setStatus(`move saved, but the board could not refresh: ${refreshError.message}`, 'danger');
      }
    } catch (error) {
      setStatus(`move failed: ${error.message}. Reloading the last confirmed board.`, 'danger');
      task.stage = oldStage;
      try {
        await refresh();
      } catch (refreshError) {
        setStatus(`move failed and the board could not reload: ${refreshError.message}`, 'danger');
      }
    }
  }

  for (const stage of STAGES) {
    const column = el('section', 'plan-board-column');
    column.dataset.stage = stage;
    const heading = el('header', 'plan-board-column-head');
    const titleId = `plan-board-${stage}-title`;
    const title = el('h2', '', STAGE_LABELS[stage]);
    title.id = titleId;
    heading.append(title, el('span', '', String(grouped[stage].length)));
    column.setAttribute('aria-labelledby', titleId);
    const list = el('ol', 'plan-board-list');
    list.dataset.stage = stage;
    lists.set(stage, list);
    for (const task of grouped[stage]) list.append(cardFor(task, selectTask));
    if (!grouped[stage].length) list.append(el('li', 'plan-board-empty', 'no tasks in this stage'));
    const inline = el('form', 'plan-board-inline-add');
    const input = el('input');
    input.type = 'text';
    input.maxLength = 500;
    input.autocomplete = 'off';
    input.placeholder = 'quick add';
    input.setAttribute('aria-label', `add task to ${STAGE_LABELS[stage]}`);
    const button = el('button', '', '+');
    button.type = 'submit';
    button.setAttribute('aria-label', `add to ${STAGE_LABELS[stage]}`);
    inline.append(input, button);
    inline.addEventListener('submit', async event => {
      event.preventDefault();
      const titleValue = input.value.trim();
      if (!titleValue) return input.focus();
    button.disabled = true;
    setStatus('adding task…');
    let created = false;
    try {
      await json(request, '/api/tasks', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title: titleValue, stage }),
      });
      created = true;
      input.value = '';
      setStatus(`added to ${STAGE_LABELS[stage]}`);
    } catch (error) {
      setStatus(`task could not be added: ${error.message}`, 'danger');
      input.focus();
    }
    if (created) {
      try {
        await refresh();
      } catch (error) {
        setStatus(`task was added, but the board could not reload: ${error.message}`, 'danger');
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
      choice.textContent = `${STAGE_LABELS[stage]} · ${count}`;
    }
  }
  search.addEventListener('input', applyFilters);

  addForm.addEventListener('submit', async event => {
    event.preventDefault();
    const title = addInput.value.trim();
    if (!title) return addInput.focus();
    addButton.disabled = true;
    setStatus('adding task…');
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
      setStatus('added to inbox');
    } catch (error) {
      setStatus(`task could not be added: ${error.message}`, 'danger');
      addInput.focus();
    }
    if (created) {
      try {
        await refresh();
      } catch (error) {
        setStatus(`task was added, but the board could not reload: ${error.message}`, 'danger');
      }
    }
    addButton.disabled = false;
  });

  layout.append(columns, detail);
  root.append(toolbar, stageStrip, status, layout);
  target.replaceChildren(root);
  disposeBoardMenu = filter.dispose;
  const initial = byId.get(selectedTaskId) || byId.get(String(grouped.doing[0]?.id || '')) || byId.get(String(tasks[0]?.id || ''));
  if (initial) selectTask(initial.id);
  else renderCompleted();
}
