# alles

讀作 "AH-luss"（/ˈaləs/），就是德語裡表示「一切」的那個詞。

> 2026 年 10 月 27 日完成審核 · 規範來源：`README.md` · 來源修訂：
> `davinci-canonical-2026-10-27`

alles 是 Google 生態系的私人替代方案。郵件、行事曆、文件、檔案、相片、聯絡人、待辦事項、財務和密碼都放在同一個應用程式裡，跑在你自己掌控的機器上，而不是別人的伺服器上。

它是為單一使用者打造的。主要資料存放在你掌控的資料夾中，要連接哪些外部服務也由你決定。另外還有 aide，一個 AI 助理：你核准它的操作後，它就能在各個應用程式中幫你做事。覺得有用就用；不接 AI 模型，本機工具也照樣能用。

每個應用程式的預覽：[jxherc.github.io/alles](https://jxherc.github.io/alles/)

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) ·
[简体中文](README.zh-Hans.md) · **繁體中文** · [日本語](README.ja.md) · [한국어](README.ko.md) ·
[العربية](README.ar.md)

## 開始使用

在 macOS 或 Linux 上執行：

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

它只下載應用程式本身，把它安裝成背景服務，並逐步顯示每個步驟。關閉終端機後 alles 會繼續執行，電腦重新開機後也會自動啟動。需要 Python 3.11 或更新版本；在 Debian 或 Ubuntu 上，如果缺少 Python 的 venv 模組，安裝程式會提議幫你裝上。

接著開啟 [http://localhost:6769](http://localhost:6769)，依照指示完成設定。開始使用不需要 API 金鑰。之後就用 `alles` 指令處理其他事：單獨執行它會顯示 alles 是否在執行以及如何開啟，`alles doctor` 會檢查安裝，`alles config` 會開啟設定檔。

預設情況下，只有這台裝置能存取 alles，而且啟動時沒有密碼。**在放到網路上之前**，請先為它設定密碼並選擇誰能開啟它：`alles access lan` 一次完成這兩件事。區域網路存取和公開存取的要求不同；請先閱讀[安全說明](../../specifications.md#security--read-before-exposing-it)。安裝完成後，它會問你要不要設定密碼（至少 8 個字元；之後可以用 `alles password` 設定或修改），以及你的其他裝置是否也要能開啟它。

### 裝到另一顆硬碟上

在硬碟上的資料夾裡執行安裝，alles 就會裝進那裡的 `Alles` 資料夾：

```bash
cd /Volumes/External
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

也可以在任何地方自己指定資料夾：

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | ALLES_HOME=/Volumes/External/Alles sh
```

這樣 alles 會把所有東西都放在這個資料夾裡：文件和檔案直接可見，資料庫、程式、備份和設定放在裡面一個隱藏的 `.alles` 資料夾中。只有 `alles` 指令和啟動服務的小檔案留在這台電腦上，之後的每個指令（包括 `alles update`）都會自己找到這個資料夾。硬碟沒接上時，安裝會在建立任何東西之前停下，`alles` 會提示硬碟不在，背景服務會等硬碟接上，而不是用空資料夾啟動。`ALLES_PORT=8000` 也可以用同樣的方式換連接埠。

在 mac 上，第一次啟動會問是否允許 `alles-server` 存取可移除式卷宗上的檔案。按「允許」，不然服務打不開硬碟上的任何東西。這需要 apple 的命令列工具（`xcode-select --install`）；之後才裝的話，執行 `alles restart`。

### 從其他裝置使用

```bash
alles access lan
```

它會要求設定擁有者密碼，重新啟動 alles，讓你的手機和其他電腦可以開啟它，並列出要使用的位址，例如 `http://100.101.102.103:6769`。`alles access device` 會讓它重新只供這台電腦使用。

### 用你自己的網域開啟

```bash
alles access domain alles.example.com
```

每個應用程式都在斜線後面：`alles.example.com/docs`、`alles.example.com/plan`。加上 `subdomain`（`alles access domain alles.example.com subdomain`）可以讓每個應用程式有自己的位址，例如 `docs.alles.example.com`，這需要萬用字元 DNS 記錄和憑證。alles 不會自己申請憑證：把網域指向這台電腦，再用 https 代理（caddy、nginx、cloudflare tunnel）把它轉到 `http://127.0.0.1:6769`。`alles access domain off` 會取消綁定。

### 讓 andromeda 成為瀏覽器的搜尋

設定 › andromeda › 預設搜尋 可以下載一個給 chrome、brave、edge 和 helium 用的小擴充功能：解壓縮後開啟 `chrome://extensions`，開啟開發人員模式並載入這個資料夾，andromeda 就成了預設搜尋。其他瀏覽器可以把那裡顯示的搜尋位址加為自訂搜尋引擎。

iphone 和 ipad 上的 safari 只能選 apple 給的那幾個搜尋引擎，所以 `safari/` 裡有一個帶 safari 擴充功能的小 app：safari 的搜尋引擎維持 google，擴充功能會把 google、bing、duckduckgo、yahoo、ecosia 或百度上的每次搜尋都送到 andromeda。用你自己的 apple 開發者團隊在 xcode 裡編譯，在 設定 › app › safari › 延伸功能 裡開啟它，允許它在所有網站上執行，再在它的彈出視窗裡填上你的 alles 位址。

### 從原始碼執行

用於開發，或不想安裝成服務時使用。在 Debian 或 Ubuntu 上，請先執行 `sudo apt install git python3-venv`。

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

這裡也可以用 `python cli.py access lan` 開啟其他裝置的存取；之後請重新啟動 `python app.py`。

如果你比較想用 Docker：

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

這樣只有你的裝置能存取，資料會存放在 `alles-data` 磁碟區中。更換容器時請保留這個磁碟區。

## 可以做什麼

| 應用程式 | 用途 |
| --- | --- |
| home | 查看今天的安排、開啟應用程式、隨手記下待辦 |
| aide | 和已設定的模型對話，並核准在你工作區中執行的操作 |
| andromeda | 搜尋網路，也可以選擇產生附引用來源的摘要；也能設為瀏覽器的搜尋引擎 |
| plan | 管理行事曆、待辦事項、提醒和倒數計時 |
| inbox | 連接帳戶後閱讀郵件、管理聯絡人 |
| docs | 撰寫 Markdown 筆記和日記 |
| files | 瀏覽本機或已連接的儲存空間、離線副本和相片 |
| library | 儲存文章和閱讀清單 |
| health | 記錄習慣和健康資料 |
| finance | 追蹤帳戶、交易、預算和訂閱 |
| vault | 加密存放機密資訊、密碼和通行密鑰，並用 alles 擴充功能在 chrome 裡填入登入、信用卡和地址 |
| server | 查看系統狀態、存取設定、備份和更新 |

在本機財務帳本中手動新增的交易可以復原。復原只會刪除那一筆交易，而且只在它儲存的內容沒有變動時才有效；如果回應中斷，同一筆交易仍可重試。Actual 交易、匯入和轉帳則沿用原本的審核與刪除流程。

有些功能要先連線才能使用。新增 IMAP/SMTP 帳戶來使用郵件，連接相應服務來使用線上儲存空間或銀行功能；想用 aide 的話，請到 **settings → models** 新增模型。也可以用 Ollama 執行本機模型。

在郵件裡選擇 gmail、outlook、icloud、yahoo 或 fastmail，表單會自動填好；gmail 在完成一次 google cloud 設定後用 google 登入，alles 會一步步帶你完成（下載用戶端 json 後拖進來即可）。銀行同步在 **財務 → 銀行連線**（加拿大和美國的大多數銀行用 plaid，也可以用 simplefin）。想用手機傳訊息給 aide，就在 **設定 → 連線** 裡打開 telegram、imessage 或 discord；**設定 → 這台機器** 還能一鍵安裝 node、pi 和 aide 的瀏覽器。

介面支援 english, français, español, 简体中文, 繁體中文, 日本語, 한국어 和 العربية。在 **設定 → 語言與地區** 裡選擇。

[specifications.md](../../specifications.md) 詳細說明各應用程式的行為、架構、API 和設定。

## 你的資料與備份

安裝後，alles 會把資料庫和它管理的檔案放在 `~/.local/share/alles/data`（Linux）或 `~/Library/Application Support/Alles/data`（macOS）；`alles status` 會顯示確切位置。從原始碼執行時使用 `data/`，若設定了 `ALLES_DATA` 則使用該位置。這個資料夾請勿公開，並記得備份。外部服務供應商會收到你透過它們的連線送出的請求。

你的文件和檔案都在一個看得見的資料夾 `~/Alles` 裡，文件在 `~/Alles/Docs`，所以在檔案裡能找到你寫的所有東西。每日備份放在資料資料夾旁邊，不在視線裡。十一月之前的安裝在你執行 `alles update accept`（或 `alles folders move`）時換成這種配置；你自己選的資料夾或在另一顆磁碟上的資料夾保持原樣，`alles doctor` 會說明原因。

開啟 **settings → backup** 可以下載加密備份。你也可以手動把備份傳送到現有的 HTTPS WebDAV 資料夾或相容 S3 的儲存貯體，或在初始設定時開啟每日本機備份。請把復原金鑰存放在 alles 以外的地方，這樣即使應用程式無法運作，你也拿得到。

alles 會先檢查備份並準備好還原，然後才套用。請先停止應用程式，再依照它提供的指令操作。搬移現有安裝之前，請閱讀[備份與還原的詳細說明](../../specifications.md#your-data-where-everything-lives)。

## 更新與移除

`alles update` 會安裝最新版本並保留前一個版本，因此 `alles update rollback` 可以連同你的資料回到前一個版本。`alles uninstall` 會移除 alles，但保留你的個人資料。`alles help` 會列出所有指令。 `alles status` 用短提交號標出目前版本，有新版本時會提示。`alles tools` 列出 aide 能用的工具（node、pi、aide 的瀏覽器），`alles tools install` 負責安裝。`alles ask` 和 `alles chat` 可以直接在終端機裡和 aide 對話，`alles logs --level warn --since 1h` 只留下日誌裡要緊的部分，`alles backup` 產生加密備份，`alles dump` 印出一份不含任何金鑰的摘要，方便回報問題。

alles 以 FastAPI、SQLite、原生 JavaScript 和 CSS 打造，前端沒有建置步驟。技術細節請見 [specifications.md](../../specifications.md)。

## 版本歷史

[davinci](../../docs/releases/davinci.md) 記錄了已完成的日常工作流程里程碑。

## 致謝與授權

aide 的靈感來自 [odysseus](https://github.com/pewdiepie-archdaemon/odysseus)。alles 是獨立實作的；[acknowledgments.md](../../ACKNOWLEDGMENTS.md) 列出了對該專案以及 alles 所用其他成果的致謝。第三方授權條款請見[第三方聲明](../../THIRD_PARTY_NOTICES.md)。

alles 採用 [MIT 授權條款](../../LICENSE)發布。
