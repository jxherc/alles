// every connection alles can make, in one list, so a connections screen draws the same rows
// from the same facts (a catalog like hermes's platform list, hermes `hermes gateway setup`).
// `how` is how the owner gives access. oauth first (owner, oct 29): where the provider allows a
// sign in for a self hosted app, `how` is 'signin' and `provider` names a /api/signin provider;
// (mcp servers keep their own oauth under /api/mcp). every other `how` carries `why`, the one line a screen shows beside the quiet fallback.
// each row is checked against the provider's current docs in "oauth first" of the oct 28 plan.
//
// how: signin (button, /api/signin), device (alles' own device login), key (pasted api key),
//      token (a token the owner makes by hand), password (an app password), link (the provider's
//      own widget), bot (a bot token, by design)
export const CATALOG = [
  { id: 'gmail', name: 'gmail', group: 'mail', how: 'signin', provider: 'google', use: 'mail' },
  { id: 'outlook', name: 'outlook and hotmail', group: 'mail', how: 'signin', provider: 'microsoft', use: 'mail', fallback: 'password', why: 'outlook.com accounts can also use an app password.' },
  { id: 'icloud-mail', name: 'icloud mail', group: 'mail', how: 'password', why: "apple has no sign in for other mail apps, so icloud needs an app specific password." },
  { id: 'yahoo', name: 'yahoo mail', group: 'mail', how: 'password', why: "yahoo's sign in for mail apps needs a review alles can't pass, so yahoo needs an app password." },
  { id: 'fastmail', name: 'fastmail', group: 'mail', how: 'password', why: "fastmail's sign in is for its own protocol (jmap), and alles reads mail over imap, so fastmail needs an app password." },
  { id: 'google-calendar', name: 'google calendar', group: 'calendar', how: 'signin', provider: 'google', use: 'calendar' },
  { id: 'icloud-calendar', name: 'icloud calendar', group: 'calendar', how: 'password', why: 'apple has no sign in for other calendar apps, so icloud needs an app specific password.' },
  { id: 'gemini', name: 'gemini', group: 'models', how: 'signin', provider: 'google', use: 'models', fallback: 'key', why: 'an api key works too.' },
  { id: 'anthropic', name: 'claude', group: 'models', how: 'signin', provider: 'anthropic', use: 'models', fallback: 'key', why: 'an api key works too.' },
  { id: 'openai', name: 'chatgpt', group: 'models', how: 'signin', provider: 'openai', use: 'models', fallback: 'key', why: 'an api key works too.' },
  { id: 'github', name: 'github', group: 'code', how: 'signin', provider: 'github', use: 'github', fallback: 'token', why: 'a personal access token works too.' },
  { id: 'imessage', name: 'imessage', group: 'chat', how: 'device', why: 'photon signs in with a code, the same way a tv app does.' },
  { id: 'telegram', name: 'telegram', group: 'chat', how: 'bot', why: 'the telegram bot api has no sign in, botfather gives your bot a token.' },
  { id: 'discord', name: 'discord', group: 'chat', how: 'bot', why: 'a discord bot signs in with its bot token by design; only the invite link is a sign in.' },
  { id: 'plaid', name: 'plaid banks', group: 'finance', how: 'link', why: "plaid asks for your own keys once, and each bank's sign in runs inside plaid's window." },
  { id: 'simplefin', name: 'simplefin', group: 'finance', how: 'token', why: "simplefin's setup token is the whole protocol." },
  { id: 'mcp', name: 'mcp servers', group: 'tools', how: 'signin', provider: 'mcp', use: 'mcp', fallback: 'token', why: 'a server that has no sign in takes a token.' },
];

export const HOW = ['signin', 'device', 'key', 'token', 'password', 'link', 'bot'];
export const GROUPS = ['mail', 'calendar', 'models', 'code', 'chat', 'finance', 'tools'];

export const catalogByGroup = (rows = CATALOG) => GROUPS
  .map(group => ({ group, rows: rows.filter(row => row.group === group) }))
  .filter(entry => entry.rows.length);
