# alles

> traduction révisée le 21 juillet 2026 · source canonique : `README.md` · révision :
> `phase10-canonical-2026-07-21`

[english](../../README.md) · **français** · [español](README.es.md) · [简体中文](README.zh-Hans.md) ·
[繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [العربية](README.ar.md)

**alles** est une application personnelle auto-hébergée. Un seul programme Python réunit Aide,
la recherche, les e-mails, les documents Markdown liés, le journal, les fichiers, le calendrier,
les tâches, les finances, les photos, les contacts et un coffre chiffré. Les données locales restent
dans un dossier que vous contrôlez. Il n’y a aucune télémétrie ; les fournisseurs externes ne
reçoivent que les requêtes que vous choisissez de leur envoyer.

## démarrage rapide

Python 3.11 ou une version plus récente est nécessaire.

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.lock
python app.py
```

Ouvrez `http://localhost:6769`. Aucune clé API n’est nécessaire pour démarrer. Ajoutez un modèle dans
**réglages → modèles** uniquement si vous souhaitez utiliser Aide.

Pour une installation macOS/Linux gérée, lancez `./alles install`. `alles update` prépare et vérifie
une nouvelle version ; `alles update rollback` restaure la paire code/données précédente.
`./alles uninstall` conserve les données personnelles.

Docker :

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

Le port limité à la boucle locale garde une nouvelle installation sur cet appareil.

## données, réseau et sauvegardes

Alles est prévu pour une seule personne. Avant tout accès réseau, activez l’authentification,
choisissez un mot de passe propriétaire fort et définissez une vraie `secret_key`. Consultez la
[section sécurité](../../specifications.md#security--read-before-exposing-it) avant une exposition.

Dans **réglages → sauvegarde**, vous pouvez créer une sauvegarde locale chiffrée ou l’envoyer
manuellement vers WebDAV ou un stockage compatible S3. Conservez la clé de récupération séparément.
Une restauration est vérifiée et préparée avant de toucher aux données actives.

## en savoir plus

La liste complète des applications, des routes et de l’architecture se trouve dans
[`specifications.md`](../../specifications.md). Les dépendances et leurs licences sont répertoriées
dans [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

## licence

MIT. Voir [`LICENSE`](../../LICENSE).
