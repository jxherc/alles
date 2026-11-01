# one owner password prompt for every protected request

## context

a protected route answers `403 recent_auth_required` until the owner confirms the password. eight
screens each wrote their own copy of the prompt, and they disagreed: settings asked on any 403,
the vault and the call screen used their own wording, project pages and aide's goals and code used
different texts, and the strings were english only in two of them. nine senders never asked at
all. on oct 28 the aide chat showed the raw "recent owner authentication required" under every
message once full access had gone stale, and switching to full access never asked in the first
place.

## decision

- one module, `static/js/recent_owner.js`: `requestWithRecentOwner` (the request, the prompt, one
  resend), `fetchWithRecentOwner` (the same over `fetch`, a refusal comes back as the 403) and
  `openWithRecentOwner` (a download the browser opens itself: confirm, then open).
- the box is the shared password dialog with the shared strings (`settings.reauth_prompt`, or
  `aide.reauth_prompt` with a reason such as "use full access"), in every language.
- it asks only for the exact `recent_auth_required` code, once at a time, and a caller that left
  while the box was open (a hung up call) never sends the password or the request again.
- a cancelled confirmation is silent. a wrong password says so in a toast.
- full access asks when it is switched on, so the later send usually finds a fresh confirmation.
  a send that still finds it stale asks right there, and a cancel puts the message back in the box
  with a retry, in plain words.
- `tests/test_recent_owner_routes_scan.py` reads the protected routes from the app and fails when
  a screen reaches one without the shared prompt, or posts the password itself.

## kept

- the server rule: ten minutes of recent confirmation, bearer tokens never count.
- the vault's own unlock prompt, which is a different secret.
