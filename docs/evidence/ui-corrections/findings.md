# Mid-build corrections (user feedback on Stage 1 / 2 output)

Six corrections to already-shipped microversions, all verified:

1. **Real brand logos** (was: hand-drawn). Rebuilt `static/js/brandlogo.js` from the actual company SVG
   marks (simple-icons: anthropic, deepseek, gemini, mistral, ollama, perplexity, x/xai; lobehub: openai),
   rendered as filled silhouettes glowing in each brand's real colour (deepseek #4d6bfe, anthropic
   #d4a574, openai #10a37f, …). Providers without an official mark fall back to a neutral spark.
   Topbar now shows the real Anthropic mark before "opus 4.8".
2. **aide card restored** — I had wrongly removed the aide home *tile*; the user meant the quick-message
   **`aide ↗` button**. Tile back (grid = 15, clean 5×3); `#ha-goto` removed.
3. **Home = original but wider** — kept the original look/alignment, only widened for 5-per-row.
4. **Home order** — schedule → note/task capture → quick message → everything else (grid moved back below
   the quick-message bar).
5. **Breadcrumb app-name click** → goes to that app's home (its subdomain root) on a normal left-click,
   via the anchor's href; only the "alles" part is intercepted for the SSO hub jump. Verified: clicking
   "docs" on docs.localhost navigates to docs.localhost/.
6. **Schedule + capture share one box** (`.home-board`) with unified spacing (the two had mismatched
   margins before).

Cache stamp bumped v77→v78 / sw v51→v52 so loaded tabs pick the changes up.

## Follow-up: full logo overhaul (v79)
- **Moonshot showed the OpenAI logo** because OpenAI-compatible endpoints report `provider:"openai"`.
  Fixed: `providerKey()` now sniffs provider + endpoint name + base_url + model id, with SPECIFIC
  providers checked before the generic openai/gpt tokens. Verified: a Moonshot endpoint (provider
  "openai", url api.moonshot.cn) → the real Moonshot sphere mark; Groq → Groq; real OpenAI → OpenAI;
  OpenRouter serving `anthropic/claude` → Anthropic.
- **Every provider now has its real stored logo** (16: anthropic, openai, deepseek, gemini, mistral,
  ollama, perplexity, xai/grok, moonshot, groq, openrouter, together, fireworks, cohere, qwen, google) —
  embedded inline in `brandlogo.js` from simple-icons / lobehub, full multi-path silhouettes inheriting
  the brand colour. No more spark fallbacks for known providers; none are hand-drawn.
- Stamp re-bumped v78→v79 / sw v52→v53.


Verified: `tests.test_home` (16) green; `tests.test_brandlogo` (9) + `pw_models_2f.py` (9/9) green; all 15
hosts load with 0 console errors; home + topbar screenshots in this dir.
