# alles

```
─────────────────────────────────────────────
 ⊹ ࣪ ˖ ( ◕ ‿ ◕ )つ  alles — your everything
─────────────────────────────────────────────
```

your everything-app, self-hosted. AI, mail, docs, files, calendar, tasks, photos, contacts, passwords, subscriptions, and countdowns — one login, one place, running on your own machine. your data never leaves it.

alles is the ecosystem. **aide** is the AI inside it — think Gemini to Google. aide can read and act across every app: your mail, your docs, your calendar, all of it. and with automation rules, alles quietly works for you even when you're not looking.

## features

- **aide** — streaming chat with any model, plus an agent mode that does real work.<br>　<sub>DeepSeek · Claude · GPT · Gemini · Grok · Ollama · any OpenAI-compatible endpoint · long-term memory · personas · deep research · model compare · image gallery</sub>
- **today** — your whole day on one screen the moment you open alles.<br>　<sub>today's events · overdue tasks · renewals this week · unread mail · recent docs · "ask aide about my day"</sub>
- **automation rules** — when this happens, do that. set it once, forget it.<br>　<sub>mail from X → task · renewal soon → push · doc saved with #tag → action · every morning → day digest</sub>
- **mail** — a real IMAP/SMTP client with a live inbox and AI built in.<br>　<sub>auto-refresh · one-click setup for Gmail / Outlook / iCloud / Yahoo / Fastmail · summarize · mail → task · mail → calendar event (AI-extracted)</sub>
- **docs** — a real WYSIWYG editor on top of plain markdown files.<br>　<sub>wikilinks · backlinks · graph view · tags · embeds · version history with restore · AI edits · extract-todos · underline / highlight / wikilink toolbar · .docx export</sub>
- **calendar** — month, week, and day views with recurring events.<br>　<sub>CalDAV sync (iCloud / Google) · .ics aware · recurrence</sub>
- **subs** — a subscription manager that actually understands billing.<br>　<sub>weekly / monthly / quarterly / yearly / custom cycles · due dates roll over on their own · monthly + yearly totals · push before anything renews</sub>
- **days** — countdowns to what's ahead, day counts since what's behind.<br>　<sub>birthdays & anniversaries (knows which one it is) · feb 29 handled · progress bars · pins · push reminders</sub>
- **files** — browse, upload, preview, and edit over any folder you point it at.
- **gallery** — a local photo library that works like iCloud Photos, minus Apple.<br>　<sub>albums · favorites · EXIF · thumbnails</sub>
- **tasks & notes** — quick capture, zero ceremony.
- **contacts** — an address book aide can use.
- **secrets** — an encrypted password vault.<br>　<sub>AES-256-GCM · master password never touches disk · locked = invisible</sub>
- **installs like an app** — alles is a PWA with real push notifications.<br>　<sub>add to home screen / dock · offline shell · reminders & renewals reach you with every tab closed</sub>

plus: artifacts, voice in and out, global search (Cmd/Ctrl+K), scheduled messages (right-click send), shell & MCP tools, prompt templates, webhooks, API tokens, OpenAI-compatible API, backup/restore, incognito sessions, light/dark theme.

## quick start

you need **Python 3.11+**, then:

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.txt
python app.py
```

open **http://localhost:8000** and you're in.

no API key needed to boot — mail, docs, files, calendar, tasks, subs, days all work out of the box. when you want aide to talk, add a model under **settings → models** (one click for OpenAI / Anthropic / DeepSeek / Groq / Gemini / Ollama / 10+ more), or drop a key like `DEEPSEEK_API_KEY` into `.env`.

prefer not to use git? hit the green **Code** button above, download the zip, unzip, run the same commands inside the folder.

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

windows (powershell): `.\alles.cmd start` — powershell needs the `.\` to run a script from the current folder. windows (cmd): `alles.cmd start`. unix / git-bash: `./alles start`. or anywhere: `python app.py`. add the folder to PATH to drop the prefix.

the launchers find `python3` or `python` automatically.

## configuration

copy `.env.example` to `.env`. everything is optional:

| var | default | what it does |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | auto-creates a DeepSeek endpoint on first boot |
| `ANTHROPIC_API_KEY` | — | auto-creates an Anthropic endpoint on first boot |
| `PORT` | `8000` | port to serve on |
| `SECRET_KEY` | `dev-secret` | signs your session — change it before exposing alles to a network |
| `AUTH_ENABLED` | `false` | set `true` to require a password |
| `AUTH_PASSWORD` | — | that password |
| `TAVILY_API_KEY` | — | better search in research mode (falls back to DuckDuckGo) |

everything else — models, mail accounts, voice, search providers, automations, appearance — is configured in the UI under **settings**.

## how it's built

```
Python 3.11 + FastAPI + SQLite (SQLAlchemy)
vanilla JS, ES modules, no bundler, no build step
fastembed (ONNX) for local embeddings
httpx for async model streaming
web push implemented from the RFCs — zero extra dependencies
```

every app lives on its own subdomain (`mail.`, `docs.`, `subs.`, …) and shares one login. all your data lives in `data/` — one SQLite file plus your uploads. nothing is sent anywhere you don't configure.

## security notes

alles is built for one person on their own machine. read this before exposing it to anything beyond localhost.

- **it ships open.** auth is off by default. if alles is reachable from your network, set `AUTH_ENABLED=true`, `AUTH_PASSWORD`, and a real `SECRET_KEY` first. without auth, anyone who can reach the port can read your mail, your files, and run shell commands as you.
- **aide has hands.** agent mode and the shell tools execute real commands on the machine alles runs on. that's the point — but don't give access to people or models you don't trust.
- **credentials are encrypted at rest, with a local key.** model API keys and mail passwords are sealed with AES-256-GCM under a key in `data/secret.key`. this protects the database file if it leaks on its own — it does not protect against someone with full access to the `data/` folder, because the server must be able to decrypt unattended.
- **backups are the whole safe, key included.** a backup zip contains the database *and* the encryption keys, so restores just work — which also means a backup is exactly as sensitive as your live data. store it like a password.
- **vault entries are different.** secrets in the password vault are encrypted with your master password, which never touches disk. no master password, no plaintext — not even from a full copy of `data/`.
- **no warranty.** this is a self-hosted hobby project, not an audited security product. it tries hard, but you run it at your own risk.

## acknowledgments

aide was inspired by [odysseus](https://github.com/pewdiepie-archdaemon/odysseus) by pewdiepie-archdaemon — the feature set, product vision, and architecture patterns originate there. aide is an independent reimplementation written from scratch. full credit in [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md).
