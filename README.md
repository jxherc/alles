# alles

```
─────────────────────────────────────────────
 ⊹ ࣪ ˖ ( ◕ ‿ ◕ )つ  alles — your everything
─────────────────────────────────────────────
```

**alles** is a self-hosted everything-app. one program that runs on your own computer and gives you ai chat, email, notes/docs, files, a calendar, tasks, photos, contacts, a password vault, subscription tracking, and countdowns — all behind one login, all storing their data in a single folder you control. nothing phones home. nothing's in someone else's cloud unless you put it there yourself.

think of **alles** as the whole house, and **aide** as the assistant who lives in it — kind of like what gemini is to google, except it's yours and it can actually open the other rooms: read your mail, edit your docs, add to your calendar, file your tasks. and with automation rules, it keeps doing little jobs for you even when you've closed the laptop.

it's *one python process*. no build step, no bundler, no `node_modules`, no account to sign up for, no analytics watching you. you clone it, run `python app.py`, and open a browser. that is genuinely the entire setup.

> **two-audience note:** this readme is written to be read two ways. if you're not a programmer, read the plain sentences and skip the grey "*under the hood*" bits — you'll still understand what every part does. if you are a programmer, the under-the-hood bits and the spec tables have the precise details (protocols, endpoints, algorithms, file formats). jargon gets a quick plain-english gloss the first time it shows up.

---

## the 30-second version

- **everything in one place, one login.** stop bouncing between fifteen tabs and ten companies.
- **it's yours.** all your data is plain files + one database in a folder called `data/`. copy that folder = you've copied your whole life. delete the app = you still have your files.
- **the ai isn't a gimmick.** it talks to *any* model (claude, gpt, deepseek, gemini, a model running on your own machine — your choice, switchable mid-chat), it remembers things across conversations, and in "agent" mode it can actually *do* things: edit files, run commands, search the web, touch your other apps.
- **private by default.** no telemetry, no cloud, runs offline if you want (with a local model). you decide what leaves your machine.
- **single user, on purpose.** this is *your* workspace, not a service you host for a hundred people.

---

## is this for me?

if you've ever wished you could mash together **notion + gmail + obsidian + google photos + google calendar + a password manager + a chatgpt that can actually open your files** — and own the whole thing on hardware you control — yes.

if you want a multi-user team product with billing and admin roles: no, that's not what this is. alles is deliberately one person, one machine.

you do **not** need to be technical to *use* it. you need to be a little technical to *install* it (you run two commands in a terminal once). the rest is clicking around a normal-looking app.

---

## table of contents

- [the apps — what you actually get](#the-apps--what-you-actually-get)
  - [aide (the ai)](#aide-the-ai) · [home](#home) · [today](#today) · [docs](#docs) · [mail](#mail) · [calendar](#calendar) · [tasks](#tasks) · [notes](#notes) · [subs](#subs) · [days](#days) · [files](#files) · [gallery](#gallery) · [contacts](#contacts) · [secrets](#secrets) · [automations](#automations)
- [aide in depth](#aide-in-depth)
- [how the model switch works](#how-the-model-switch-works) — *the part everyone asks about*
- [the agent in depth](#the-agent-in-depth)
- [how each app works under the hood](#how-each-app-works-under-the-hood)
- [keyboard shortcuts & global search](#keyboard-shortcuts--global-search)
- [quick start](#quick-start)
- [the cli](#the-cli)
- [configuration](#configuration)
- [architecture: one server, many subdomains](#architecture-one-server-many-subdomains)
- [the api (for other tools)](#the-api-for-other-tools)
- [your data: where everything lives](#your-data-where-everything-lives)
- [how it's built](#how-its-built)
- [project layout](#project-layout)
- [security — read before exposing it](#security--read-before-exposing-it)
- [performance & reliability](#performance--reliability)
- [testing](#testing)
- [what it's based on](#what-its-based-on)
- [license](#license)

---

## the apps — what you actually get

every one of these is a real, finished app — not a placeholder. they each live on their own subdomain (more on that later) so it feels like a proper suite, but it's all one program.

### aide (the ai)
**plain version:** a chat window that talks to whatever ai model you want, remembers you between chats, and — when you let it — can do real work on your machine instead of just talking.

**what's in it:**
- streaming chat (the reply types itself out live, word by word)
- works with any provider: claude, openai/gpt, deepseek, gemini, groq, mistral, a local model, and ~15 others — switch any time, even mid-conversation
- **agent mode** — a do-it-for-me mode with files, shell, web, and cross-app tools (full section below)
- **research mode** — searches the web, *reads the pages*, and writes you a cited report
- **compare** — run one prompt against several models at once, side by side, and vote
- **long-term memory** — it remembers facts/preferences across all your chats
- **personas** — saved system prompts / characters you can switch between
- **projects** — group chats together with shared context
- **artifacts** — when the model writes html/svg/a webpage/code, you see it rendered live, not as a wall of text
- **voice** — talk to it and have it talk back (speech-to-text in, text-to-speech out)
- **vision** — drop in an image and capable models can see it
- **incognito chats** — conversations that aren't saved
- **slash commands** (`/new`, `/clear`, `/rename`, …) and `@`-mentions to pull a file into context

### home
**plain version:** the front page. a launcher you can arrange however you like, with a box to jot something down fast.

- a grid of tiles, one per app — **drag them to reorder**, and when you drag, a glowing line shows exactly where the tile will drop
- hit **customize** to rearrange or **hide** apps you never use (×/+ on each tile); your layout is remembered
- a **quick-capture** box up top: type a thought and save it as a **note** (it names the note after what you wrote) or a **task**, without leaving the page
- a "today" strip and a live clock + greeting

### today
**plain version:** your whole day on one screen the moment you open alles.

- today's calendar events, tasks that are overdue or due today, reminders, subscriptions about to renew, day-countdowns, unread mail, and recently-edited docs — all in one list
- one button: **"ask aide about my day"** — hands all of that to the ai for a friendly rundown of what to do first and what you're about to miss

### docs
**plain version:** a really good notes app — like obsidian — where your notes are plain text files you own, linked together, with a live, pretty editor.

this is the most feature-dense app, so here's the full list:

- a true **wysiwyg** editor (you see bold as bold, headings as headings) built on **codemirror 6**, doing obsidian-style *live preview*: the markdown symbols (the `**` and `#`) hide themselves, the text styles inline, and the raw symbols reappear on whatever line your cursor is on. *under the hood:* codemirror edits the plain text directly, so what gets saved is byte-for-byte what you typed — a save can't silently corrupt a doc.
- three view modes you cycle with one button: **live** (the wysiwyg) · **source** (raw markdown) · **preview** (fully rendered)
- **`[[wikilinks]]`** to link notes together, **backlinks** (see what links *to* this note), and **unlinked mentions** (notes that name this one in plain text but haven't linked it yet)
- **`[[` autocomplete** — start typing a link and it suggests your notes
- **find & replace** inside a doc (Ctrl+F)
- **a graph view** — your notes as dots, links as lines, drag-explore
- **`#tags`** with a clickable tag sidebar + filter, and **`![[embeds]]`** to pull one note (or an image) inside another
- **frontmatter** (the `key: value` block at the top) rendered as a clean property table
- **paste smarts:** paste a web link onto selected text → it becomes a link; paste or drop an **image** → it uploads and embeds automatically
- **quick switcher** (Cmd/Ctrl+O) — fuzzy-jump to any doc by name
- **pin** favorite docs to the top, **sort** the tree a–z or by recently-edited, **foldable folders**, and **drag files into folders** to organize (with a drop highlight)
- **templates** — new-from-template menu (seeds starter meeting/daily/project templates with `{{date}}`/`{{title}}` tokens)
- **task rollup** — every `- [ ] checkbox` across all your notes in one panel, tickable from there
- **word count + reading time**, live in the header
- **version history** — every save snapshots a revision you can preview and restore
- **daily notes** — one-click "today" journal entry
- **math** (via katex) and **diagrams** (via mermaid) render right in the doc
- **ai edits** — tell the ai "summarize this" / "fix the grammar" and it rewrites the note in place, streaming
- **extract to-dos** — ai pulls action items out of a doc into real tasks
- **import** `.md` / `.txt` / `.docx` (word) / `.html` / `.pdf`, or paste a **youtube link** → it grabs the transcript and ai-summarizes it into a note
- **export** to **pdf**, **html**, or **docx** (word)

### mail
**plain version:** a real email client (read + send), with one-click setup for the big providers and ai help built in.

- connects to **any imap/smtp account** (imap = how apps read your inbox, smtp = how they send) — one-click presets for gmail, outlook, icloud, yahoo, fastmail, or your own domain
- live inbox that auto-refreshes; open, read, and reply to mail
- compose and send (with cc)
- **ai:** summarize a long thread, turn an email into a task, or turn an email into a calendar event (the ai reads out the date/time/title for you)
- *under the hood:* built directly on python's standard `imaplib`/`smtplib` — no third-party mail library. it pools live connections, caches what it's read, loads the inbox by range (not a slow "search everything"), and opens a message by pulling *only* its text/html body — not the attachments — so it stays fast on a weak connection.

### calendar
**plain version:** a calendar with month / week / day views and repeating events.

- real time-grid week and day views, plus a month grid
- **recurring events** — daily / weekly / monthly
- create an event from plain language via the ai ("lunch with sam friday 1pm")
- optional **two-way sync with caldav** (the open calendar-sync standard used by icloud and google) if you add your credentials

### tasks
**plain version:** a to-do list. simple, fast.

- add tasks, check them off, set priority and a due date
- **active / history tabs** — checking a task off doesn't make it vanish forever; the **history** tab shows everything you've completed, and you can un-check one to send it back to active
- tasks created anywhere (quick-capture, "extract to-dos" from a doc, the ai's `task_add` tool) all land here

### notes
**plain version:** lightweight scratch notes (separate from the full docs app) for when you just want to jot something with zero ceremony — also where home's quick-capture "note" lands as a properly-named note.

### subs
**plain version:** track what you're paying for every month so nothing surprises you.

- weekly / monthly / quarterly / yearly / custom billing cycles
- due dates roll forward automatically as they pass
- monthly **and** yearly totals computed for you
- a **push notification before anything renews** so you can cancel in time

### days
**plain version:** countdowns to things coming up, and day-counts since things that happened.

- birthdays & anniversaries (it knows *which* anniversary — "3 years")
- handles feb 29 sanely
- progress bars, pins, and push reminders as the day approaches

### files
**plain version:** a file browser over any folder you point it at — browse, upload, preview, organize.

- browse folders, upload, rename, delete
- **inline preview** without downloading: images, **pdfs** (in a real pdf viewer), **video**, **audio**, and text/markdown
- download anything with one click

### gallery
**plain version:** a local photo library that feels like icloud/google photos, minus the company.

- your photos grouped into date "moments," plus albums and favorites
- reads **exif** (the camera/date info baked into a photo) and makes thumbnails automatically
- everything stored as plain files under `data/` — they're just your photos in a folder

### contacts
**plain version:** an address book — and one the ai can read and use (e.g. when drafting mail).

### secrets
**plain version:** a password vault. properly encrypted, not just "hidden."

- stores logins/secrets, organized by category
- *under the hood:* each entry is sealed with **aes-256-gcm** (a strong authenticated encryption) under a key derived from your master password with **pbkdf2-hmac-sha-256, 260,000 iterations** (a deliberately slow key-stretch so guessing the password is expensive). the master password is held **in memory only** and never written to disk. locked, the vault is unreadable even to someone holding a full copy of your database.

### automations
**plain version:** *when this happens, do that.* set a rule once and alles runs it for you.

- examples: mail from a certain sender → make a task · a subscription is about to renew → push me · a doc gets saved with `#urgent` → do something · every morning → build me a day digest
- *under the hood:* rules live in the database and fire off a small background job system (see [under the hood](#how-each-app-works-under-the-hood))

**and the smaller stuff:** global search across everything (Cmd/Ctrl+K), scheduled messages (right-click send → have aide message you later), prompt templates / a cookbook, webhooks, api tokens, an openai-compatible api so other tools can use alles as their "openai," backup & restore to a zip, light/dark themes **with a customizable accent color**, and it **installs like an app** (it's a pwa with real push notifications — add it to your home screen/dock and reminders reach you with every tab closed).

---

## aide in depth

aide looks like a normal chat box. the differences are under it:

- **one box, every model.** you register "endpoints" (each is just a web address + an api key) and pick a model. switch providers mid-conversation; aide handles the protocol differences. ([how that works →](#how-the-model-switch-works))
- **it remembers.** long-term memory backed by **local vector search** — *vector search* means it finds memories by *meaning*, not exact words. it uses `fastembed` (an embedding model that runs on your cpu via onnx — no embedding api, no cost, no data leaving), and falls back to keyword search if that's unavailable. you can browse, search, edit, pin, and delete memories, and it can auto-extract durable facts from a conversation.
- **it can act.** *agent mode* is a real autonomous loop (full section below).
- **it researches.** *research mode* runs multiple rounds: search → read the actual pages → pull findings → decide what to search next → write a cited markdown report. free with no key (duckduckgo + wikipedia); better with a free tavily/brave key.
- **it sees.** drop an image and capable providers receive it as vision input.
- **it compares.** run the same prompt across several models at once and vote on the winner.
- **personas & projects.** personas are saved system prompts (give it a character/role). projects group related chats with shared context and files.
- **artifacts.** ask for a webpage/chart/snippet and it renders live in a sandboxed frame next to the chat.
- **voice.** push-to-talk speech-to-text in, text-to-speech out — local (`faster-whisper`) or via a provider, your choice in settings.
- **reasoning view.** for "thinking" models (deepseek-r1, qwen3, claude extended thinking) you get a live "thought for N s" timer and can read the reasoning.

---

## how the model switch works

this is the single most-asked question, so here's the precise answer.

aide does **not** hardcode a provider. you register **endpoints** under settings → models; each endpoint is just a `base_url` (web address) + an `api_key`. when you send a message, aide looks at that url and routes the request to the right protocol. all of that lives in one function, [`detect_provider()` in `services/llm.py`](services/llm.py):

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

**plain version:** there are really only three "languages" ai providers speak. aide speaks all three and translates, so you never have to care which one answered.

**the three wire protocols:**

| protocol | who speaks it | endpoint | notes |
|---|---|---|---|
| **openai-compatible** | openai, deepseek, groq, openrouter, moonshot/kimi, xai/grok, gemini, mistral, perplexity, together, fireworks, cohere, vllm, lm studio, **+ anything that copies the format** | `POST /v1/chat/completions` | the default and the fallback |
| **anthropic messages** | claude | `POST /v1/messages` | different headers, system-prompt placement, and tool/vision shapes |
| **ollama native** | local models via [ollama](https://ollama.com) | `POST /api/chat` | point an endpoint at `http://localhost:11434` and you're fully offline, no keys |

for each, aide builds the correct request body, sends it, and streams the reply back through a parser that **normalizes everything into the same internal events**: `{"delta": …}` for text, `{"thinking": …}` for reasoning tokens, `{"tool_call": …}` for function calls, and `{"done": …, "usage": …}` at the end. the rest of the app only ever sees those four shapes.

details that matter in practice:

- **true token streaming** over sse (server-sent events, the `data: {json}\n\n` format) — not batched. you watch it type.
- **reasoning models** that go quiet before answering show an elapsed-time heartbeat so the ui never looks frozen.
- **vision / tool-calls / tool-results** are translated per provider (e.g. openai `tool_calls` ⇄ anthropic `tool_use` blocks; base64 images ⇄ anthropic image blocks).
- **auto-failover + cooldown:** an endpoint that errors twice gets a 20-second cooldown so one dead provider doesn't stall you.
- **localhost stays direct:** behind an http proxy (e.g. clash), aide honors `NO_PROXY` and sends `localhost`/`127.0.0.1` straight through, so a local model never gets proxied.
- **model lists auto-refresh:** aide periodically re-pulls each provider's available models (and on demand), so new releases show up on their own.
- **zero-config start:** put `DEEPSEEK_API_KEY` or `ANTHROPIC_API_KEY` in `.env` and the matching endpoint is created on first boot — or add any endpoint in the ui with one click (presets for everything above).

aide also **exposes its own** openai-compatible api (`GET /v1/models`, `POST /v1/chat/completions`), so other tools can point at alles as if it were openai.

---

## the agent in depth

**plain version:** agent mode turns the chat into something that *does the task* — it plans, uses tools, checks its work, and reports back, looping on its own for many steps.

*under the hood:* it's a multi-turn loop ([`services/agent_runtime.py`](services/agent_runtime.py)). each turn the model can call tools; results feed back in; it keeps going until done or it hits a turn limit (6 / 18 / 36 turns for low / medium / high "effort"). long runs auto-trim old tool output to stay within the context window, and screenshots are fed back as real vision input.

**the toolset (~58 tools), by category:**

- **files:** `read_file`, `write_file`, `edit_file` (exact find/replace), `apply_patch` (unified diffs), `list_files`, `glob_files`, `grep_files`, `revert_file`
- **shell:** `shell` / `bash` (optionally sandboxed in docker), `execute python`
- **code intelligence:** `code_symbols`, `find_definition`, `diagnostics` (run linters)
- **git:** `git_status`, `git_diff`, `git_branch`, `git_commit`
- **web:** `web_search`, `web_fetch` (fetch + read a page)
- **memory:** `memory_search`, `memory_add`
- **cross-app:** `calendar_list/create/delete`, `task_list/add/done`, `note_list/read/write/search`, `contact_list/add`, `mail_list/read/send`
- **github** (when you connect a token): `github_me`, `github_list_repos`, `github_get_repo`, `github_get_file`, `github_list_issues`, `github_create_issue`, `github_list_prs`, `github_create_pr`, `github_search_code`, `github_search_repos`
- **integrations:** `mcp_list_tools`, `mcp_call_tool` (mcp = model context protocol, a standard for plugging external tools into ai), `opencode_run` (hand a coding subtask to opencode), `skill_list`, `skill_load`
- **delegation:** `spawn_agent`, `spawn_agents` (fire off parallel sub-agents for independent subtasks)
- **computer use** (opt-in, needs `pyautogui`): `screenshot`, `computer_click/move/type/key/scroll` — it can drive your actual screen
- **planning:** `todo_update` (keeps a live checklist you can watch)

**safety:**

- **permission modes** — *full-auto* (does it), *approve* (asks before every change, showing you the exact diff first), or *plan* (read-only — it inspects and writes you a plan, and the change-making tools are removed entirely that turn)
- **checkpoints** — every file edit is snapshotted, so you can **revert a whole run** with one click
- **prompt-injection guard** — when the agent reads something it didn't write (a web page, an email, a file, repo contents, an mcp result), that text is wrapped as *data, not instructions* before it goes back to the model, and scanned for the classic attacks ("ignore previous instructions," "reveal your system prompt," "email the api key to…"). anything that trips gets flagged. so a booby-trapped webpage can't quietly hijack a run. *(it's a seatbelt, not a force field — see security.)*
- **sandbox** — the shell can run inside a docker container with the workspace mounted at `/work` and (optionally) no network, so commands can't touch your real filesystem
- a project-level **`AGENTS.md`** (or `aide.md`) in the working folder is auto-loaded as standing instructions — the same cross-tool convention claude code and others use

---

## how each app works under the hood

the whole point of self-hosting is that nothing is magic. here's what each app *actually does*:

- **docs** — your notes are **real `.md` files** in `data/vault/` (path configurable). the editor is **codemirror 6** doing obsidian-style live preview; it edits the plain text directly, so *what's saved equals what you typed*. `[[wikilinks]]`, backlinks, unlinked mentions, `#tags`, `![[embeds]]`, frontmatter, the graph, the outline, the task rollup, and word count are all computed over those files on demand. images you paste/drop go to `data/vault/_assets/`; templates live in `data/vault/_templates/` (both hidden from the tree). math renders with katex, diagrams with mermaid (lazy-loaded from a cdn; raw text shown if you're offline). every save writes a revision row you can restore.
- **mail** — a thin client over python's stdlib `imaplib`/`smtplib` (no mail dependency). it pools live imap connections, caches reads, loads the inbox by sequence range (no slow `SEARCH ALL`), and opens a message by fetching only its text/html body parts (not attachments) for speed on bad links. a background poll only re-fetches when the mailbox actually changed. credentials are stored locally, encrypted, and never sent back to the browser.
- **research** — a search-and-read loop: pick a query → search (tavily / brave / searxng / google programmable search / serper if you have a key, else duckduckgo → wikipedia for free) → fetch and strip the top pages to text → ask the model for findings → decide what to look up next → write a cited report, streamed live.
- **calendar** — events in sqlite with recurrence expanded on the fly; optional two-way caldav sync if you install `caldav` and add credentials.
- **gallery / photos** — you import photos; pillow makes thumbnails and reads exif; they're grouped into date "moments." stored as plain files under `data/`.
- **secrets** — entries sealed with aes-256-gcm under a pbkdf2-hmac-sha-256 (260k iterations) key derived from your master password, which lives in memory only.
- **automations & jobs** — a small background **job registry + event bus** ([`services/jobs.py`](services/jobs.py)) ticks the recurring work every 30 seconds: subscription renewals, day-event checks, scheduled reminders/messages, automation rules, and a periodic model-list refresh. rules live in the db and fire on events (mail arrived, doc saved, renewal soon, every morning). new features can register their own jobs or react to events without wiring into the main loop.
- **push notifications** — web push implemented straight from the rfcs (vapid keys + message encryption) with **no third-party library**, so reminders, renewals, and scheduled messages reach you even with every tab closed.

---

## keyboard shortcuts & global search

| shortcut | does |
|---|---|
| **Ctrl/Cmd + K** | global search across everything (chats, docs, tasks, mail, …) |
| **Ctrl/Cmd + O** | (in docs) quick-switch to any note by name |
| **Ctrl/Cmd + F** | (in docs) find & replace inside the current note |
| **Ctrl/Cmd + B** | toggle the sidebar |
| **Ctrl/Cmd + ,** | open settings |
| **Ctrl/Cmd + N** | new chat |
| **Ctrl/Cmd + Enter** | send |
| **Ctrl/Cmd + B / I / E / K** | (in docs) bold / italic / inline-code / link |

shortcuts are remappable in settings. global search is fuzzy and grouped by app; from results you jump straight into the item.

---

## quick start

you need **python 3.11 or newer**. then:

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.txt
python app.py
```

open **http://localhost:8000** and you're in.

**no api key is needed to boot.** mail, docs, files, calendar, tasks, subs, days, photos, contacts, secrets — all work out of the box. when you want aide to talk, add a model under **settings → models** (one click for openai / anthropic / deepseek / groq / gemini / ollama and ~10 more), or drop a key like `DEEPSEEK_API_KEY` into `.env`.

not a git person? click the green **code** button at the top of the github page, download the zip, unzip it, and run the same commands inside the folder.

want it fully offline and free? install [ollama](https://ollama.com), `ollama pull` a model, add an endpoint pointing at `http://localhost:11434`, and no key or internet is needed for the ai.

---

## the cli

a small command runs the server for you:

```
alles start         start in the background (waits until it's actually up)
alles stop          stop it
alles restart       restart it
alles status        running/stopped + url + reachability
alles logs [N]      print the last N log lines (default 60)
alles logs -f       follow the log live
alles update        git pull, then restart
alles open          open the browser
```

- **windows (powershell):** `.\alles.cmd start` (powershell needs the `.\`), or just `alles start` if the folder is on your `PATH`
- **windows (cmd):** `alles.cmd start`
- **macos / linux / git bash:** `./alles start`
- **anywhere:** `python app.py`

the launchers find `python3`/`python` on their own. add the alles folder to your `PATH` to type `alles` from any directory.

---

## configuration

copy `.env.example` to `.env`. **everything is optional** — alles runs fine with an empty `.env`. these are the environment variables (settings you set before launch):

| var | default | what it does |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | auto-creates a deepseek endpoint on first boot |
| `ANTHROPIC_API_KEY` | — | auto-creates an anthropic (claude) endpoint on first boot |
| `PORT` | `8000` | port to serve on |
| `SECRET_KEY` | `dev-secret` | signs your login cookie — **change this before exposing alles to a network** |
| `AUTH_ENABLED` | `false` | set `true` to require a password to log in |
| `AUTH_PASSWORD` | — | that password |
| `BASE_DOMAIN` | — | your real domain, for the subdomain setup (see architecture) |
| `TAVILY_API_KEY` | — | better research search (falls back to duckduckgo + wikipedia, no key needed) |

**everything else is configured in the app, under settings** — no files to hand-edit. that includes: model endpoints, mail accounts, the search provider (tavily / brave / searxng / google pse / serper) and fallback chain, voice (stt/tts provider, model, language, voice, speed), the agent (permission mode, max turns/tokens, docker sandbox + image + no-net, sub-agents, computer-use, context files, allowed roots), the system prompt, memory auto-inject, artifacts on/off, context limit + auto-compact, themes/appearance, caldav accounts, webhooks, and api tokens. all of those persist as a settings row in the database.

---

## architecture: one server, many subdomains

alles is **one server** serving **one single-page app**, but each app gets its own subdomain so it feels like a real suite:

```
alles.localhost          the hub (launcher / home)
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

`static/js/subdomain.js` maps each host to the views it shows; `app.js` scopes the sidebar to that app and `navigateTo()` cross-jumps between them. this works **today with zero dns setup** — browsers route `*.localhost` to your own machine automatically.

**one login across all of them.** because a cookie set for `localhost` isn't sent to `*.localhost` subdomains, alles logs you in per-host and quietly relays the session on first cross-navigation via a one-time handoff code — so you authenticate once and every app just works, even on a direct visit or a bookmark.

**on a real domain:** set `BASE_DOMAIN=yourdomain`, put a wildcard reverse proxy in front (e.g. caddy: `*.yourdomain, yourdomain { reverse_proxy 127.0.0.1:8000 }`), and cookies become `Domain=yourdomain; Secure` so single-sign-on spans every subdomain over https.

---

## the api (for other tools)

alles is scriptable. two flavors:

**1. an openai-compatible api.** point any tool that "speaks openai" at alles:

| method | path | does |
|---|---|---|
| `GET` | `/v1/models` | list available models |
| `POST` | `/v1/chat/completions` | chat (streaming or not), openai request/response shape |

**2. the native rest api** (everything the ui uses; all under `/api`). a representative slice:

- **chat/agent:** `POST /api/chat`, `POST /api/chat/stop/{id}`, `GET /api/sessions`, `POST /api/agent/background`, `GET /api/agent/runs`, `POST /api/agent/runs/{id}/revert`, `POST /api/research`
- **docs:** `GET /api/vault-md/tree`, `GET/PUT/POST/DELETE /api/vault-md/file`, `/search`, `/grep`, `/graph`, `/tags`, `/backlinks`, `/unlinked`, `/tasks`, `/templates`, `/youtube`, `/import`, `/export-docx`, `/revisions`
- **mail:** `GET /api/mail/accounts`, `GET /api/mail/inbox/{id}`, `GET /api/mail/message/{id}`, `POST /api/mail/send/{id}`, `POST /api/mail/summarize`, `POST /api/mail/make-task`, `POST /api/mail/extract-event`
- **tasks/calendar/notes/contacts/subs/days:** standard `GET/POST/PATCH/DELETE` on `/api/tasks`, `/api/calendar`, `/api/notes`, `/api/contacts`, `/api/subscriptions`, `/api/days`
- **files/photos:** `/api/files/{list,raw,upload,mkdir,rename,delete}`, `/api/photos/{gallery,gallery/upload,albums,thumb}`
- **secrets:** `/api/vault` (+ `/unlock`, `/lock`, `/{id}/reveal`)
- **memory/personas/projects/cookbook:** `/api/memories` (+ `/search`, `/extract`), `/api/personas`, `/api/projects`, `/api/cookbook`
- **platform:** `/api/settings`, `/api/today`, `/api/backup` (+ `/restore`), `/api/tokens`, `/api/webhooks`, `/api/push/*`, `/api/mcp/*`, `/api/connections`, `/api/automations`, `/api/jobs`

protect it with **api tokens** (settings → tokens) and, if exposed, **`AUTH_ENABLED`**.

---

## your data: where everything lives

everything is in one folder, **`data/`**:

- **`data/aide.db`** — a single sqlite database file holding the structured stuff. ~30 tables: `sessions`, `messages`, `model_endpoints`, `notes`, `tasks`, `calendar_events`, `gallery_images`, `cookbook`, `personas`, `webhooks`, `api_tokens`, `memories`, `projects`, `uploads`, `documents`, `vault_entries`, `contacts`, `mail_accounts`, `albums`, `photos`, `reminders`, `automation_rules`, `day_events`, `subscriptions`, `doc_revisions`, `push_subscriptions`, `session_templates`, `mcp_servers`, `connections`.
- **`data/vault/`** — your docs as plain `.md` files (with `_assets/` for embedded images and `_templates/` for templates).
- **`data/`** (other) — uploads, photos, and file-app content as plain files; **`data/secret.key`** — the encryption key for stored credentials.

*under the hood:* the schema is sqlalchemy models in [`core/database.py`](core/database.py) with lightweight in-place column migrations (it adds new columns to existing tables on boot, so upgrades don't wipe your db). **back up the `data/` folder and you've backed up your entire alles** — or use settings → backup for a zip.

---

## how it's built

```
python 3.11 + fastapi + sqlite (via sqlalchemy)
vanilla js, es modules, one module per feature — no bundler, no build step
httpx for async, streaming model calls
fastembed (onnx) for local embeddings — no embedding api needed
web push implemented straight from the rfcs — zero extra dependencies
```

the dependency list is deliberately tiny — `fastapi`, `uvicorn`, `httpx`, `sqlalchemy`, `pydantic`, `cryptography`, `bcrypt`, `fastembed`, plus `python-docx` and `pillow`. optional extras are opt-in and clearly marked: `pyautogui` (agent computer-use), `faster-whisper` (offline voice), `caldav` (calendar sync), `pypdf` (pdf import).

the frontend is genuinely just files: `static/index.html` is the whole app shell, `static/js/` is **one es module per feature** (~40 of them — `app.js`, `chat.js`, `vaultmd.js`, `mail.js`, `agent`-related, etc.) imported by `app.js`, and `static/style.css` holds the design tokens (sharp, monochrome, 2–3px radii, no shadows). "view source" actually shows you the app. the **one** exception is the docs editor: codemirror 6 is vendored as a single pre-built file (`static/vendor/cm6.bundle.js`), so there's still no build step you have to run.

---

## project layout

```
alles/
├── app.py                 fastapi entry — routers, middleware, lifespan, background jobs, env bootstrap
├── cli.py                 the alles cli (start/stop/restart/status/logs/update/open)
├── core/
│   ├── database.py        every sqlalchemy model + lightweight migrations
│   ├── settings.py        settings load/save, base-domain helpers
│   └── auth.py            bcrypt login, in-memory tokens, cross-subdomain handoff
├── services/
│   ├── llm.py             provider-agnostic streaming client (the model switch)
│   ├── agent_runtime.py   the autonomous agent loop
│   ├── agent_tools.py     every agent tool (+ the prompt-injection guard)
│   ├── agent_state.py     durable agent run logs / checkpoints
│   ├── jobs.py            background job registry + event bus
│   ├── research_engine.py search + read-the-page research loop
│   ├── mail.py            imap/smtp over stdlib
│   ├── vault_md.py        markdown docs on disk (tree, links, tags, graph, tasks)
│   ├── doc_import.py      import .md/.txt/.docx/.html/.pdf → markdown
│   ├── youtube.py         youtube transcript → note
│   ├── memory_store.py    fastembed vector memory + keyword fallback
│   ├── crypto.py          aes-256-gcm vault encryption
│   ├── webpush.py         web push from the rfcs
│   └── …                  files, photos, caldav, automations, docx export, stt
├── routes/                one apirouter per feature, all under /api (+ /v1 openai-compat)
├── tests/                 unit tests
└── static/
    ├── index.html         the app shell
    ├── style.css          design tokens + all styling
    ├── sw.js              service worker (offline shell + push)
    ├── vendor/            the prebuilt codemirror 6 bundle (no build step)
    └── js/                ~40 es modules, one per feature, imported by app.js
```

---

## security — read before exposing it

alles is built for **one person on their own machine.** read this before you put it on a network.

- **it ships open.** auth is off by default. if alles is reachable beyond localhost, set `AUTH_ENABLED=true`, a strong `AUTH_PASSWORD`, and a real `SECRET_KEY` **first**. without auth, anyone who can reach the port can read your mail and files and run shell commands as you.
- **aide has hands.** agent mode and the shell tools run real commands on the machine alles is on. that's the point — but don't hand access to people or models you don't trust. the prompt-injection guard reduces the risk of a malicious web page/email steering the agent, but treat it as a seatbelt, not a force field.
- **credentials are encrypted at rest with a local key.** model api keys and mail passwords are sealed with aes-256-gcm under `data/secret.key`. this protects the database file if it leaks *on its own* — it does **not** protect against someone who has the whole `data/` folder, because the server must be able to decrypt unattended.
- **backups are the whole safe, key included.** a backup zip contains the database **and** the keys so restores just work — which means a backup is exactly as sensitive as your live data. store it like a password.
- **the password vault is different.** vault secrets are encrypted with your **master password**, which never touches disk. no master password, no plaintext — not even from a full copy of `data/`.
- **no warranty.** this is a self-hosted hobby project, not an audited security product. it tries hard; you run it at your own risk.

---

## performance & reliability

small touches that keep it snappy and sturdy:

- **streaming everywhere** so you never wait on a full response to start reading
- **endpoint cooldown** — a provider that errors twice is benched for 20s instead of stalling you
- **mail**: connection pooling, read caching, body-only fetches, and a change-detecting poll
- **service worker** caches the app shell for instant loads + offline, and serves the codemirror bundle stale-while-revalidate (fast, but always refreshes in the background so updates land)
- **agent context trimming** so long autonomous runs don't blow the model's context window
- **lightweight migrations** so upgrading the app never throws away your database
- **graceful degradation** — no search key → free providers; offline → cached shell + local model; missing optional dep → that one feature is disabled with a clear message, nothing else breaks

---

## testing

```bash
python -m unittest discover -s tests
```

**76 unit tests** and counting — covering the docs vault (links, tags, graph, tasks, templates, asset/import handling, unlinked mentions), document import, the youtube id parser, the job registry + event bus, the agent's tool-gating and prompt-injection guard, mail parsing, crypto, the model client, photos, and more.

---

## what it's based on

aide was inspired by **[odysseus](https://github.com/pewdiepie-archdaemon/odysseus)** by pewdiepie-archdaemon. the concept — a self-hosted personal ai with memory, research mode, shell access, mcp, a multi-provider model backend, and a suite of apps around it — comes from that project. alles is an independent reimplementation written from scratch, but odysseus is where the idea came from and it deserves the credit. go give that repo a star. full note in [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md).

it stands on the shoulders of some great open-source work: [fastapi](https://fastapi.tiangolo.com) + [uvicorn](https://www.uvicorn.org), [sqlalchemy](https://www.sqlalchemy.org), [httpx](https://www.python-httpx.org), [fastembed](https://github.com/qdrant/fastembed), [codemirror](https://codemirror.net), [katex](https://katex.org), [mermaid](https://mermaid.js.org), [pillow](https://python-pillow.org), [python-docx](https://python-docx.readthedocs.io), [pypdf](https://pypdf.readthedocs.io), [cryptography](https://cryptography.io), and python's own `imaplib`/`smtplib`. models come from whichever provider you point it at; local ones via [ollama](https://ollama.com).

---

## license

mit. do whatever you want with it. if you build something cool on top, a link back is appreciated but not required.
