# alles

> 2026 年 10 月 27 日レビュー済み · 正本: `README.md` · ソースリビジョン:
> `davinci-canonical-2026-10-27`

alles は Google のエコシステムを置き換える、プライベートなアプリです。メール、カレンダー、ドキュメント、ファイル、写真、連絡先、タスク、お金、パスワードを、他人のサーバーではなく自分で管理するマシン上の 1 つのアプリにまとめられます。

1 人で使うことを前提に作られています。主なデータは自分で管理するフォルダーに保存され、どの外部サービスにつなぐかも自分で決められます。AI アシスタントの aide も入っていて、あなたが操作を承認すれば、各アプリで作業してくれます。役に立つなら使ってください。ローカルのツールは AI モデルがなくても動きます。

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) ·
[简体中文](README.zh-Hans.md) · [繁體中文](README.zh-Hant.md) · **日本語** · [한국어](README.ko.md) ·
[العربية](README.ar.md)

## はじめに

macOS や Linux では、次を実行します。

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

アプリ本体だけをダウンロードし、バックグラウンドのサービスとして設定しながら、各ステップを順に表示します。ターミナルを閉じても alles は動き続け、再起動後も自動で立ち上がります。Python 3.11 以降が必要です。Debian や Ubuntu で Python の venv モジュールがない場合は、インストーラーが追加を提案します。

そのあと [http://localhost:6769](http://localhost:6769) を開き、セットアップに沿って進めてください。始めるのに API キーは要りません。あとは `alles` コマンドで足ります。単体で実行すると alles が動いているかと開き方を表示し、`alles doctor` はインストールを確認し、`alles config` は設定ファイルを開きます。

標準では、alles にはこのデバイスからしかアクセスできず、パスワードなしで起動します。**ネットワークに公開する前に**、パスワードを設定し、誰が開けるかを決めてください。`alles access lan` で両方できます。ローカルネットワークでの利用と公開アクセスでは条件が異なります。先に[セキュリティ](../../specifications.md#security--read-before-exposing-it)を読んでください。

### ほかのデバイスから使う

```bash
alles access lan
```

オーナーパスワードを尋ね、スマートフォンやほかのパソコンから開けるように alles を再起動し、使うアドレス（例: `http://100.101.102.103:6769`）を表示します。`alles access device` で、このパソコンだけで使う状態に戻せます。

### ソースから実行する

開発用、またはサービスにせずに動かしたいとき向けです。Debian や Ubuntu では、先に `sudo apt install git python3-venv` を実行してください。

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

ここでも `python cli.py access lan` でほかのデバイスからのアクセスを設定できます。そのあと `python app.py` をもう一度起動してください。

Docker を使う場合は、次のとおりです。

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

これでアクセスは自分のデバイスだけに限られ、データは `alles-data` ボリュームに保存されます。コンテナーを入れ替えるときも、このボリュームは残してください。

## できること

| アプリ | 用途 |
| --- | --- |
| home | 1 日の予定を見る、アプリを開く、タスクをさっとメモする |
| aide | 設定したモデルとチャットし、ワークスペースでの操作を承認する |
| andromeda | Web を検索し、必要なら出典付きの概要も作る |
| plan | カレンダー、タスク、リマインダー、カウントダウンを管理する |
| inbox | アカウントを接続して、メールを読み、連絡先を管理する |
| docs | Markdown のノートや日記を書く |
| files | ローカルや接続先のストレージ、オフラインコピー、写真を見る |
| library | 記事やリーディングリストを保存する |
| health | 習慣や健康の記録をつける |
| finance | 口座、取引、予算、サブスクリプションを管理する |
| vault | シークレット、パスワード、パスキーを暗号化して保管する |
| server | 状態、アクセス設定、バックアップ、アップデートを確認する |

ローカルの財務台帳に手動で保存した新しい取引は、元に戻せます。元に戻すと削除されるのはその取引だけで、保存された内容が変わっていない間に限られます。応答が途中で切れた場合は、同じ取引をもう一度試せます。Actual の取引、インポート、振替は、これまでどおりの確認と削除の手順で扱います。

一部の機能は、接続してから使えるようになります。メールには IMAP/SMTP アカウントを追加し、オンラインストレージや銀行には対応するサービスを接続してください。aide を使うなら **settings → models** でモデルを追加します。Ollama のローカルモデルも使えます。

画面の言語は english, français, español, 简体中文, 繁體中文, 日本語, 한국어、العربية から選べます。**設定 → 言語と地域** で切り替えてください。

アプリの詳しい動作、アーキテクチャ、API、設定は [specifications.md](../../specifications.md) にまとめています。

## データとバックアップ

インストールした alles は、データベースと管理するファイルを Linux では `~/.local/share/alles/data`、macOS では `~/Library/Application Support/Alles/data` に置きます。場所は `alles status` で確認できます。ソースから実行した場合は `data/` を使い、`ALLES_DATA` を設定していればその場所を使います。このフォルダーは非公開にして、バックアップを取っておきましょう。外部プロバイダーには、その接続を通じてあなたが送ったリクエストが届きます。

**settings → backup** を開くと、暗号化したバックアップをダウンロードできます。既存の HTTPS の WebDAV フォルダーや S3 互換バケットへ手動で送ることも、初回セットアップ時に毎日のローカルバックアップを設定することもできます。アプリが動かなくなっても取り出せるよう、リカバリーキーは alles の外に保管してください。

alles はバックアップを確認し、復元の準備をしてから適用します。アプリを止めてから、表示されるコマンドに従ってください。既存のインストールを移す前に、[バックアップと復元の詳細](../../specifications.md#your-data-where-everything-lives)を読んでください。

## 更新と削除

`alles update` は最新版を入れ、前のバージョンも残すので、`alles update rollback` でデータごと前の状態に戻せます。`alles uninstall` は alles を削除しますが、個人データは残します。`alles help` ですべてのコマンドを表示できます。

alles は FastAPI、SQLite、素の JavaScript、CSS で作られています。フロントエンドのビルド手順はありません。技術的な詳細は [specifications.md](../../specifications.md) にあります。

## リリース履歴

[davinci](../../docs/releases/davinci.md) には、完了した日常ワークフローのマイルストーンを記録しています。

## クレジットとライセンス

aide は [odysseus](https://github.com/pewdiepie-archdaemon/odysseus) に着想を得ました。alles は独立した実装です。[acknowledgments.md](../../ACKNOWLEDGMENTS.md) には、そのプロジェクトと alles が使っているほかの成果へのクレジットを載せています。サードパーティのライセンスは[サードパーティ通知](../../THIRD_PARTY_NOTICES.md)にあります。

alles は [MIT ライセンス](../../LICENSE)で公開しています。
