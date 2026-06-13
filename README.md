# alles

```
─────────────────────────────────────────────
 ⊹ ࣪ ˖ ( ◕ ‿ ◕ )つ  alles — your everything
─────────────────────────────────────────────
```

**alles** is a self-hosted everything-app. AI, mail, docs, files, calendar, tasks, photos, contacts, passwords, subscriptions, and countdowns — one login, one place, running on your own machine. Your data lives in a single folder on a computer you control and never leaves it unless you tell it to.

alles is the *ecosystem*. **aide** is the AI living inside it — think Gemini to Google. aide can read and act across every other app: your mail, your docs, your calendar, your tasks. And with automation rules, alles keeps working for you when you're not even looking.

It's one Python process. No build step, no bundler, no node_modules, no cloud account, no telemetry. Clone it, run `python app.py`, open a browser. That's the whole thing.

> **Who is this for?** One person who wants their own software. It's a personal workspace, not a multi-tenant SaaS — single user by design. If you've ever wanted Notion + Gmail + Obsidian + Google Photos + a ChatGPT that can actually touch your files, all on hardware you own, that's the pitch.

---

## table of contents

- [what's inside](#whats-inside)
- [the AI: aide](#the-ai-aide)
- [how the model switch works](#how-the-model-switch-works) — *the part people ask about*
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

Every one of these is a real app, not a stub:

- **aide** — streaming chat with any model, plus an agent mode that does real work.<br>　<sub>any provider (see below) · long-term memory · personas · deep research · model compare · image gallery · artifacts · voice in/out</sub>
- **today** — your whole day on one screen the moment you open alles.<br>　<sub>today's events · overdue tasks · renewals this week · unread mail · recent docs · "ask aide about my day"</sub>
- **automation rules** — *when this happens, do that.* Set it once, forget it.<br>　<sub>mail from X → task · renewal soon → push · doc saved with #tag → action · every morning → a day digest</sub>
- **mail** — a real IMAP/SMTP client with a live inbox and AI built in.<br>　<sub>auto-refresh · one-click setup for Gmail / Outlook / iCloud / Yahoo / Fastmail / your own domain · summarize · mail → task · mail → calendar event (AI-extracted)</sub>
- **docs** — a fast markdown editor with live preview, over plain `.md` files on disk.<br>　<sub>edit / split / preview · `[[wikilinks]]` + backlinks · graph view · #tags · embeds · frontmatter · version history with restore · one-click formatting toolbar · math (KaTeX) · diagrams (Mermaid) · AI edits · extract-todos · .docx export</sub>
- **calendar** — month, week, and day views with recurring events.<br>　<sub>real time-grid week/day views · daily/weekly/monthly recurrence · optional CalDAV sync (iCloud / Google)</sub>
- **subs** — a subscription manager that actually understands billing.<br>　<sub>weekly / monthly / quarterly / yearly / custom cycles · due dates roll over on their own · monthly + yearly totals · push before anything renews</sub>
- **days** — countdowns to what's ahead, day-counts since what's behind.<br>　<sub>birthdays & anniversaries (knows which one it is) · Feb 29 handled · progress bars · pins · push reminders</sub>
- **files** — browse, upload, preview, and edit over any folder you point it at.
- **gallery** — a local photo library that works like iCloud Photos, minus Apple.<br>　<sub>date "moments" · albums · favorites · EXIF · auto thumbnails</sub>
- **tasks & notes** — quick capture, zero ceremony.
- **contacts** — an address book aide can read and use.
- **secrets** — an encrypted password vault.<br>　<sub>AES-256-GCM · the master password never touches disk · locked = invisible, even to someone holding your database file</sub>
- **installs like an app** — alles is a PWA with real push notifications.<br>　<sub>add to home screen / dock · offline shell · reminders & renewals reach you with every tab closed</sub>

Plus the smaller stuff: artifacts (the model writes HTML/SVG/code, you see it rendered live), voice in and out, global search across everything (Cmd/Ctrl+K), scheduled messages (right-click send), shell & MCP tools for the agent, prompt templates, webhooks, API tokens, an OpenAI-compatible API, backup/restore, incognito sessions, and light/dark themes.

---

## the AI: aide

aide is the brain. It's a normal streaming chat on the surface, but it has a few things a chat window usually doesn't:

- **It talks to any model.** One chat box, every provider — flip between Claude, GPT, DeepSeek, Gemini, a local Llama, whatever, mid-conversation. (How that works is the next section.)
- **It remembers.** Long-term memory backed by local vector search (`fastembed`, ONNX, runs on your CPU — no embedding API needed), with a keyword fallback if embeddings aren't available.
- **It can act.** Agent mode is a real autonomous tool-using loop — read/write files, run shell commands, search the web, hit MCP servers, and reach into your other apps (create a calendar event, add a task, write a note). With permission modes so it asks before it touches anything you didn't approve.
- **It does deep research.** Research mode runs a multi-round search loop: it searches the web, *reads the actual pages* (not just the result snippets), pulls findings, decides what to search next, and writes a cited markdown report. Works with no API key at all via DuckDuckGo + Wikipedia, and gets better with a (free) Tavily/Brave key.
- **It sees.** Drop in an image, the right providers get it as vision input.
- **It compares.** Model compare runs the same prompt against several models side-by-side.

---

## how the model switch works

This is the question everyone asks, so here's the precise answer.

aide doesn't hardcode a provider. You register **endpoints** (settings → models), each one just a `base_url` + an `api_key`. When you send a message, aide looks at the endpoint's URL and routes the request to the right protocol. That routing lives in one function, [`detect_provider()` in `services/llm.py`](services/llm.py):

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

Under the hood there are really only **three wire protocols**, and aide speaks all three:

| protocol | who uses it | endpoint | notes |
|---|---|---|---|
| **OpenAI-compatible** | OpenAI, DeepSeek, Groq, OpenRouter, Moonshot/Kimi, xAI/Grok, Gemini, Mistral, Perplexity, Together, Fireworks, Cohere, vLLM, LM Studio, **+ any server that speaks the format** | `POST /v1/chat/completions` | the default and the fallback |
| **Anthropic Messages** | Claude | `POST /v1/messages` | different headers, system prompt, and tool/vision shapes |
| **Ollama native** | local models via [Ollama](https://ollama.com) | `POST /api/chat` | point an endpoint at `http://localhost:11434` and you're fully offline, no keys |

For each, aide builds the correct request body, sends it, and streams the response back through a parser that normalizes everything into the same internal events: `{"delta": ...}` for text, `{"thinking": ...}` for reasoning tokens (DeepSeek-R1, Qwen3, Claude extended thinking — shown as a live "thought for Ns" timer), `{"tool_call": ...}` for function calls, and `{"done": ..., "usage": ...}` at the end. So the rest of the app never has to care which provider answered.

A few details that matter in practice:

- **Streaming is true token streaming** over SSE (`data: {json}\n\n`), not batched — you watch the answer type itself out.
- **Reasoning models** that go silent for a while before answering show an elapsed-time heartbeat so the UI never looks frozen.
- **Vision, tool-calling, and tool-results** are translated per provider (e.g. OpenAI `tool_calls` ⇄ Anthropic `tool_use` blocks, base64 images ⇄ Anthropic image blocks).
- **Auto-failover & cooldown:** an endpoint that errors twice gets a 20-second cooldown so a dead provider doesn't stall you.
- **Localhost stays direct:** if you run behind an HTTP proxy (e.g. Clash), aide honors `NO_PROXY` and routes `localhost`/`127.0.0.1` straight through, so Ollama / LM Studio never get proxied.
- **Zero-config start:** set `DEEPSEEK_API_KEY` or `ANTHROPIC_API_KEY` in `.env` and aide auto-creates that endpoint on first boot. Or add any endpoint in the UI with one click (presets for all the providers above) — no `.env` edit required.

aide also **exposes** an OpenAI-compatible API of its own (`GET /v1/models`, `POST /v1/chat/completions`) so other tools can point at alles as if it were OpenAI.

---

## quick start

You need **Python 3.11+**. Then:

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.txt
python app.py
```

Open **http://localhost:8000** and you're in.

**No API key is needed to boot.** Mail, docs, files, calendar, tasks, subs, days, photos, contacts, secrets — all work out of the box. When you want aide to talk, add a model under **settings → models** (one click for OpenAI / Anthropic / DeepSeek / Groq / Gemini / Ollama and ~10 more), or drop a key like `DEEPSEEK_API_KEY` into `.env`.

Prefer not to use git? Hit the green **Code** button up top, download the zip, unzip, and run the same commands inside the folder.

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

- **Windows (PowerShell):** `.\alles.cmd start` — PowerShell needs the `.\` to run a script from the current folder.
- **Windows (cmd):** `alles.cmd start`
- **macOS / Linux / Git Bash:** `./alles start`
- **anywhere:** `python app.py`

The launchers find `python3` or `python` automatically. Add the folder to your `PATH` to drop the prefix.

---

## configuration

Copy `.env.example` to `.env`. **Everything is optional** — alles runs with an empty `.env`.

| var | default | what it does |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | auto-creates a DeepSeek endpoint on first boot |
| `ANTHROPIC_API_KEY` | — | auto-creates an Anthropic (Claude) endpoint on first boot |
| `PORT` | `8000` | port to serve on |
| `SECRET_KEY` | `dev-secret` | signs your session cookie — **change this before exposing alles to a network** |
| `AUTH_ENABLED` | `false` | set `true` to require a password to log in |
| `AUTH_PASSWORD` | — | that password |
| `BASE_DOMAIN` | — | your real domain, for the subdomain setup (see architecture) |
| `TAVILY_API_KEY` | — | better research search (falls back to DuckDuckGo + Wikipedia, which need no key) |

Everything else — models, mail accounts, voice, search providers, automations, appearance, CalDAV — is configured in the UI under **settings**. No config files to hand-edit.

---

## how it's built

```
Python 3.11 + FastAPI + SQLite (via SQLAlchemy)
vanilla JS, ES modules, one module per feature — no bundler, no build step
httpx for async, streaming model calls
fastembed (ONNX) for local embeddings — no embedding API needed
web push implemented straight from the RFCs — zero extra dependencies
```

The dependency list is deliberately tiny (`fastapi`, `uvicorn`, `httpx`, `sqlalchemy`, `pydantic`, `cryptography`, `bcrypt`, `fastembed`, plus `python-docx` and `pillow`). Optional extras are opt-in and clearly marked: `pyautogui` (agent computer-use), `faster-whisper` (offline voice), `caldav` (calendar sync).

The frontend is genuinely just files. `static/index.html` is the whole SPA shell; `static/js/` has one ES module per feature, imported by `app.js`; `static/style.css` holds the design tokens (sharp, monochrome, 2–3px radii, no shadows). View source actually shows you the app.

---

## how each app works under the hood

The whole point of self-hosting is that nothing is magic. Here's what each app actually does:

- **docs** — your notes are **real `.md` files** in `data/vault/` (configurable). The editor is a plain markdown textarea — *what you type is exactly what's saved*, so a doc can never get silently mangled — with a live HTML preview alongside it. `[[wikilinks]]`, backlinks, `#tags`, `![[embeds]]`, frontmatter, the graph, and the outline are all computed over those files. Math renders with KaTeX, diagrams with Mermaid (both loaded lazily from a CDN, raw text shown if offline). Every save snapshots a revision you can restore.
- **mail** — a thin client over Python's stdlib `imaplib`/`smtplib` (no mail dependency). It pools live IMAP connections, caches reads, loads the inbox by sequence range (no slow `SEARCH ALL`), and — to stay fast on a bad connection — opens a message by fetching *only* its text/HTML body parts instead of downloading the whole thing with its attachments. The background poll only re-fetches when the mailbox actually changed. Credentials are stored locally and never sent back to the browser.
- **research** — a search-and-read loop: it picks a query, searches (Tavily / Brave / SearXNG / Google PSE / Serper if you have a key, else DuckDuckGo → Wikipedia for free), fetches and strips the top pages to text, asks the model for findings, decides what to look up next, and writes a cited report — all streamed live as it works.
- **calendar** — events in SQLite with recurrence expanded on the fly; optional two-way CalDAV sync if you install `caldav` and add your credentials.
- **gallery** — you import photos; Pillow makes thumbnails and reads EXIF; they're grouped into date "moments." Stored as plain files under `data/`.
- **secrets** — entries are sealed with AES-256-GCM under a key derived from your master password (PBKDF2-HMAC-SHA-256, 260k iterations). The master password is held in memory only and never written to disk.
- **automations & push** — rules live in the DB and fire on events (mail arrived, doc saved, renewal soon, every morning). Web push is implemented from the RFCs (VAPID + message encryption) with no third-party library, so reminders reach you even with every tab closed.

---

## architecture: one server, many subdomains

alles is **one server** that serves **one SPA**, but each app lives on its own subdomain so it feels like a real suite:

```
alles.localhost          the hub (launcher)
aide.localhost           chat, agent, memory, compare, AI gallery
mail.localhost           mail
docs.localhost           docs (notes)
calendar.localhost       calendar
tasks.localhost          tasks
files.localhost          files
gallery.localhost        photos
contacts.localhost       contacts
secrets.localhost        the vault
```

`static/js/subdomain.js` maps each host to the views it shows; `app.js` scopes the sidebar to that app and `navigateTo()` cross-jumps between them. This works **today with zero DNS setup** — browsers route `*.localhost` to your machine automatically.

**One login across all of them.** Because `Domain=localhost` cookies aren't sent to `*.localhost` subdomains, alles logs you in per-host and silently relays the session on first cross-navigation via a one-time handoff code — so you authenticate once and every app just works (even on a direct visit or a bookmark).

**On a real domain:** set `BASE_DOMAIN=yourdomain`, put a wildcard reverse proxy in front (e.g. Caddy: `*.yourdomain, yourdomain { reverse_proxy 127.0.0.1:8000 }`), and cookies become `Domain=yourdomain; Secure` so SSO spans every subdomain over HTTPS.

All of your data is in **`data/`** — one SQLite file (`data/aide.db`) plus your docs, files, photos, and uploads as plain files, and the encryption key (`data/secret.key`). Back up that folder and you've backed up everything.

---

## the agent

Agent mode turns aide from a chat into something that does the work. It's a multi-turn autonomous loop with a real toolset:

- **files & shell** — read / write / edit / patch files, list / glob / grep, run shell commands (optionally sandboxed in Docker)
- **web** — search and fetch pages
- **code** — symbol index, find-definition, run linters/diagnostics
- **memory** — search and add long-term memories
- **cross-app** — create calendar events, add tasks, read/write notes, list contacts
- **integrations** — MCP servers, and GitHub when you connect a token (repos, issues, PRs, code search)
- **sub-agents** — spawn parallel helpers for a task
- **computer use** — screenshot/click/type (opt-in, needs `pyautogui`)

It runs under **permission modes** — *approve* (asks before any mutating action, with a unified diff to review), *plan* (read-only; mutating tools are removed entirely), or *full-auto*. Every file change is checkpointed so you can revert a whole run. `@`-mention a file to pull it into context. Drop a long task into the background and keep working.

A project-level `AGENTS.md` (or `aide.md`) is auto-loaded as standing instructions — the same cross-tool convention Claude Code and others use.

---

## project layout

```
alles/
├── app.py                 FastAPI entry — routers, middleware, lifespan, env bootstrap
├── cli.py                 the alles CLI (start/stop/restart/status/logs/update/open)
├── core/
│   ├── database.py        every SQLAlchemy model + lightweight migrations
│   ├── settings.py        settings load/save, base-domain helpers
│   └── auth.py            bcrypt login, in-memory tokens, cross-subdomain handoff
├── services/
│   ├── llm.py             provider-agnostic streaming client (the model switch)
│   ├── agent_runtime.py   the autonomous agent loop
│   ├── agent_tools.py     every agent tool
│   ├── research_engine.py search + read-the-page research loop
│   ├── mail.py            IMAP/SMTP over stdlib
│   ├── vault_md.py        markdown docs on disk (tree, links, tags, graph)
│   ├── memory_store.py    fastembed vector memory + keyword fallback
│   ├── crypto.py          AES-256-GCM vault encryption
│   ├── webpush.py         web push from the RFCs
│   └── …                  files, photos, caldav, automations, docx, stt
├── routes/                one APIRouter per feature, all under /api
└── static/
    ├── index.html         the SPA shell
    ├── style.css          design tokens + all styling
    └── js/                one ES module per feature, imported by app.js
```

Run the tests with `python -m unittest discover -s tests` (56 and counting).

---

## security

alles is built for one person on their own machine. Read this before you expose it to anything beyond localhost.

- **It ships open.** Auth is off by default. If alles is reachable from your network, set `AUTH_ENABLED=true`, a strong `AUTH_PASSWORD`, and a real `SECRET_KEY` *first*. Without auth, anyone who can reach the port can read your mail and your files and run shell commands as you.
- **aide has hands.** Agent mode and the shell tools execute real commands on the machine alles runs on. That's the point — but don't hand access to people or models you don't trust.
- **Credentials are encrypted at rest with a local key.** Model API keys and mail passwords are sealed with AES-256-GCM under the key in `data/secret.key`. This protects the database file if it leaks *on its own* — it does not protect against someone with the whole `data/` folder, because the server must be able to decrypt unattended.
- **Backups are the whole safe, key included.** A backup zip contains the database *and* the keys so restores just work — which means a backup is exactly as sensitive as your live data. Store it like a password.
- **The password vault is different.** Vault secrets are encrypted with your master password, which never touches disk. No master password, no plaintext — not even from a full copy of `data/`.
- **No warranty.** This is a self-hosted hobby project, not an audited security product. It tries hard, but you run it at your own risk.

---

## what it's based on

aide was inspired by **[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)** by pewdiepie-archdaemon. The concept — a self-hosted personal AI with memory, research mode, shell access, MCP, a multi-provider model backend, and a suite of apps around it — comes from that project. alles is an independent reimplementation written from scratch, but Odysseus is where the idea came from and deserves the credit. Go give that repo a star. Full note in [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md).

It stands on the shoulders of some great open-source work: [FastAPI](https://fastapi.tiangolo.com) + [Uvicorn](https://www.uvicorn.org), [SQLAlchemy](https://www.sqlalchemy.org), [httpx](https://www.python-httpx.org), [fastembed](https://github.com/qdrant/fastembed), [KaTeX](https://katex.org), [Mermaid](https://mermaid.js.org), [Pillow](https://python-pillow.org), [python-docx](https://python-docx.readthedocs.io), [cryptography](https://cryptography.io), and Python's own `imaplib`/`smtplib`. Models come from whichever provider you point it at; local models via [Ollama](https://ollama.com).

---

## license

MIT. Do whatever you want with it. If you build something cool on top, a link back is appreciated but not required.
```
