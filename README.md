# alles

read this in: **english** · [français](docs/readme/README.fr.md) · [español](docs/readme/README.es.md) ·
[简体中文](docs/readme/README.zh-Hans.md) · [繁體中文](docs/readme/README.zh-Hant.md) ·
[日本語](docs/readme/README.ja.md) · [한국어](docs/readme/README.ko.md) · [العربية](docs/readme/README.ar.md)

```
─────────────────────────────────────────────
 ⊹ ࣪ ˖ ( ◕ ‿ ◕ )つ  alles — your everything
─────────────────────────────────────────────
```

**alles** is a self-hosted everything-app. one single python program that runs on your machine and gives you ai chat, search, email, linked docs, a journal, files, a calendar, tasks, money & budgets, photos, contacts, a secrets vault, subscription tracking, and countdowns. all behind one login, with local data in a folder you control. there is no telemetry; model, search, mail, and sync providers receive only the requests you choose to send through them.

think of **alles** as the whole house, and **aide** as the assistant who lives in it: like what gemini is to google, except it's yours and it can actually open the other rooms (read your mail, edit your docs, add to your calendar, file your tasks).

it's *one python process*. no build step, no bundler, no `node_modules`, no account, no analytics. you clone it, run `python app.py`, and open a browser. that's the entire setup.

<p align="center"><em>one interface to run your whole digital life.</em></p>

---

## what it runs on

- **backend**: python 3.11, fastapi, sqlite, sqlalchemy
- **frontend**: vanilla js, es modules, plain css (no build step, no bundler)
- **ai layer**: httpx (streaming), fastembed (local vectors), unified openai/anthropic/ollama client
- **extras**: web push (native), codemirror 6 (markdown), trafilatura (web scraping)


## the 30-second version

- **everything in one place, one login.** stop bouncing between fifteen tabs and ten companies.
- **it's yours.** all your data is plain files + one database in a folder called `data/`. use the encrypted backup flow to protect managed data and configured external vaults. deleting the app keeps your personal files.
- **the ai isn't a gimmick.** it talks to *any* model (claude, gpt, deepseek, gemini, a local model, all switchable mid-chat), remembers things on your terms, and can use approved tools and continue longer work in the background within Aide.
- **local by default.** there is no telemetry, your main data stays on your machine, and Aide can run offline with a local model. connected providers see the requests you send to them.
- **single user, on purpose.** this is *your* workspace, not a service you host for a hundred people. it's your personal un-siloed digital brain.

## is this for me?

if you've ever wished you could mash together **notion + gmail + obsidian + google photos + google calendar + a password manager + a chatgpt that can actually open your files**, and own the whole thing on hardware you control: yes.

if you want a multi-user team product with billing and admin roles: no, that's not what this is. alles is deliberately one person, one machine.

you do **not** need to be technical to *use* it. you need to be a little technical to *install* it (two commands in a terminal, once). the rest is clicking around a normal-looking app.

---

## the apps

alles has three primary spaces and nine specialist apps. each app shares the same navigation;
older links open the matching section inside its current app.

| space or app | what you can do |
|---|---|
| **home** | see what needs attention, your schedule, running work, briefs, and pinned apps; capture a task without an ai model |
| **aide** | chat, use approved tools, and run background or scheduled work; group conversations in General or folder-backed Projects |
| **andromeda** | search the web and inspect normal results with an optional cited overview |
| **plan** | manage your agenda, week, task board, calendar, tasks, reminders, and countdowns |
| **inbox** | read configured imap/smtp mail and manage contacts |
| **docs** | read and edit owned markdown notes and journal entries |
| **files** | browse local or configured online storage, keep offline copies, and open the photo gallery |
| **library** | manage saved articles, reading lists, and news |
| **health** | track habits and health records |
| **finance** | manage accounts, transactions, budgets, subscriptions, and imports; optional bank and Actual connections need setup |
| **vault** | keep encrypted secrets, passwords, passkeys, and paired browser access |
| **server** | inspect system health, services, backups, updates, activity, and access policy |

plus the smaller stuff: global search (cmd/ctrl+k), scheduled messages, prompt cookbook, webhooks, api tokens, an openai-compatible api, encrypted local, WebDAV, and S3-compatible backup with an offline staged restore and rollback, light/dark themes with a custom accent, and it installs like a pwa with real push notifications.

**→ full details on every app, the internals, the api, and the architecture are in [specifications.md](./specifications.md).**

---

## quick start

you need **python 3.11 or newer**. then:

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.lock
python app.py
```

open **http://localhost:6769** and you're in.

on `dev-afterlife`, the new shell and Andromeda are still behind explicit release flags. preview the
delivered Phase 4 surfaces with:

```bash
ALLES_AFTERLIFE_FEATURES=afterlife_shell,afterlife_today,afterlife_aide_projects,afterlife_andromeda,afterlife_jarvis,afterlife_storage_locations python app.py
```

**want a normal mac/linux install?** run `./alles install` once. it builds a private,
versioned Python environment, adds the `alles` launcher, and registers a user-owned launchd or
systemd service. program releases stay separate from private app data and the visible Vault/Files
folders. `alles update` stages and health-checks a new release with encrypted rollback data;
`alles update rollback` restores the paired code and data. `./alles uninstall` removes only verified
program, launcher, and service files and keeps personal data.

on a server with a venv:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock
./alles install      # now `alles start` works anywhere
```

if you only want the old checkout launcher without a managed runtime or service, use
`./alles install --launcher-only` and remove it with `./alles uninstall --launcher-only`.

**no ai api key is needed to boot.** local docs, files, calendar, tasks, and other local tools work without a model. mail, online storage, bank connections, and remote providers need their own setup. when you want aide to talk, add a model under **settings → models** (one click for openai / anthropic / deepseek / groq / gemini / ollama and ~10 more), or drop a key like `deepseek_api_key` into `.env`.

**prefer docker?** `docker build -t alles . && docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles`. the `data/` volume keeps your db, vault, uploads, and keys across rebuilds. the loopback-only port keeps the fresh container on this device. native LAN access requires `ALLES_ACCESS_PROFILE=lan`, enabled authentication, and a real owner password. public access also requires an HTTPS public URL, matching base domain, trusted hosts, and exact proxy IPs; see `.env.example` for the setting names.

**want it fully offline and free?** install [ollama](https://ollama.com), `ollama pull` a model, add an endpoint pointing at `http://localhost:11434`. no key or internet needed for the ai.

Andromeda can use DuckDuckGo or another configured provider, including an external HTTPS SearXNG
instance. the bundled SearXNG service is pinned and loopback-only. managed installation requires
a supported Docker runtime and data location; Server reports the reason when those are unavailable.

> **before you put it on a network:** alles ships with auth off. set `auth_enabled=true`, a strong `auth_password`, and a real `secret_key` first. details in the [security section](./specifications.md#security--read-before-exposing-it).

---

## backups

open **settings → backup** to download an encrypted `.alles-backup`, or send the same encrypted file to an existing https WebDAV folder or S3-compatible bucket. remote backup is manual right now and is not Files sync.

first-run Protection can also enable a daily encrypted local backup to a folder outside Alles data.
Alles checks hourly, creates at most one artifact per day, keeps the newest seven artifacts it owns,
and leaves unrelated files alone. remote WebDAV and S3 targets remain manual.

before the first remote backup, download the recovery key. keep that key and your remote-storage login somewhere outside Alles. the recovery-key file is never uploaded separately or in plaintext.

a restore verifies and stages the data without changing the live install. stop Alles, then run the `alles restore apply ...` command shown in the UI. disconnecting a target removes its saved login from Alles; it does not delete remote backups.

the WebDAV folder must support `PROPFIND`, `PUT`, `MOVE`, `GET`, and `DELETE`.

S3 backup needs an existing bucket, an https endpoint, a region, and an access-key pair. path-style and virtual-hosted endpoints are supported. this first version uses one conditional server-side copy per backup, so each encrypted artifact must be 5 GB or smaller.

## passwords in your browser

unlock Passwords, open its settings, and download the Alles Passwords extension from **connected
browsers**. unzip it, load it from `chrome://extensions` with developer mode enabled, then enter your
exact Alles origin in the popup. verify and approve the pairing code inside Passwords.

pairing does not unlock anything. each fill session needs a separate owner approval, lives for five
minutes, matches the exact scheme/host/port, and releases only the login you select. the extension
fills the current top-level login form but never submits it. browser/server restart, explicit lock,
computer lock, or revoke removes fill authority.

---

## what it's based on

aide was inspired by **[odysseus](https://github.com/pewdiepie-archdaemon/odysseus)** by pewdiepie-archdaemon. the concept (a self-hosted personal ai with memory, research mode, shell access, mcp, a multi-provider model backend, and a suite of apps around it) comes from that project. alles is an independent reimplementation written from scratch, but odysseus is where the idea came from and it deserves the credit. go give that repo a star. full note in [acknowledgments.md](./acknowledgments.md).

it stands on the shoulders of some great open-source work: [fastapi](https://fastapi.tiangolo.com) + [uvicorn](https://www.uvicorn.org), [sqlalchemy](https://www.sqlalchemy.org), [httpx](https://www.python-httpx.org), [fastembed](https://github.com/qdrant/fastembed), [codemirror](https://codemirror.net), [leaflet](https://leafletjs.com) with map tiles from [openstreetmap](https://www.openstreetmap.org/copyright), [katex](https://katex.org), [mermaid](https://mermaid.js.org), [pillow](https://python-pillow.org), [python-docx](https://python-docx.readthedocs.io), [pypdf](https://pypdf.readthedocs.io), [cryptography](https://cryptography.io), and python's own `imaplib`/`smtplib`. models come from whichever provider you point it at; local ones via [ollama](https://ollama.com).

---

## license

mit. do whatever you want with it. if you build something cool on top, a link back is appreciated but not required.
