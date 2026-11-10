# alles

said "AH-luss" (/ˈaləs/), like the german word for "everything".

alles is a private replacement for the google ecosystem. your mail, calendar, docs, files, photos, contacts, tasks, money and passwords live in one app on a machine you control, instead of on someone else's servers.

it's built for one person. your main data lives in a folder you control, and you decide which outside services to connect. there's also aide, an ai assistant that can work with the apps when you approve its actions. use it if it's helpful; the local tools work without an ai model.

a quick look at every app: [jxherc.github.io/alles](https://jxherc.github.io/alles/)

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

by default, alles is only accessible from this device and starts without a password. right after installing it asks whether you want one (8 characters or more; `alles password` sets or changes it later) and whether your other devices should open it. **before putting it on your network**, give it a password and choose who can open it: `alles access lan` does both. local network and public access have different requirements; read [security](specifications.md#security--read-before-exposing-it) first.

### put it on another drive

run the install from a folder on the drive and alles goes into an `Alles` folder there:

```bash
cd /Volumes/External
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

or name the folder yourself, from anywhere:

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | ALLES_HOME=/Volumes/External/Alles sh
```

alles then keeps everything in that folder: your docs and files where you can see them, and the database, app, backups and settings in a hidden `.alles` folder inside it. only the `alles` command and the small file that starts the service stay on this computer, and every later command (`alles update` too) finds the folder on its own. if the drive isn't plugged in, the install stops before it makes anything, `alles` says the drive is missing, and the service waits for the drive instead of starting empty. `ALLES_PORT=8000` picks another port the same way.

on a mac, the first start asks whether `alles-server` may access files on a removable volume. click Allow, or the service can't open anything on the drive. this needs apple's command line tools (`xcode-select --install`); if you add them later, run `alles restart`.

### use it from another device

```bash
alles access lan
```

it asks for an owner password, restarts alles so your phone and other computers can open it, and prints the addresses to use, like `http://100.101.102.103:6769`. `alles access device` makes it private to this computer again.

### open it at your own domain

```bash
alles access domain alles.example.com
```

every app then sits after a slash: `alles.example.com/docs`, `alles.example.com/plan`. add `subdomain` (`alles access domain alles.example.com subdomain`) to give each app its own address like `docs.alles.example.com`; that needs a wildcard dns record and certificate. alles doesn't make the certificate itself: point the domain at this computer and have an https proxy (caddy, nginx, a cloudflare tunnel) send it to `http://127.0.0.1:6769`. `alles access domain off` forgets it.

### make andromeda your browser's search

settings › andromeda › default search downloads a small extension for chrome, brave, edge and helium: unzip it, open `chrome://extensions`, turn on developer mode and load the folder, and andromeda becomes the default search. any other browser can take the search address shown there as a custom engine.

safari on an iphone or ipad only offers apple's own list of engines, so `safari/` holds a small app with a safari extension instead: keep google as safari's engine, and the extension sends every google, bing, duckduckgo, yahoo, ecosia or baidu search to andromeda. build it in xcode with your own apple developer team, turn it on in settings › apps › safari › extensions, allow it on every website, then enter your alles address in its popup.

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
| andromeda | search the web and optionally get a cited overview; it can be your browser's search too |
| plan | keep a calendar, tasks, reminders, and countdowns |
| inbox | read mail and manage contacts after connecting your account |
| docs | write markdown notes and journal entries |
| files | browse local or connected storage, offline copies, and photos |
| library | save articles and reading lists |
| health | track habits and health records |
| finance | track accounts, transactions, budgets, and subscriptions |
| vault | store encrypted secrets, passwords, and passkeys, and fill logins, cards and addresses in chrome with the alles extension |
| server | check health, access settings, backups, and updates |

new manual transactions saved in the local finance ledger have an undo action.
undo removes that exact transaction only while its saved details remain unchanged;
an interrupted reply keeps a retry for the same transaction. Actual transactions,
imports, and transfers use their existing review and deletion workflows.

some things need a connection before they work. in mail, pick gmail, outlook, icloud, yahoo or fastmail and the form fills itself in; gmail signs in with google after a one-time google cloud setup that alles walks you through (download the client json and drop it in). bank sync lives under **finance → bank connections** (plaid for most banks in canada and the us, or simplefin). to text aide from your phone, turn on telegram, imessage or discord in **settings → connections**; **settings → this machine** installs node, pi and aide's browser with one click. add a model in **settings → models** if you want to use aide; local models through ollama work too.

the interface comes in english, français, español, 简体中文, 繁體中文, 日本語, 한국어 and العربية. pick yours in **settings → language & region**.

[specifications.md](specifications.md) has the detailed app behavior, architecture, api, and configuration.

## your data and backups

an installed alles keeps your database and the files it manages in `~/.local/share/alles/data` on linux or `~/Library/Application Support/Alles/data` on macos; `alles status` shows where. a source run uses `data/`, or `ALLES_DATA` if you set it. keep that folder private and back it up. outside providers receive the requests you send them through their connections.

your docs and files sit in one folder you can open and see, `~/Alles`, with docs in `~/Alles/Docs`, so files shows everything you wrote. daily backups go next to the data folder, out of view. an install from before november moves into this layout when you run `alles update accept` (or `alles folders move`); folders you picked yourself or that sit on another disk stay where they are, and `alles doctor` says why.

open **settings → backup** to download an encrypted backup. you can also send one manually to an existing https webdav folder or s3-compatible bucket, or set up daily local backups during the initial setup. keep your recovery key somewhere outside alles so you can still get to it if the app stops working.

alles checks a backup and prepares the restore before applying it. stop the app, then follow the command it gives you. read [the backup and restore details](specifications.md#your-data-where-everything-lives) before moving an existing installation.

## updating and removing

`alles update` gets the newest version and keeps the previous one, so `alles update rollback` can return to it with your data. `alles status` names the release by its short commit and says when a newer one is out. `alles tools` shows what aide can use (node, pi, its browser) and `alles tools install` adds them. `alles uninstall` removes alles and keeps your personal data. `alles help` lists every command. `alles ask` and `alles chat` talk to aide right in the terminal, `alles logs --level warn --since 1h` cuts the log down to what matters, `alles backup` writes an encrypted backup and `alles dump` prints a summary for a bug report with no secrets in it.

it's built with fastapi, sqlite, vanilla javascript, and css. there's no frontend build step. the technical details are in [specifications.md](specifications.md).

## release history

[davinci](docs/releases/davinci.md) records the completed daily-workflows milestone.

## credits and license

aide was inspired by [odysseus](https://github.com/pewdiepie-archdaemon/odysseus). alles is an independent implementation; [acknowledgments.md](ACKNOWLEDGMENTS.md) credits that project and the other work it uses. third-party licenses are in [third-party notices](THIRD_PARTY_NOTICES.md).

alles is released under the [mit license](LICENSE).
