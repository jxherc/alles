# alles

> 2026 年 7 月 21 日完成審核 · 規範來源：`README.md` · 來源修訂：
> `phase10-canonical-2026-07-21`

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) ·
[简体中文](README.zh-Hans.md) · **繁體中文** · [日本語](README.ja.md) · [한국어](README.ko.md) ·
[العربية](README.ar.md)

**alles** 是一款自架的個人應用程式。一個 Python 程式整合了 Aide、搜尋、郵件、互相連結的
Markdown 文件、日記、檔案、行事曆、工作、財務、照片、聯絡人和加密密碼庫。本機資料保存在
由你控制的資料夾中。Alles 不收集遙測資料；外部服務只會收到你主動選擇傳送的要求。

## 快速開始

需要 Python 3.11 或更新版本。

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.lock
python app.py
```

開啟 `http://localhost:6769`。啟動不需要 API 金鑰。只有需要使用 Aide 時，才要在
**設定 → 模型**中加入模型。

在 macOS/Linux 上進行受管理的安裝可執行 `./alles install`。`alles update` 會暫存並健康檢查
新版本；`alles update rollback` 會還原相符的舊程式與資料。`./alles uninstall` 會保留個人資料。

Docker：

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

只綁定本機回環位址，可讓新容器維持在目前裝置上。

## 資料、網路與備份

Alles 專為單一使用者設計。允許網路存取前，請啟用驗證、設定強式擁有者密碼，並配置真正的
`secret_key`。對外提供服務前請閱讀[安全說明](../../specifications.md#security--read-before-exposing-it)。

你可以在**設定 → 備份**建立加密本機備份，或手動傳送至 WebDAV 或 S3 相容儲存空間。復原金鑰
必須分開保存。還原流程會先驗證並暫存資料，不會直接修改使用中的資料。

## 更多資訊

完整的應用程式、路由與架構說明請見 [`specifications.md`](../../specifications.md)。相依套件及授權請見
[`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md)。

## 授權

MIT。請參閱 [`LICENSE`](../../LICENSE)。
