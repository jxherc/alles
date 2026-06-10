# alles

your everything-app, self-hosted. one place for your AI, mail, docs, files, calendar, tasks, photos, contacts, and passwords — all running on your own machine, your data never leaving it.

alles is the ecosystem. **aide** is the AI inside it, think Gemini to Google. aide can read and act across every app: your mail, your docs, your calendar, all of it.

## what's inside

every app lives on its own subdomain and shares one login.

- **aide** — streaming chat with any model (DeepSeek, Claude, GPT, Gemini, Grok, local Ollama...). agent mode, long-term memory, side-by-side model compare, image gallery, and deep research.
- **mail** — a real IMAP/SMTP client. one-click setup for Gmail, Outlook, iCloud, Yahoo, Fastmail, or bring your own. one click turns a mail into a calendar event (AI-extracted).
- **docs** — a WYSIWYG editor that stores plain markdown underneath. wikilinks, embeds, tags, backlinks, graph view, AI editing, and version history with restore.
- **files** — browse, upload, and preview files over any folder you point it at.
- **calendar** — month, week, and day views, recurring events, CalDAV sync.
- **tasks** — quick lists, nothing fancy.
- **subs** — a subscription manager. billing cycles, next-due dates that roll over on their own, monthly/yearly totals, and a push notification before anything renews.
- **days** — countdowns and day counters. counts down to a trip, counts up since you quit something, tracks birthdays and anniversaries every year (which one it is included), and pings you before the day arrives.
- **gallery** — a local photo library with albums, favorites, and EXIF. works like iCloud Photos, minus Apple.
- **contacts** — an address book.
- **secrets** — an encrypted password vault (AES-256-GCM), unlocked by a master password that never touches disk.

plus: artifacts, voice in and out, global search (Cmd/Ctrl+K), shell and MCP tools, personas, prompt templates, webhooks, API tokens, backup/restore, incognito sessions, and a light/dark theme.

alles also installs as an app: add it to your home screen or dock (it's a PWA), and reminders reach you as push notifications even when no tab is open — enable them in the reminders view.

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
alles start         start the server in the background (waits until it's actually up)
alles stop          stop it
alles restart       restart it
alles status        running/stopped + url + reachability
alles logs [N]      print the last N log lines (default 60)
alles logs -f       follow the log live
alles update        git pull, then restart
alles open          open the browser
```

windows (powershell): `.\alles.cmd restart` — powershell needs the `.\` to run a script from the current folder. windows (cmd): just `alles.cmd restart`. unix / git-bash: `./alles restart`. or anywhere: `python app.py`. add the folder to PATH to drop the prefix.

the launchers find `python3` or `python` automatically, so `./alles` works whether or not bare `python` is on your PATH.

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

## security notes

alles is built for one person on their own machine. read this before exposing it to anything beyond localhost.

- **it ships open.** auth is off by default. if alles is reachable from your network (or worse, the internet), set `AUTH_ENABLED=true`, `AUTH_PASSWORD`, and a real `SECRET_KEY` first. without auth, anyone who can reach the port can read your mail, your files, and run shell commands as you.
- **aide has hands.** agent mode and the shell tools can execute real commands on the machine alles runs on. that's the point — but it means a prompt, a model, or anyone with access to the UI can do real things. don't give access to people or models you don't trust.
- **credentials are encrypted at rest, with a local key.** model API keys and mail passwords are sealed with AES-256-GCM under a key in `data/secret.key`. this protects the database file if it leaks on its own — it does not protect against someone with full access to the `data/` folder, because the server must be able to decrypt unattended.
- **backups are the whole safe, key included.** a backup zip contains the database *and* `secret.key`, so restores just work — which also means a backup is exactly as sensitive as your live data. store it like a password.
- **vault entries are different.** secrets in the password vault are encrypted with your master password, which never touches disk. no master password, no plaintext — not even from a full copy of `data/`.
- **no warranty.** this is a self-hosted hobby project, not an audited security product. it tries hard, but you run it at your own risk.

## acknowledgments

aide was inspired by [odysseus](https://github.com/pewdiepie-archdaemon/odysseus) by pewdiepie-archdaemon — the feature set, product vision, and architecture patterns originate there. aide is an independent reimplementation written from scratch. full credit in [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md).
