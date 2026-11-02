// the names an app module takes from undo_delete.js, for tests that run a module's source inside
// a vm context with its import lines cut off (the real functions, so rows keep their more menu)
import { createUndoDelete, deleteItemHtml, goneTextHtml, moreButton, moreMenuHtml, undoButtonHtml, wireMoreMenus } from '../../../static/js/undo_delete.js';

export const undoGlobals = { createUndoDelete, deleteItemHtml, goneTextHtml, moreButton, moreMenuHtml, undoButtonHtml, wireMoreMenus };
