// one sign in component for every connection that can sign in with a provider.
// the api it speaks is /api/signin, pinned by tests/test_signin_contract.py:
//   GET  /providers                      {providers: [{id, name, flow, ready, not_ready, uses}]}
//   POST /start {provider, use, login_hint}   device: {attempt, user_code, verify_url, expires_at, poll_every}
//                                             redirect, paste_code: {attempt, url}
//   GET  /attempts/{id}                  {state: waiting|done|expired|denied|cancelled|error, error, account}
//   POST /attempts/{id}/cancel, POST /attempts/{id}/code {code}
//   GET  /accounts, POST /accounts/{id}/check, DELETE /accounts/{id}
// screens place it with mountSignin(host, {use, provider, fallback}) and don't draw anything of
// their own around it: the button first, the accounts signed in, and the quiet fallback with its
// one line reason ("use an app password instead", only where the provider has no sign in).
import { requestWithRecentOwner } from './recent_owner.js';
import { formatDate, serverText, t } from './i18n.js';
import { icon } from './icons.js';

const API = '/api/signin';
const TERMINAL = new Set(['done', 'expired', 'denied', 'cancelled', 'error']);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function timeLeft(ms) {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

// `?signin=<attempt>` is where a redirect sign in lands (the server sends the browser back to
// "/?signin=<id>"); the screen that mounts the component hands this to `resume`
export function signinReturn(href = globalThis.location?.href || '') {
  try {
    const id = new URL(href).searchParams.get('signin');
    return id && /^[A-Za-z0-9_-]{1,64}$/.test(id) ? id : '';
  } catch { return ''; }
}

export function mountSignin(host, options = {}) {
  const {
    use = '',
    provider: only = '',
    loginHint = '',
    fallback = null,            // {label, reason, onClick}: only where the provider has no sign in
    onDone = () => {},
    doneClearMs = 6000,
    pollMinMs = 2000,
    now = () => Date.now(),
    openUrl = url => globalThis.open?.(url, '_blank', 'noopener'),
  } = options;
  const doFetch = options.fetch || ((...args) => globalThis.fetch(...args));
  const state = { providers: [], accounts: [], slots: new Map(), loading: true, failed: '', notice: null };
  let destroyed = false;
  host.classList.add('signin');

  const json = async (path, init = {}, strict = false) => {
    const headers = init.body ? { 'content-type': 'application/json' } : undefined;
    const send = strict ? (p, i) => requestWithRecentOwner(doFetch, p, i) : doFetch;
    const response = await send(`${API}${path}`, { ...init, ...(headers ? { headers } : {}) });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(serverText(body?.detail?.message || body?.detail || '') || t('signin.error'));
      error.code = body?.code || '';
      error.status = response.status;
      throw error;
    }
    return body;
  };

  const providerList = () => state.providers.filter(p => (!only || p.id === only) && (!use || p.uses.some(u => u.id === use)));
  const accountsFor = p => state.accounts.filter(a => a.provider === p.id && (!use || a.use === use));
  const slot = p => {
    if (!state.slots.has(p.id)) state.slots.set(p.id, { phase: 'idle' });
    return state.slots.get(p.id);
  };
  const useOf = p => use || p.uses[0]?.id || '';

  // ---- loading ----
  async function load() {
    try {
      const [providers, accounts] = await Promise.all([json('/providers'), json('/accounts')]);
      Object.assign(state, { providers: providers.providers || [], accounts: accounts.accounts || [], failed: '' });
    } catch (error) { state.failed = error.message; }
    state.loading = false;
    render();
  }

  async function reloadAccounts() {
    try { state.accounts = (await json('/accounts')).accounts || []; } catch { /* the list stays as it was */ }
    render();
  }

  // ---- one attempt ----
  function stop(s) {
    clearTimeout(s.poll);
    clearInterval(s.tick);
    s.poll = s.tick = null;
  }

  function finish(p, s, attempt) {
    stop(s);
    if (attempt.state === 'done') {
      s.phase = 'done';
      s.account = attempt.account;
      state.accounts = [attempt.account, ...state.accounts.filter(a => a.id !== attempt.account?.id)].filter(Boolean);
      clearTimeout(s.clear);
      if (doneClearMs) s.clear = setTimeout(() => { if (s.phase === 'done') { s.phase = 'idle'; render(); } }, doneClearMs);
      onDone(attempt.account, p);
    } else if (attempt.state === 'cancelled') {
      s.phase = 'idle';
    } else {
      s.phase = attempt.state; // expired, denied, error
      s.error = attempt.error?.text ? serverText(attempt.error.text) : '';
    }
    render(true);
  }

  function schedulePoll(p, s) {
    clearTimeout(s.poll);
    s.poll = setTimeout(async () => {
      if (destroyed || !s.attempt) return;
      try {
        const attempt = await json(`/attempts/${encodeURIComponent(s.attempt)}`);
        if (destroyed || s.stale) return;
        if (TERMINAL.has(attempt.state)) return finish(p, s, attempt);
      } catch (error) {
        if (error.status === 404) { stop(s); s.phase = 'lost'; return render(true); }
      }
      schedulePoll(p, s);
    }, s.pollMs || pollMinMs);
  }

  function startTick(s) {
    clearInterval(s.tick);
    s.tick = setInterval(() => {
      const el = host.querySelector(`[data-left="${CSS.escape(s.id)}"]`);
      if (el) el.textContent = t('signin.left', { time: timeLeft(Date.parse(s.expires) - now()) });
    }, 1000);
  }

  async function begin(p, hint = loginHint) {
    const s = slot(p);
    stop(s);
    clearTimeout(s.clear);
    s.stale = false;
    s.phase = 'starting';
    s.id = p.id;
    s.error = '';
    render();
    // a window opened in the click itself isn't taken for a popup; it gets its address once known
    const popup = p.flow === 'redirect' ? globalThis.open?.('about:blank', '_blank') : null;
    try {
      const started = await json('/start', { method: 'POST', body: JSON.stringify({ provider: p.id, use: useOf(p), ...(hint ? { login_hint: hint } : {}) }) }, true);
      s.attempt = started.attempt;
      s.flow = started.flow;
      s.pollMs = Math.max(pollMinMs, (started.poll_every || 0) * 1000);
      if (started.flow === 'device') {
        Object.assign(s, { phase: 'device', code: started.user_code, url: started.verify_url_complete || started.verify_url, expires: started.expires_at });
        startTick(s);
      } else {
        s.url = started.url;
        s.phase = started.flow === 'paste_code' ? 'paste' : 'redirect';
        if (started.flow === 'redirect') {
          if (popup) { try { popup.location.href = started.url; } catch { popup.close(); } } else openUrl(started.url);
        }
      }
      schedulePoll(p, s);
    } catch (error) {
      popup?.close();
      s.phase = error.code === 'not_ready' ? 'not_ready' : 'error';
      s.error = error.message;
      if (error.code === 'not_ready') p.ready = false, p.not_ready = { code: 'not_ready', text: error.message };
    }
    render(true);
  }

  async function cancel(p) {
    const s = slot(p);
    const attempt = s.attempt;
    s.stale = true;
    stop(s);
    s.phase = 'idle';
    render(true);
    if (attempt) await json(`/attempts/${encodeURIComponent(attempt)}/cancel`, { method: 'POST' }).catch(() => {});
  }

  async function sendCode(p, code) {
    const s = slot(p);
    if (!code.trim()) return;
    s.busy = true;
    s.error = '';
    render();
    try {
      const attempt = await json(`/attempts/${encodeURIComponent(s.attempt)}/code`, { method: 'POST', body: JSON.stringify({ code: code.trim() }) }, true);
      s.busy = false;
      if (attempt.state === 'done') {
        const full = await json(`/attempts/${encodeURIComponent(s.attempt)}`).catch(() => attempt);
        return finish(p, s, full.account ? full : attempt);
      }
      if (TERMINAL.has(attempt.state)) return finish(p, s, attempt);
    } catch (error) { s.error = error.message; }
    s.busy = false;
    render(true);
  }

  async function checkAccount(account) {
    state.notice = null;
    account.busy = 'check';
    render();
    try {
      const fresh = await json(`/accounts/${encodeURIComponent(account.id)}/check`, { method: 'POST' });
      state.accounts = state.accounts.map(a => (a.id === fresh.id ? fresh : a));
    } catch (error) { account.busy = ''; account.failed = error.message; }
    render(true);
  }

  async function signOut(account) {
    state.notice = null;
    account.busy = 'out';
    render();
    try {
      const result = await json(`/accounts/${encodeURIComponent(account.id)}`, { method: 'DELETE' }, true);
      state.accounts = state.accounts.filter(a => a.id !== account.id);
      const p = state.providers.find(x => x.id === account.provider);
      state.notice = result.revoked === false ? t('signin.signed_out_here', { provider: p?.name || account.provider }) : t('signin.signed_out');
      state.noticeFocus = true;
    } catch (error) { account.busy = ''; account.failed = error.message; }
    render(true);
  }

  // ---- drawing ----
  function accountRow(a, p) {
    const name = a.login || a.email || p.name;
    const use_ = p.uses.find(u => u.id === a.use)?.name || '';
    const meta = [use_, a.email && a.email !== name ? a.email : ''].filter(Boolean).join(' · ');
    const bad = a.state !== 'ok';
    const busy = a.busy;
    const status = a.state === 'needs_sign_in' ? t('signin.needs_sign_in') : a.state === 'error' ? (a.error?.text ? serverText(a.error.text) : t('signin.error')) : '';
    return `<li class="signin-account" data-account="${esc(a.id)}" data-state="${esc(a.state)}">
      <span class="signin-mark" aria-hidden="true">${icon(bad ? 'x-circle' : 'check-circle')}</span>
      <span class="signin-who"><strong>${esc(name)}</strong><span>${esc(bad ? status : meta)}${a.failed ? ` <em>${esc(a.failed)}</em>` : ''}</span></span>
      <span class="signin-acts">
        ${a.state === 'needs_sign_in' ? `<button class="signin-act primary" type="button" data-act="again" data-id="${esc(a.id)}"${slot(p).phase === 'starting' ? ' disabled' : ''}>${esc(t('signin.again'))}</button>` : ''}
        <button class="signin-act" type="button" data-act="check" data-id="${esc(a.id)}"${busy ? ' disabled' : ''}>${esc(busy === 'check' ? t('signin.checking') : t('signin.check'))}</button>
        <button class="signin-act" type="button" data-act="out" data-id="${esc(a.id)}"${busy ? ' disabled' : ''}>${esc(busy === 'out' ? t('signin.signing_out') : t('signin.sign_out'))}</button>
      </span>
      <span class="signin-sr">${esc(t('signin.signed_in_label', { date: a.signed_in_at ? formatDate(a.signed_in_at) : '' }))}</span>
    </li>`;
  }

  function panel(p, s) {
    const name = esc(p.name);
    const again = `<button class="btn" type="button" data-act="start" data-provider="${esc(p.id)}">${esc(t('signin.try_again'))}</button>`;
    const line = (text, tone = '') => `<p class="signin-line" data-tone="${tone}" role="${tone === 'bad' ? 'alert' : 'status'}">${esc(text)}</p>`;
    switch (s.phase) {
      case 'starting':
        return `<p class="signin-line" role="status">${esc(t('signin.starting'))}</p>`;
      case 'device':
        return `<div class="signin-device" role="group" aria-label="${esc(t('signin.code_label'))}">
          <div class="signin-code" data-code translate="no"><span class="signin-sr">${esc(t('signin.code_label'))}: </span>${esc(s.code)}</div>
          <div class="signin-row">
            <button class="btn" type="button" data-act="copy" data-provider="${esc(p.id)}">${esc(s.copied ? t('signin.copied') : t('signin.copy'))}</button>
            <a class="btn primary" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(t('signin.open_page', { provider: p.name }))}</a>
            <button class="signin-act" type="button" data-act="cancel" data-provider="${esc(p.id)}">${esc(t('signin.cancel'))}</button>
          </div>
          <div class="signin-wait"><span class="signin-spin" aria-hidden="true"></span><span role="status">${esc(t('signin.waiting'))}</span> <span class="signin-left" data-left="${esc(s.id)}">${esc(t('signin.left', { time: timeLeft(Date.parse(s.expires) - now()) }))}</span></div>
        </div>`;
      case 'redirect':
        return `<div class="signin-device">
          <div class="signin-wait"><span class="signin-spin" aria-hidden="true"></span><span role="status">${esc(t('signin.finish_on', { provider: p.name }))}</span></div>
          <div class="signin-row">
            <a class="btn primary" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(t('signin.open_page', { provider: p.name }))}</a>
            <button class="signin-act" type="button" data-act="cancel" data-provider="${esc(p.id)}">${esc(t('signin.cancel'))}</button>
          </div>
        </div>`;
      case 'paste':
        return `<form class="signin-device" data-paste="${esc(p.id)}">
          <div class="signin-row">
            <a class="btn primary" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(t('signin.open_page', { provider: p.name }))}</a>
            <button class="signin-act" type="button" data-act="cancel" data-provider="${esc(p.id)}">${esc(t('signin.cancel'))}</button>
          </div>
          <label class="signin-label" for="signin-code-${esc(p.id)}">${esc(t('signin.paste_label', { provider: p.name }))}</label>
          <div class="signin-row">
            <input class="settings-input signin-input" id="signin-code-${esc(p.id)}" autocomplete="off" spellcheck="false" autocapitalize="off" data-focus${s.error ? ` aria-invalid="true" aria-describedby="signin-err-${esc(p.id)}"` : ''}>
            <button class="btn primary" type="submit"${s.busy ? ' disabled' : ''}>${esc(s.busy ? t('signin.finishing') : t('signin.finish'))}</button>
          </div>
          ${s.error ? `<p class="signin-line" id="signin-err-${esc(p.id)}" data-tone="bad" role="alert">${esc(s.error)}</p>` : ''}
        </form>`;
      case 'done':
        return `<p class="signin-line signin-done" data-tone="good" role="status"><span aria-hidden="true">${icon('check')}</span>${esc(t('signin.done', { name: s.account?.login || s.account?.email || p.name }))}
          <button class="signin-act" type="button" data-act="dismiss" data-provider="${esc(p.id)}" aria-label="${esc(t('signin.dismiss'))}">${icon('close')}</button></p>`;
      case 'expired':
        return `${line(t('signin.expired'), 'bad')}${again}`;
      case 'denied':
        return `${line(t('signin.denied', { provider: p.name }) + (s.error ? `: ${s.error}` : ''), 'bad')}${again}`;
      case 'lost':
        return `${line(t('signin.lost'), 'bad')}${again}`;
      case 'error':
        return `${line(s.error || t('signin.error'), 'bad')}${again}`;
      default:
        return '';
    }
  }

  function providerBlock(p) {
    const s = slot(p);
    const accounts = accountsFor(p);
    const multi = accounts.length > 0;
    const busy = ['starting', 'device', 'redirect', 'paste'].includes(s.phase);
    const idle = !busy && s.phase === 'idle';
    // one github or one model login at a time; mail and calendar can hold several accounts
    const single = use === 'github' || use === 'models';
    const showButton = (idle || s.phase === 'done') && !(multi && single);
    const label = multi ? t('signin.another', { provider: p.name }) : t('signin.with', { provider: p.name });
    const reasonId = `signin-why-${esc(p.id)}`;
    const notReady = !p.ready;
    return `<section class="signin-provider" data-provider="${esc(p.id)}" data-phase="${esc(s.phase)}" aria-label="${esc(p.name)}">
      ${accounts.length ? `<ul class="signin-accounts" aria-label="${esc(t('signin.accounts_label', { provider: p.name }))}">${accounts.map(a => accountRow(a, p)).join('')}</ul>` : ''}
      ${busy || ['done', 'expired', 'denied', 'lost', 'error'].includes(s.phase) ? `<div class="signin-panel">${panel(p, s)}</div>` : ''}
      ${showButton ? `<div class="signin-start">
        <button class="btn primary signin-button" type="button" data-act="start" data-provider="${esc(p.id)}"${notReady ? ` disabled aria-describedby="${reasonId}"` : ''}>${esc(label)}</button>
        ${notReady ? `<p class="signin-line" id="${reasonId}" data-tone="quiet">${esc(serverText(p.not_ready?.text || ''))}</p>` : ''}
      </div>` : ''}
      ${fallback && (idle || s.phase === 'done') ? `<button class="signin-act signin-fallback" type="button" data-act="fallback">
        <span>${esc(fallback.label)}</span><span class="signin-reason">${esc(fallback.reason)}</span>
      </button>` : ''}
    </section>`;
  }

  function render(focus = false) {
    if (destroyed) return;
    const had = host.contains(document.activeElement) ? document.activeElement : null;
    const keep = had ? { act: had.dataset?.act, id: had.dataset?.id || had.dataset?.provider, field: had.id } : null;
    if (state.loading) { host.innerHTML = `<p class="signin-line" role="status">${esc(t('signin.loading'))}</p>`; return; }
    const list = providerList();
    host.innerHTML = state.failed
      ? `<p class="signin-line" data-tone="bad" role="alert">${esc(state.failed)}</p><button class="btn" type="button" data-act="reload">${esc(t('signin.try_again'))}</button>`
      : `${list.map(providerBlock).join('')}${state.notice ? `<p class="signin-line" role="status" data-notice tabindex="-1">${esc(state.notice)}</p>` : ''}`;
    const field = host.querySelector('[data-paste] input');
    if (field && slotPaste.value) field.value = slotPaste.value;
    if (focus || keep) {
      const target = host.querySelector('[data-focus]')
        || (state.noticeFocus && host.querySelector('[data-notice]'))
        || (keep && (keep.field && host.querySelector(`#${CSS.escape(keep.field)}`)
          || host.querySelector(`[data-act="${keep.act}"][data-id="${keep.id}"]`)
          || host.querySelector(`[data-act="${keep.act}"][data-provider="${keep.id}"]`)
          || host.querySelector(`[data-act="${keep.act}"]`)))
        || host.querySelector('[data-act="start"]:not([disabled])');
      state.noticeFocus = false;
      // focus follows the work: a finished or failed step, or the field a paste step needs
      if (focus && target?.focus) target.focus({ preventScroll: true });
      else if (keep && target?.focus) target.focus({ preventScroll: true });
    }
  }

  // the text typed in a paste field survives a redraw
  const slotPaste = { value: '' };
  host.addEventListener('input', event => { if (event.target.matches?.('.signin-input')) slotPaste.value = event.target.value; });

  host.addEventListener('submit', event => {
    const form = event.target.closest?.('[data-paste]');
    if (!form) return;
    event.preventDefault();
    const p = state.providers.find(x => x.id === form.dataset.paste);
    const value = form.querySelector('input').value;
    slotPaste.value = '';
    if (p) sendCode(p, value);
  });

  host.addEventListener('click', async event => {
    const button = event.target.closest?.('[data-act]');
    if (!button || button.disabled) return;
    const p = state.providers.find(x => x.id === (button.dataset.provider || state.accounts.find(a => a.id === button.dataset.id)?.provider));
    const account = state.accounts.find(a => a.id === button.dataset.id);
    switch (button.dataset.act) {
      case 'start': return p && begin(p);
      case 'again': return p && begin(p, account?.login || account?.email || loginHint);
      case 'cancel': return p && cancel(p);
      case 'copy':
        if (!p) return;
        try { await globalThis.navigator.clipboard.writeText(slot(p).code); slot(p).copied = true; }
        catch { slot(p).copied = false; }
        render(true);
        return setTimeout(() => { slot(p).copied = false; if (slot(p).phase === 'device') render(); }, 2000);
      case 'dismiss': if (p) { slot(p).phase = 'idle'; render(true); } return;
      case 'check': return account && checkAccount(account);
      case 'out': return account && signOut(account);
      case 'fallback': return fallback?.onClick?.();
      case 'reload': state.loading = true; render(); return load();
      default:
    }
  });

  load();

  return {
    // pick up an attempt the browser came back from (a redirect sign in)
    async resume(attemptId) {
      if (!attemptId) return;
      try {
        const attempt = await json(`/attempts/${encodeURIComponent(attemptId)}`);
        const p = state.providers.find(x => x.id === attempt.provider) || (await load(), state.providers.find(x => x.id === attempt.provider));
        if (!p) return;
        const s = slot(p);
        s.id = p.id; s.attempt = attemptId;
        if (TERMINAL.has(attempt.state)) finish(p, s, attempt);
        else { s.phase = 'redirect'; schedulePoll(p, s); render(); }
      } catch { /* an old link: nothing to resume */ }
    },
    refresh: reloadAccounts,
    destroy() {
      destroyed = true;
      for (const s of state.slots.values()) { stop(s); clearTimeout(s.clear); }
      host.innerHTML = '';
      host.classList.remove('signin');
    },
  };
}
