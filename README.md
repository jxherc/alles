# alles

**your everything-app, self-hosted.** one place for your AI, mail, docs, files, calendar, tasks, photos, contacts, and passwords — all running on your own machine, your data never leaving it.

alles is the ecosystem. **aide** is the AI inside it — think Gemini to Google. aide can read and act across every app: your mail, your docs, your calendar, all of it.

---

## what's inside

every app lives on its own subdomain (`aide.localhost:8000`, `mail.localhost:8000`, …) and shares one login.

- **aide** — streaming chat with any model (DeepSeek, Claude, GPT, Gemini, Grok, local Ollama…). agent mode that uses tools and acts across your apps, long-term memory, side-by-side model compare, an image gallery, and deep research.
- **mail** — a real IMAP/SMTP client. one-click setup for Gmail / Outlook / iCloud / Yahoo / Fastmail, or bring your own domain. inbox · unread · sent, and reading a mail actually marks it read.
- **docs** — a visual **WYSIWYG editor** (write like Google Docs: a toolbar, visual tables, images, code, a color picker) that's plain **markdown underneath**, with a pure-markdown tab. plus `[[wikilinks]]`, embeds, tags, backlinks, a graph view, and AI editing.
- **files** — browse, upload, and preview files over any folder you point it at.
- **calendar** — month / week / day, recurring events, CalDAV sync.
- **tasks** — quick lists, nothing fancy.
- **gallery** — a local photo library with albums, favorites, and EXIF — works like iCloud Photos, minus Apple.
- **contacts** — an address book.
- **secrets** — an encrypted password vault (AES-256-GCM), unlocked by a master password that never touches disk.

plus: artifacts (live HTML/SVG/code panels), voice in and out, global search (`Cmd/Ctrl+K`) across everything, shell + MCP tools, personas, prompt templates, webhooks, API tokens, backup/restore, incognito sessions, and a light/dark theme.

---

## get started

you need **Python 3.11+**. then:

```
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.txt
python app.py
```

open **http://localhost:8000** — done.

> no API key needed to boot. mail, docs, files, calendar, tasks — all work out of the box. when you want aide to talk, add a model in **settings → models** (or drop a `DEEPSEEK_API_KEY` into `.env`).

**prefer not to use git?** hit the green **Code** button above → *Download ZIP*, unzip it, and run the same three commands from inside the folder.

---

## writing in docs — markdown guide

the docs editor is **visual** — a toolbar + WYSIWYG, like Google Docs — but it stores plain **markdown**. you rarely need to type syntax, but you can (flip to the **Markdown** tab). here's the vocabulary, also in-app via **guide**:

| you type | you get |
|---|---|
| `# H1`  `## H2`  `### H3` | headings |
| `**bold**` | **bold** |
| `*italic*` | *italic* |
| `~~strike~~` | ~~strikethrough~~ |
| `==highlight==` | highlighted text |
| `{color:red}text{/color}` | colored text (name or #hex) |
| `` `code` `` | inline code |
| `> quote` | blockquote |
| `- item` | bullet list |
| `1. item` | numbered list |
| `- [ ] todo` · `- [x] done` | task list with checkboxes |
| `[text](url)` | link |
| `![alt](url)` | image |
| `[[doc]]` · `[[doc\|alias]]` | link another doc — click to jump |
| `![[doc]]` · `![[pic.png]]` | embed a doc or image inline |
| `#tag` | tag — click it to filter docs |
| `> [!note] title` | callout box (note · tip · warning · danger) |
| `---` | divider |

**code blocks** — fence with triple backticks and a language:

````
```python
print("hello from inside a doc")
```
````

**frontmatter** — a `---` fenced block at the very top of a doc becomes a properties panel:

```
---
title: my note
tags: ideas
---
```

**tables** — pipe columns with a separator row:

```
| col a | col b |
|-------|-------|
| 1     | 2     |
```

switch between the **WYSIWYG** and **Markdown** tabs at the bottom-right of the editor any time. links between docs build a backlink list and a graph automatically.

---

## slash commands

type these in aide's chat box:

| command | what it does |
|---|---|
| `/new` | start a new chat |
| `/clear` | clear the display (keeps history) |
| `/rename [name]` | rename the chat — blank lets the AI name it |
| `/archive` | archive this chat |
| `/export` | download the chat as markdown |
| `/incognito` | start a chat that saves nothing |
| `/model` | open the model picker |
| `/persona [name]` | switch persona |
| `/research` | toggle research mode |
| `/agent` | toggle agent mode |
| `/remember <text>` | save something to memory |
| `/memories` | open memory (settings → memory) |
| `/forget <id>` | delete a memory by id |
| `/todo <task>` | add a task |
| `/note <text>` | jot a note |
| `/compare` | open model compare |
| `/docs` | open the doc editor |
| `/search [query]` | open global search |
| `/system <prompt>` | set this chat's system prompt |
| `/backup` | download a backup zip |
| `/help` | list every command in chat |

add your own under **settings → cookbook**.

---

## cli

```
alles start      start the server in the background
alles stop       stop it
alles restart    restart it
alles status     running/stopped + url
alles logs       tail the log
alles open       open the browser
```

windows: `alles.cmd` (add the folder to PATH). unix / git-bash: `./alles` (already executable). or just `python app.py`.

---

## configuration

copy `.env.example` to `.env` and set whatever you need — everything is optional:

| var | default | for |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | auto-creates a DeepSeek endpoint on first boot |
| `ANTHROPIC_API_KEY` | — | auto-creates an Anthropic endpoint on first boot |
| `PORT` | `8000` | port to serve on |
| `SECRET_KEY` | `dev-secret` | signs your session — **change it** if you expose alles on a network |
| `AUTH_ENABLED` | `false` | `true` requires a password to open alles |
| `AUTH_PASSWORD` | — | that password (bcrypt-hashed on first boot) |
| `TAVILY_API_KEY` | — | better research-mode search — falls back to DuckDuckGo without it |

add Ollama, OpenAI, OpenRouter, Groq, Gemini, and friends under **settings → models → add endpoint**.

---

## stack

```
Python 3.11 + FastAPI + SQLite (SQLAlchemy)
vanilla JS — ES modules, no bundler (Toast UI Editor vendored for docs)
fastembed (ONNX) for local embeddings
httpx for async model streaming
```

all your data lives in `data/` — one SQLite file plus uploads. nothing is sent anywhere you don't configure.

---

## acknowledgments

aide was inspired by [odysseus](https://github.com/pewdiepie-archdaemon/odysseus) by pewdiepie-archdaemon — the feature set, product vision, and architecture patterns originate there. aide is an independent reimplementation written from scratch. full credit in [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md).
