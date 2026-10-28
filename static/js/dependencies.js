// "what Aide can use": node, pi, Aide's browser and SearXNG with their real state and one-click
// installs. settings and the setup wizard both mount it.
import { t } from './i18n.js';
import { requestWithRecentOwner } from './recent_owner.js';
import { toast, plainError } from './util.js';

const POLL_MS = 2000;
// these states have nothing to install: the owner fixes something else, then checks again
const CHECK_AGAIN = new Set(['needs_node', 'needs_docker', 'docker_off']);
const esc = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function statusLine(row) {
  const name = t(`dependencies.name_${row.id}`);
  switch (row.state) {
    case 'ready': return row.version ? t('dependencies.ready_version', { version: row.version }) : t('dependencies.ready');
    case 'installing': return t('dependencies.installing');
    case 'outdated': return t('dependencies.outdated', { version: row.version });
    case 'needs_node': return t('dependencies.needs_node');
    case 'needs_docker': return t('dependencies.needs_docker');
    case 'docker_off': return t('dependencies.docker_off');
    case 'stopped': return t('dependencies.stopped');
    case 'failed': return t('dependencies.failed', { name, error: row.error || t('aide.code_unknown_error') });
    default: return t('dependencies.missing');
  }
}

function buttonLabel(row) {
  if (CHECK_AGAIN.has(row.state)) return t('dependencies.check_again');
  if (row.state === 'failed') return t('dependencies.try_again');
  if (row.state === 'stopped') return t('dependencies.start');
  return t('dependencies.install');
}

export function mountDependencies(host) {
  host.classList.add('dep-list');
  host.setAttribute('aria-live', 'polite');
  let timer = 0;
  let stopped = false;

  const rowFor = id => host.querySelector(`[data-dep="${id}"]`);

  function paint(rows) {
    host.querySelector('.settings-row-empty')?.remove();
    for (const row of rows) {
      let node = rowFor(row.id);
      if (!node) {
        node = document.createElement('div');
        node.className = 'dep-row';
        node.dataset.dep = row.id;
        node.innerHTML = `<div class="dep-copy"><span class="dep-name"></span><span class="dep-meta"></span></div><button class="btn" type="button"></button>`;
        host.append(node);
      }
      node.dataset.state = row.state;
      node.querySelector('.dep-name').textContent = t(`dependencies.name_${row.id}`);
      const meta = node.querySelector('.dep-meta');
      meta.textContent = statusLine(row);
      meta.dataset.state = row.state;
      if (row.link) {
        const link = document.createElement('a');
        link.href = row.link;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = t('dependencies.get_docker');
        meta.append(' ', link);
      }
      const button = node.querySelector('button');
      const hidden = row.state === 'ready' || (row.state !== 'installing' && !row.can_install && !CHECK_AGAIN.has(row.state));
      button.hidden = hidden;
      // aria-disabled, not disabled: a disabled button drops keyboard focus
      button.setAttribute('aria-disabled', String(row.state === 'installing'));
      button.setAttribute('aria-busy', String(row.state === 'installing'));
      // while it installs the button keeps its label, so nothing around it moves
      if (row.state !== 'installing' || !button.textContent) {
        button.textContent = buttonLabel(row);
        button.setAttribute('aria-label', `${buttonLabel(row)} ${t(`dependencies.name_${row.id}`)}`);
      }
      button.onclick = () => { if (button.getAttribute('aria-disabled') !== 'true') void act(row); };
    }
    clearTimeout(timer);
    // polls only while something installs, and only while the panel is still on screen
    if (rows.some(row => row.state === 'installing') && !stopped) timer = setTimeout(() => void reload(), POLL_MS);
  }

  async function reload() {
    if (stopped || !host.isConnected) return;
    try {
      const response = await fetch('/api/system/dependencies');
      if (!response.ok) throw new Error();
      paint(await response.json());
    } catch {
      if (!host.querySelector('.dep-row')) {
        host.innerHTML = `<div class="settings-row-empty">${esc(t('dependencies.load_failed'))}</div>`;
      }
    }
  }

  async function act(row) {
    if (CHECK_AGAIN.has(row.state)) { await reload(); return; }
    const button = rowFor(row.id)?.querySelector('button');
    button?.setAttribute('aria-disabled', 'true');
    try {
      const response = await requestWithRecentOwner(fetch, `/api/system/dependencies/${row.id}/install`, { method: 'POST' });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.message || body.detail || t('common.request_failed'));
      await reload();
    } catch (error) {
      toast(plainError(error.message), 'error');
      await reload();
    }
  }

  return {
    reload() { stopped = false; return reload(); },
    stop() { stopped = true; clearTimeout(timer); },
  };
}
