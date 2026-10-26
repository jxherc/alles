import { plainError } from './util.js';
import { openPlaidLink, plaidReturnBinding, cancelPlaidReturn } from './finance_plaid.js';
import { applyAppearance } from './theme.js';
import { cachedLocalizationSettings, prepareLocalization, t } from './i18n.js';

applyAppearance();

const status = document.getElementById('plaid-return-status');
const retry = document.getElementById('plaid-return-retry');
const controller = new AbortController();
document.getElementById('plaid-return-finance').addEventListener('click', () => {
  controller.abort();
  cancelPlaidReturn();
});

async function resume() {
  retry.hidden = true;
  status.textContent = t('finance.plaid_resuming');
  status.dataset.error = 'false';
  try {
    const binding = plaidReturnBinding();
    const result = await openPlaidLink({ id: binding.connection_id }, {
      binding, receivedRedirectUri: location.href, signal: controller.signal,
    });
    status.textContent = result.cancelled
      ? t('finance.plaid_closed_saved')
      : t('finance.plaid_connected');
  } catch (error) {
    status.textContent = plainError(error.message);
    status.dataset.error = 'true';
    try { plaidReturnBinding(); retry.hidden = false; } catch {}
  }
}

retry.addEventListener('click', resume);
prepareLocalization(cachedLocalizationSettings()).catch(() => {}).then(() => {
  document.getElementById('plaid-return-title').textContent = t('finance.plaid_connection');
  retry.textContent = t('finance.try_again');
  document.getElementById('plaid-return-finance').textContent = t('finance.return_to_finance');
  resume();
});
