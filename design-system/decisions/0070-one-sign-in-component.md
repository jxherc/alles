# one sign in component

## context

owner, oct 29: "if its asking for connections i really want to make sure oauth its the option if
possible". gmail had a button, outlook, github and google calendar had forms or tokens, and each
connection screen drew its own version of the wait, the error and the fallback.

## decision

- one component, `static/js/signin.js` (`mountSignin(host, {use, provider, fallback})`), speaks the
  `/api/signin` contract and draws everything a sign in needs. a screen places it and draws nothing
  of its own around it.
- the button comes first ("sign in with github"). it is the one primary on the block.
- the device step shows the code large (monospace, tabular figures), then copy, open the provider's
  page and cancel on one row, then one live line with the time left. no progress bar, no ring.
- a redirect sign in opens the provider in a new tab and waits here; a provider that shows a code
  gets a paste field. every step has cancel.
- a finished step clears after six seconds and has a close mark; a failed step stays, in words (the
  provider's own message), with "try again".
- signed in accounts are plain rows: a check mark, who, and quiet text actions (check, sign out, and
  "sign in again" when the account needs it). sign out takes effect at once, and says when the
  provider can't revoke from here.
- the fallback ("use an app password instead") is a quiet text action with its one line reason inside
  it, so the reason can't be separated from the action. only a provider with no sign in shows no
  button, and a catalog row says why (`static/js/connection_catalog.js`).
- a provider that isn't set up yet shows the button disabled with the server's reason under it.
- state is carried by wording and tone, never color alone; every action keeps a 44px target; text is
  role 13 or more.

## checks

every state at four sizes in both themes on `static/signin-test.html` (served only with
`ALLES_TEST_DATA=1`, against `static/js/signin_fake.js`), measured by `tests/pw_signin_states.py`.
