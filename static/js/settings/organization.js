// settings organized around the owner's jobs (28.28, decision 0057). three working layouts, the
// owner flips between them in general › settings layout; "jobs" is the default. every pane in the
// nav has exactly one home in every layout (scripts/settings_homes.py proves it)
import { t } from '../i18n.js';

// the block between the markers is plain json so scripts/settings_homes.py can read it
/* organizations:start */
export const ORGANIZATIONS = {
  "jobs": [
    { "group": "settings.org_you", "panes": ["general", "themes", "home", "notifications"] },
    { "group": "settings.org_how_aide_answers", "panes": ["models", "personas", "voice", "ai"] },
    { "group": "settings.org_what_aide_knows", "panes": ["memory", "search", "recall", "andromeda"] },
    { "group": "settings.org_on_its_own", "panes": ["proactive", "rules", "intelligence"] },
    { "group": "settings.org_accounts", "panes": ["tools", "agent", "machine", "developer"] },
    { "group": "settings.org_safety", "panes": ["security", "backup", "@server", "credits"] }
  ],
  "often": [
    { "group": "settings.org_every_day", "panes": ["models", "themes", "voice", "home"] },
    { "group": "settings.org_now_and_then", "panes": ["personas", "ai", "memory", "search", "andromeda", "proactive", "rules"] },
    { "group": "settings.org_once", "panes": ["general", "notifications", "tools", "agent", "machine", "developer", "recall", "intelligence"] },
    { "group": "settings.org_rarely", "panes": ["security", "backup", "@server", "credits"] }
  ],
  "things": [
    { "group": "settings.org_this_device", "panes": ["general", "themes", "notifications", "voice"] },
    { "group": "settings.org_aide", "panes": ["models", "personas", "ai", "memory", "proactive", "intelligence", "recall"] },
    { "group": "settings.org_your_accounts", "panes": ["tools", "agent", "machine", "search", "developer", "rules"] },
    { "group": "common.apps", "panes": ["home", "andromeda"] },
    { "group": "settings.org_this_alles", "panes": ["security", "backup", "@server", "credits"] }
  ],
  "classic": [
    { "group": "shell.settings.you", "panes": ["general", "home", "themes", "notifications"] },
    { "group": "settings.org_aide", "panes": ["models", "ai", "memory", "personas", "voice", "search", "recall", "proactive", "intelligence"] },
    { "group": "common.apps", "panes": ["andromeda"] },
    { "group": "common.connections", "panes": ["tools", "agent", "machine", "developer", "rules"] },
    { "group": "shell.settings.this_alles", "panes": ["security", "backup", "@server", "credits"] }
  ]
};
/* organizations:end */

export const ORGANIZATION_LABELS = {
  jobs: 'settings.org_by_job',
  often: 'settings.org_by_often',
  things: 'settings.org_by_thing',
  classic: 'settings.org_classic',
};

const KEY = 'alles-settings-organization';

export function savedOrganization() {
  try {
    const id = localStorage.getItem(KEY);
    return ORGANIZATIONS[id] ? id : 'jobs';
  } catch {
    return 'jobs';
  }
}

export function saveOrganization(id) {
  try { localStorage.setItem(KEY, id); } catch { /* the layout still applies for this visit */ }
}

// moves the existing nav buttons (their listeners stay) under fresh group headings
export function applyOrganization(nav, id = savedOrganization()) {
  if (!nav) return;
  const layout = ORGANIZATIONS[id] || ORGANIZATIONS.jobs;
  const items = new Map([...nav.querySelectorAll('.s-nav-item')].map(item => [item.dataset.pane || `@${item.dataset.link}`, item]));
  nav.querySelectorAll('.s-nav-group').forEach(group => group.remove());
  for (const { group, panes } of layout) {
    const heading = document.createElement('div');
    heading.className = 's-nav-group';
    heading.dataset.i18n = group;
    heading.textContent = t(group);
    nav.append(heading);
    for (const pane of panes) {
      const item = items.get(pane);
      if (item) nav.append(item);
    }
  }
  nav.dataset.organization = ORGANIZATIONS[id] ? id : 'jobs';
}
