const remainingBody = document.body;
const remainingById = id => document.getElementById(id);

function remainingAnnounce(message) {
  const status = remainingBody.dataset.starter === 'plan-board'
    ? remainingById('board-live-status')
    : remainingById('news-live-status');
  if (status) status.textContent = message;
  const toast = remainingById('starter-toast');
  if (!toast) return;
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(remainingAnnounce.timer);
  remainingAnnounce.timer = setTimeout(() => { toast.hidden = true; }, 2200);
}

function chooseRadio(radio, focus = false) {
  const group = radio.closest('[role="radiogroup"]');
  if (!group) return;
  const radios = [...group.querySelectorAll('[role="radio"]')];
  radios.forEach(item => {
    const selected = item === radio;
    item.setAttribute('aria-checked', String(selected));
    item.tabIndex = selected ? 0 : -1;
  });
  if (radio.dataset.mobileStageChoice) {
    remainingBody.dataset.mobileStage = radio.dataset.mobileStageChoice;
  }
  if (focus) radio.focus();
}

document.querySelectorAll('[role="radiogroup"]').forEach(group => {
  const radios = [...group.querySelectorAll('[role="radio"]')];
  radios.forEach((radio, index) => {
    radio.addEventListener('click', () => chooseRadio(radio));
    radio.addEventListener('keydown', event => {
      let next = null;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = radios[(index + 1) % radios.length];
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = radios[(index - 1 + radios.length) % radios.length];
      if (event.key === 'Home') next = radios[0];
      if (event.key === 'End') next = radios.at(-1);
      if (!next) return;
      event.preventDefault();
      chooseRadio(next, true);
    });
  });
});

/* Plan board local behavior */

const planStages = ['backlog', 'next', 'doing', 'waiting'];
const planStageLabels = { backlog: 'inbox', next: 'planned', doing: 'in progress', waiting: 'blocked' };
let selectedTask = document.querySelector('.board-card[aria-selected="true"]');
let projectFilter = 'all';

function planCards() {
  return [...document.querySelectorAll('.board-card')];
}

function refreshPlanCounts() {
  planStages.forEach(stage => {
    const count = document.querySelectorAll(`.board-card[data-stage="${stage}"]:not([hidden])`).length;
    document.querySelectorAll(`[data-count-for="${stage}"]`).forEach(node => { node.textContent = String(count); });
  });
}

function renderTaskDetail(card) {
  if (!card) return;
  delete remainingBody.dataset.boardEmpty;
  selectedTask = card;
  planCards().forEach(item => item.setAttribute('aria-selected', String(item === card)));
  const stage = card.dataset.stage;
  remainingById('task-detail-stage').textContent = planStageLabels[stage] || stage;
  remainingById('task-detail-title').textContent = card.dataset.title;
  remainingById('task-detail-project').textContent = card.dataset.project;
  remainingById('task-detail-due').textContent = card.dataset.due;
  remainingById('task-detail-notes').textContent = card.dataset.notes;
  const index = planStages.indexOf(stage);
  remainingById('task-move-back').disabled = index <= 0;
  remainingById('task-move-forward').disabled = index >= planStages.length - 1;
  remainingById('task-complete').disabled = false;
}

function clearTaskDetail(boardIsEmpty = planCards().length === 0) {
  selectedTask = null;
  if (boardIsEmpty) remainingBody.dataset.boardEmpty = 'true';
  else delete remainingBody.dataset.boardEmpty;
  planCards().forEach(item => item.setAttribute('aria-selected', 'false'));
  remainingById('task-detail-stage').textContent = boardIsEmpty ? 'empty' : 'filtered';
  remainingById('task-detail-title').textContent = boardIsEmpty ? 'no task selected' : 'no matching tasks';
  remainingById('task-detail-project').textContent = boardIsEmpty ? 'none' : 'change the filters';
  remainingById('task-detail-due').textContent = 'no date';
  remainingById('task-detail-notes').textContent = boardIsEmpty
    ? 'Add a task to Inbox to continue.'
    : 'Active tasks are still here. Clear the search or choose another project.';
  remainingById('task-move-back').disabled = true;
  remainingById('task-move-forward').disabled = true;
  remainingById('task-complete').disabled = true;
}

function bindPlanCard(card) {
  card.querySelector('.board-card-button')?.addEventListener('click', () => renderTaskDetail(card));
  const handle = card.querySelector('.drag-handle');
  handle?.addEventListener('dragstart', event => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', card.dataset.taskId);
  });
}

function moveTask(card, nextStage, message = '') {
  const list = document.querySelector(`[data-drop-stage="${nextStage}"]`);
  if (!card || !list || !planStages.includes(nextStage)) return;
  list.append(card);
  card.dataset.stage = nextStage;
  refreshPlanCounts();
  renderTaskDetail(card);
  remainingBody.dataset.mobileStage = nextStage;
  const mobileChoice = document.querySelector(`[data-mobile-stage-choice="${nextStage}"]`);
  if (mobileChoice) chooseRadio(mobileChoice);
  remainingAnnounce(message || `moved to ${planStageLabels[nextStage]} in this starter`);
}

planCards().forEach(bindPlanCard);
renderTaskDetail(selectedTask);
refreshPlanCounts();

document.querySelectorAll('[data-drop-stage]').forEach(list => {
  list.addEventListener('dragover', event => {
    event.preventDefault();
    list.dataset.dragOver = 'true';
  });
  list.addEventListener('dragleave', () => { delete list.dataset.dragOver; });
  list.addEventListener('drop', event => {
    event.preventDefault();
    delete list.dataset.dragOver;
    const card = document.querySelector(`[data-task-id="${CSS.escape(event.dataTransfer.getData('text/plain'))}"]`);
    moveTask(card, list.dataset.dropStage);
  });
});

remainingById('task-move-back')?.addEventListener('click', () => {
  const index = planStages.indexOf(selectedTask?.dataset.stage);
  if (index > 0) moveTask(selectedTask, planStages[index - 1]);
});
remainingById('task-move-forward')?.addEventListener('click', () => {
  const index = planStages.indexOf(selectedTask?.dataset.stage);
  if (index >= 0 && index < planStages.length - 1) moveTask(selectedTask, planStages[index + 1]);
});

remainingById('task-complete')?.addEventListener('click', () => {
  if (!selectedTask) return;
  const title = selectedTask.dataset.title;
  const item = document.createElement('li');
  const copy = document.createElement('div');
  const strong = document.createElement('strong');
  const meta = document.createElement('span');
  const restore = document.createElement('button');
  strong.textContent = title;
  meta.textContent = `completed just now · ${selectedTask.dataset.project}`;
  restore.type = 'button';
  restore.dataset.restoreTitle = title;
  restore.dataset.restoreProject = selectedTask.dataset.project;
  restore.textContent = 'restore to inbox';
  copy.append(strong, meta);
  item.append(copy, restore);
  remainingById('completed-list')?.prepend(item);
  const former = selectedTask;
  item._completedCard = former;
  selectedTask = null;
  former.remove();
  applyPlanFilters();
  remainingAnnounce(`completed ${title}`);
});

function makePlanCard(title, stage = 'backlog', project = 'personal') {
  const card = document.createElement('li');
  card.className = 'board-card';
  card.dataset.taskId = `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  card.dataset.project = project;
  card.dataset.stage = stage;
  card.dataset.title = title;
  card.dataset.due = 'no date';
  card.dataset.notes = 'Added locally in this fake-data starter.';
  const handle = document.createElement('button');
  handle.className = 'drag-handle';
  handle.type = 'button';
  handle.draggable = true;
  handle.setAttribute('aria-label', `drag ${title}`);
  const button = document.createElement('button');
  button.className = 'board-card-button';
  button.type = 'button';
  const titleNode = document.createElement('span');
  titleNode.className = 'board-card-title';
  titleNode.textContent = title;
  const meta = document.createElement('span');
  meta.className = 'board-card-meta';
  const projectNode = document.createElement('span');
  const dueNode = document.createElement('span');
  projectNode.textContent = project;
  dueNode.textContent = 'no date';
  meta.append(projectNode, dueNode);
  button.append(titleNode, meta);
  card.append(handle, button);
  bindPlanCard(card);
  return card;
}

function addPlanTask(title, stage = 'backlog') {
  const clean = title.trim();
  if (!clean) {
    remainingAnnounce('enter a task title first');
    return null;
  }
  const project = projectFilter === 'all' ? 'personal' : projectFilter;
  const card = makePlanCard(clean, stage, project);
  document.querySelector(`[data-drop-stage="${stage}"]`)?.append(card);
  refreshPlanCounts();
  applyPlanFilters();
  reconcilePlanSelection(card);
  remainingAnnounce(`added to ${planStageLabels[stage]} in this starter`);
  return card;
}

remainingById('board-quick-add')?.addEventListener('click', () => {
  const input = remainingById('board-quick-title');
  if (addPlanTask(input.value)) input.value = '';
  input.focus();
});
remainingById('board-quick-title')?.addEventListener('keydown', event => {
  if (event.key !== 'Enter') return;
  event.preventDefault();
  remainingById('board-quick-add').click();
});
document.querySelectorAll('[data-inline-add]').forEach(form => {
  form.addEventListener('submit', event => {
    event.preventDefault();
    const input = form.querySelector('input');
    if (addPlanTask(input.value, form.dataset.inlineAdd)) input.value = '';
    input.focus();
  });
});

function reconcilePlanSelection(preferred = null) {
  const visible = planCards().filter(card => !card.hidden);
  const next = preferred && !preferred.hidden
    ? preferred
    : selectedTask && !selectedTask.hidden
      ? selectedTask
      : visible[0];
  if (next) renderTaskDetail(next);
  else clearTaskDetail(planCards().length === 0);
}

function applyPlanFilters() {
  const query = (remainingById('board-search')?.value || '').trim().toLowerCase();
  planCards().forEach(card => {
    const projectMatch = projectFilter === 'all' || card.dataset.project === projectFilter;
    const searchMatch = !query || `${card.dataset.title} ${card.dataset.project} ${card.dataset.notes}`.toLowerCase().includes(query);
    card.hidden = !(projectMatch && searchMatch);
  });
  refreshPlanCounts();
  reconcilePlanSelection();
}
remainingById('board-search')?.addEventListener('input', applyPlanFilters);

const filterTrigger = remainingById('board-filter-trigger');
const filterMenu = remainingById('board-filter-menu');
const filterItems = filterMenu ? [...filterMenu.querySelectorAll('[role="menuitemradio"]')] : [];

function closeFilterMenu(returnFocus = false) {
  if (!filterMenu || !filterTrigger) return;
  filterMenu.hidden = true;
  filterTrigger.setAttribute('aria-expanded', 'false');
  if (returnFocus) filterTrigger.focus();
}

function chooseProjectFilter(item) {
  projectFilter = item.dataset.projectFilter;
  filterItems.forEach(option => option.setAttribute('aria-checked', String(option === item)));
  filterTrigger.textContent = projectFilter === 'all' ? 'project: all' : `project: ${item.textContent.trim()}`;
  applyPlanFilters();
  closeFilterMenu(true);
}

filterTrigger?.addEventListener('click', () => {
  const open = filterTrigger.getAttribute('aria-expanded') !== 'true';
  filterTrigger.setAttribute('aria-expanded', String(open));
  filterMenu.hidden = !open;
  if (open) filterItems.find(item => item.getAttribute('aria-checked') === 'true')?.focus();
});
filterItems.forEach((item, index) => {
  item.addEventListener('click', () => chooseProjectFilter(item));
  item.addEventListener('keydown', event => {
    let next = null;
    if (event.key === 'ArrowDown') next = filterItems[(index + 1) % filterItems.length];
    if (event.key === 'ArrowUp') next = filterItems[(index - 1 + filterItems.length) % filterItems.length];
    if (event.key === 'Home') next = filterItems[0];
    if (event.key === 'End') next = filterItems.at(-1);
    if (event.key === 'Escape') return closeFilterMenu(true);
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      return chooseProjectFilter(item);
    }
    if (!next) return;
    event.preventDefault();
    next.focus();
  });
});

document.addEventListener('click', event => {
  if (!filterMenu || filterMenu.hidden || filterMenu.contains(event.target) || filterTrigger?.contains(event.target)) return;
  closeFilterMenu();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && filterMenu && !filterMenu.hidden) closeFilterMenu(true);
});

remainingById('completed-list')?.addEventListener('click', event => {
  const button = event.target.closest('[data-restore-title]');
  if (!button) return;
  const completedItem = button.closest('li');
  const card = completedItem?._completedCard
    || makePlanCard(button.dataset.restoreTitle, 'backlog', button.dataset.restoreProject);
  card.dataset.stage = 'backlog';
  document.querySelector('[data-drop-stage="backlog"]')?.prepend(card);
  completedItem?.remove();
  refreshPlanCounts();
  applyPlanFilters();
  let filtersChanged = false;
  if (card.hidden) {
    filtersChanged = true;
    const search = remainingById('board-search');
    if (search) search.value = '';
    projectFilter = card.dataset.project;
    filterItems.forEach(item => item.setAttribute(
      'aria-checked',
      String(item.dataset.projectFilter === projectFilter),
    ));
    filterTrigger.textContent = `project: ${projectFilter}`;
    applyPlanFilters();
  }
  reconcilePlanSelection(card);
  remainingAnnounce(
    `restored ${button.dataset.restoreTitle} to inbox${filtersChanged ? '; filters updated to show it' : ''}`,
  );
});

/* Scheduled News local behavior */

const newsEnable = remainingById('news-enable');
newsEnable?.addEventListener('click', () => {
  const state = remainingById('news-workflow-state');
  const enabled = state.dataset.enabled !== 'true';
  state.dataset.enabled = String(enabled);
  state.textContent = enabled ? 'news is enabled' : 'news is off';
  newsEnable.textContent = enabled ? 'disable news' : 'enable news';
  remainingAnnounce(enabled ? 'News enabled locally; next fake run is tomorrow at 07:30' : 'News disabled; sources and past briefs kept');
});

remainingById('news-preview-action')?.addEventListener('click', () => remainingAnnounce('preview refreshed from fake sources'));

document.querySelectorAll('[data-save-article]').forEach(button => {
  button.addEventListener('click', () => {
    const saved = button.getAttribute('aria-pressed') !== 'true';
    button.setAttribute('aria-pressed', String(saved));
    button.textContent = saved ? 'saved to Library' : 'save to Library';
    remainingAnnounce(saved ? `${button.dataset.saveArticle} saved locally in this starter` : `${button.dataset.saveArticle} removed from the fake Library`);
  });
});

const sourceTest = remainingById('source-test');
const sourceSave = remainingById('source-save');
const sourceUrl = remainingById('source-url');
let testedSourceUrl = '';

function resetSourceTest() {
  testedSourceUrl = '';
  if (sourceSave) sourceSave.disabled = true;
  const result = remainingById('source-test-result');
  if (result) result.hidden = true;
}

sourceUrl?.addEventListener('input', resetSourceTest);
sourceTest?.addEventListener('click', () => {
  const result = remainingById('source-test-result');
  let parsed;
  try {
    parsed = new URL(sourceUrl?.value.trim() || '');
  } catch {
    resetSourceTest();
    remainingAnnounce('enter a valid http or https feed URL first');
    return;
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    resetSourceTest();
    remainingAnnounce('enter a valid http or https feed URL first');
    return;
  }
  testedSourceUrl = parsed.href;
  sourceUrl.value = testedSourceUrl;
  result.hidden = false;
  sourceSave.disabled = false;
  remainingAnnounce('source test passed; nothing saved yet');
});
sourceSave?.addEventListener('click', () => {
  if (sourceSave.disabled || sourceUrl?.value.trim() !== testedSourceUrl) {
    resetSourceTest();
    return;
  }
  sourceSave.closest('.modal')?.querySelector('[data-close-modal]')?.click();
  remainingAnnounce('source saved locally in this starter');
});
