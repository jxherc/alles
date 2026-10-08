# alles

> 2026 年 7 月 21 日レビュー済み · 正本: `README.md` · ソースリビジョン:
> `phase10-canonical-2026-07-21`

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) ·
[简体中文](README.zh-Hans.md) · [繁體中文](README.zh-Hant.md) · **日本語** · [한국어](README.ko.md) ·
[العربية](README.ar.md)

**alles** はセルフホスト型の個人用アプリです。1 つの Python プログラムに Aide、検索、
メール、リンクされた Markdown ドキュメント、日記、ファイル、カレンダー、タスク、家計、
写真、連絡先、暗号化された保管庫がまとまっています。ローカルデータは自分で管理する
フォルダーに残ります。テレメトリはなく、外部プロバイダーへ送られるのは自分で選んだ要求だけです。

## クイックスタート

Python 3.11 以降が必要です。

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.lock
python app.py
```

`http://localhost:6769` を開きます。起動に API キーは不要です。Aide を使う場合だけ、
**設定 → モデル**でモデルを追加してください。

macOS/Linux の管理インストールには `./alles install` を使います。`alles update` は新しい
リリースを準備してヘルスチェックし、`alles update rollback` は対応するコードとデータを
元に戻します。`./alles uninstall` は個人データを残します。

Docker:

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

ループバックだけに公開するため、新しいコンテナはこの端末からのみアクセスできます。

## データ、ネットワーク、バックアップ

Alles は単一ユーザー向けです。ネットワークからアクセスさせる前に認証を有効化し、強い所有者
パスワードと実際の `secret_key` を設定してください。公開前に
[セキュリティの説明](../../specifications.md#security--read-before-exposing-it)を確認してください。

**設定 → バックアップ**で暗号化したローカルバックアップを作成し、WebDAV または S3 互換
ストレージへ手動送信できます。復旧キーは別の場所に保存してください。復元データは、使用中の
データへ触れる前に検証されてステージングされます。

## 詳細

アプリ、ルート、構成の一覧は [`specifications.md`](../../specifications.md) にあります。
依存関係とライセンスは [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) を参照してください。

## ライセンス

MIT。[`LICENSE`](../../LICENSE) を参照してください。
