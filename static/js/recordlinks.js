import { replaceRouteUrl } from './route_history.js';

const VIEWS = new Set(['tasks', 'calendar', 'reminders', 'habits', 'subs', 'days', 'mail', 'chat']);

export function recordTarget(view, id, occurrence = '') {
  if (!VIEWS.has(view) || typeof id !== 'string' || !/^[a-zA-Z0-9_-]{1,160}$/.test(id)) return null;
  if (view === 'mail' && !/^(task|event)-[a-zA-Z0-9_-]+$/.test(id)) return null;
  const date = /^\d{4}-\d{2}-\d{2}$/.test(occurrence) ? occurrence : '';
  return { view, id, occurrence: view === 'calendar' ? date : '' };
}

export function readRecordTarget(url) {
  const params = new URL(url).searchParams;
  return recordTarget(params.get('record_view'), params.get('record'), params.get('occurrence') || '');
}

export function withRecordTarget(url, target) {
  const result = new URL(url);
  result.searchParams.set('record_view', target.view);
  result.searchParams.set('record', target.id);
  if (target.occurrence) result.searchParams.set('occurrence', target.occurrence);
  else result.searchParams.delete('occurrence');
  return result;
}

export function replaceLinkedRecord(view, previousId, id, occurrence) {
  const current = readRecordTarget(location.href);
  const target = recordTarget(view, id, occurrence ?? (current?.id === id ? current.occurrence : ''));
  if (!target || current?.view !== view || current.id !== previousId) return;
  const url = withRecordTarget(location.href, target);
  replaceRouteUrl(url.pathname + url.search + url.hash);
}

export async function revealRecord(target, isCurrent = () => true) {
  if (target.view === 'chat') {
    const module = await import('./aiderun.js');
    return isCurrent() && module.openAideRun(target.id, isCurrent);
  }
  if (target.view === 'mail') {
    const module = await import('./mail.js');
    return isCurrent() && module.openMailSource(target.id, isCurrent);
  }
  if (target.view === 'tasks') {
    const module = await import('./tasks.js');
    return isCurrent() && module.openTaskRecord(target.id, isCurrent);
  }
  if (target.view === 'calendar') {
    const module = await import('./calendar.js');
    return isCurrent() && module.openEvent(target.id, target.occurrence || null);
  }
  const selectors = {
    reminders: '#reminder-list .settings-list-row',
    habits: '#habits-body .habit-card',
    subs: '#subs-list .sub-item',
    days: '#days-grid .day-card',
  };
  const row = [...document.querySelectorAll(selectors[target.view])]
    .find(item => item.dataset.id === target.id && item.getClientRects().length);
  if (!row || !isCurrent()) return false;
  row.classList.add('record-target');
  row.tabIndex = -1;
  row.scrollIntoView({ block: 'center', behavior: 'instant' });
  row.focus({ preventScroll: true });
  return true;
}
