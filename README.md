# alles

[français](docs/readme/README.fr.md) · [español](docs/readme/README.es.md) ·
[简体中文](docs/readme/README.zh-Hans.md) · [繁體中文](docs/readme/README.zh-Hant.md) ·
[日本語](docs/readme/README.ja.md) · [한국어](docs/readme/README.ko.md) ·
[العربية](docs/readme/README.ar.md)

alles puts your notes, files, calendar, tasks, mail, photos, money, passwords, and an AI assistant in one place. It runs on your own machine, and its main data lives in a folder you control. You can use the local tools without setting up an AI model; connect outside services only when you want them.

It's built for one person who wants a personal workspace without sending every part of it to a separate service. Aide is the assistant inside Alles: it can chat, search, and use the app's tools when you approve them. You can also ignore Aide and use the other apps on their own.

## get started

You need Python 3.11 or newer. On macOS or Linux:

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

Open [http://localhost:6769](http://localhost:6769). The first-run setup walks you through the basics. You don't need an API key to start using local features.

By default, Alles listens only on this device and starts without a password. **Before making it available on your network**, enable authentication, set a strong owner password and `SECRET_KEY`, and choose the matching access profile. LAN and public access have separate requirements; read [security](specifications.md#security--read-before-exposing-it) and [.env.example](.env.example) first.

If you prefer Docker, the image uses the same app and keeps data in a named volume:

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

The published port is limited to this device. Keep the volume if you replace the container.

## what you can do

| app | use it for |
| --- | --- |
| home | see your day, open your apps, and capture a task |
| aide | chat with a configured model and approve actions in your workspace |
| andromeda | search the web and optionally get a cited overview |
| plan | keep a calendar, tasks, reminders, and countdowns |
| inbox | read mail and manage contacts after connecting your account |
| docs | write Markdown notes and journal entries |
| files | browse local or connected storage, offline copies, and photos |
| library | save articles and reading lists |
| health | track habits and health records |
| finance | track accounts, transactions, budgets, and subscriptions |
| vault | store encrypted secrets, passwords, and passkeys |
| server | check health, access settings, backups, and updates |

The apps share navigation and search. Some features need extra setup: mail needs an IMAP/SMTP account; online storage and banking need their own connections; Aide needs a model endpoint before it can reply. You can configure models in **settings → models**, including local models through Ollama.

[specifications.md](specifications.md) has the detailed app behavior, architecture, API, and configuration.

## your data and backups

The default data folder is `data/` in the checkout. Set `ALLES_DATA` to use a different location. It holds the database and app-managed files, so keep it private and back it up. Connected providers receive the requests you choose to send them.

In **settings → backup**, you can download an encrypted backup or send one manually to an existing HTTPS WebDAV folder or S3-compatible bucket. First-run Protection can also set up daily encrypted local backups in a separate folder. Save the recovery key outside Alles before relying on remote backups.

A restore is staged and checked before you apply it. Follow the command shown in the app while Alles is stopped. See [the backup and restore details](specifications.md#your-data-where-everything-lives) before moving an existing installation.

## installing as a service

For a regular macOS or Linux install, `bash alles install` sets up a private Python environment, a launcher, and a user service. `alles update` checks a new release before switching to it; `alles update rollback` restores the previous code and paired data. `bash alles uninstall` keeps your personal data. Run `bash alles --help` for the current commands.

The app uses FastAPI, SQLite, vanilla JavaScript, and CSS. There's no frontend build step. For the complete technical layout, see [specifications.md](specifications.md).

## credits and license

Aide was inspired by [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus). Alles is an independent implementation; [acknowledgments.md](acknowledgments.md) credits that project and other work it uses. Third-party licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Alles is released under the [MIT license](LICENSE).
