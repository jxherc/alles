// the alles address searches go to. saving it sets the redirect rules; turning off clears them
const $ = id => document.getElementById(id);
const say = (key, error = false) => {
  $('status').textContent = key ? browser.i18n.getMessage(key) : '';
  $('status').className = error ? 'error' : 'quiet';
};

for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = browser.i18n.getMessage(el.dataset.i18n);

// only the origin: https, or plain http on a private address (a tailnet or home network)
function cleanOrigin(raw) {
  let url;
  try { url = new URL(raw.includes('://') ? raw : `https://${raw}`); } catch { return ''; }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return '';
  if (url.username || url.password || !url.hostname.includes('.')) return '';
  return url.origin;
}

async function setRules(origin) {
  const ids = ENGINES.map((_, index) => index + 1);
  const rules = origin ? engineRules(origin) : [];
  try {
    await browser.declarativeNetRequest.updateDynamicRules({ removeRuleIds: ids, addRules: rules });
    return true;
  } catch {
    // the page script still redirects; only the head start before the engine is lost
    await browser.declarativeNetRequest.updateDynamicRules({ removeRuleIds: ids }).catch(() => {});
    return false;
  }
}

const SEARCH_PAGES = () => browser.runtime.getManifest().host_permissions;

// safari asks before an extension may see a site: without it nothing here can catch a search
async function showAccess() {
  let granted = false;
  try { granted = await browser.permissions.contains({ origins: SEARCH_PAGES() }); } catch {}
  $('access').hidden = granted;
}

async function show() {
  const { origin, caught, rulesFailed } = await browser.storage.local.get(['origin', 'caught', 'rulesFailed']);
  $('origin').value = origin || '';
  $('off').hidden = !origin;
  say(origin ? (rulesFailed ? 'on_late' : 'on') : 'off_now');
  $('caught').textContent = caught?.host && origin
    ? browser.i18n.getMessage('caught', [caught.host, new Date(caught.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })])
    : '';
  await showAccess();
}

$('allow').addEventListener('click', async () => {
  try { await browser.permissions.request({ origins: SEARCH_PAGES() }); } catch {}
  await showAccess();
});

$('form').addEventListener('submit', async event => {
  event.preventDefault();
  const origin = cleanOrigin($('origin').value.trim());
  if (!origin) { say('invalid', true); $('origin').focus(); return; }
  await browser.storage.local.set({ origin });
  const early = await setRules(origin);
  await browser.storage.local.set({ rulesFailed: !early });
  $('origin').value = origin;
  $('off').hidden = false;
  say(early ? 'on' : 'on_late');
  await showAccess();
});

$('off').addEventListener('click', async () => {
  await browser.storage.local.remove('origin');
  await setRules('');
  await show();
});

show();
