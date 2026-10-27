# alles

> traduction révisée le 27 octobre 2026 · source canonique : `README.md` · révision :
> `davinci-canonical-2026-10-27`

alles est une alternative privée à l’écosystème Google. e-mails, agenda, documents, fichiers, photos, contacts, tâches, argent et mots de passe : tout tient dans une seule app, sur une machine que vous contrôlez, et non sur les serveurs de quelqu’un d’autre.

alles est conçu pour une seule personne. vos données principales restent dans un dossier que vous contrôlez, et c’est vous qui décidez quels services externes connecter. il y a aussi Aide, un assistant IA qui peut travailler avec les apps quand vous approuvez ses actions. servez-vous-en s’il vous est utile ; les outils locaux fonctionnent sans modèle d’IA.

[english](../../README.md) · **français** · [español](README.es.md) · [简体中文](README.zh-Hans.md) ·
[繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [العربية](README.ar.md)

## pour commencer

il vous faut git et Python 3.11 ou plus récent. sous Debian ou Ubuntu, lancez d’abord `sudo apt install git python3-venv`. ensuite, sous macOS ou Linux :

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

ouvrez [http://localhost:6769](http://localhost:6769) et suivez la configuration. pas besoin de clé API pour commencer.

par défaut, alles n’est accessible que depuis cet appareil et démarre sans mot de passe. **avant de le mettre sur votre réseau**, activez l’authentification, définissez un mot de passe propriétaire solide et une `SECRET_KEY`, et choisissez le bon profil d’accès. le réseau local et l’accès public n’ont pas les mêmes exigences ; lisez d’abord la section [sécurité](../../specifications.md#security--read-before-exposing-it) et [.env.example](../../.env.example).

si vous préférez Docker :

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

l’accès reste ainsi limité à votre appareil, et vos données sont enregistrées dans le volume `alles-data`. gardez ce volume quand vous remplacez le conteneur.

### l’utiliser depuis un autre appareil

pour ouvrir alles depuis votre téléphone ou un autre ordinateur, sur votre réseau local ou via [Tailscale](https://tailscale.com), donnez-lui d’abord un mot de passe. mettez ces lignes dans un fichier `.env` dans le dossier d’alles :

```dotenv
ALLES_ACCESS_PROFILE=lan
AUTH_ENABLED=true
AUTH_PASSWORD=a-long-password-only-you-know
SECRET_KEY=paste-a-random-key-here
ALLES_HOST=100.101.102.103
```

générez la clé avec `python3 -c "import secrets; print(secrets.token_hex(32))"`. réglez `ALLES_HOST` sur l’adresse qu’utilisent vos autres appareils, par exemple l’IP Tailscale du serveur, pour qu’alles n’écoute nulle part ailleurs. relancez ensuite `python app.py` et ouvrez cette adresse sur le port 6769, par exemple `http://100.101.102.103:6769`.

## ce que vous pouvez faire

| app | à quoi elle sert |
| --- | --- |
| home | voir votre journée, ouvrir vos apps et noter une tâche au vol |
| Aide | discuter avec un modèle configuré et approuver des actions dans votre espace de travail |
| andromeda | chercher sur le web et, si vous le voulez, obtenir une synthèse avec ses sources |
| plan | gérer un calendrier, des tâches, des rappels et des comptes à rebours |
| inbox | lire vos e-mails et gérer vos contacts une fois votre compte connecté |
| docs | écrire des notes en Markdown et tenir un journal |
| files | parcourir un stockage local ou connecté, des copies hors ligne et des photos |
| library | enregistrer des articles et des listes de lecture |
| health | suivre vos habitudes et vos données de santé |
| finance | suivre vos comptes, transactions, budgets et abonnements |
| vault | conserver des secrets, mots de passe et clés d’accès chiffrés |
| server | vérifier l’état du serveur, les réglages d’accès, les sauvegardes et les mises à jour |

les nouvelles transactions saisies à la main dans le registre financier local peuvent être annulées.
l’annulation supprime uniquement cette transaction, et seulement tant que ses détails enregistrés n’ont pas changé ;
si la réponse est interrompue, un nouvel essai reste possible pour la même transaction. les transactions Actual,
les imports et les virements passent par leurs circuits habituels de vérification et de suppression.

certaines fonctions demandent une connexion avant de marcher. ajoutez votre compte IMAP/SMTP pour les e-mails, connectez un service pour le stockage en ligne ou les services bancaires, et ajoutez un modèle dans **settings → models** si vous voulez utiliser Aide. les modèles locaux via Ollama marchent aussi.

l’interface existe en english, français, español, 简体中文, 繁體中文, 日本語, 한국어 et العربية. choisissez la vôtre dans **réglages → langue et région**.

[specifications.md](../../specifications.md) décrit en détail le comportement des apps, l’architecture, l’API et la configuration.

## vos données et vos sauvegardes

par défaut, votre base de données et les fichiers gérés par alles se trouvent dans `data/`. définissez `ALLES_DATA` pour les mettre ailleurs. gardez ce dossier privé et sauvegardez-le. les fournisseurs externes reçoivent les requêtes que vous leur envoyez via leurs connexions.

ouvrez **settings → backup** pour télécharger une sauvegarde chiffrée. vous pouvez aussi en envoyer une à la main vers un dossier WebDAV existant en HTTPS ou un bucket compatible S3, ou programmer des sauvegardes locales quotidiennes pendant la configuration initiale. gardez votre clé de récupération ailleurs que dans alles, pour pouvoir la retrouver si l’app ne fonctionne plus.

alles vérifie la sauvegarde et prépare la restauration avant de l’appliquer. arrêtez l’app, puis suivez la commande qu’il vous indique. lisez [les détails sur la sauvegarde et la restauration](../../specifications.md#your-data-where-everything-lives) avant de déplacer une installation existante.

## installer en tant que service

pour faire tourner alles comme service sous macOS ou Linux, lancez `bash alles install`. il crée son propre environnement Python et ajoute la commande `alles`. utilisez `alles update` pour le mettre à jour, ou `alles update rollback` pour revenir au code et aux données d’avant. `bash alles uninstall` conserve vos données personnelles. `bash alles --help` liste les commandes.

alles est construit avec FastAPI, SQLite, du JavaScript vanilla et du CSS. il n’y a pas d’étape de build pour le frontend. les détails techniques sont dans [specifications.md](../../specifications.md).

## historique des versions

[davinci](../../docs/releases/davinci.md) retrace l’étape terminée consacrée aux usages du quotidien.

## crédits et licence

Aide s’inspire d’[odysseus](https://github.com/pewdiepie-archdaemon/odysseus). alles est une implémentation indépendante ; [acknowledgments.md](../../ACKNOWLEDGMENTS.md) mentionne ce projet et les autres travaux qu’il utilise. les licences tierces se trouvent dans les [mentions tierces](../../THIRD_PARTY_NOTICES.md).

alles est publié sous [licence MIT](../../LICENSE).
