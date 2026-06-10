# alles

your everything-app, self-hosted. one place for your AI, mail, docs, files, calendar, tasks, photos, contacts, and passwords — all running on your own machine, your data never leaving it.

alles is the ecosystem. **aide** is the AI inside it, think Gemini to Google. aide can read and act across every app: your mail, your docs, your calendar, all of it.

## what's inside

every app lives on its own subdomain and shares one login.

- **aide** — streaming chat with any model (DeepSeek, Claude, GPT, Gemini, Grok, local Ollama...). agent mode, long-term memory, side-by-side model compare, image gallery, and deep research.
- **mail** — a real IMAP/SMTP client. one-click setup for Gmail, Outlook, iCloud, Yahoo, Fastmail, or bring your own.
- **docs** — a WYSIWYG editor that stores plain markdown underneath. wikilinks, embeds, tags, backlinks, graph view, and AI editing.
- **files** — browse, upload, and preview files over any folder you point it at.
- **calendar** — month, week, and day views, recurring events, CalDAV sync.
- **tasks** — quick lists, nothing fancy.
- **gallery** — a local photo library with albums, favorites, and EXIF. works like iCloud Photos, minus Apple.
- **contacts** — an address book.
- **secrets** — an encrypted password vault (AES-256-GCM), unlocked by a master password that never touches disk.

plus: artifacts, voice in and out, global search (Cmd/Ctrl+K), shell and MCP tools, personas, prompt templates, webhooks, API tokens, backup/restore, incognito sessions, and a light/dark theme.

## get started

you need **Python 3.11+**, then:

```
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.txt
python app.py
```

open **http://localhost:8000** and you're in.

no API key needed to boot. mail, docs, files, calendar, tasks — all work out of the box. when you want aide to talk, add a model in settings > models, or drop a key like `DEEPSEEK_API_KEY` into `.env`.

prefer not to use git? hit the green Code button above, download the zip, unzip it, and run the same commands from inside the folder.

## cli

```
alles start      start the server in the background
alles stop       stop it
alles restart    restart it
alles status     running/stopped + url
alles logs       tail the log
alles open       open the browser
```

windows: `alles.cmd` (add the folder to PATH). unix / git-bash: `./alles`. or just `python app.py`.

## configuration

copy `.env.example` to `.env`. everything is optional:

| var | default | what it does |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | auto-creates a DeepSeek endpoint on first boot |
| `ANTHROPIC_API_KEY` | — | auto-creates an Anthropic endpoint on first boot |
| `PORT` | `8000` | port to serve on |
| `SECRET_KEY` | `dev-secret` | signs your session, change it if you expose alles on a network |
| `AUTH_ENABLED` | `false` | set to `true` to require a password |
| `AUTH_PASSWORD` | — | that password |
| `TAVILY_API_KEY` | — | better search in research mode, falls back to DuckDuckGo without it |

you can add Ollama, OpenAI, OpenRouter, Groq, Gemini, and others under settings > models > add endpoint.

## stack

```
Python 3.11 + FastAPI + SQLite (SQLAlchemy)
vanilla JS, ES modules, no bundler
fastembed (ONNX) for local embeddings
httpx for async model streaming
```

all your data lives in `data/`, one SQLite file plus uploads. nothing is sent anywhere you don't configure.

## acknowledgments

aide was inspired by [odysseus](https://github.com/pewdiepie-archdaemon/odysseus) by pewdiepie-archdaemon — the feature set, product vision, and architecture patterns originate there. aide is an independent reimplementation written from scratch. full credit in [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md).
