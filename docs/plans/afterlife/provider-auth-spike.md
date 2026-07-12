# provider authentication spike

- **checked:** 2026-07-12
- **scope:** model-provider access for a self-hosted, single-user Alles server
- **decision:** keep API keys and local/custom endpoints; do not expose provider sign-in buttons yet

## short answer

Alles must not pretend that a consumer chat subscription is an API login.

| provider | official API access found | decision for Alles |
|---|---|---|
| OpenAI | API key or short-lived workload-identity token | keep API keys; no **Sign in with OpenAI** button |
| Claude | API key or short-lived workload-identity token | keep API keys; no **Sign in with Claude** button |
| Google Gemini API | API key or OAuth tied to the owner's Google Cloud project | keep API keys now; OAuth is a later, named Google Cloud connection |
| local/custom | provider-specific key, local trust, or no authentication | keep the current endpoint form |

Workload identity is meant for managed infrastructure. It is not consumer account OAuth and does not
turn a ChatGPT or Claude subscription into API quota.

## evidence

### OpenAI

The current OpenAI API reference accepts bearer credentials from an API key or a short-lived token
created through workload identity federation. It does not document a third-party consumer OAuth flow
for model API use.

- [OpenAI API authentication](https://developers.openai.com/api/reference/overview#authentication)
- [OpenAI API key safety](https://help.openai.com/en/articles/8304786-preventing-unauthorized-usage)

**Result:** Alles may accept an encrypted API key. A future enterprise-only workload-identity adapter
would be a separate feature. Alles must not reuse ChatGPT or Codex browser/session credentials.

### Claude

The current Claude API documentation accepts a Console API key or a short-lived workload-identity
token. Anthropic also states that paid Claude plans and Claude API billing are separate.

- [Claude API authentication](https://platform.claude.com/docs/en/api/overview#authentication)
- [Claude plan and API separation](https://support.claude.com/en/articles/9876003-i-have-a-paid-claude-subscription-pro-max-team-or-enterprise-plans-why-do-i-have-to-pay-separately-to-use-the-claude-api-and-console)

**Result:** Alles may accept an encrypted API key. A future enterprise-only workload-identity adapter
would be separate. Alles must not copy Claude Desktop or Claude Code session credentials.

### Google Gemini API

Google officially documents OAuth for the Gemini API. The owner must create or select a Google Cloud
project, enable the API, configure consent, create an OAuth client, and grant the required scopes. The
official quickstart warns that its simplified flow is for testing and requires a production credential
review.

- [Gemini API OAuth quickstart](https://ai.google.dev/gemini-api/docs/oauth)
- [Gemini API key guidance](https://ai.google.dev/gemini-api/docs/api-key)

**Result:** Google OAuth is technically possible, but the UI must call it **Connect Google Cloud for
Gemini**, not imply that a consumer Gemini subscription supplies API quota. It remains unshipped until
the production flow passes the proof below.

## required proof before any provider login ships

The implementation must pass all of these:

1. Use a provider-documented client type, authorization URL, token URL, and exact minimum scopes.
2. Use state, PKCE when supported, exact callback validation, and a short callback lifetime.
3. Encrypt access and refresh tokens through the existing connector keyring. Never put them in URLs,
   logs, browser storage, exports, or API responses.
4. Prove refresh, expiry, revocation or disconnect, account identity, and provider error handling.
5. Prove both model-catalog refresh and a real model request with the same credential type.
6. Show the provider, cloud project or account identity, granted scope, expiry, and connection state.
7. Show this warning before connect and before making it a default: **This can use your provider quota
   or credits faster than normal chat.**
8. Require recent owner authentication to connect, replace, export, or disconnect credentials.
9. Keep API-key and local/custom endpoint setup available.
10. Re-check official provider documentation and terms at implementation time.

## phase decision

Phase 1 adds no model-provider OAuth schema, routes, callbacks, dependencies, or buttons. That is the
safe outcome of this spike, not missing work. Google Cloud OAuth can return as a later implementation
slice after its production scopes and full refresh/revoke path are proven. OpenAI and Claude consumer
sign-in stay unavailable unless those providers publish a permitted third-party API flow.
