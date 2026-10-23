// Keyboard path for clickable date grids (calendar month, mini calendar, journal
// heatmap). One tab stop per grid, arrows move by the given steps, Enter or
// Space does what a click does. Cells stay small spans/divs, so the 44px
// button minimum never stretches them. Callers group cells into role=row.

export function wireGridNav(grid, { cells, steps, label, start } = {}) {
  if (!grid) return;
  const list = () => [...grid.querySelectorAll(cells)];
  const all = list();
  if (!all.length) return;
  grid.setAttribute('role', 'grid');
  if (label) grid.setAttribute('aria-label', label);
  const first = (start && all.find(start)) || all[0];
  all.forEach(cell => {
    cell.setAttribute('role', 'gridcell');
    cell.tabIndex = cell === first ? 0 : -1;
  });
  grid._gridSteps = steps;
  if (grid.dataset.gridNav) return;   // one listener, even when cells re-render
  grid.dataset.gridNav = '1';
  grid.addEventListener('keydown', event => {
    // keys on a control inside a cell (an event chip) belong to that control
    if (!event.target.matches?.('[role="gridcell"]')) return;
    const items = list();
    const at = items.indexOf(event.target);
    if (at < 0) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const key = items[at].dataset.date || items[at].id;
      items[at].click();
      // activation may re-render the grid; keep focus on the same day
      setTimeout(() => {
        if (items[at].isConnected || !key) return;
        const again = document.querySelector(`${cells}[data-date="${key}"], ${cells}#${CSS.escape(key)}`);
        if (again) { again.tabIndex = 0; again.focus(); }
      });
      return;
    }
    const step = grid._gridSteps?.[event.key];
    if (!step) return;
    event.preventDefault();
    const next = items[at + step];
    if (!next) return;
    items[at].tabIndex = -1;
    next.tabIndex = 0;
    next.focus();
  });
}

export const WEEK_ROWS = Object.freeze({ ArrowRight: 1, ArrowLeft: -1, ArrowDown: 7, ArrowUp: -7 });
export const WEEK_COLUMNS = Object.freeze({ ArrowDown: 1, ArrowUp: -1, ArrowRight: 7, ArrowLeft: -7 });
