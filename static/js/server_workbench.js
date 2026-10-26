// Server owns safe service control, search/model policy, backup status, release
// information, logs, and the explicit host-control policy. Every mutation uses
// an existing typed API; this UI never accepts shell commands or arbitrary paths.

import { plainError } from './util.js';
import { formatNumber, t, tp } from './i18n.js';
import { confirm as confirmDialog } from './dialog.js';
import { requestWithRecentOwner } from './recent_owner.js';
import { announceModelRoles, onModelRoles } from './settings/model_roles.js';

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== '') node.textContent = text;
  return node;
}

function errorMessage(payload, fallback) {
  for (const value of [payload?.error?.message, payload?.detail?.message, payload?.detail, payload?.message]) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  if (Array.isArray(payload?.detail)) {
    const messages = payload.detail.map(item => item?.msg).filter(value => typeof value === 'string' && value.trim());
    if (messages.length) return messages.join('; ');
  }
  return fallback;
}

async function json(request, url, options) {
  const method = String(options?.method || 'GET').toUpperCase();
  const response = method === 'GET' || method === 'HEAD'
    ? await request(url, options)
    : await requestWithRecentOwner(request, url, options);
  let payload = null;
  try { payload = await response.json(); } catch { /* keep the bounded fallback */ }
  if (!response.ok) throw new Error(errorMessage(payload, t('server.wb_request_failed', { status: response.status })));
  return payload;
}

function card(title, copy = '') {
  const section = el('section', 'server-workbench-card');
  section.append(el('h2', '', title));
  if (copy) section.append(el('p', 'server-workbench-copy', copy));
  return section;
}

function statusLine(message = '', tone = '') {
  const node = el('p', `server-workbench-status${tone ? ` is-${tone}` : ''}`, message);
  node.setAttribute('role', 'status');
  node.setAttribute('aria-live', 'polite');
  return node;
}

function fact(label, value) {
  const row = el('div', 'server-workbench-fact');
  row.append(el('span', '', label), el('strong', '', String(value ?? t('common.unavailable'))));
  return row;
}

function action(label, run, className = '') {
  const button = el('button', className, label);
  button.type = 'button';
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    const restoreFocus = document.activeElement === button;
    const surface = button.closest('.server-workbench-content');
    const owner = button.closest('.server-workbench-card');
    const title = owner?.querySelector('h2')?.textContent;
    const index = owner ? [...owner.querySelectorAll('button')].indexOf(button) : -1;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try { await run(button); }
    catch (error) {
      const parent = button.closest('.server-workbench-card');
      let region = parent?.querySelector('.server-workbench-status');
      if (!region && parent) { region = statusLine(); parent.append(region); }
      if (region) { region.textContent = plainError(error.message || t('server.wb_action_failed')); region.classList.add('is-error'); }
    } finally {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      if (restoreFocus && surface?.isConnected && document.activeElement === document.body) {
        const current = [...surface.querySelectorAll('.server-workbench-card')]
          .find(card => card.querySelector('h2')?.textContent === title);
        const replacement = button.isConnected ? button : current?.querySelectorAll('button')[index];
        if (replacement && !replacement.disabled) replacement.focus({ preventScroll: true });
        else if (current) {
          const heading = current.querySelector('h2');
          heading.tabIndex = -1;
          heading.focus({ preventScroll: true });
        }
      }
    }
  });
  return button;
}

function destructiveAction(label, consequence, run) {
  return action(label, async button => {
    if (!await confirmDialog(consequence)) return;
    await run(button);
  }, 'is-destructive');
}

const VERBS = ['install', 'start', 'stop', 'restart', 'update', 'rollback', 'backup', 'test'];
const verbLabel = verb => (VERBS.includes(verb) ? t(`server.verb_${verb}`) : verb);

function serviceAction(subject, verb, run) {
  if (!['stop', 'restart', 'update', 'rollback'].includes(verb)) return action(verbLabel(verb), run);
  const consequence = verb === 'stop'
    ? t('server.wb_confirm_stop', { subject })
    : verb === 'restart'
      ? t('server.wb_confirm_restart', { subject })
      : verb === 'update'
        ? t('server.wb_confirm_update', { subject })
        : t('server.wb_confirm_rollback', { subject });
  return destructiveAction(verbLabel(verb), consequence, run);
}

function choice(label, options, selected, onChange) {
  const field = el('fieldset', 'server-workbench-choice');
  field.append(el('legend', '', label));
  const list = el('div', 'server-workbench-choice-list');
  list.setAttribute('role', 'radiogroup');
  list.setAttribute('aria-label', label);
  let choiceBusy = false;
  const select = selectedButton => {
    buttons.forEach(item => {
      const chosen = item === selectedButton;
      item.setAttribute('aria-checked', chosen ? 'true' : 'false');
      item.tabIndex = chosen ? 0 : -1;
    });
  };
  const reportFailure = error => {
    const owner = field.closest('.server-workbench-card');
    let region = owner?.querySelector('.server-workbench-status');
    if (!region && owner) { region = statusLine(); owner.append(region); }
    if (region) { region.textContent = plainError(error.message || t('server.wb_setting_failed')); region.classList.add('is-error'); }
  };
  const buttons = options.map(option => {
    const button = el('button', '', option.label);
    button.type = 'button';
    button.dataset.value = option.value;
    button.setAttribute('role', 'radio');
    const active = option.value === selected;
    button.setAttribute('aria-checked', active ? 'true' : 'false');
    button.tabIndex = active ? 0 : -1;
    button.addEventListener('click', async () => {
      if (choiceBusy || button.getAttribute('aria-checked') === 'true') return;
      const previous = buttons.find(item => item.getAttribute('aria-checked') === 'true');
      let focusTarget = button;
      choiceBusy = true;
      list.setAttribute('aria-busy', 'true');
      buttons.forEach(item => { item.setAttribute('aria-disabled', 'true'); });
      select(button);
      try { await onChange(option.value); }
      catch (error) {
        select(previous || button);
        focusTarget = previous || button;
        reportFailure(error);
      } finally {
        choiceBusy = false;
        list.removeAttribute('aria-busy');
        buttons.forEach(item => { item.removeAttribute('aria-disabled'); });
        if (field.isConnected && list.contains(document.activeElement)) {
          focusTarget.focus({ preventScroll: true });
        }
      }
    });
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      if (choiceBusy) return;
      const current = buttons.indexOf(button);
      const backwards = event.key === 'ArrowLeft' || event.key === 'ArrowUp';
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
        : (current + (backwards ? -1 : 1) + buttons.length) % buttons.length;
      buttons[next].focus();
      buttons[next].click();
    });
    list.append(button);
    return button;
  });
  field.append(list);
  return field;
}

function switchButton(label, pressed, onChange) {
  const row = el('div', 'server-workbench-switch-row');
  const button = el('button', 'home-settings-switch');
  button.type = 'button';
  button.setAttribute('role', 'switch');
  button.setAttribute('aria-label', label);
  button.setAttribute('aria-checked', pressed ? 'true' : 'false');
  button.addEventListener('click', async () => {
    if (button.getAttribute('aria-disabled') === 'true') return;
    // Keep focus on this control while saving. A delayed response must not
    // reclaim focus from another control whose save is still pending.
    button.setAttribute('aria-disabled', 'true');
    button.setAttribute('aria-busy', 'true');
    const previous = button.getAttribute('aria-checked') === 'true';
    button.setAttribute('aria-checked', previous ? 'false' : 'true');
    try { await onChange(!previous); }
    catch (error) {
      button.setAttribute('aria-checked', previous ? 'true' : 'false');
      const owner = button.closest('.server-workbench-card');
      let region = owner?.querySelector('.server-workbench-status');
      if (!region && owner) { region = statusLine(); owner.append(region); }
      if (region) { region.textContent = plainError(error.message || t('server.wb_setting_failed')); region.classList.add('is-error'); }
    } finally {
      button.removeAttribute('aria-disabled');
      button.removeAttribute('aria-busy');
    }
  });
  row.append(el('span', '', label), button);
  return row;
}

function inputField(label, type, value = '') {
  const field = el('label', 'server-workbench-field');
  field.append(el('span', '', label));
  const input = el('input');
  input.type = type;
  input.value = value;
  input.autocomplete = type === 'password' ? 'new-password' : 'off';
  field.append(input);
  return { field, input };
}

function managedList(title, items, render) {
  const section = el('section', 'server-managed-section');
  section.append(el('h3', '', title));
  const list = el('div', 'server-managed-list');
  if (!items.length) list.append(el('p', 'server-workbench-empty', t('server.wb_none')));
  else items.forEach(item => list.append(render(item)));
  section.append(list);
  return section;
}

function adguardSurface(service, request, rerender) {
  const host = el('div', 'server-managed-surface');
  const state = statusLine(t('server.wb_adguard_loading'));
  host.append(state);
  void (async () => {
    try {
      const dashboard = await json(request, '/api/system/companions/adguard-home/dashboard');
      const stats = dashboard.stats || {};
      const filtering = dashboard.filtering || {};
      const summary = el('div', 'server-workbench-grid server-managed-summary');
      summary.append(
        fact(t('server.wb_queries_today'), formatNumber(Number(stats.num_dns_queries || 0))),
        fact(t('server.wb_blocked_today'), formatNumber(Number(stats.num_blocked_filtering || 0))),
        fact(t('server.wb_avg_response'), `${Math.round(Number(stats.avg_processing_time || 0) * 1000)} ms`),
      );
      const controls = el('div', 'server-managed-controls');
      const interval = inputField(t('server.wb_filter_hours'), 'number', String(filtering.interval ?? 24));
      interval.input.min = '0'; interval.input.max = '168';
      controls.append(
        interval.field,
        switchButton(t('server.wb_dns_filtering'), Boolean(filtering.enabled), async enabled => {
          const feedback = host.closest('.server-workbench-card')?.querySelector('.server-workbench-status');
          if (feedback) { feedback.classList.remove('is-error'); feedback.textContent = t('common.saving'); }
          await json(request, '/api/system/companions/adguard-home/filtering', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled, interval: Number(interval.input.value) }),
          });
          // Keep this form and its other unsaved fields in place after the
          // acknowledged setting change. Re-entry reloads dashboard state.
          if (feedback) feedback.textContent = t('common.saved');
        }),
      );
      const rewrites = managedList(t('server.wb_dns_rewrites'), dashboard.rewrites || [], rewrite => {
        const row = el('div', 'server-managed-row');
        row.append(el('span', '', `${rewrite.domain} → ${rewrite.answer}`));
        row.append(destructiveAction(t('common.remove'), t('server.wb_remove_rewrite', { domain: rewrite.domain }), async () => {
          await json(request, '/api/system/companions/adguard-home/rewrites/delete', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain: rewrite.domain, answer: rewrite.answer }),
          });
          await rerender();
        }));
        return row;
      });
      const rewriteForm = el('div', 'server-managed-form');
      const domain = inputField(t('server.wb_domain'), 'text');
      const answer = inputField(t('server.wb_answer'), 'text');
      rewriteForm.append(domain.field, answer.field, action(t('server.wb_add_rewrite'), async () => {
        await json(request, '/api/system/companions/adguard-home/rewrites/add', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ domain: domain.input.value, answer: answer.input.value }),
        });
        await rerender();
      }, 'is-primary'));
      rewrites.append(rewriteForm);
      const logItems = (dashboard.querylog || []).slice(0, 8);
      const querylog = managedList(t('server.wb_recent_dns'), logItems, item => {
        const question = item.question?.name || item.question?.host || item.question || t('server.wb_unknown_query');
        const reason = item.reason || item.status || t('server.wb_processed');
        return el('div', 'server-managed-row is-readonly', `${question} · ${reason}`);
      });
      host.replaceChildren(summary, controls, rewrites, querylog);
    } catch (error) {
      state.textContent = plainError(error.message);
      state.classList.add('is-error');
    }
  })();
  return host;
}

function npmConnectSurface(request, rerender, message) {
  const form = el('div', 'server-managed-form');
  const identity = inputField(t('server.wb_npm_email'), 'email');
  const secret = inputField(t('server.wb_npm_password'), 'password');
  form.append(
    el('p', 'server-workbench-copy', t('server.wb_npm_connect_copy')),
    identity.field,
    secret.field,
    action(t('server.wb_npm_connect'), async () => {
      message.textContent = t('server.wb_npm_connecting');
      await json(request, '/api/system/companions/nginx-proxy-manager/connect', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identity: identity.input.value, secret: secret.input.value }),
      });
      secret.input.value = '';
      await rerender();
    }, 'is-primary'),
  );
  return form;
}

function npmSurface(service, request, rerender) {
  const host = el('div', 'server-managed-surface');
  const state = statusLine(t('server.wb_npm_loading'));
  host.append(state);
  void (async () => {
    let dashboard;
    try { dashboard = await json(request, '/api/system/companions/nginx-proxy-manager/dashboard'); }
    catch (error) {
      state.textContent = plainError(error.message);
      host.append(npmConnectSurface(request, rerender, state));
      return;
    }
    const hosts = managedList(t('server.wb_proxy_hosts'), dashboard.proxy_hosts || [], item => {
      const domains = (item.domain_names || []).join(', ') || t('server.wb_unnamed_host');
      return el('div', 'server-managed-row is-readonly', `${domains} → ${item.forward_scheme || 'http'}://${item.forward_host}:${item.forward_port} · ${item.enabled ? t('server.wb_enabled') : t('server.wb_disabled')}`);
    });
    const certificates = managedList(t('server.wb_certificates'), dashboard.certificates || [], item => {
      const domains = (item.domain_names || []).join(', ') || item.nice_name || t('server.wb_unnamed_cert');
      return el('div', 'server-managed-row is-readonly', `${domains} · ${item.expires_on || t('server.wb_no_expiry')}`);
    });
    const form = el('div', 'server-managed-form');
    const domains = inputField(t('server.wb_domains_csv'), 'text');
    const forwardHost = inputField(t('server.wb_forward_host'), 'text', '127.0.0.1');
    const forwardPort = inputField(t('server.wb_forward_port'), 'number', '6769');
    forwardPort.input.min = '1'; forwardPort.input.max = '65535';
    let scheme = 'http'; let certificateId = 0; let sslForced = false;
    const schemeChoice = choice(t('server.wb_forward_scheme'), [{ label: 'http', value: 'http' }, { label: 'https', value: 'https' }], scheme, value => { scheme = value; });
    const certificateOptions = [{ label: t('server.wb_no_certificate'), value: '0' }, ...(dashboard.certificates || []).map(item => ({ label: item.nice_name || (item.domain_names || []).join(', ') || t('server.wb_certificate_id', { id: item.id }), value: String(item.id) }))];
    const certificateChoice = choice(t('server.wb_certificate'), certificateOptions, '0', value => { certificateId = Number(value); });
    form.append(
      domains.field, schemeChoice, forwardHost.field, forwardPort.field, certificateChoice,
      switchButton(t('server.wb_force_https'), false, value => { sslForced = value; }),
      action(t('server.wb_create_proxy'), async () => {
        await json(request, '/api/system/companions/nginx-proxy-manager/proxy-hosts', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            domain_names: domains.input.value.split(',').map(value => value.trim()).filter(Boolean),
            forward_scheme: scheme,
            forward_host: forwardHost.input.value,
            forward_port: Number(forwardPort.input.value),
            certificate_id: certificateId,
            ssl_forced: sslForced,
          }),
        });
        await rerender();
      }, 'is-primary'),
      destructiveAction(t('server.wb_disconnect_token'), t('server.wb_disconnect_confirm'), async () => {
        await json(request, '/api/system/companions/nginx-proxy-manager/disconnect', { method: 'POST' });
        await rerender();
      }),
    );
    host.replaceChildren(hosts, certificates, form);
  })();
  return host;
}

function companionCard(service, request, rerender) {
  const panel = card(service.name, t('server.wb_companion_copy'));
  panel.dataset.companion = service.service_id;
  const state = !service.prepared ? t('server.wb_not_prepared') : !service.owned ? t('server.wb_ownership_failed') : service.healthy ? t('server.system_healthy') : service.running ? t('server.system_unhealthy') : service.activated ? t('server.system_stopped') : t('server.wb_prepared_inactive');
  panel.append(
    fact(t('server.wb_state'), state),
    fact(t('server.wb_version'), service.version),
    fact(t('server.wb_license'), service.license),
    fact(t('server.wb_image'), service.image),
  );
  const message = statusLine();
  panel.append(message);
  const actions = el('div', 'server-workbench-actions');
  if (!service.prepared) {
    actions.append(action(t('server.wb_prepare_image'), async () => {
      message.textContent = t('server.wb_preparing');
      await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/prepare`, { method: 'POST' });
      await rerender();
    }, 'is-primary'));
    panel.append(actions);
    return panel;
  }

  const configure = action(t('server.wb_configure'), () => {
    form.hidden = !form.hidden;
    configure.setAttribute('aria-expanded', form.hidden ? 'false' : 'true');
    if (!form.hidden) bind.input.focus();
  });
  configure.setAttribute('aria-expanded', 'false');
  actions.append(configure);
  if (service.activated) {
    actions.append(destructiveAction(t('server.wb_rollback_activation'), t('server.wb_rollback_confirm', { name: service.name }), async () => {
      message.textContent = t('server.wb_rolling_back');
      await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/rollback`, { method: 'POST' });
      await rerender();
    }));
  }
  actions.append(destructiveAction(t('server.wb_remove_ownership'), t('server.wb_remove_ownership_confirm', { name: service.name }), async () => {
    message.textContent = t('server.wb_stopping_companion');
    await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/uninstall`, { method: 'POST' });
    await rerender();
  }));
  panel.append(actions);

  const form = el('div', 'server-companion-form');
  form.hidden = true;
  form.append(el('p', 'server-workbench-copy', service.service_id === 'adguard-home'
    ? t('server.wb_activation_dns')
    : t('server.wb_activation_http')));
  const current = service.activation || {};
  const bind = inputField(t('server.wb_exact_interface'), 'text', current.bind || '127.0.0.1');
  const portFields = {};
  const portGrid = el('div', 'server-workbench-grid server-companion-ports');
  const specs = service.service_id === 'adguard-home' ? [['dns', 53]] : [['http', 80], ['https', 443]];
  for (const [name, fallback] of specs) {
    const item = inputField(t('server.wb_port', { name }), 'number', String(current.ports?.[name] || fallback));
    item.input.min = '1';
    item.input.max = '65535';
    portFields[name] = item.input;
    portGrid.append(item.field);
  }
  const username = inputField(t('server.wb_admin_username'), 'text', 'admin');
  const password = inputField(t('server.wb_new_admin_password'), 'password');
  password.input.minLength = 12;
  const confirmation = inputField(t('server.wb_type_activate', { phrase: service.confirmation_phrase }), 'text');
  const results = el('div', 'server-companion-checks');
  results.setAttribute('role', 'status');
  results.setAttribute('aria-live', 'polite');
  const formActions = el('div', 'server-workbench-actions');
  let verifiedSignature = '';
  const values = () => ({
    bind: bind.input.value.trim(),
    ports: Object.fromEntries(Object.entries(portFields).map(([name, input]) => [name, Number(input.value)])),
  });
  const signature = () => JSON.stringify(values());
  const activateButton = action(t('server.wb_activate'), async () => {
    if (signature() !== verifiedSignature) throw new Error(t('server.wb_preflight_again'));
    message.textContent = t('server.wb_starting_companion');
    await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...values(),
        admin_username: username.input.value.trim(),
        admin_password: password.input.value,
        confirmation: confirmation.input.value.trim(),
      }),
    });
    password.input.value = '';
    await rerender();
  }, 'is-primary');
  activateButton.disabled = true;
  const invalidate = () => { verifiedSignature = ''; activateButton.disabled = true; results.replaceChildren(); };
  bind.input.addEventListener('input', invalidate);
  Object.values(portFields).forEach(input => input.addEventListener('input', invalidate));
  formActions.append(
    action(t('server.wb_preflight'), async () => {
      const result = await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/preflight`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values()),
      });
      results.replaceChildren(...result.checks.map(check => el('p', check.ok ? 'is-ok' : 'is-error', t(check.ok ? 'server.wb_check_pass' : 'server.wb_check_blocked', { name: check.name }))));
      verifiedSignature = result.ok ? signature() : '';
      activateButton.disabled = !result.ok;
    }),
    activateButton,
  );
  form.append(bind.field, portGrid);
  if (service.admin_setup === 'private_wizard') {
    form.append(el('p', 'server-workbench-copy', t('server.wb_npm_wizard_copy')));
  } else {
    form.append(username.field, password.field);
  }
  form.append(confirmation.field, results, formActions);
  panel.append(form);
  if (service.healthy) {
    const admin = el('a', 'server-workbench-admin', t('server.wb_open_admin'));
    admin.href = service.admin_url;
    admin.target = '_blank';
    admin.rel = 'noopener noreferrer';
    panel.append(admin, service.service_id === 'adguard-home'
      ? adguardSurface(service, request, rerender)
      : npmSurface(service, request, rerender));
  }
  return panel;
}

async function patchSettings(request, patch) {
  return json(request, '/api/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

async function renderServices(target, request) {
  const [ownedResult, searxngResult, actualResult, hostResult, companionsResult] = await Promise.allSettled([
    json(request, '/api/system/services'),
    json(request, '/api/system/searxng'),
    json(request, '/api/finance/actual'),
    json(request, '/api/system/host-services'),
    json(request, '/api/system/companions'),
  ]);
  const heading = card(t('server.wb_service_control'), t('server.wb_service_control_copy'));
  const message = statusLine();
  heading.append(message);
  const rerender = () => renderServices(target, request);
  const owned = ownedResult.status === 'fulfilled' ? ownedResult.value.services || [] : [];
  if (!owned.length) heading.append(el('p', 'server-workbench-empty', ownedResult.status === 'rejected' ? ownedResult.reason.message : t('server.wb_no_owned')));
  for (const service of owned) {
    const row = el('div', 'server-workbench-service');
    const copy = el('div');
    copy.append(el('strong', '', service.name || service.service_id), el('span', '', `${service.manager} · ${service.running ? t('server.wb_running') : service.available ? t('server.system_stopped') : t('common.unavailable')}${service.owned ? '' : ` · ${t('server.wb_ownership_unverified')}`}`));
    const actions = el('div', 'server-workbench-actions');
    for (const verb of service.actions || []) {
      actions.append(serviceAction(service.name || service.service_id, verb, async () => {
        message.textContent = t('server.wb_in_progress', { action: verbLabel(verb) });
        await json(request, `/api/system/services/${encodeURIComponent(service.service_id)}/${verb}`, { method: 'POST' });
        await rerender();
      }));
    }
    row.append(copy, actions);
    heading.append(row);
  }

  const search = card('searxng', t('server.wb_searxng_copy'));
  if (searxngResult.status === 'rejected') {
    search.append(statusLine(searxngResult.reason.message, 'error'));
  } else {
    const service = searxngResult.value;
    const runtime = service.available ? (service.docker_version ? t('server.system_docker_version', { version: service.docker_version }) : t('server.wb_docker_available')) : t('server.system_docker_unavailable');
    const state = !service.installed ? t('server.system_not_installed') : !service.owned ? t('server.wb_ownership_failed') : service.healthy ? t('server.system_healthy') : service.running ? t('server.system_unhealthy') : t('server.system_stopped');
    const searchMessage = statusLine();
    search.append(fact(t('server.wb_state'), state), fact(t('server.wb_runtime'), runtime), fact(t('server.wb_bind'), service.bind || t('server.wb_local_only')), searchMessage);
    const actions = el('div', 'server-workbench-actions');
    const verbs = [];
    if (!service.installed && service.support_verified) verbs.push('install');
    if (service.installed && service.owned) {
      verbs.push(service.running ? 'stop' : 'start', 'restart', 'test', 'update', 'rollback');
    }
    for (const verb of verbs) {
      const run = async () => {
        searchMessage.classList.remove('is-error');
        searchMessage.textContent = t('server.wb_in_progress', { action: verbLabel(verb) });
        const result = await json(request, `/api/system/searxng/${verb}`, { method: 'POST' });
        if (verb === 'test') {
          if (result?.ok !== true || !Number.isInteger(result.results) || result.results < 0) throw new Error(t('server.wb_invalid_test'));
          searchMessage.textContent = tp('server.system_json_passed', result.results);
        }
        else await rerender();
      };
      actions.append(['stop', 'restart', 'update', 'rollback'].includes(verb)
        ? serviceAction('SearXNG', verb, run)
        : action(verb === 'test' ? t('server.system_test_search') : verbLabel(verb), run));
    }
    search.append(actions);
  }

  const host = card(t('server.wb_host_services'), t('server.wb_host_services_copy'));
  if (hostResult.status === 'rejected') host.append(statusLine(hostResult.reason.message, 'error'));
  else {
    const payload = hostResult.value;
    host.append(fact(t('server.wb_policy'), payload.policy_valid ? payload.control_mode : t('server.wb_policy_invalid')));
    for (const service of payload.services || []) {
      const row = el('div', 'server-workbench-service');
      const copy = el('div');
      copy.append(el('strong', '', service.id), el('span', '', service.manager));
      const actions = el('div', 'server-workbench-actions');
      for (const verb of ['start', 'stop', 'restart']) {
        actions.append(serviceAction(service.id, verb, async () => {
          message.textContent = t('server.wb_in_progress', { action: verbLabel(verb) });
          await json(request, `/api/system/host-services/${service.manager}/${encodeURIComponent(service.id)}/${verb}`, { method: 'POST' });
          message.textContent = t('server.wb_complete', { id: service.id, action: verbLabel(verb) });
        }));
      }
      row.append(copy, actions);
      host.append(row);
    }
    if (!(payload.services || []).length) host.append(el('p', 'server-workbench-empty', t('server.wb_no_host_services')));
  }
  target.replaceChildren(heading, search, host);
  const actual = card(t('server.wb_actual'), t('server.wb_actual_copy'));
  if (actualResult.status === 'rejected') actual.append(statusLine(actualResult.reason.message, 'error'));
  else {
    const payload = actualResult.value;
    const service = payload.service || {};
    actual.append(
      fact(t('server.wb_service'), !service.available ? t('server.wb_runtime_unavailable') : !service.installed ? t('server.system_not_installed') : service.healthy ? t('server.system_healthy') : service.running ? t('server.system_unhealthy') : t('server.system_stopped')),
      fact(t('server.wb_saved_in'), { alles: 'Alles', actual: 'Actual' }[payload.ledger?.mode] || t('server.wb_not_reported')),
    );
    if (service.installed) actual.append(fact(t('server.wb_managed_by'), service.owned === false ? t('server.wb_not_verified') : 'Alles'));
    if (!service.available) actual.append(el('p', 'server-workbench-copy', t('server.wb_node_required')));
    const actions = el('div', 'server-workbench-actions');
    const verbs = [];
    if (service.available && !service.installed) verbs.push('install');
    if (service.available && service.installed) verbs.push(service.running ? 'stop' : 'start', 'restart', 'update', 'rollback', 'backup');
    for (const verb of verbs) {
      actions.append(serviceAction('Actual Budget', verb, async () => {
        message.textContent = t('server.wb_actual_in_progress', { action: verbLabel(verb) });
        await json(request, `/api/finance/actual/service/${verb}`, { method: 'POST' });
        await rerender();
      }));
    }
    actual.append(actions);
  }
  actual.append(el('p', 'server-workbench-copy', t('server.wb_choose_ledger')));
  const financeActions = el('div', 'server-workbench-actions');
  financeActions.append(action(t('server.wb_open_finance'), () => window._navigateSpecialistSection('finance', 'overview')));
  actual.append(financeActions);
  target.append(actual);
  const companions = card(t('server.wb_companions'), t('server.wb_companions_copy'));
  if (companionsResult.status === 'rejected') companions.append(statusLine(companionsResult.reason.message, 'error'));
  else {
    const rows = companionsResult.value.companions || [];
    if (!rows.length) companions.append(el('p', 'server-workbench-empty', t('server.wb_no_companions')));
    for (const service of rows) companions.append(companionCard(service, request, rerender));
  }
  target.append(companions);
}

function modelOptions(endpoints) {
  const options = [];
  for (const endpoint of endpoints || []) {
    for (const model of endpoint.models || []) {
      options.push({
        value: `${endpoint.id}\u0000${model}`,
        label: `${endpoint.name} · ${model}`,
        endpointId: endpoint.id,
        model,
      });
    }
  }
  return options;
}

async function renderSearch(target, request) {
  const [settingsResult, endpointsResult, rolesResult, enginesResult] = await Promise.allSettled([
    json(request, '/api/settings'),
    json(request, '/api/models'),
    json(request, '/api/models/roles'),
    json(request, '/api/search/engines'),
  ]);
  const engines = enginesResult.status === 'fulfilled' ? enginesResult.value.engines || [] : [];
  if (settingsResult.status === 'rejected') throw settingsResult.reason;
  let settings = settingsResult.value;
  const panel = card(t('server.wb_search_models'), t('server.wb_search_models_copy'));
  const message = statusLine();
  panel.append(message);
  const save = async patch => {
    message.classList.remove('is-error');
    message.textContent = t('common.saving');
    try {
      settings = await patchSettings(request, patch);
      message.textContent = t('common.saved');
      return settings;
    } catch (error) {
      message.textContent = plainError(error.message);
      message.classList.add('is-error');
      throw error;
    }
  };
  const providerOptions = [
    ...(engines.length ? engines.map(engine => [engine.id, engine.id === 'duckduckgo' ? t('server.wb_free_search') : engine.label.toLowerCase()]) : [['duckduckgo', t('server.wb_free_search')]]),
    ['disabled', t('server.wb_disabled')],
  ].map(([value, label]) => ({ value, label }));
  panel.append(
    choice(t('server.wb_primary_provider'), providerOptions, settings.search_provider || 'duckduckgo', value => save({ search_provider: value })),
    choice(t('server.wb_results_per_search'), [5, 8, 10, 12].map(value => ({ value: String(value), label: String(value) })), String(settings.search_result_count || 8), value => save({ search_result_count: Number(value) })),
    switchButton(t('server.wb_fact_check'), settings.andromeda_verification_enabled !== false, value => save({ andromeda_verification_enabled: value })),
    choice(t('server.wb_fact_schedule'), [
      { value: 'freshness-sensitive', label: t('server.wb_sched_fresh') },
      { value: 'always', label: t('server.wb_sched_always') },
      { value: 'manual', label: t('server.wb_sched_manual') },
      { value: 'off', label: t('server.wb_sched_off') },
    ], settings.andromeda_verifier_mode || 'freshness-sensitive', value => save({ andromeda_verifier_mode: value })),
  );

  const limits = el('div', 'server-workbench-grid');
  for (const spec of [
    [t('server.wb_answer_tokens'), 'andromeda_answer_max_tokens', 100, 2000],
    [t('server.wb_answer_seconds'), 'andromeda_answer_timeout_seconds', 5, 120],
    [t('server.wb_verifier_tokens'), 'andromeda_verifier_max_tokens', 100, 2000],
    [t('server.wb_verifier_seconds'), 'andromeda_verifier_timeout_seconds', 5, 120],
  ]) {
    const [label, key, min, max] = spec;
    const field = el('label', 'server-workbench-field');
    field.append(el('span', '', label));
    const input = el('input');
    input.type = 'number';
    input.min = String(min);
    input.max = String(max);
    input.value = String(settings[key]);
    input.addEventListener('change', () => { void save({ [key]: Number(input.value) }).catch(() => {}); });
    field.append(input);
    limits.append(field);
  }
  panel.append(limits);

  const credentials = card(t('server.wb_credentials'), t('server.wb_credentials_copy'));
  // one key field per keyed engine, from the shared engine list; google pse also needs its cx
  const credentialSpecs = [
    ...engines.filter(engine => engine.key_setting && !engine.custom).map(engine => [
      t('server.wb_api_key', { name: engine.label.toLowerCase() }), engine.key_setting, `${engine.key_setting}_configured`, 'password',
    ]),
    [t('server.wb_google_cx'), 'google_pse_cx', '', 'text'],
    [t('server.wb_searxng_url'), 'searxng_url', '', 'url'],
  ];
  for (const [label, key, configuredKey, type] of credentialSpecs) {
    const field = el('label', 'server-workbench-field');
    field.append(el('span', '', label));
    const input = el('input');
    input.type = type;
    input.autocomplete = type === 'password' ? 'new-password' : 'off';
    input.placeholder = configuredKey && settings[configuredKey] ? t('server.wb_configured_replace') : t('server.wb_not_configured');
    if (!configuredKey && key === 'google_pse_cx') input.value = settings[key] || '';
    if (!configuredKey && key === 'searxng_url') input.placeholder = settings[key] || 'https://search.example.com';
    input.addEventListener('change', () => {
      void save({ [key]: input.value.trim() }).then(() => {
        if (type === 'password') input.value = '';
      }).catch(() => {});
    });
    field.append(input);
    credentials.append(field);
  }

  const models = card(t('server.wb_roles'), t('server.wb_roles_copy'));
  if (endpointsResult.status === 'rejected' || rolesResult.status === 'rejected') {
    models.append(statusLine(t('server.wb_models_unavailable'), 'error'));
  } else {
    const choices = modelOptions(endpointsResult.value);
    const roles = rolesResult.value;
    if (!choices.length) models.append(el('p', 'server-workbench-empty', t('server.wb_no_models')));
    for (const role of ['andromeda_answer', 'andromeda_verifier']) {
      const configured = roles[role]?.configured || {};
      const configuredValue = configured.endpoint_id && configured.model ? `${configured.endpoint_id}\u0000${configured.model}` : '';
      const selected = choices.some(item => item.value === configuredValue) ? configuredValue : '';
      const options = [{ value: '', label: t('common.automatic') }, ...choices];
      models.append(choice(role === 'andromeda_answer' ? t('server.wb_answer_model') : t('server.wb_verifier_model'), options, selected, async value => {
        // read the roles again: settings or andromeda may have changed one since this was drawn
        const fresh = await json(request, '/api/settings');
        const nextRoles = { ...(fresh.model_roles || {}) };
        if (!value) nextRoles[role] = {};
        else {
          const picked = choices.find(item => item.value === value);
          nextRoles[role] = { endpoint_id: picked.endpointId, model: picked.model };
        }
        const saved = await save({ model_roles: nextRoles });
        announceModelRoles(saved?.model_roles || nextRoles, 'server');
      }));
      models.append(fact(role === 'andromeda_answer' ? t('server.wb_answer_status') : t('server.wb_verifier_status'), roles[role]?.status || t('common.unavailable')));
    }
  }
  target.replaceChildren(panel, models, credentials);
  // a role picked in settings or andromeda shows here too, without a reload
  _roleWatch.get(target)?.();
  const off = onModelRoles(({ source }) => {
    if (!target.isConnected) return off();
    if (source !== 'server') void renderSearch(target, request).catch(() => {});
  });
  _roleWatch.set(target, off);
}

const _roleWatch = new WeakMap();

async function renderBackups(target, request, completed = null) {
  const [settingsResult, locationsResult, webdavResult, s3Result] = await Promise.allSettled([
    json(request, '/api/settings'),
    json(request, '/api/storage-locations'),
    json(request, '/api/backup/webdav'),
    json(request, '/api/backup/s3'),
  ]);
  const intro = card(t('server.wb_backups'), t('server.wb_backups_copy'));
  const local = card(t('server.wb_auto_backup'), t('server.wb_auto_backup_copy'));
  if (settingsResult.status === 'rejected') local.append(statusLine(settingsResult.reason.message, 'error'));
  else {
    const settings = settingsResult.value;
    local.append(
      fact(t('server.wb_enabled'), settings.automatic_backup_enabled ? t('server.wb_yes') : t('server.wb_no')),
      fact(t('server.wb_destination'), settings.automatic_backup_dir || t('server.wb_not_configured')),
      fact(t('server.wb_last_success'), settings.automatic_backup_last_success || t('server.wb_never')),
    );
    if (settings.automatic_backup_last_error) local.append(statusLine(settings.automatic_backup_last_error, 'error'));
  }
  const storage = card(t('server.wb_storage'), t('server.wb_storage_copy'));
  storage.append(action(t('server.wb_open_files'), () => window._navigateTo('files')));
  if (locationsResult.status === 'rejected') storage.append(statusLine(locationsResult.reason.message, 'error'));
  else {
    const locations = locationsResult.value.locations || [];
    if (!locations.length) storage.append(el('p', 'server-workbench-empty', t('server.wb_no_storage')));
    for (const location of locations) storage.append(fact(location.name || t('server.wb_location'), `${location.kind} · ${location.enabled ? t('server.wb_enabled') : t('server.wb_disabled')} · ${location.access}`));
  }
  const appendDestination = (title, type, result) => {
    const section = card(title);
    if (result.status === 'rejected') {
      section.append(statusLine(result.reason.message, 'error'));
      return section;
    }
    const value = result.value;
    section.append(
      fact(t('server.wb_configured'), value.configured ? t('server.wb_yes') : t('server.wb_no')),
      fact(t('server.wb_last_backup'), value.last_backup_at || t('server.wb_never')),
      fact(t('server.wb_last_verified'), value.last_verified_at || t('server.wb_never')),
    );
    const finished = completed?.type === type;
    const message = statusLine(finished ? completed.message : value.error || '', !finished && value.error ? 'error' : '');
    section.append(message);
    const button = action(t('server.wb_run_backup'), async () => {
      message.classList.remove('is-error');
      message.textContent = t('server.wb_creating_backup');
      let saved;
      try { saved = await json(request, `/api/backup/${type}/run`, { method: 'POST' }); }
      catch (error) { message.textContent = ''; throw error; }
      await renderBackups(target, request, { type, message: t('server.wb_backup_complete', { filename: saved.filename }) });
    });
    button.disabled = !value.configured;
    section.append(button);
    return section;
  };
  target.replaceChildren(intro, local, storage, appendDestination('webdav', 'webdav', webdavResult), appendDestination(t('server.wb_s3'), 's3', s3Result));
}

async function renderUpdates(target, request) {
  const section = card(t('server.wb_release'), t('server.wb_release_copy'));
  try {
    const build = await json(request, '/api/system/build');
    section.append(
      fact(t('server.wb_version'), build.version),
      fact(t('server.wb_build'), build.build_id),
      fact(t('server.wb_migration_head'), build.migration_head),
      fact(t('server.wb_update_action'), t('server.wb_update_action_value')),
    );
  } catch (error) {
    section.append(statusLine(error.message, 'error'));
  }
  target.replaceChildren(section);
}

function logEntry(entry) {
  const row = el('div', 'server-workbench-log');
  const when = entry.created_at || entry.timestamp || entry.time || entry.ts || '';
  const actionName = entry.action || entry.level || entry.event || t('server.wb_entry');
  const detail = entry.message || entry.outcome || entry.target || '';
  row.append(el('time', '', String(when)), el('strong', '', String(actionName)), el('span', '', String(detail)));
  return row;
}

async function renderLogs(target, request) {
  const [logsResult, auditResult] = await Promise.allSettled([
    json(request, '/api/system/logs?limit=80'),
    json(request, '/api/system/audit?limit=80'),
  ]);
  const append = (title, result) => {
    const section = card(title);
    if (result.status === 'rejected') section.append(statusLine(result.reason.message, 'error'));
    else {
      const entries = result.value.entries || [];
      if (!entries.length) section.append(el('p', 'server-workbench-empty', t('server.wb_no_entries')));
      entries.forEach(entry => section.append(logEntry(entry)));
    }
    return section;
  };
  target.replaceChildren(append(t('server.wb_runtime_logs'), logsResult), append(t('server.wb_audit'), auditResult));
}

async function renderPolicy(target, request) {
  const section = card(t('server.wb_policy_title'), t('server.wb_policy_copy'));
  section.append(el('p', 'server-workbench-copy', t('server.wb_policy_file_copy')));
  const message = statusLine();
  let current;
  try { current = await json(request, '/api/system/policy'); }
  catch (error) {
    section.append(statusLine(error.message, 'error'));
    target.replaceChildren(section);
    return;
  }
  const effectiveState = fact(t('server.wb_effective_state'), current.valid ? current.policy.control_mode : t('server.wb_host_unavailable'));
  const policyError = current.valid ? null : statusLine(t('server.wb_policy_error', { error: current.error }), 'error');
  section.append(fact(t('server.wb_file'), current.path), effectiveState, fact(t('server.wb_local_device'), current.local_device ? t('server.wb_yes') : t('server.wb_no')));
  if (policyError) section.append(policyError);
  const label = el('label', 'server-workbench-field');
  label.append(el('span', '', t('server.wb_policy_json')));
  const editor = el('textarea');
  editor.rows = 12;
  editor.spellcheck = false;
  editor.value = current.canonical;
  label.append(editor);
  section.append(label);
  const diff = el('pre', 'server-workbench-diff', t('server.wb_no_changes'));
  const confirmation = el('label', 'server-workbench-field');
  confirmation.hidden = true;
  confirmation.append(el('span', '', t('server.wb_type_allow', { phrase: current.confirmation_phrase })));
  const confirmInput = el('input');
  confirmInput.type = 'text';
  confirmInput.autocomplete = 'off';
  confirmation.append(confirmInput);
  const actions = el('div', 'server-workbench-actions');
  const inspect = async () => {
    const result = await json(request, '/api/system/policy/diff', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ policy: editor.value }),
    });
    diff.textContent = result.diff.length ? result.diff.join('\n') : t('server.wb_no_changes');
    confirmation.hidden = result.policy.control_mode !== 'allowlisted_host';
    message.classList.remove('is-error');
    message.textContent = t('server.wb_policy_valid');
    return result;
  };
  actions.append(
    action(t('server.wb_validate'), async () => {
      try { await inspect(); } catch (error) { message.textContent = plainError(error.message); message.classList.add('is-error'); }
    }),
    action(t('server.wb_save_policy'), async () => {
      try {
        const candidate = await inspect();
        const saved = await json(request, '/api/system/policy', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ policy: editor.value, confirmation: candidate.policy.control_mode === 'allowlisted_host' ? confirmInput.value : '' }),
        });
        editor.value = saved.canonical;
        effectiveState.querySelector('strong').textContent = saved.policy.control_mode;
        // emptied, not removed: its line stays reserved so the actions do not jump
        if (policyError) {
          policyError.style.minHeight = `${policyError.offsetHeight}px`;
          policyError.textContent = '';
          policyError.classList.remove('is-error');
        }
        message.classList.remove('is-error');
        message.textContent = t('server.wb_policy_saved');
        confirmation.hidden = saved.policy.control_mode !== 'allowlisted_host';
      } catch (error) {
        message.textContent = plainError(error.message);
        message.classList.add('is-error');
      }
    }, 'is-primary'),
    message,
  );
  section.append(actions, confirmation, diff);
  target.replaceChildren(section);
}

export async function renderServerSection(target, request = fetch, section = 'services') {
  // The workbench moves these children out of its staging element. Keep the
  // action target attached so refreshes update this section after that move.
  const content = el('div', 'server-workbench-content');
  target.replaceChildren(content);
  target = content;
  target.replaceChildren(el('p', 'server-workbench-empty', t('server.wb_loading')));
  try {
    if (section === 'services') return await renderServices(target, request);
    if (section === 'search') return await renderSearch(target, request);
    if (section === 'backups') return await renderBackups(target, request);
    if (section === 'updates') return await renderUpdates(target, request);
    if (section === 'logs') return await renderLogs(target, request);
    if (section === 'policy') return await renderPolicy(target, request);
    target.replaceChildren(statusLine(t('server.wb_section_unavailable'), 'error'));
  } catch (error) {
    target.replaceChildren(statusLine(error.message || t('server.wb_load_failed'), 'error'));
  }
}
