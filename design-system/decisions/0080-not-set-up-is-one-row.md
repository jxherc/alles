# something that is not set up is one row

## context

owner (vault, dont.md): "no panels of status rows and buttons for something that isn't set up",
"no buttons without a clear job", "every setting feels like its pieced together". webdav and s3
backup each showed "not connected / last successful backup: never / last verified: never / back up
now / refresh backups / remote backup / verify and stage" with nothing behind them, and the recovery
key chooser three times. connections and tools held about nine screens, and the shared sign in block
drew a disabled button with a line about why it could not work.

## decision

- a block for something that is not connected or not installed is one row: its name, one short state
  word ("not connected", "not installed") and one action that starts the setup (`.conn-catalog-row`).
  its status rows, lists, secondary buttons and version lines show only once it is set up.
- the action opens the setup form in place, under the row, and moves focus into it. nothing else on
  the page moves except what sits below the opened block. a saved form closes and focus returns to
  the row's action, which now reads "edit".
- applied to webdav and s3 backup (the recovery key chooser and "verify and stage" show once the
  remote has a backup to restore), the Actual ledger, ollama in local serving (not installed offers
  "get Ollama", stopped offers "start Ollama", the hardware line, models and pull field show once it
  runs) and macOS integration (one row with its state, its parts open on "show"). "rotate credential
  key" shows only while a credential is saved. empty lists are one quiet line with no heading.
- warnings that prevent a real mistake stay (save the recovery key apart, live data stays unchanged
  until the cli command runs, s3 copies are not atomic and at most 5 GB). lines that only describe go.
- the shared sign in block never draws a dead button (amends 0070). a provider the owner can set up
  (google with their own client) shows an active "set up google sign in" that opens that setup. a
  provider with no path on this install (a shipped client id that is not there, a plain http address)
  is not drawn. all sign in buttons are the shared quiet button, none purple. in models the older
  "connect Gemini with Google OAuth" button is that setup: the same row opens its form.
- connections and tools is three panes (amends 0057), in "accounts and connections": "connections"
  (keeps the pane id `tools`: the connection list, chat channels, sign in to a site, github and
  tokens), "agent" (the agent's switches, permission rules, mcp servers, the tool list behind one
  "29 tools" row) and "this machine" (macOS integration, docker, searxng, the Actual ledger). the
  agent counts are one line of facts, not a grid of chips.
- a section heading carries no icon, and a pane's first heading does not repeat the pane's title.

## checks

`scripts/settings_homes.py` gives every pane one home in all four layouts. rendered at ipad
landscape and phone, in the three panes: no state shows a row with nothing behind it, every action
is a 44px target and opening a row moves nothing above it.
