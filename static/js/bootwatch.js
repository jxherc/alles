// the page starts hidden (body.preboot) and app.js shows it. when app.js never gets there (a
// module failed to load, a request hung), this says so with a retry instead of a blank screen.
// a classic script on purpose: it has to work when the module graph doesn't
(() => {
  const LIMIT_MS = 12000;
  setTimeout(() => {
    if (!document.body.classList.contains('preboot')) return;
    document.body.classList.remove('preboot');
    document.body.classList.add('login-mode');
    const screen = document.getElementById('notrunning-screen');
    if (screen) screen.style.display = 'flex';
    const retry = document.getElementById('notrunning-retry');
    if (retry && !retry.dataset.wired) {
      retry.dataset.wired = '1';
      retry.addEventListener('click', () => location.reload());
    }
  }, LIMIT_MS);
})();
