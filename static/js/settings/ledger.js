// the money ledger's setup (where money is saved, Actual's service, its checks) lives in settings
// (u.05: no setup on a working page). the finance overview links here with
// openSettingsAt('s-ledger'), or /?view=settings#s-ledger
import { t } from '../i18n.js';

export async function loadLedger(isCurrent = () => true) {
  const host = document.getElementById('s-ledger-body');
  if (!host) return;
  host.setAttribute('aria-busy', 'true');
  const [{ renderLedgerSetup }, value] = await Promise.all([
    import('../specialist_groups.js?v=17'),
    fetch('/api/finance/actual').then(r => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  if (!isCurrent() || !host.isConnected) return;
  host.removeAttribute('aria-busy');
  if (!value) {
    host.replaceChildren(Object.assign(document.createElement('p'), { className: 's-card-hint', textContent: t('finance.actual_status_unavailable', { error: t('finance.err_actual') }) }));
    return;
  }
  const panel = renderLedgerSetup(value, fetch);
  // here the setup is the page: always open, and the card's own title names it
  panel.querySelector('.finance-actual-toggle')?.remove();
  panel.querySelector('.finance-actual-head h2')?.remove();
  const content = panel.querySelector('#finance-actual-content');
  if (content) { content.hidden = false; content.id = 's-ledger-content'; }
  host.replaceChildren(panel);
}
