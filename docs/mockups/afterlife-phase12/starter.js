(() => {
  const root = document.documentElement;
  const body = document.body;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const focusSoon = (element) => {
    if (!element) return;
    if (reduceMotion) element.focus();
    else window.requestAnimationFrame(() => element.focus());
  };

  const announce = (message) => {
    const live = document.querySelector('[data-live]');
    if (live) live.textContent = message;
    const feedback = document.querySelector('[data-demo-feedback]');
    if (feedback) feedback.textContent = message;
  };

  document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
      const light = root.dataset.theme !== 'light';
      root.dataset.theme = light ? 'light' : 'dark';
      button.setAttribute('aria-pressed', String(light));
      announce(`${light ? 'light' : 'dark'} theme preview`);
    });
  });

  const stateButtons = [...document.querySelectorAll('[data-demo-state]')];
  const setDemoState = (state) => {
    body.dataset.state = state;
    stateButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.demoState === state));
    });
    document.querySelectorAll('[data-state-only]').forEach((region) => {
      region.hidden = region.dataset.stateOnly !== state;
    });
    document.querySelectorAll('[data-normal-content]').forEach((region) => {
      region.hidden = state !== 'ready';
    });
    announce(`${state} state preview`);
  };
  stateButtons.forEach((button) => button.addEventListener('click', () => setDemoState(button.dataset.demoState)));

  const choiceGroups = [...document.querySelectorAll('[role="radiogroup"]')];
  choiceGroups.forEach((group) => {
    const choices = [...group.querySelectorAll('[role="radio"]')];
    const choose = (choice, moveFocus = false) => {
      choices.forEach((item) => {
        const selected = item === choice;
        item.setAttribute('aria-checked', String(selected));
        item.tabIndex = selected ? 0 : -1;
      });
      group.dispatchEvent(new CustomEvent('choicechange', { bubbles: true, detail: { value: choice.dataset.value } }));
      if (moveFocus) choice.focus();
    };
    choices.forEach((choice) => {
      choice.addEventListener('click', () => choose(choice));
      choice.addEventListener('keydown', (event) => {
        const current = choices.indexOf(choice);
        let next = null;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (current + 1) % choices.length;
        if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (current - 1 + choices.length) % choices.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = choices.length - 1;
        if (next === null) return;
        event.preventDefault();
        choose(choices[next], true);
      });
    });
  });

  document.querySelectorAll('[role="switch"]').forEach((button) => {
    button.addEventListener('click', () => {
      const next = button.getAttribute('aria-checked') !== 'true';
      button.setAttribute('aria-checked', String(next));
      const target = button.dataset.controlsDisabled && document.getElementById(button.dataset.controlsDisabled);
      if (target) {
        target.toggleAttribute('aria-disabled', !next);
        target.querySelectorAll('button, input, textarea').forEach((control) => { control.disabled = !next; });
      }
      announce(`${button.dataset.label || 'setting'} ${next ? 'on' : 'off'}`);
    });
  });

  const tabLists = [...document.querySelectorAll('[role="tablist"]')];
  tabLists.forEach((tabList) => {
    const tabs = [...tabList.querySelectorAll('[role="tab"]')];
    const selectTab = (tab, moveFocus = false) => {
      tabs.forEach((item) => {
        const selected = item === tab;
        item.setAttribute('aria-selected', String(selected));
        item.tabIndex = selected ? 0 : -1;
        const panel = item.getAttribute('aria-controls') && document.getElementById(item.getAttribute('aria-controls'));
        if (panel) panel.hidden = !selected;
      });
      if (moveFocus) tab.focus();
      announce(`${tab.textContent.trim()} view`);
    };
    tabs.forEach((tab) => {
      tab.addEventListener('click', () => selectTab(tab));
      tab.addEventListener('keydown', (event) => {
        const current = tabs.indexOf(tab);
        let next = null;
        if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
        if (event.key === 'ArrowLeft') next = (current - 1 + tabs.length) % tabs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = tabs.length - 1;
        if (next === null) return;
        event.preventDefault();
        selectTab(tabs[next], true);
      });
    });
  });

  const directory = document.querySelector('[data-directory]');
  const workbenches = [...document.querySelectorAll('[data-workbench]')];
  if (directory && workbenches.length) {
    const showDirectory = (push = true) => {
      directory.hidden = false;
      workbenches.forEach((view) => { view.hidden = true; });
      if (push) history.pushState({ view: 'directory' }, '', '#apps');
      focusSoon(directory.querySelector('main'));
    };
    const openWorkbench = (name, push = true, pane = 'main') => {
      const view = workbenches.find((item) => item.dataset.workbench === name);
      if (!view) return showDirectory(push);
      directory.hidden = true;
      workbenches.forEach((item) => { item.hidden = item !== view; });
      const bodyRegion = view.querySelector('.workbench-body');
      if (bodyRegion) bodyRegion.dataset.mobilePane = pane;
      if (push) history.pushState({ view: name }, '', `#${name}`);
      focusSoon(view.querySelector('main'));
      announce(`${name} workbench opened`);
    };
    document.querySelectorAll('[data-open-app]').forEach((button) => {
      button.addEventListener('click', () => openWorkbench(button.dataset.openApp));
    });
    document.querySelectorAll('[data-open-directory]').forEach((button) => {
      button.addEventListener('click', () => showDirectory());
    });
    document.querySelectorAll('button[data-mobile-pane]').forEach((button) => {
      button.addEventListener('click', () => {
        const workbench = button.closest('[data-workbench]');
        const region = workbench?.querySelector('.workbench-body');
        if (!region || !workbench) return;
        region.dataset.mobilePane = button.dataset.mobilePane;
        history.pushState(
          { view: workbench.dataset.workbench, pane: button.dataset.mobilePane },
          '',
          `#${workbench.dataset.workbench}/${button.dataset.mobilePane}`
        );
        const target = region.querySelector(button.dataset.mobilePane === 'nav' ? '.local-panel' : button.dataset.mobilePane === 'detail' ? '.detail-pane' : '.main-pane');
        focusSoon(target);
      });
    });
    window.addEventListener('popstate', () => {
      const [name, pane = 'main'] = location.hash.replace('#', '').split('/');
      if (!name || name === 'apps') showDirectory(false);
      else openWorkbench(name, false, pane);
    });
    const [initial, initialPane = 'main'] = location.hash.replace('#', '').split('/');
    if (initial && initial !== 'apps') openWorkbench(initial, false, initialPane);
    else history.replaceState({ view: 'directory' }, '', '#apps');
  }

  document.querySelectorAll('[data-row-select]').forEach((row) => {
    row.addEventListener('click', () => {
      const scope = row.closest('[data-select-scope]') || row.parentElement;
      scope.querySelectorAll('[data-row-select]').forEach((item) => item.setAttribute('aria-selected', String(item === row)));
      const title = row.querySelector('.row-title')?.textContent.trim() || row.textContent.trim();
      const detail = row.closest('[data-workbench]')?.querySelector('[data-detail-title]');
      if (detail) detail.textContent = title;
      announce(`${title} selected`);
    });
  });

  const andromedaIdle = document.querySelector('[data-andromeda-idle]');
  const andromedaResults = document.querySelector('[data-andromeda-results]');
  const searchShell = document.querySelector('.search-shell');
  const andromedaForms = [...document.querySelectorAll('[data-andromeda-form]')];
  if (andromedaIdle && andromedaResults) {
    const setSearchView = (view) => {
      searchShell.dataset.searchView = view;
      const results = view === 'results';
      andromedaIdle.hidden = results;
      andromedaResults.hidden = !results;
    };
    const showResults = (query) => {
      const normalized = query.trim() || 'latest SQLite release';
      document.querySelectorAll('[data-query-input]').forEach((input) => { input.value = normalized; });
      setSearchView('results');
      history.pushState({ andromeda: 'results' }, '', '#results');
      focusSoon(andromedaResults);
      announce('Results ready. Background verification started.');
    };
    andromedaForms.forEach((form) => {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        showResults(form.querySelector('[data-query-input]')?.value || '');
      });
    });
    document.querySelectorAll('[data-search-home]').forEach((button) => button.addEventListener('click', () => {
      setSearchView('idle');
      history.pushState({ andromeda: 'idle' }, '', '#idle');
      focusSoon(andromedaIdle.querySelector('input'));
    }));
    window.addEventListener('popstate', () => {
      setSearchView(location.hash === '#results' ? 'results' : 'idle');
    });
    if (location.hash === '#results') {
      setSearchView('results');
    } else {
      setSearchView('idle');
      history.replaceState({ andromeda: 'idle' }, '', '#idle');
    }
  }

  const verificationStates = {
    checking: {
      label: 'checking current claims',
      verdict: 'checking',
      copy: 'SQLite 3.50.4 is the latest stable release in the supplied release evidence. The project published it on 2026-07-18, with fixes for query planning and the CLI.[1][2]'
    },
    verified: {
      label: 'checked today · 3 claims verified',
      verdict: 'verified',
      copy: 'SQLite 3.50.4 is the latest stable release in the supplied release evidence. The project published it on 2026-07-18, with fixes for query planning and the CLI.[1][2]'
    },
    corrected: {
      label: 'corrected after verification · checked today',
      verdict: 'corrected',
      copy: 'SQLite 3.50.4 is the latest stable release in the supplied release evidence. It was published on 2026-07-18, not July 17 as the first answer stated.[1][2]'
    },
    failed: {
      label: 'not independently checked',
      verdict: 'failed',
      copy: 'SQLite 3.50.4 is the latest stable release in the supplied release evidence. The project published it on 2026-07-18, with fixes for query planning and the CLI.[1][2]'
    }
  };
  const renderAnswerFocus = (target, copy, focus = '3.50.4') => {
    if (!target) return;
    const start = copy.indexOf(focus);
    target.replaceChildren();
    if (start < 0) {
      target.textContent = copy;
      return;
    }
    const marker = document.createElement('mark');
    marker.className = 'answer-highlight';
    marker.textContent = copy.slice(start, start + focus.length);
    target.append(document.createTextNode(copy.slice(0, start)), marker, document.createTextNode(copy.slice(start + focus.length)));
  };
  document.querySelectorAll('[data-verification]').forEach((button) => {
    button.addEventListener('click', () => {
      const state = verificationStates[button.dataset.verification];
      if (!state) return;
      const label = document.querySelector('[data-verification-state]');
      const copy = document.querySelector('[data-answer-copy]');
      if (label) {
        label.textContent = state.label;
        label.dataset.verdict = state.verdict;
      }
      const answerText = copy?.querySelector('[data-answer-text]');
      renderAnswerFocus(answerText, state.copy.replace('[1][2]', ''));
      document.querySelectorAll('[data-verification-only]').forEach((region) => {
        region.hidden = region.dataset.verificationOnly !== state.verdict;
      });
      announce(state.label);
    });
  });

  const serverPages = [...document.querySelectorAll('[data-server-page]')];
  if (serverPages.length) {
    const serverBody = document.querySelector('.server-body');
    const openServerPage = (name, push = true, pane = 'main') => {
      const page = serverPages.find((item) => item.dataset.serverPage === name) || serverPages[0];
      serverPages.forEach((item) => { item.hidden = item !== page; });
      document.querySelectorAll('[data-open-server-page]').forEach((button) => {
        button.setAttribute('aria-current', button.dataset.openServerPage === page.dataset.serverPage ? 'page' : 'false');
      });
      if (serverBody) serverBody.dataset.mobilePane = pane;
      const context = document.querySelector('[data-server-context]');
      if (context) context.textContent = page.dataset.serverPage.replaceAll('-', ' ');
      if (push) history.pushState({ server: page.dataset.serverPage }, '', `#${page.dataset.serverPage}`);
      focusSoon(page);
      announce(`${page.dataset.serverPage.replaceAll('-', ' ')} opened`);
    };
    document.querySelectorAll('[data-open-server-page]').forEach((button) => {
      button.addEventListener('click', () => openServerPage(button.dataset.openServerPage));
    });
    document.querySelectorAll('[data-server-nav]').forEach((button) => {
      button.addEventListener('click', () => {
        if (serverBody) serverBody.dataset.mobilePane = 'nav';
        const current = serverPages.find((page) => !page.hidden)?.dataset.serverPage || 'overview';
        history.pushState({ server: current, pane: 'nav' }, '', `#${current}/nav`);
        focusSoon(serverBody?.querySelector('.local-panel'));
      });
    });
    window.addEventListener('popstate', () => {
      const [name = 'overview', pane = 'main'] = location.hash.replace('#', '').split('/');
      openServerPage(name || 'overview', false, pane);
    });
    const [initialServerPage = 'overview', initialServerPane = 'main'] = location.hash.replace('#', '').split('/');
    openServerPage(initialServerPage || 'overview', false, initialServerPane);
  }

  const policyEditor = document.querySelector('[data-policy-editor]');
  const policyStatus = document.querySelector('[data-policy-status]');
  const policyDialog = document.querySelector('[data-policy-dialog]');
  const policyTrigger = document.querySelector('[data-save-policy]');
  let dialogTrigger = null;

  document.querySelector('[data-policy-mode]')?.addEventListener('choicechange', (event) => {
    if (!policyEditor) return;
    const allowHost = event.detail.value === 'allowlisted_host';
    policyEditor.value = allowHost
      ? '{\n  "control_mode": "allowlisted_host",\n  "host_services": [\n    { "manager": "launchd", "id": "com.example.indexer" }\n  ]\n}'
      : '{\n  "control_mode": "owned_only",\n  "host_services": []\n}';
    if (policyStatus) {
      policyStatus.textContent = 'unsaved changes';
      policyStatus.style.color = 'var(--permission)';
    }
  });

  const parsePolicy = () => {
    if (!policyEditor) return null;
    try {
      const value = JSON.parse(policyEditor.value);
      const keys = Object.keys(value);
      if (keys.some((key) => !['control_mode', 'host_services'].includes(key))) throw new Error('Unknown fields are not allowed.');
      if (!['owned_only', 'allowlisted_host'].includes(value.control_mode)) throw new Error('Choose owned_only or allowlisted_host.');
      if (!Array.isArray(value.host_services)) throw new Error('host_services must be a list.');
      if (value.host_services.some((service) => !service || !['launchd', 'systemd'].includes(service.manager) || !/^[A-Za-z0-9_.@:-]+$/.test(service.id || ''))) {
        throw new Error('Every service needs an exact manager and identifier.');
      }
      return value;
    } catch (error) {
      if (policyStatus) {
        policyStatus.textContent = error.message;
        policyStatus.style.color = 'var(--danger)';
      }
      return null;
    }
  };

  document.querySelector('[data-validate-policy]')?.addEventListener('click', () => {
    const value = parsePolicy();
    if (!value || !policyStatus) return;
    policyStatus.textContent = `${value.host_services.length} exact host service${value.host_services.length === 1 ? '' : 's'} · valid locally`;
    policyStatus.style.color = 'var(--success)';
    announce('Policy is valid locally');
  });

  const closeDialog = () => {
    if (!policyDialog) return;
    policyDialog.hidden = true;
    dialogTrigger?.focus();
  };
  policyTrigger?.addEventListener('click', () => {
    const value = parsePolicy();
    if (!value) return;
    if (value.control_mode === 'allowlisted_host') {
      dialogTrigger = policyTrigger;
      policyDialog.hidden = false;
      focusSoon(policyDialog.querySelector('input'));
    } else if (policyStatus) {
      policyStatus.textContent = 'owned-only policy saved';
      policyStatus.style.color = 'var(--success)';
      announce('Owned-only policy saved');
    }
  });
  document.querySelectorAll('[data-close-dialog]').forEach((button) => button.addEventListener('click', closeDialog));
  policyDialog?.addEventListener('click', (event) => { if (event.target === policyDialog) closeDialog(); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && policyDialog && !policyDialog.hidden) {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (event.key === 'Tab' && policyDialog && !policyDialog.hidden) {
      const controls = [...policyDialog.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href]')];
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  document.querySelector('[data-confirm-policy]')?.addEventListener('click', () => {
    const field = document.querySelector('[data-confirm-field]');
    if (field?.value !== 'allow host services') {
      field?.setAttribute('aria-invalid', 'true');
      const error = document.querySelector('[data-confirm-error]');
      if (error) error.hidden = false;
      return;
    }
    closeDialog();
    if (policyStatus) {
      policyStatus.textContent = 'allowlisted-host policy saved · audit recorded';
      policyStatus.style.color = 'var(--success)';
    }
    announce('Allowlisted-host policy saved and audit recorded');
  });

  const initialState = stateButtons.find((button) => button.getAttribute('aria-pressed') === 'true')?.dataset.demoState;
  if (initialState) setDemoState(initialState);

  document.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.matches('[data-theme-toggle], [data-demo-state], [data-verification], [data-open-app], [data-open-server-page], [data-server-nav], [data-search-home], [data-validate-policy], [data-save-policy], [data-confirm-policy], [data-close-dialog], [role="switch"], [role="radio"]')) return;
      const concise = button.querySelector('.app-entry-name, .row-title')?.textContent.trim();
      const label = button.getAttribute('aria-label') || concise || button.textContent.trim();
      if (label) announce(`${label} preview`);
    });
  });
})();
