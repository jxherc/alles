// Server owns safe service control, search/model policy, backup status, release
// information, logs, and the explicit host-control policy. Every mutation uses
// an existing typed API; this UI never accepts shell commands or arbitrary paths.

import { formatNumber } from './i18n.js';
import { confirm as confirmDialog } from './dialog.js';
import { requestWithRecentOwner } from './recent_owner.js';

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== '') node.textContent = text;
  return node;
}

function errorMessage(payload, fallback) {
  return payload?.error?.message || payload?.detail?.message || payload?.detail || payload?.message || fallback;
}

async function json(request, url, options) {
  const method = String(options?.method || 'GET').toUpperCase();
  const response = method === 'GET' || method === 'HEAD'
    ? await request(url, options)
    : await requestWithRecentOwner(request, url, options);
  let payload = null;
  try { payload = await response.json(); } catch { /* keep the bounded fallback */ }
  if (!response.ok) throw new Error(errorMessage(payload, `request failed: ${response.status}`));
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
  row.append(el('span', '', label), el('strong', '', String(value ?? 'unavailable')));
  return row;
}

function action(label, run, className = '') {
  const button = el('button', className, label);
  button.type = 'button';
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try { await run(button); }
    catch (error) {
      const parent = button.closest('.server-workbench-card');
      let region = parent?.querySelector('.server-workbench-status');
      if (!region && parent) { region = statusLine(); parent.append(region); }
      if (region) { region.textContent = error.message || 'action failed'; region.classList.add('is-error'); }
    } finally {
      button.disabled = false;
      button.removeAttribute('aria-busy');
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

function serviceAction(subject, verb, run) {
  if (!['stop', 'restart', 'update', 'rollback'].includes(verb)) return action(verb, run);
  const consequence = verb === 'stop'
    ? `stop ${subject}? it will be unavailable until it is started again.`
    : verb === 'restart'
      ? `restart ${subject}? active requests may be interrupted.`
      : verb === 'update'
        ? `update ${subject}? Alles will replace the managed release after verification.`
        : `roll back ${subject}? the current managed release will be replaced by its verified predecessor.`;
  return destructiveAction(verb, consequence, run);
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
    if (region) { region.textContent = error.message || 'setting failed'; region.classList.add('is-error'); }
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
      let rollbackFocus = null;
      choiceBusy = true;
      list.setAttribute('aria-busy', 'true');
      buttons.forEach(item => { item.disabled = true; });
      select(button);
      try { await onChange(option.value); }
      catch (error) {
        select(previous || button);
        rollbackFocus = previous || button;
        reportFailure(error);
      } finally {
        choiceBusy = false;
        list.removeAttribute('aria-busy');
        buttons.forEach(item => { item.disabled = false; });
        rollbackFocus?.focus();
      }
    });
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
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
  const button = el('button', 'server-workbench-switch');
  button.type = 'button';
  button.setAttribute('role', 'switch');
  button.setAttribute('aria-checked', pressed ? 'true' : 'false');
  const name = el('span', '', label);
  const state = el('strong', '', pressed ? 'on' : 'off');
  button.append(name, state);
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    const previous = button.getAttribute('aria-checked') === 'true';
    const next = button.getAttribute('aria-checked') !== 'true';
    button.setAttribute('aria-checked', next ? 'true' : 'false');
    state.textContent = next ? 'on' : 'off';
    try { await onChange(next); }
    catch (error) {
      button.setAttribute('aria-checked', previous ? 'true' : 'false');
      state.textContent = previous ? 'on' : 'off';
      const card = button.closest('.server-workbench-card');
      let region = card?.querySelector('.server-workbench-status');
      if (!region && card) { region = statusLine(); card.append(region); }
      if (region) { region.textContent = error.message || 'setting failed'; region.classList.add('is-error'); }
    } finally {
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  });
  return button;
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
  if (!items.length) list.append(el('p', 'server-workbench-empty', 'none'));
  else items.forEach(item => list.append(render(item)));
  section.append(list);
  return section;
}

function adguardSurface(service, request, rerender) {
  const host = el('div', 'server-managed-surface');
  const state = statusLine('loading AdGuard status…');
  host.append(state);
  void (async () => {
    try {
      const dashboard = await json(request, '/api/system/companions/adguard-home/dashboard');
      const stats = dashboard.stats || {};
      const filtering = dashboard.filtering || {};
      const summary = el('div', 'server-workbench-grid server-managed-summary');
      summary.append(
        fact('queries today', formatNumber(Number(stats.num_dns_queries || 0))),
        fact('blocked today', formatNumber(Number(stats.num_blocked_filtering || 0))),
        fact('average response', `${Math.round(Number(stats.avg_processing_time || 0) * 1000)} ms`),
      );
      const controls = el('div', 'server-managed-controls');
      const interval = inputField('filter refresh hours', 'number', String(filtering.interval ?? 24));
      interval.input.min = '0'; interval.input.max = '168';
      controls.append(
        interval.field,
        switchButton('DNS filtering', Boolean(filtering.enabled), async enabled => {
          await json(request, '/api/system/companions/adguard-home/filtering', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled, interval: Number(interval.input.value) }),
          });
          await rerender();
        }),
      );
      const rewrites = managedList('DNS rewrites', dashboard.rewrites || [], rewrite => {
        const row = el('div', 'server-managed-row');
        row.append(el('span', '', `${rewrite.domain} → ${rewrite.answer}`));
        row.append(destructiveAction('remove', `remove the DNS rewrite for ${rewrite.domain}?`, async () => {
          await json(request, '/api/system/companions/adguard-home/rewrites/delete', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain: rewrite.domain, answer: rewrite.answer }),
          });
          await rerender();
        }));
        return row;
      });
      const rewriteForm = el('div', 'server-managed-form');
      const domain = inputField('domain', 'text');
      const answer = inputField('answer', 'text');
      rewriteForm.append(domain.field, answer.field, action('add rewrite', async () => {
        await json(request, '/api/system/companions/adguard-home/rewrites/add', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ domain: domain.input.value, answer: answer.input.value }),
        });
        await rerender();
      }, 'is-primary'));
      rewrites.append(rewriteForm);
      const logItems = (dashboard.querylog || []).slice(0, 8);
      const querylog = managedList('recent DNS activity', logItems, item => {
        const question = item.question?.name || item.question?.host || item.question || 'unknown query';
        const reason = item.reason || item.status || 'processed';
        return el('div', 'server-managed-row is-readonly', `${question} · ${reason}`);
      });
      host.replaceChildren(summary, controls, rewrites, querylog);
    } catch (error) {
      state.textContent = error.message;
      state.classList.add('is-error');
    }
  })();
  return host;
}

function npmConnectSurface(request, rerender, message) {
  const form = el('div', 'server-managed-form');
  const identity = inputField('Nginx admin email', 'email');
  const secret = inputField('Nginx admin password', 'password');
  form.append(
    el('p', 'server-workbench-copy', 'Connect after completing the private setup wizard. The password is exchanged locally and never stored; only the encrypted API token is retained.'),
    identity.field,
    secret.field,
    action('connect private admin', async () => {
      message.textContent = 'connecting to the loopback-only API…';
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
  const state = statusLine('loading proxy hosts and certificates…');
  host.append(state);
  void (async () => {
    let dashboard;
    try { dashboard = await json(request, '/api/system/companions/nginx-proxy-manager/dashboard'); }
    catch (error) {
      state.textContent = error.message;
      host.append(npmConnectSurface(request, rerender, state));
      return;
    }
    const hosts = managedList('proxy hosts', dashboard.proxy_hosts || [], item => {
      const domains = (item.domain_names || []).join(', ') || 'unnamed host';
      return el('div', 'server-managed-row is-readonly', `${domains} → ${item.forward_scheme || 'http'}://${item.forward_host}:${item.forward_port} · ${item.enabled ? 'enabled' : 'disabled'}`);
    });
    const certificates = managedList('certificates', dashboard.certificates || [], item => {
      const domains = (item.domain_names || []).join(', ') || item.nice_name || 'unnamed certificate';
      return el('div', 'server-managed-row is-readonly', `${domains} · ${item.expires_on || 'no expiry reported'}`);
    });
    const form = el('div', 'server-managed-form');
    const domains = inputField('domains, comma separated', 'text');
    const forwardHost = inputField('forward host', 'text', '127.0.0.1');
    const forwardPort = inputField('forward port', 'number', '6769');
    forwardPort.input.min = '1'; forwardPort.input.max = '65535';
    let scheme = 'http'; let certificateId = 0; let sslForced = false;
    const schemeChoice = choice('forward scheme', [{ label: 'http', value: 'http' }, { label: 'https', value: 'https' }], scheme, value => { scheme = value; });
    const certificateOptions = [{ label: 'no certificate', value: '0' }, ...(dashboard.certificates || []).map(item => ({ label: item.nice_name || (item.domain_names || []).join(', ') || `certificate ${item.id}`, value: String(item.id) }))];
    const certificateChoice = choice('certificate', certificateOptions, '0', value => { certificateId = Number(value); });
    form.append(
      domains.field, schemeChoice, forwardHost.field, forwardPort.field, certificateChoice,
      switchButton('force HTTPS', false, value => { sslForced = value; }),
      action('create proxy host', async () => {
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
      destructiveAction('disconnect API token', 'disconnect the private Nginx Proxy Manager API token? managed proxy data will stay in place.', async () => {
        await json(request, '/api/system/companions/nginx-proxy-manager/disconnect', { method: 'POST' });
        await rerender();
      }),
    );
    host.replaceChildren(hosts, certificates, form);
  })();
  return host;
}

function companionCard(service, request, rerender) {
  const panel = card(service.name, 'Pinned and independently licensed. Alles prepares its private data and verifies ownership before it can open any network listener.');
  panel.dataset.companion = service.service_id;
  const state = !service.prepared ? 'not prepared' : !service.owned ? 'ownership failed' : service.healthy ? 'healthy' : service.running ? 'unhealthy' : service.activated ? 'stopped' : 'prepared, inactive';
  panel.append(
    fact('state', state),
    fact('version', service.version),
    fact('license', service.license),
    fact('image', service.image),
  );
  const message = statusLine();
  panel.append(message);
  const actions = el('div', 'server-workbench-actions');
  if (!service.prepared) {
    actions.append(action('prepare pinned image', async () => {
      message.textContent = 'checking Docker and downloading the pinned image…';
      await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/prepare`, { method: 'POST' });
      await rerender();
    }, 'is-primary'));
    panel.append(actions);
    return panel;
  }

  const configure = action('configure activation', () => {
    form.hidden = !form.hidden;
    configure.setAttribute('aria-expanded', form.hidden ? 'false' : 'true');
    if (!form.hidden) bind.input.focus();
  });
  configure.setAttribute('aria-expanded', 'false');
  actions.append(configure);
  if (service.activated) {
    actions.append(destructiveAction('rollback activation', `roll back ${service.name} activation? its network listeners will stop and the previous configuration will be restored.`, async () => {
      message.textContent = 'stopping and restoring the previous listener configuration…';
      await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/rollback`, { method: 'POST' });
      await rerender();
    }));
  }
  actions.append(destructiveAction('remove ownership, keep data', `remove Alles ownership of ${service.name}? its service will stop, but its private data will remain.`, async () => {
    message.textContent = 'stopping the companion and retaining its private data…';
    await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/uninstall`, { method: 'POST' });
    await rerender();
  }));
  panel.append(actions);

  const form = el('div', 'server-companion-form');
  form.hidden = true;
  form.append(el('p', 'server-workbench-copy', service.service_id === 'adguard-home'
    ? 'Activation opens DNS on one exact interface. Alles does not change your router or operating-system DNS automatically.'
    : 'Activation opens HTTP and HTTPS on one exact interface. The admin interface remains on loopback port 8181.'));
  const current = service.activation || {};
  const bind = inputField('exact interface address', 'text', current.bind || '127.0.0.1');
  const portFields = {};
  const portGrid = el('div', 'server-workbench-grid server-companion-ports');
  const specs = service.service_id === 'adguard-home' ? [['dns', 53]] : [['http', 80], ['https', 443]];
  for (const [name, fallback] of specs) {
    const item = inputField(`${name} port`, 'number', String(current.ports?.[name] || fallback));
    item.input.min = '1';
    item.input.max = '65535';
    portFields[name] = item.input;
    portGrid.append(item.field);
  }
  const username = inputField('admin username', 'text', 'admin');
  const password = inputField('new private admin password', 'password');
  password.input.minLength = 12;
  const confirmation = inputField(`type “${service.confirmation_phrase}” to activate`, 'text');
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
  const activateButton = action('activate verified listeners', async () => {
    if (signature() !== verifiedSignature) throw new Error('run the network preflight again');
    message.textContent = 'starting the pinned companion and checking its private admin endpoint…';
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
    action('run network preflight', async () => {
      const result = await json(request, `/api/system/companions/${encodeURIComponent(service.service_id)}/preflight`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values()),
      });
      results.replaceChildren(...result.checks.map(check => el('p', check.ok ? 'is-ok' : 'is-error', `${check.ok ? 'pass' : 'blocked'} · ${check.name}`)));
      verifiedSignature = result.ok ? signature() : '';
      activateButton.disabled = !result.ok;
    }),
    activateButton,
  );
  form.append(bind.field, portGrid);
  if (service.admin_setup === 'private_wizard') {
    form.append(el('p', 'server-workbench-copy', 'Create the first admin inside the loopback-only Nginx Proxy Manager wizard after activation. Alles never places that password in Docker environment or logs.'));
  } else {
    form.append(username.field, password.field);
  }
  form.append(confirmation.field, results, formActions);
  panel.append(form);
  if (service.healthy) {
    const admin = el('a', 'server-workbench-admin', 'open private admin');
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
  const heading = card('service control', 'Alles-owned services can be controlled here. Host services stay disabled unless the policy tab explicitly allowlists exact IDs.');
  const message = statusLine();
  heading.append(message);
  const rerender = () => renderServerSection(target, request, 'services');
  const owned = ownedResult.status === 'fulfilled' ? ownedResult.value.services || [] : [];
  if (!owned.length) heading.append(el('p', 'server-workbench-empty', ownedResult.status === 'rejected' ? ownedResult.reason.message : 'no Alles-owned services are registered'));
  for (const service of owned) {
    const row = el('div', 'server-workbench-service');
    const copy = el('div');
    copy.append(el('strong', '', service.name || service.service_id), el('span', '', `${service.manager} · ${service.running ? 'running' : service.available ? 'stopped' : 'unavailable'}${service.owned ? '' : ' · ownership unverified'}`));
    const actions = el('div', 'server-workbench-actions');
    for (const verb of service.actions || []) {
      actions.append(serviceAction(service.name || service.service_id, verb, async () => {
        message.textContent = `${verb} in progress…`;
        await json(request, `/api/system/services/${encodeURIComponent(service.service_id)}/${verb}`, { method: 'POST' });
        await rerender();
      }));
    }
    row.append(copy, actions);
    heading.append(row);
  }

  const search = card('searxng', 'Optional self-hosted web search managed inside the Alles data boundary. External providers continue to work when this is absent.');
  if (searxngResult.status === 'rejected') {
    search.append(statusLine(searxngResult.reason.message, 'error'));
  } else {
    const service = searxngResult.value;
    const runtime = service.available ? `docker ${service.docker_version || 'available'}` : 'docker unavailable';
    const state = !service.installed ? 'not installed' : !service.owned ? 'ownership failed' : service.healthy ? 'healthy' : service.running ? 'unhealthy' : 'stopped';
    search.append(fact('state', state), fact('runtime', runtime), fact('bind', service.bind || 'local only'));
    const actions = el('div', 'server-workbench-actions');
    const verbs = [];
    if (!service.installed && service.support_verified) verbs.push('install');
    if (service.installed && service.owned) {
      verbs.push(service.running ? 'stop' : 'start', 'restart', 'test', 'update', 'rollback');
    }
    for (const verb of verbs) {
      const run = async () => {
        message.textContent = `${verb} in progress…`;
        const result = await json(request, `/api/system/searxng/${verb}`, { method: 'POST' });
        if (verb === 'test') message.textContent = `json search passed · ${result.results ?? 0} results`;
        else await rerender();
      };
      actions.append(['stop', 'restart', 'update', 'rollback'].includes(verb)
        ? serviceAction('SearXNG', verb, run)
        : action(verb === 'test' ? 'test json search' : verb, run));
    }
    search.append(actions);
  }

  const host = card('allowlisted host services', 'This is intentionally empty in the default owned-only policy. Edit the access policy before any host service can appear.');
  if (hostResult.status === 'rejected') host.append(statusLine(hostResult.reason.message, 'error'));
  else {
    const payload = hostResult.value;
    host.append(fact('policy', payload.policy_valid ? payload.control_mode : 'invalid · control disabled'));
    for (const service of payload.services || []) {
      const row = el('div', 'server-workbench-service');
      const copy = el('div');
      copy.append(el('strong', '', service.id), el('span', '', service.manager));
      const actions = el('div', 'server-workbench-actions');
      for (const verb of ['start', 'stop', 'restart']) {
        actions.append(serviceAction(service.id, verb, async () => {
          message.textContent = `${verb} in progress…`;
          await json(request, `/api/system/host-services/${service.manager}/${encodeURIComponent(service.id)}/${verb}`, { method: 'POST' });
          message.textContent = `${service.id} · ${verb} complete`;
        }));
      }
      row.append(copy, actions);
      host.append(row);
    }
    if (!(payload.services || []).length) host.append(el('p', 'server-workbench-empty', 'no host services are allowlisted'));
  }
  target.replaceChildren(heading, search, host);
  const actual = card('actual budget service', 'Actual is the canonical Finance service when its ledger cutover is active. Service lifecycle actions keep the existing Finance authority guard.');
  if (actualResult.status === 'rejected') actual.append(statusLine(actualResult.reason.message, 'error'));
  else {
    const payload = actualResult.value;
    const service = payload.service || {};
    actual.append(
      fact('service', !service.available ? 'runtime unavailable' : !service.installed ? 'not installed' : service.healthy ? 'healthy' : service.running ? 'unhealthy' : 'stopped'),
      fact('ledger', payload.ledger?.mode || 'Alles'),
      fact('ownership', service.owned === false ? 'unverified' : 'Alles-managed'),
    );
    const actions = el('div', 'server-workbench-actions');
    const verbs = [];
    if (service.available && !service.installed) verbs.push('install');
    if (service.available && service.installed) verbs.push(service.running ? 'stop' : 'start', 'restart', 'update', 'rollback', 'backup');
    for (const verb of verbs) {
      actions.append(serviceAction('Actual Budget', verb, async () => {
        message.textContent = `Actual ${verb} in progress…`;
        await json(request, `/api/finance/actual/service/${verb}`, { method: 'POST' });
        await rerender();
      }));
    }
    actual.append(actions);
  }
  target.append(actual);
  const companions = card('network companions', 'AdGuard Home and Nginx Proxy Manager stay separate from Alles. Preparing downloads pinned images only; activation is a second, verified network step.');
  if (companionsResult.status === 'rejected') companions.append(statusLine(companionsResult.reason.message, 'error'));
  else {
    const rows = companionsResult.value.companions || [];
    if (!rows.length) companions.append(el('p', 'server-workbench-empty', 'no managed companions are available'));
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
  const [settingsResult, endpointsResult, rolesResult] = await Promise.allSettled([
    json(request, '/api/settings'),
    json(request, '/api/models'),
    json(request, '/api/models/roles'),
  ]);
  if (settingsResult.status === 'rejected') throw settingsResult.reason;
  let settings = settingsResult.value;
  const panel = card('andromeda search and models', 'Compact cited answers use the answer model. Freshness checking is a separate, optional background model with its own cost limits.');
  const message = statusLine();
  panel.append(message);
  const save = async patch => {
    message.classList.remove('is-error');
    message.textContent = 'saving…';
    try {
      settings = await patchSettings(request, patch);
      message.textContent = 'saved';
      return settings;
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('is-error');
      throw error;
    }
  };
  const providerOptions = [
    ['duckduckgo', 'duckduckgo'], ['searxng', 'searxng'], ['brave', 'brave'],
    ['tavily', 'tavily'], ['google_pse', 'google pse'], ['serper', 'serper'], ['disabled', 'disabled'],
  ].map(([value, label]) => ({ value, label }));
  panel.append(
    choice('primary search provider', providerOptions, settings.search_provider || 'duckduckgo', value => save({ search_provider: value })),
    choice('results per search', [5, 8, 10, 12].map(value => ({ value: String(value), label: String(value) })), String(settings.search_result_count || 8), value => save({ search_result_count: Number(value) })),
    switchButton('background fact check', settings.andromeda_verification_enabled !== false, value => save({ andromeda_verification_enabled: value })),
    choice('fact-check schedule', [
      { value: 'freshness-sensitive', label: 'current-date questions' },
      { value: 'always', label: 'every answer' },
      { value: 'manual', label: 'manual only' },
      { value: 'off', label: 'off' },
    ], settings.andromeda_verifier_mode || 'freshness-sensitive', value => save({ andromeda_verifier_mode: value })),
  );

  const limits = el('div', 'server-workbench-grid');
  for (const spec of [
    ['answer tokens', 'andromeda_answer_max_tokens', 100, 2000],
    ['answer seconds', 'andromeda_answer_timeout_seconds', 5, 120],
    ['verifier tokens', 'andromeda_verifier_max_tokens', 100, 2000],
    ['verifier seconds', 'andromeda_verifier_timeout_seconds', 5, 120],
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

  const credentials = card('search credentials', 'Secrets are never read back. A configured field only shows its status; entering a value replaces it.');
  const credentialSpecs = [
    ['tavily api key', 'tavily_api_key', 'tavily_api_key_configured', 'password'],
    ['brave api key', 'brave_api_key', 'brave_api_key_configured', 'password'],
    ['google pse api key', 'google_pse_api_key', 'google_pse_api_key_configured', 'password'],
    ['google pse cx', 'google_pse_cx', '', 'text'],
    ['serper api key', 'serper_api_key', 'serper_api_key_configured', 'password'],
    ['external searxng https url', 'searxng_url', '', 'url'],
  ];
  for (const [label, key, configuredKey, type] of credentialSpecs) {
    const field = el('label', 'server-workbench-field');
    field.append(el('span', '', label));
    const input = el('input');
    input.type = type;
    input.autocomplete = type === 'password' ? 'new-password' : 'off';
    input.placeholder = configuredKey && settings[configuredKey] ? 'configured · enter a replacement' : 'not configured';
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

  const models = card('answer and verifier roles', 'Choose independently. The verifier should be fast and cheap; it only checks claims against fresh cited evidence.');
  if (endpointsResult.status === 'rejected' || rolesResult.status === 'rejected') {
    models.append(statusLine('model choices are unavailable; existing role settings were not changed', 'error'));
  } else {
    const choices = modelOptions(endpointsResult.value);
    const roles = rolesResult.value;
    if (!choices.length) models.append(el('p', 'server-workbench-empty', 'no enabled chat models are available; add an endpoint in model settings first'));
    for (const role of ['andromeda_answer', 'andromeda_verifier']) {
      const configured = roles[role]?.configured || {};
      const configuredValue = configured.endpoint_id && configured.model ? `${configured.endpoint_id}\u0000${configured.model}` : '';
      const selected = choices.some(item => item.value === configuredValue) ? configuredValue : '';
      const options = [{ value: '', label: 'automatic' }, ...choices];
      models.append(choice(role === 'andromeda_answer' ? 'answer model' : 'verifier model', options, selected, async value => {
        const nextRoles = { ...(settings.model_roles || {}) };
        if (!value) nextRoles[role] = {};
        else {
          const picked = choices.find(item => item.value === value);
          nextRoles[role] = { endpoint_id: picked.endpointId, model: picked.model };
        }
        await save({ model_roles: nextRoles });
      }));
      models.append(fact(`${role === 'andromeda_answer' ? 'answer' : 'verifier'} status`, roles[role]?.status || 'unavailable'));
    }
  }
  target.replaceChildren(panel, models, credentials);
}

async function renderBackups(target, request) {
  const [settingsResult, locationsResult, webdavResult, s3Result] = await Promise.allSettled([
    json(request, '/api/settings'),
    json(request, '/api/storage-locations'),
    json(request, '/api/backup/webdav'),
    json(request, '/api/backup/s3'),
  ]);
  const intro = card('backups and storage', 'Backup destinations are reported independently. A failed destination never makes another one look healthy.');
  const message = statusLine();
  intro.append(message);
  const local = card('automatic local backup', 'The background scheduler checks this encrypted destination hourly and writes at most once every 24 hours.');
  if (settingsResult.status === 'rejected') local.append(statusLine(settingsResult.reason.message, 'error'));
  else {
    const settings = settingsResult.value;
    local.append(
      fact('enabled', settings.automatic_backup_enabled ? 'yes' : 'no'),
      fact('destination', settings.automatic_backup_dir || 'not configured'),
      fact('last success', settings.automatic_backup_last_success || 'never'),
    );
    if (settings.automatic_backup_last_error) local.append(statusLine(settings.automatic_backup_last_error, 'error'));
  }
  const storage = card('storage locations', 'Files storage registrations remain read-only here; coordinates and credentials keep their existing typed setup boundary.');
  if (locationsResult.status === 'rejected') storage.append(statusLine(locationsResult.reason.message, 'error'));
  else {
    const locations = locationsResult.value.locations || [];
    if (!locations.length) storage.append(el('p', 'server-workbench-empty', 'no storage locations'));
    for (const location of locations) storage.append(fact(location.name || 'location', `${location.kind} · ${location.enabled ? 'enabled' : 'disabled'} · ${location.access}`));
  }
  const appendDestination = (title, type, result) => {
    const section = card(title);
    if (result.status === 'rejected') {
      section.append(statusLine(result.reason.message, 'error'));
      return section;
    }
    const value = result.value;
    section.append(
      fact('configured', value.configured ? 'yes' : 'no'),
      fact('last backup', value.last_backup_at || 'never'),
      fact('last verified', value.last_verified_at || 'never'),
    );
    if (value.error) section.append(statusLine(value.error, 'error'));
    const button = action('run encrypted backup', async () => {
      message.textContent = `${title} backup running…`;
      const saved = await json(request, `/api/backup/${type}/run`, { method: 'POST' });
      message.textContent = `${title} backup complete · ${saved.filename}`;
      await renderBackups(target, request);
    });
    button.disabled = !value.configured;
    section.append(button);
    return section;
  };
  target.replaceChildren(intro, local, storage, appendDestination('webdav', 'webdav', webdavResult), appendDestination('s3-compatible storage', 's3', s3Result));
}

async function renderUpdates(target, request) {
  const section = card('release and update status', 'This page reports the running build. Installing an update remains a native supervisor or CLI action because this browser process cannot safely replace itself.');
  try {
    const build = await json(request, '/api/system/build');
    section.append(
      fact('version', build.version),
      fact('build', build.build_id),
      fact('database migration head', build.migration_head),
      fact('update action', 'use the native Alles updater or `python cli.py update`'),
    );
  } catch (error) {
    section.append(statusLine(error.message, 'error'));
  }
  target.replaceChildren(section);
}

function logEntry(entry) {
  const row = el('div', 'server-workbench-log');
  const when = entry.created_at || entry.timestamp || entry.time || '';
  const actionName = entry.action || entry.level || entry.event || 'entry';
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
      if (!entries.length) section.append(el('p', 'server-workbench-empty', 'no entries'));
      entries.forEach(entry => section.append(logEntry(entry)));
    }
    return section;
  };
  target.replaceChildren(append('runtime logs', logsResult), append('owner audit trail', auditResult));
}

async function renderPolicy(target, request) {
  const section = card('server access policy', 'The default is owned-only. The file accepts only a control mode and exact launchd or systemd service IDs. Commands, arguments, paths, and globs are rejected.');
  const message = statusLine();
  section.append(message);
  let current;
  try { current = await json(request, '/api/system/policy'); }
  catch (error) {
    section.append(statusLine(error.message, 'error'));
    target.replaceChildren(section);
    return;
  }
  section.append(fact('file', current.path), fact('effective state', current.valid ? current.policy.control_mode : `fail closed · ${current.error_code}`), fact('local device', current.local_device ? 'yes' : 'no'));
  if (!current.valid) section.append(statusLine(`${current.error}. Nothing outside Alles can be controlled until a valid owner-only file is saved.`, 'error'));
  const label = el('label', 'server-workbench-field');
  label.append(el('span', '', 'policy json'));
  const editor = el('textarea');
  editor.rows = 12;
  editor.spellcheck = false;
  editor.value = current.canonical;
  label.append(editor);
  section.append(label);
  const diff = el('pre', 'server-workbench-diff', 'no proposed changes');
  const confirmation = el('label', 'server-workbench-field');
  confirmation.hidden = true;
  confirmation.append(el('span', '', `type “${current.confirmation_phrase}” to allow host services`));
  const confirmInput = el('input');
  confirmInput.type = 'text';
  confirmInput.autocomplete = 'off';
  confirmation.append(confirmInput);
  const actions = el('div', 'server-workbench-actions');
  const inspect = async () => {
    const result = await json(request, '/api/system/policy/diff', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ policy: editor.value }),
    });
    diff.textContent = result.diff.length ? result.diff.join('\n') : 'no proposed changes';
    confirmation.hidden = result.policy.control_mode !== 'allowlisted_host';
    message.textContent = 'policy is valid';
    return result;
  };
  actions.append(
    action('validate and show diff', async () => {
      try { await inspect(); } catch (error) { message.textContent = error.message; message.classList.add('is-error'); }
    }),
    action('save policy', async () => {
      try {
        const candidate = await inspect();
        const saved = await json(request, '/api/system/policy', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ policy: editor.value, confirmation: candidate.policy.control_mode === 'allowlisted_host' ? confirmInput.value : '' }),
        });
        editor.value = saved.canonical;
        message.textContent = 'saved and verified with owner-only permissions';
        confirmation.hidden = saved.policy.control_mode !== 'allowlisted_host';
      } catch (error) {
        message.textContent = error.message;
        message.classList.add('is-error');
      }
    }, 'is-primary'),
  );
  section.append(actions, confirmation, diff);
  target.replaceChildren(section);
}

export async function renderServerSection(target, request = fetch, section = 'services') {
  target.replaceChildren(el('p', 'server-workbench-empty', 'loading current server state…'));
  try {
    if (section === 'services') return await renderServices(target, request);
    if (section === 'search') return await renderSearch(target, request);
    if (section === 'backups') return await renderBackups(target, request);
    if (section === 'updates') return await renderUpdates(target, request);
    if (section === 'logs') return await renderLogs(target, request);
    if (section === 'policy') return await renderPolicy(target, request);
    target.replaceChildren(statusLine('this server section is unavailable', 'error'));
  } catch (error) {
    target.replaceChildren(statusLine(error.message || 'server state could not be loaded', 'error'));
  }
}
