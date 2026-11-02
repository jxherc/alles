// delete is never one tap away (u.10): a row keeps a "more" menu, delete sits in it, and the row
// turns into "deleted · undo" for a few seconds. the server call goes out only when that time is
// up. tasks.js and days.js did this first; the apps after them share this file.
import { wireActionMenu } from './kokuen.js?v=5';
import { t } from './i18n.js';

export const UNDO_MS = 6000;

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const icon = name => (globalThis.window?.icon ? globalThis.window.icon(name) : '');   // central icon set, load-order safe
const part = id => String(id).replace(/[^\w-]/g, '_');

// the row's more button and its menu; `items` is the menu's own buttons (role="menuitem")
export function moreMenuHtml(key, id, name, items, wrapClass = '') {
  const base = `${key}-${part(id)}`;
  return `<span class="row-more-wrap${wrapClass ? ' ' + wrapClass : ''}"><button type="button" class="icon-btn row-more" id="more-${base}" aria-haspopup="menu" aria-expanded="false" aria-controls="menu-${base}" aria-label="${esc(t('tasks.more_named', { task: name }))}">${icon('more')}</button>
    <div class="ctx-menu row-menu" id="menu-${base}" role="menu" aria-labelledby="more-${base}" hidden>${items}</div></span>`;
}

export const deleteItemHtml = (attrs = '', label = t('common.delete')) =>
  `<button type="button" class="ctx-item danger" role="menuitem" ${attrs}>${esc(label)}</button>`;

export function wireMoreMenus(root) {
  root?.querySelectorAll('.row-more').forEach(button => wireActionMenu(button, document.getElementById(button.getAttribute('aria-controls'))));
}

export const moreButton = (key, id) => document.getElementById(`more-${key}-${part(id)}`);

// "deleted “name”" and the undo button, for the row that stands in while the delete waits
export const goneTextHtml = name => `<span class="row-gone-text">${esc(t('tasks.deleted_named', { task: name }))}</span>`;
export const undoButtonHtml = (id, cls = 'btn') => `<button type="button" class="${cls}" data-undo-del="${esc(id)}">${esc(t('common.undo'))}</button>`;
export const undoButton = id => document.querySelector(`[data-undo-del="${CSS.escape(String(id))}"]`);

// one waiting delete at a time (a second one sends the first at once).
//   remove(id, extra): the server call, throws when it fails
//   render(): draws the list again from the app's own state (gone() says which row stands in)
//   after(gone, ok, hadFocus): reload what the app shows, and put focus back where it was
//   focusBack(id): where focus goes when undo is pressed (default: the row's more button)
export function createUndoDelete({ key, remove, render, after, focusBack = null, failed = null }) {
  let gone = null;
  const now = async () => {
    const pending = gone;
    if (!pending) return;
    clearTimeout(pending.timer);
    gone = null;
    const hadFocus = document.activeElement?.hasAttribute?.('data-undo-del') ?? false;
    let ok = true;
    try { await remove(pending.id, pending); } catch (error) { ok = false; failed?.(pending.id, error); }
    // a failed delete brings the row back at once, before the reload
    if (!ok) render();
    await after?.(pending, ok, hadFocus);
  };
  return {
    gone: () => gone,
    is: id => gone !== null && String(gone.id) === String(id),
    now,
    later(id, extra = {}) {
      if (gone) now();
      gone = { ...extra, id, timer: setTimeout(now, UNDO_MS) };
      render();
      undoButton(id)?.focus();
    },
    undo() {
      if (!gone) return;
      clearTimeout(gone.timer);
      const { id } = gone;
      gone = null;
      render();
      (focusBack ? focusBack(id) : moreButton(key, id))?.focus();
    },
  };
}
