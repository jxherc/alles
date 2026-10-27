# alles

alles is a private replacement for the google ecosystem. your mail, calendar, docs, files, photos, contacts, tasks, money and passwords live in one app on a machine you control, instead of on someone else's servers.

it's built for one person. your main data lives in a folder you control, and you decide which outside services to connect. there's also aide, an ai assistant that can work with the apps when you approve its actions. use it if it's helpful; the local tools work without an ai model.

[français](docs/readme/README.fr.md) · [español](docs/readme/README.es.md) ·
[简体中文](docs/readme/README.zh-Hans.md) · [繁體中文](docs/readme/README.zh-Hant.md) ·
[日本語](docs/readme/README.ja.md) · [한국어](docs/readme/README.ko.md) ·
[العربية](docs/readme/README.ar.md)

## get started

on macos or linux, run:

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

it downloads only the app, sets it up as a background service and shows each step as it goes. alles keeps running after you close the terminal and starts again after a restart. it needs python 3.11 or newer; on debian or ubuntu it offers to add python's venv module if that's missing.

then open [http://localhost:6769](http://localhost:6769) and follow the setup. you don't need an api key to get started. from then on, the `alles` command does the rest: on its own it shows whether alles is running and how to open it, `alles doctor` checks the install, and `alles config` opens the settings file.

by default, alles is only accessible from this device and starts without a password. **before putting it on your network**, give it a password and choose who can open it: `alles access lan` does both. local network and public access have different requirements; read [security](specifications.md#security--read-before-exposing-it) first.

### use it from another device

```bash
alles access lan
```

it asks for an owner password, restarts alles so your phone and other computers can open it, and prints the addresses to use, like `http://100.101.102.103:6769`. `alles access device` makes it private to this computer again.

### run it from source

for development, or to run it without the service. on debian or ubuntu, run `sudo apt install git python3-venv` first.

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

`python cli.py access lan` sets up access from other devices here too; start `python app.py` again afterwards.

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

new manual transactions saved in the local finance ledger have an undo action.
undo removes that exact transaction only while its saved details remain unchanged;
an interrupted reply keeps a retry for the same transaction. Actual transactions,
imports, and transfers use their existing review and deletion workflows.

some things need a connection before they work. add your imap/smtp account for mail, connect a service for online storage or banking, and add a model in **settings → models** if you want to use aide. local models through ollama work too.

the interface comes in english, français, español, 简体中文, 繁體中文, 日本語, 한국어 and العربية. pick yours in **settings → language & region**.

[specifications.md](specifications.md) has the detailed app behavior, architecture, api, and configuration.

## your data and backups

an installed alles keeps your database and the files it manages in `~/.local/share/alles/data` on linux or `~/Library/Application Support/Alles/data` on macos; `alles status` shows where. a source run uses `data/`, or `ALLES_DATA` if you set it. keep that folder private and back it up. outside providers receive the requests you send them through their connections.

open **settings → backup** to download an encrypted backup. you can also send one manually to an existing https webdav folder or s3-compatible bucket, or set up daily local backups during the initial setup. keep your recovery key somewhere outside alles so you can still get to it if the app stops working.

alles checks a backup and prepares the restore before applying it. stop the app, then follow the command it gives you. read [the backup and restore details](specifications.md#your-data-where-everything-lives) before moving an existing installation.

## updating and removing

`alles update` gets the newest version and keeps the previous one, so `alles update rollback` can return to it with your data. `alles uninstall` removes alles and keeps your personal data. `alles help` lists every command.

it's built with fastapi, sqlite, vanilla javascript, and css. there's no frontend build step. the technical details are in [specifications.md](specifications.md).

## release history

[davinci](docs/releases/davinci.md) records the completed daily-workflows milestone.

## credits and license

aide was inspired by [odysseus](https://github.com/pewdiepie-archdaemon/odysseus). alles is an independent implementation; [acknowledgments.md](ACKNOWLEDGMENTS.md) credits that project and the other work it uses. third-party licenses are in [third-party notices](THIRD_PARTY_NOTICES.md).

alles is released under the [mit license](LICENSE).
