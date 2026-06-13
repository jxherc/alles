# alles

```
─────────────────────────────────────────────
 ⊹ ࣪ ˖ ( ◕ ‿ ◕ )つ  alles — your everything
─────────────────────────────────────────────
```

**alles** is a self-hosted everything-app. ai, mail, docs, files, calendar, tasks, photos, contacts, passwords, subscriptions, countdowns — one login, one place, running on your own machine. your data sits in a single folder on a computer you own and never leaves unless you tell it to.

think of alles as the *ecosystem* and **aide** as the ai living inside it — kinda like gemini to google. aide can read and act across every other app: your mail, your docs, your calendar, your tasks. and with automation rules, alles keeps doing stuff for you even when you're not looking.

it's one python process. no build step, no bundler, no node_modules, no cloud account, no telemetry. clone it, run `python app.py`, open a browser. that's literally the whole thing.

> **who's this for?** one person who wants their own software. it's a personal workspace, not a multi-tenant saas — single-user on purpose. if you've ever wished for notion + gmail + obsidian + google photos + a chatgpt that can actually touch your files, all on hardware you own — yeah, that's the idea.

---

## table of contents

- [what's inside](#whats-inside)
- [the ai: aide](#the-ai-aide)
- [how the model switch works](#how-the-model-switch-works) — *the part everyone asks about*
- [quick start](#quick-start)
- [the cli](#the-cli)
- [configuration](#configuration)
- [how it's built](#how-its-built)
- [how each app works under the hood](#how-each-app-works-under-the-hood)
- [architecture: one server, many subdomains](#architecture-one-server-many-subdomains)
- [the agent](#the-agent)
- [project layout](#project-layout)
- [security](#security)
- [what it's based on](#what-its-based-on)
- [license](#license)

---

## what's inside

every one of these is a real app, not a stub:

- **aide** — streaming chat with any model, plus an agent mode that does actual work.<br>　<sub>any provider (see below) · long-term memory · personas · deep research · model compare · image gallery · artifacts · voice in/out</sub>
- **home** — a launcher you can make your own.<br>　<sub>drag the app tiles to reorder, hide the ones you never touch (hit *customize*) · quick-capture box up top: jot a note or a task without leaving the screen · your whole day at a glance</sub>
- **today** — your day on one screen the second you open alles.<br>　<sub>today's events · overdue tasks · renewals this week · unread mail · recent docs · "ask aide about my day"</sub>
- **automation rules** — *when this happens, do that.* set it once, forget it.<br>　<sub>mail from X → task · renewal soon → push · doc saved with #tag → action · every morning → a day digest</sub>
- **mail** — a real imap/smtp client with a live inbox and ai baked in.<br>　<sub>auto-refresh · one-click setup for gmail / outlook / icloud / yahoo / fastmail / your own domain · summarize · mail → task · mail → calendar event (ai pulls the details)</sub>
- **docs** — a proper wysiwyg markdown editor with live preview, over plain `.md` files on disk.<br>　<sub>codemirror 6, obsidian-style live preview · `[[wikilinks]]` + backlinks + unlinked mentions · graph view · #tags · embeds · frontmatter · find/replace · `[[` autocomplete · paste a url → link, paste/drop an image → it uploads + embeds · quick switcher (cmd/ctrl+o) · pin + sort · templates · task rollup · word count · version history · math (katex) · diagrams (mermaid) · ai edits · import .docx/.html/.pdf and youtube links · export pdf/html/docx</sub>
- **calendar** — month, week, and day views with recurring events.<br>　<sub>real time-grid week/day views · daily/weekly/monthly recurrence · optional caldav sync (icloud / google)</sub>
- **subs** — a subscription tracker that actually gets billing.<br>　<sub>weekly / monthly / quarterly / yearly / custom cycles · due dates roll over on their own · monthly + yearly totals · push before anything renews</sub>
- **days** — countdowns to what's coming, day-counts since what's passed.<br>　<sub>birthdays & anniversaries (knows which one it is) · feb 29 handled · progress bars · pins · push reminders</sub>
- **files** — browse, upload, preview, edit over any folder you point it at.<br>　<sub>inline preview for images, pdfs, video, audio, and text — no download needed</sub>
- **gallery** — a local photo library that feels like icloud photos, minus apple.<br>　<sub>date "moments" · albums · favorites · exif · auto thumbnails</sub>
- **tasks & notes** — quick capture, zero ceremony.
- **contacts** — an address book aide can read and use.
- **secrets** — an encrypted password vault.<br>　<sub>aes-256-gcm · the master password never touches disk · locked = invisible, even to someone holding your database file</sub>
- **installs like an app** — alles is a pwa with real push notifications.<br>　<sub>add to home screen / dock · offline shell · reminders & renewals reach you with every tab closed</sub>

plus the smaller stuff: artifacts (the model writes html/svg/code, you see it rendered live), voice in and out, global search across everything (cmd/ctrl+k), scheduled messages (right-click send), shell & mcp tools for the agent, prompt templates, webhooks, api tokens, an openai-compatible api, backup/restore, incognito sessions, and light/dark themes.

---

## the ai: aide

aide's the brain. it looks like a normal streaming chat, but it does a few things a chat window usually can't:

- **it talks to any model.** one chat box, every provider — flip between claude, gpt, deepseek, gemini, a local llama, whatever, mid-conversation. (how that works is the next section.)
- **it remembers.** long-term memory backed by local vector search (`fastembed`, onnx, runs on your cpu — no embedding api needed), with a keyword fallback if embeddings aren't around.
- **it can act.** agent mode is a real autonomous tool-using loop — read/write files, run shell commands, search the web, hit mcp servers, reach into your other apps (make a calendar event, add a task, write a note). with permission modes so it asks before touching anything you didn't ok.
- **it does deep research.** research mode runs a multi-round loop: it searches the web, *reads the actual pages* (not just the snippets), pulls findings, decides what to search next, and writes a cited markdown report. works with no api key at all via duckduckgo + wikipedia, gets better with a (free) tavily/brave key.
- **it sees.** drop in an image and the right providers get it as vision input.
- **it compares.** model compare runs the same prompt against several models side by side.

---

## how the model switch works

this is the question everyone asks, so here's the precise answer.

aide doesn't hardcode a provider. you register **endpoints** (settings → models), each one just a `base_url` + an `api_key`. when you send a message, aide looks at the endpoint's url and routes the request to the right protocol. that routing lives in one function, [`detect_provider()` in `services/llm.py`](services/llm.py):

```python
def detect_provider(base_url):
    if "anthropic.com"   in url: return "anthropic"
    if "deepseek.com"    in url: return "deepseek"
    if "openrouter.ai"   in url: return "openrouter"
    if "groq.com"        in url: return "groq"
    if "moonshot.cn"     in url: return "moonshot"
    if "api.x.ai"        in url: return "xai"
    if "googleapis.com"  in url: return "gemini"
    if "mistral.ai"      in url: return "mistral"
    if "perplexity.ai"   in url: return "perplexity"
    if "together.xyz"    in url: return "together"
    if "fireworks.ai"    in url: return "fireworks"
    if "cohere"          in url: return "cohere"
    if "openai.com"      in url: return "openai"
    if ":11434" in url or "ollama" in url: return "ollama"
    return "openai"   # anything else: treat as OpenAI-compatible
```

under the hood there are really only **three wire protocols**, and aide speaks all three:

| protocol | who uses it | endpoint | notes |
|---|---|---|---|
| **openai-compatible** | openai, deepseek, groq, openrouter, moonshot/kimi, xai/grok, gemini, mistral, perplexity, together, fireworks, cohere, vllm, lm studio, **+ anything that speaks the format** | `POST /v1/chat/completions` | the default and the fallback |
| **anthropic messages** | claude | `POST /v1/messages` | different headers, system prompt, and tool/vision shapes |
| **ollama native** | local models via [ollama](https://ollama.com) | `POST /api/chat` | point an endpoint at `http://localhost:11434` and you're fully offline, no keys |

for each one, aide builds the right request body, sends it, and streams the response back through a parser that normalizes everything into the same internal events: `{"delta": ...}` for text, `{"thinking": ...}` for reasoning tokens (deepseek-r1, qwen3, claude extended thinking — shown as a live "thought for Ns" timer), `{"tool_call": ...}` for function calls, and `{"done": ..., "usage": ...}` at the end. so the rest of the app never has to care which provider answered.

a few things that matter in practice:

- **streaming is true token streaming** over sse (`data: {json}\n\n`), not batched — you watch the answer type itself out.
- **reasoning models** that go quiet for a bit before answering show an elapsed-time heartbeat so the ui never looks frozen.
- **vision, tool-calling, and tool-results** get translated per provider (e.g. openai `tool_calls` ⇄ anthropic `tool_use` blocks, base64 images ⇄ anthropic image blocks).
- **auto-failover & cooldown:** an endpoint that errors twice gets a 20-second cooldown so a dead provider doesn't stall you.
- **localhost stays direct:** if you run behind an http proxy (e.g. clash), aide honors `NO_PROXY` and routes `localhost`/`127.0.0.1` straight through, so ollama / lm studio never get proxied.
- **zero-config start:** drop `DEEPSEEK_API_KEY` or `ANTHROPIC_API_KEY` in `.env` and aide auto-creates that endpoint on first boot. or add any endpoint in the ui with one click (presets for all the providers above) — no `.env` edit needed.

aide also **exposes** an openai-compatible api of its own (`GET /v1/models`, `POST /v1/chat/completions`) so other tools can point at alles like it's openai.

---

## quick start

you need **python 3.11+**. then:

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.txt
python app.py
```

open **http://localhost:8000** and you're in.

**no api key needed to boot.** mail, docs, files, calendar, tasks, subs, days, photos, contacts, secrets — all work out of the box. when you want aide to talk, add a model under **settings → models** (one click for openai / anthropic / deepseek / groq / gemini / ollama and ~10 more), or drop a key like `DEEPSEEK_API_KEY` into `.env`.

not a git person? hit the green **code** button up top, grab the zip, unzip, run the same commands inside the folder.

---

## the cli

```
alles start         start the server in the background (waits until it's actually up)
alles stop          stop it
alles restart       restart it
alles status        running/stopped + url + reachability
alles logs [N]      print the last N log lines (default 60)
alles logs -f       follow the log live
alles update        git pull, then restart
alles open          open the browser
```

- **windows (powershell):** `.\alles.cmd start` — powershell wants the `.\` to run a script from the current folder.
- **windows (cmd):** `alles.cmd start`
- **macos / linux / git bash:** `./alles start`
- **anywhere:** `python app.py`

the launchers find `python3` or `python` on their own. add the folder to your `PATH` to drop the prefix.

---

## configuration

copy `.env.example` to `.env`. **everything's optional** — alles runs fine with an empty `.env`.

| var | default | what it does |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | auto-creates a deepseek endpoint on first boot |
| `ANTHROPIC_API_KEY` | — | auto-creates an anthropic (claude) endpoint on first boot |
| `PORT` | `8000` | port to serve on |
| `SECRET_KEY` | `dev-secret` | signs your session cookie — **change this before exposing alles to a network** |
| `AUTH_ENABLED` | `false` | set `true` to require a password to log in |
| `AUTH_PASSWORD` | — | that password |
| `BASE_DOMAIN` | — | your real domain, for the subdomain setup (see architecture) |
| `TAVILY_API_KEY` | — | better research search (falls back to duckduckgo + wikipedia, which need no key) |

everything else — models, mail accounts, voice, search providers, automations, appearance, caldav — lives in the ui under **settings**. no config files to hand-edit.

---

## how it's built

```
python 3.11 + fastapi + sqlite (via sqlalchemy)
vanilla js, es modules, one module per feature — no bundler, no build step
httpx for async, streaming model calls
fastembed (onnx) for local embeddings — no embedding api needed
web push implemented straight from the rfcs — zero extra dependencies
```

the dependency list is deliberately tiny (`fastapi`, `uvicorn`, `httpx`, `sqlalchemy`, `pydantic`, `cryptography`, `bcrypt`, `fastembed`, plus `python-docx` and `pillow`). optional extras are opt-in and clearly marked: `pyautogui` (agent computer-use), `faster-whisper` (offline voice), `caldav` (calendar sync), `pypdf` (pdf import).

the frontend is genuinely just files. `static/index.html` is the whole spa shell; `static/js/` has one es module per feature, imported by `app.js`; `static/style.css` holds the design tokens (sharp, monochrome, 2–3px radii, no shadows). view-source actually shows you the app. the one exception is the docs editor — codemirror 6 is vendored as a single pre-built bundle (`static/vendor/cm6.bundle.js`), so there's still no build step to run.

---

## how each app works under the hood

the whole point of self-hosting is that nothing's magic. here's what each app actually does:

- **docs** — your notes are **real `.md` files** in `data/vault/` (configurable). the editor is **codemirror 6** doing obsidian-style live preview: the markdown symbols hide, the text styles itself inline, and the raw symbols come back on whatever line your cursor's on. codemirror edits the plain text directly, so *what's saved is exactly what you typed* — a save literally can't mangle a doc. `[[wikilinks]]`, backlinks, unlinked mentions, `#tags`, `![[embeds]]`, frontmatter, the graph, and the outline are all computed over those files. there's find/replace (ctrl+f), `[[` autocomplete, a cmd/ctrl+o quick switcher, pinning + a–z/recent sort, templates, a vault-wide task rollup you can tick off, word count + reading time, and version history with restore. paste a url onto a selection and it becomes a link; paste or drop an image and it uploads to `data/vault/_assets/` and embeds. math renders with katex, diagrams with mermaid (both lazy-loaded from a cdn, raw text shown if you're offline). you can pull stuff in — import `.md`/`.txt`/`.docx`/`.html`/`.pdf`, or paste a youtube link and it grabs the transcript and ai-summarizes it into a doc — and push stuff out: export to pdf, html, or docx.
- **mail** — a thin client over python's stdlib `imaplib`/`smtplib` (no mail dependency). it pools live imap connections, caches reads, loads the inbox by sequence range (no slow `SEARCH ALL`), and — to stay quick on a bad connection — opens a message by fetching *only* its text/html body parts instead of dragging down the whole thing with attachments. the background poll only re-fetches when the mailbox actually changed. credentials are stored locally and never sent back to the browser.
- **research** — a search-and-read loop: it picks a query, searches (tavily / brave / searxng / google pse / serper if you've got a key, else duckduckgo → wikipedia for free), fetches and strips the top pages to text, asks the model for findings, decides what to look up next, and writes a cited report — all streamed live as it goes.
- **calendar** — events in sqlite with recurrence expanded on the fly; optional two-way caldav sync if you install `caldav` and add your credentials.
- **gallery** — you import photos; pillow makes thumbnails and reads exif; they get grouped into date "moments." stored as plain files under `data/`.
- **secrets** — entries are sealed with aes-256-gcm under a key derived from your master password (pbkdf2-hmac-sha-256, 260k iterations). the master password lives in memory only and never hits disk.
- **automations & jobs** — there's a little background job registry + event bus (`services/jobs.py`) that ticks the recurring stuff every 30s: subscription renewals, day-event checks, scheduled reminders/messages, automation rules, and a periodic model-list refresh. rules live in the db and fire on events (mail arrived, doc saved, renewal soon, every morning). web push is implemented from the rfcs (vapid + message encryption) with no third-party library, so reminders reach you even with every tab shut.

---

## architecture: one server, many subdomains

alles is **one server** serving **one spa**, but each app gets its own subdomain so it feels like a real suite:

```
alles.localhost          the hub (launcher)
aide.localhost           chat, agent, memory, compare, ai gallery
mail.localhost           mail
docs.localhost           docs (notes)
calendar.localhost       calendar
tasks.localhost          tasks
files.localhost          files
gallery.localhost        photos
contacts.localhost       contacts
secrets.localhost        the vault
```

`static/js/subdomain.js` maps each host to the views it shows; `app.js` scopes the sidebar to that app and `navigateTo()` cross-jumps between them. this works **today with zero dns setup** — browsers route `*.localhost` to your machine automatically.

**one login across all of them.** because `Domain=localhost` cookies don't get sent to `*.localhost` subdomains, alles logs you in per-host and quietly relays the session on first cross-navigation via a one-time handoff code — so you authenticate once and every app just works (even on a direct visit or a bookmark).

**on a real domain:** set `BASE_DOMAIN=yourdomain`, put a wildcard reverse proxy in front (e.g. caddy: `*.yourdomain, yourdomain { reverse_proxy 127.0.0.1:8000 }`), and cookies become `Domain=yourdomain; Secure` so sso spans every subdomain over https.

all your data is in **`data/`** — one sqlite file (`data/aide.db`) plus your docs, files, photos, and uploads as plain files, and the encryption key (`data/secret.key`). back up that folder and you've backed up everything.

---

## the agent

agent mode turns aide from a chat into something that does the work. it's a multi-turn autonomous loop with a real toolset:

- **files & shell** — read / write / edit / patch files, list / glob / grep, run shell commands (optionally sandboxed in docker)
- **web** — search and fetch pages
- **code** — symbol index, find-definition, run linters/diagnostics
- **memory** — search and add long-term memories
- **cross-app** — make calendar events, add tasks, read/write notes, list contacts
- **integrations** — mcp servers, and github when you connect a token (repos, issues, prs, code search)
- **sub-agents** — spawn parallel helpers for a task
- **computer use** — screenshot/click/type (opt-in, needs `pyautogui`)

it runs under **permission modes** — *approve* (asks before any mutating action, with a unified diff to review), *plan* (read-only; mutating tools are removed entirely), or *full-auto*. every file change is checkpointed so you can revert a whole run. `@`-mention a file to pull it into context. drop a long task in the background and keep working.

there's also a **prompt-injection guard**: anything the agent pulls from an untrusted source — web pages, files, emails, repo contents, mcp results — gets wrapped as *data, not instructions* before it goes back to the model, and scanned for the classic "ignore previous instructions / reveal your system prompt / exfiltrate the api key" patterns, which get flagged when they show up. so a booby-trapped webpage can't quietly hijack a run.

a project-level `AGENTS.md` (or `aide.md`) is auto-loaded as standing instructions — the same cross-tool convention claude code and others use.

---

## project layout

```
alles/
├── app.py                 fastapi entry — routers, middleware, lifespan, env bootstrap
├── cli.py                 the alles cli (start/stop/restart/status/logs/update/open)
├── core/
│   ├── database.py        every sqlalchemy model + lightweight migrations
│   ├── settings.py        settings load/save, base-domain helpers
│   └── auth.py            bcrypt login, in-memory tokens, cross-subdomain handoff
├── services/
│   ├── llm.py             provider-agnostic streaming client (the model switch)
│   ├── agent_runtime.py   the autonomous agent loop
│   ├── agent_tools.py     every agent tool (+ the prompt-injection guard)
│   ├── jobs.py            background job registry + event bus
│   ├── research_engine.py search + read-the-page research loop
│   ├── mail.py            imap/smtp over stdlib
│   ├── vault_md.py        markdown docs on disk (tree, links, tags, graph, tasks)
│   ├── doc_import.py      import .md/.txt/.docx/.html/.pdf → markdown
│   ├── youtube.py         youtube transcript → note
│   ├── memory_store.py    fastembed vector memory + keyword fallback
│   ├── crypto.py          aes-256-gcm vault encryption
│   ├── webpush.py         web push from the rfcs
│   └── …                  files, photos, caldav, automations, docx, stt
├── routes/                one apirouter per feature, all under /api
└── static/
    ├── index.html         the spa shell
    ├── style.css          design tokens + all styling
    ├── vendor/            the prebuilt codemirror 6 bundle (no build step)
    └── js/                one es module per feature, imported by app.js
```

run the tests with `python -m unittest discover -s tests` (76 and counting).

---

## security

alles is built for one person on their own machine. read this before you expose it to anything past localhost.

- **it ships open.** auth is off by default. if alles is reachable from your network, set `AUTH_ENABLED=true`, a strong `AUTH_PASSWORD`, and a real `SECRET_KEY` *first*. without auth, anyone who can reach the port can read your mail and your files and run shell commands as you.
- **aide has hands.** agent mode and the shell tools run real commands on the machine alles is on. that's the point — but don't hand access to people or models you don't trust. (the prompt-injection guard helps, but it's a seatbelt, not a force field.)
- **credentials are encrypted at rest with a local key.** model api keys and mail passwords are sealed with aes-256-gcm under the key in `data/secret.key`. this protects the database file if it leaks *on its own* — it does not protect against someone with the whole `data/` folder, because the server has to be able to decrypt unattended.
- **backups are the whole safe, key included.** a backup zip has the database *and* the keys so restores just work — which means a backup is exactly as sensitive as your live data. store it like a password.
- **the password vault is different.** vault secrets are encrypted with your master password, which never touches disk. no master password, no plaintext — not even from a full copy of `data/`.
- **no warranty.** this is a self-hosted hobby project, not an audited security product. it tries hard, but you run it at your own risk.

---

## what it's based on

aide was inspired by **[odysseus](https://github.com/pewdiepie-archdaemon/odysseus)** by pewdiepie-archdaemon. the concept — a self-hosted personal ai with memory, research mode, shell access, mcp, a multi-provider model backend, and a suite of apps around it — comes from that project. alles is an independent reimplementation written from scratch, but odysseus is where the idea came from and it deserves the credit. go give that repo a star. full note in [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md).

it stands on the shoulders of some great open-source work: [fastapi](https://fastapi.tiangolo.com) + [uvicorn](https://www.uvicorn.org), [sqlalchemy](https://www.sqlalchemy.org), [httpx](https://www.python-httpx.org), [fastembed](https://github.com/qdrant/fastembed), [codemirror](https://codemirror.net), [katex](https://katex.org), [mermaid](https://mermaid.js.org), [pillow](https://python-pillow.org), [python-docx](https://python-docx.readthedocs.io), [cryptography](https://cryptography.io), and python's own `imaplib`/`smtplib`. models come from whichever provider you point it at; local ones via [ollama](https://ollama.com).

---

## license

mit. do whatever you want with it. if you build something cool on top, a link back is appreciated but not required.
