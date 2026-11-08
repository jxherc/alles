# alles

读作 "AH-luss"（/ˈaləs/），就是德语里表示“一切”的那个词。

> 2026 年 10 月 27 日完成审核 · 规范源文件：`README.md` · 源修订：
> `davinci-canonical-2026-10-27`

alles 是一套私有的 Google 全家桶替代方案。邮件、日历、文档、文件、照片、联系人、任务、财务和密码都放在同一个应用里，运行在你自己掌控的机器上，而不是别人的服务器上。

它只为一个人设计。主要数据保存在你掌控的文件夹里，连接哪些外部服务也由你决定。另外还有 aide，一个 AI 助手：你批准它的操作后，它就能在各个应用里帮你做事。觉得有用就用；不接 AI 模型，本地工具也照样能用。

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) · **简体中文** ·
[繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [العربية](README.ar.md)

## 开始使用

在 macOS 或 Linux 上运行：

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

它只下载应用本身，把它装成后台服务，并逐步显示每一步。关掉终端后 alles 会继续运行，机器重启后也会自动启动。需要 Python 3.11 或更高版本；在 Debian 或 Ubuntu 上，如果缺少 Python 的 venv 模块，安装程序会提出帮你装上。

然后打开 [http://localhost:6769](http://localhost:6769)，按提示完成设置。开始使用不需要 API 密钥。之后用 `alles` 命令处理其余的事：单独运行它会显示 alles 是否在运行以及如何打开，`alles doctor` 检查安装，`alles config` 打开设置文件。

默认情况下，只有这台设备能访问 alles，而且启动时没有密码。**在放到网络上之前**，先给它设密码并选择谁能打开它：`alles access lan` 两件事一起完成。局域网访问和公网访问的要求不同；请先阅读[安全说明](../../specifications.md#security--read-before-exposing-it)。安装完成后，它会问你要不要设置密码（至少 8 个字符；之后可以用 `alles password` 设置或修改），以及你的其他设备是否也要能打开它。

### 装到另一块硬盘上

在硬盘上的文件夹里运行安装，alles 就会装进那里的 `Alles` 文件夹：

```bash
cd /Volumes/External
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

也可以在任何地方自己指定文件夹：

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | ALLES_HOME=/Volumes/External/Alles sh
```

这样 alles 会把所有东西都放在这个文件夹里：文档和文件直接可见，数据库、程序、备份和设置放在里面一个隐藏的 `.alles` 文件夹中。只有 `alles` 命令和启动服务的小文件留在这台电脑上，之后的每个命令（包括 `alles update`）都会自己找到这个文件夹。硬盘没插上时，安装会在创建任何东西之前停下，`alles` 会提示硬盘不在，后台服务会等硬盘插上，而不是用空文件夹启动。`ALLES_PORT=8000` 也可以用同样的方式换端口。

在 mac 上，第一次启动会问是否允许 `alles-server` 访问可移除宗卷上的文件。点「允许」，不然服务打不开硬盘上的任何东西。这需要 apple 的命令行工具（`xcode-select --install`）；之后才装的话，运行 `alles restart`。

### 从其他设备使用

```bash
alles access lan
```

它会要求设置所有者密码，重启 alles 让你的手机和其他电脑可以打开它，并列出要用的地址，例如 `http://100.101.102.103:6769`。`alles access device` 会让它重新只供这台电脑使用。

### iphone 和 ipad 应用

`ios/` 里是一个 iphone 和 ipad 原生应用（ios 26.1 或更新），用的是苹果的 liquid glass 风格。首页显示接下来的安排、今天到期的任务和今天的习惯。aide 就是一个普通的聊天，回复到一半时离开，回复会在标签栏上方的小条里继续。plan 有今天、日历和任务，andromeda 在标签栏的搜索位置，docs 可以阅读和编辑你的 markdown，其他应用会打开 alles 自己的网页。先运行 `alles access lan`，用你自己的 apple 开发者团队在 xcode 里打开 `ios/Alles.xcodeproj`，然后用 alles 地址和所有者密码登录。应用会保存自己的令牌（设置的令牌列表里能看到），所以重启 alles 不会让它退出登录。

### 用你自己的域名打开

```bash
alles access domain alles.example.com
```

每个应用都在斜杠后面：`alles.example.com/docs`、`alles.example.com/plan`。加上 `subdomain`（`alles access domain alles.example.com subdomain`）可以让每个应用有自己的地址，比如 `docs.alles.example.com`，这需要通配符 DNS 记录和证书。alles 不会自己申请证书：把域名指向这台电脑，再用 https 代理（caddy、nginx、cloudflare tunnel）把它转到 `http://127.0.0.1:6769`。`alles access domain off` 会取消绑定。

### 让 andromeda 成为浏览器的搜索

设置 › andromeda › 默认搜索 可以下载一个给 chrome、brave、edge 和 helium 用的小扩展：解压后打开 `chrome://extensions`，开启开发者模式并加载这个文件夹，andromeda 就成了默认搜索。其他浏览器可以把那里显示的搜索地址加为自定义搜索引擎。

iphone 和 ipad 上的 safari 只能选 apple 给的那几个搜索引擎，所以 `safari/` 里有一个带 safari 扩展的小 app：safari 的搜索引擎保持 google，扩展会把 google、bing、duckduckgo、yahoo、ecosia 或百度上的每次搜索都发到 andromeda。用你自己的 apple 开发者团队在 xcode 里编译，在 设置 › app › safari › 扩展 里打开它，允许它在所有网站上运行，再在它的弹窗里填上你的 alles 地址。

### 从源码运行

用于开发，或者不想装成服务时使用。在 Debian 或 Ubuntu 上，先运行 `sudo apt install git python3-venv`。

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

这里也可以用 `python cli.py access lan` 开启其他设备的访问；之后重新启动 `python app.py`。

如果你更想用 Docker：

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

这样只有你的设备能访问，数据保存在 `alles-data` 卷中。替换容器时请保留这个卷。

## 能做什么

| 应用 | 用途 |
| --- | --- |
| home | 查看今天的安排、打开应用、随手记下任务 |
| aide | 与已配置的模型对话，并批准在你工作区中执行的操作 |
| andromeda | 搜索网页，还可以选择生成附带引用的概览；也可以设为浏览器的搜索引擎 |
| plan | 管理日历、任务、提醒和倒计时 |
| inbox | 连接账户后阅读邮件、管理联系人 |
| docs | 写 Markdown 笔记和日记 |
| files | 浏览本地或已连接的存储、离线副本和照片 |
| library | 保存文章和阅读清单 |
| health | 记录习惯和健康数据 |
| finance | 记录账户、交易、预算和订阅 |
| vault | 加密存放机密信息、密码和通行密钥，并用 alles 扩展在 chrome 里填写登录、银行卡和地址 |
| server | 查看运行状态、访问设置、备份和更新 |

在本地财务账本中手动新建的交易可以撤销。撤销只会删除那一笔交易，而且前提是它保存的内容没有改动过；如果响应中断，同一笔交易仍可重试。Actual 交易、导入和转账沿用各自已有的审核和删除流程。

有些功能需要先连接才能用。添加 IMAP/SMTP 账户来使用邮件，连接相应服务来使用在线存储或银行功能；想用 aide 的话，到 **settings → models** 添加模型。也可以用 Ollama 运行本地模型。

在邮件里选择 gmail、outlook、icloud、yahoo 或 fastmail，表单会自动填好；gmail 在完成一次 google cloud 设置后用 google 登录，alles 会一步步带你完成（下载客户端 json 后拖进来即可）。银行同步在 **财务 → 银行连接**（加拿大和美国的大多数银行用 plaid，也可以用 simplefin）。想用手机给 aide 发消息，就在 **设置 → 连接与工具** 里打开 telegram、imessage 或 discord；同一页还能一键安装 node、pi 和 aide 的浏览器。

界面支持 english, français, español, 简体中文, 繁體中文, 日本語, 한국어 和 العربية。在 **设置 → 语言与地区** 里选择。

[specifications.md](../../specifications.md) 详细介绍了各应用的行为、架构、API 和配置。

## 你的数据与备份

安装后，alles 会把数据库和它管理的文件放在 `~/.local/share/alles/data`（Linux）或 `~/Library/Application Support/Alles/data`（macOS）；`alles status` 会显示具体位置。从源码运行时使用 `data/`，设置了 `ALLES_DATA` 就用它指定的位置。这个文件夹不要公开，并记得备份。外部服务商会收到你通过它们的连接发出的请求。

你的文档和文件都在一个看得见的文件夹 `~/Alles` 里，文档在 `~/Alles/Docs`，所以在文件里能找到你写的所有东西。每日备份放在数据文件夹旁边，不在视线里。十一月之前的安装在你运行 `alles update accept`（或 `alles folders move`）时换成这种布局；你自己选的文件夹或在另一块磁盘上的文件夹保持原样，`alles doctor` 会说明原因。

打开 **settings → backup** 可以下载加密备份。你也可以手动把备份发送到现有的 HTTPS WebDAV 文件夹或兼容 S3 的存储桶，或者在初始设置时开启每日本地备份。请把恢复密钥存放在 alles 之外的地方，这样即使应用无法运行，你也能找到它。

alles 会先检查备份并准备好恢复，然后才应用。请先停止应用，再按照它给出的命令操作。迁移现有安装之前，请阅读[备份与恢复详情](../../specifications.md#your-data-where-everything-lives)。

## 更新与卸载

`alles update` 会安装最新版本并保留上一个版本，所以 `alles update rollback` 可以连同你的数据一起回到上一个版本。`alles uninstall` 会移除 alles，但保留你的个人数据。`alles help` 会列出所有命令。 `alles status` 用短提交号标出当前版本，有新版本时会提示。`alles tools` 列出 aide 能用的工具（node、pi、aide 的浏览器），`alles tools install` 负责安装。`alles ask` 和 `alles chat` 可以直接在终端里和 aide 对话，`alles logs --level warn --since 1h` 只留下日志里要紧的部分，`alles backup` 生成加密备份，`alles dump` 打印一份不含任何密钥的摘要，方便报告问题。

alles 用 FastAPI、SQLite、原生 JavaScript 和 CSS 构建，前端没有构建步骤。技术细节见 [specifications.md](../../specifications.md)。

## 版本历史

[davinci](../../docs/releases/davinci.md) 记录了已完成的日常工作流里程碑。

## 致谢与许可证

aide 的灵感来自 [odysseus](https://github.com/pewdiepie-archdaemon/odysseus)。alles 是独立实现的；[acknowledgments.md](../../ACKNOWLEDGMENTS.md) 列出了对该项目以及 alles 所用其他成果的致谢。第三方许可证见[第三方声明](../../THIRD_PARTY_NOTICES.md)。

alles 采用 [MIT 许可证](../../LICENSE)发布。
