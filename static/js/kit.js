// the kit page (static/kit.html): every universal piece on one page, wired by the real modules.
// the theme comes from ?theme=light|dark so a check can screenshot both without the app
import { initKokuenPrimitives } from './kokuen.js?v=5';
import './motion.js';
import { initDatePickers } from './datepick.js';

const root = document.documentElement;
root.dataset.theme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark';
const theme = document.getElementById('kit-theme');
theme.querySelector(`[data-theme-pick="${root.dataset.theme}"]`).setAttribute('aria-checked', 'true');
initKokuenPrimitives(document);
initDatePickers(document);
theme.addEventListener('click', event => {
  const pick = event.target.closest('[data-theme-pick]');
  if (!pick) return;
  root.dataset.theme = pick.dataset.themePick;
  const url = new URL(location.href);
  url.searchParams.set('theme', pick.dataset.themePick);
  history.replaceState(null, '', url);
});
