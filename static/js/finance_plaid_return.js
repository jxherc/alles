import { openPlaidLink, plaidReturnBinding, cancelPlaidReturn } from './finance_plaid.js';
import { applyAppearance } from './theme.js';

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
  status.textContent = 'resuming Plaid Link…';
  status.dataset.error = 'false';
  try {
    const binding = plaidReturnBinding();
    const result = await openPlaidLink({ id: binding.connection_id }, {
      binding, receivedRedirectUri: location.href, signal: controller.signal,
    });
    status.textContent = result.cancelled
      ? 'Plaid Link closed. your saved connection is available in Finance.'
      : 'Plaid connected. return to Finance and sync when you are ready.';
  } catch (error) {
    status.textContent = error.message;
    status.dataset.error = 'true';
    try { plaidReturnBinding(); retry.hidden = false; } catch {}
  }
}

retry.addEventListener('click', resume);
resume();
