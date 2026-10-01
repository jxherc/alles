# alles

alles is for keeping your everyday stuff in one place, on a machine you control. write notes, plan your week, check your mail, find your files, and track your money without jumping between a bunch of different apps.

it's built for one person. your main data lives in a folder you control, and you decide which outside services to connect. there's also aide, an ai assistant that can work with the apps when you approve its actions. use it if it's helpful; the local tools work without an ai model.

[français](docs/readme/README.fr.md) · [español](docs/readme/README.es.md) ·
[简体中文](docs/readme/README.zh-Hans.md) · [繁體中文](docs/readme/README.zh-Hant.md) ·
[日本語](docs/readme/README.ja.md) · [한국어](docs/readme/README.ko.md) ·
[العربية](docs/readme/README.ar.md)

## get started

you need python 3.11 or newer. on macos or linux:

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

open [http://localhost:6769](http://localhost:6769) and follow the setup. you don't need an api key to get started.

by default, alles is only accessible from this device and starts without a password. **before putting it on your network**, turn on authentication, set a strong owner password and `SECRET_KEY`, and choose the right access profile. local network and public access have different requirements; read [security](specifications.md#security--read-before-exposing-it) and [.env.example](.env.example) first.

if you'd rather use docker:

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

this keeps access limited to your device and saves your data in the `alles-data` volume. keep that volume when you replace the container.

## what you can do

| app | use it for |
| --- | --- |
| home | see your day, open your apps, and capture a task |
| aide | chat with a configured model and approve actions in your workspace |
| andromeda | search the web and optionally get a cited overview |
| plan | keep a calendar, tasks, reminders, and countdowns |
| inbox | read mail and manage contacts after connecting your account |
| docs | write markdown notes and journal entries |
| files | browse local or connected storage, offline copies, and photos |
| library | save articles and reading lists |
| health | track habits and health records |
| finance | track accounts, transactions, budgets, and subscriptions |
| vault | store encrypted secrets, passwords, and passkeys |
| server | check health, access settings, backups, and updates |

some things need a connection before they work. add your imap/smtp account for mail, connect a service for online storage or banking, and add a model in **settings → models** if you want to use aide. local models through ollama work too.

[specifications.md](specifications.md) has the detailed app behavior, architecture, api, and configuration.

## your data and backups

your database and the files alles manages live in `data/` by default. set `ALLES_DATA` if you want them somewhere else. keep that folder private and back it up. outside providers receive the requests you send them through their connections.

open **settings → backup** to download an encrypted backup. you can also send one manually to an existing https webdav folder or s3-compatible bucket, or set up daily local backups during the initial setup. keep your recovery key somewhere outside alles so you can still get to it if the app stops working.

alles checks a backup and prepares the restore before applying it. stop the app, then follow the command it gives you. read [the backup and restore details](specifications.md#your-data-where-everything-lives) before moving an existing installation.

## installing as a service

if you want alles to run as a service on macos or linux, run `bash alles install`. it sets up its own python environment and adds the `alles` command. use `alles update` to update it, or `alles update rollback` to return to the previous code and data. `bash alles uninstall` keeps your personal data. `bash alles --help` lists the commands.

it's built with fastapi, sqlite, vanilla javascript, and css. there's no frontend build step. the technical details are in [specifications.md](specifications.md).

## credits and license

aide was inspired by [odysseus](https://github.com/pewdiepie-archdaemon/odysseus). alles is an independent implementation; [acknowledgments.md](ACKNOWLEDGMENTS.md) credits that project and the other work it uses. third-party licenses are in [third-party notices](THIRD_PARTY_NOTICES.md).

alles is released under the [mit license](LICENSE).
