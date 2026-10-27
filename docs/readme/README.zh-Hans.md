# alles

> 2026 年 10 月 27 日完成审核 · 规范源文件：`README.md` · 源修订：
> `davinci-canonical-2026-10-27`

alles 是一套私有的 Google 全家桶替代方案。邮件、日历、文档、文件、照片、联系人、任务、财务和密码都放在同一个应用里，运行在你自己掌控的机器上，而不是别人的服务器上。

它只为一个人设计。主要数据保存在你掌控的文件夹里，连接哪些外部服务也由你决定。另外还有 aide，一个 AI 助手：你批准它的操作后，它就能在各个应用里帮你做事。觉得有用就用；不接 AI 模型，本地工具也照样能用。

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) · **简体中文** ·
[繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [العربية](README.ar.md)

## 开始使用

需要 git 和 Python 3.11 或更高版本。在 Debian 或 Ubuntu 上，先运行 `sudo apt install git python3-venv`。然后在 macOS 或 Linux 上运行：

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

打开 [http://localhost:6769](http://localhost:6769)，按提示完成设置。开始使用不需要 API 密钥。

默认情况下，只有这台设备能访问 alles，而且它启动时没有密码。**在把它放到网络上之前**，请开启身份验证，设置足够强的所有者密码和 `SECRET_KEY`，并选择合适的访问配置。局域网访问和公网访问的要求不同；请先阅读[安全说明](../../specifications.md#security--read-before-exposing-it)和 [.env.example](../../.env.example)。

如果你更想用 Docker：

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

这样只有你的设备能访问，数据保存在 `alles-data` 卷中。替换容器时请保留这个卷。

### 从其他设备使用

想在手机或另一台电脑上打开 alles（通过家里的局域网或 [Tailscale](https://tailscale.com)），先给它设一个密码。在 alles 文件夹里新建一个 `.env` 文件，写入这几行：

```dotenv
ALLES_ACCESS_PROFILE=lan
AUTH_ENABLED=true
AUTH_PASSWORD=a-long-password-only-you-know
SECRET_KEY=paste-a-random-key-here
ALLES_HOST=100.101.102.103
```

用 `python3 -c "import secrets; print(secrets.token_hex(32))"` 生成密钥。把 `ALLES_HOST` 设成其他设备访问时用的地址，比如服务器的 Tailscale IP，这样 alles 不会在别的网络上监听。然后重新启动 `python app.py`，用这个地址的 6769 端口打开，例如 `http://100.101.102.103:6769`。

## 能做什么

| 应用 | 用途 |
| --- | --- |
| home | 查看今天的安排、打开应用、随手记下任务 |
| aide | 与已配置的模型对话，并批准在你工作区中执行的操作 |
| andromeda | 搜索网页，还可以选择生成附带引用的概览 |
| plan | 管理日历、任务、提醒和倒计时 |
| inbox | 连接账户后阅读邮件、管理联系人 |
| docs | 写 Markdown 笔记和日记 |
| files | 浏览本地或已连接的存储、离线副本和照片 |
| library | 保存文章和阅读清单 |
| health | 记录习惯和健康数据 |
| finance | 记录账户、交易、预算和订阅 |
| vault | 加密存放机密信息、密码和通行密钥 |
| server | 查看运行状态、访问设置、备份和更新 |

在本地财务账本中手动新建的交易可以撤销。撤销只会删除那一笔交易，而且前提是它保存的内容没有改动过；如果响应中断，同一笔交易仍可重试。Actual 交易、导入和转账沿用各自已有的审核和删除流程。

有些功能需要先连接才能用。添加 IMAP/SMTP 账户来使用邮件，连接相应服务来使用在线存储或银行功能；想用 aide 的话，到 **settings → models** 添加模型。也可以用 Ollama 运行本地模型。

界面支持 english, français, español, 简体中文, 繁體中文, 日本語, 한국어 和 العربية。在 **设置 → 语言与地区** 里选择。

[specifications.md](../../specifications.md) 详细介绍了各应用的行为、架构、API 和配置。

## 你的数据与备份

默认情况下，数据库和 alles 管理的文件都放在 `data/` 中。想放到别处，可以设置 `ALLES_DATA`。这个文件夹不要公开，并记得备份。外部服务商会收到你通过它们的连接发出的请求。

打开 **settings → backup** 可以下载加密备份。你也可以手动把备份发送到现有的 HTTPS WebDAV 文件夹或兼容 S3 的存储桶，或者在初始设置时开启每日本地备份。请把恢复密钥存放在 alles 之外的地方，这样即使应用无法运行，你也能找到它。

alles 会先检查备份并准备好恢复，然后才应用。请先停止应用，再按照它给出的命令操作。迁移现有安装之前，请阅读[备份与恢复详情](../../specifications.md#your-data-where-everything-lives)。

## 作为服务安装

如果想在 macOS 或 Linux 上把 alles 作为服务运行，请执行 `bash alles install`。它会创建自己的 Python 环境，并添加 `alles` 命令。用 `alles update` 更新，或用 `alles update rollback` 回到之前的代码和数据。`bash alles uninstall` 会保留你的个人数据。`bash alles --help` 会列出所有命令。

alles 用 FastAPI、SQLite、原生 JavaScript 和 CSS 构建，前端没有构建步骤。技术细节见 [specifications.md](../../specifications.md)。

## 版本历史

[davinci](../../docs/releases/davinci.md) 记录了已完成的日常工作流里程碑。

## 致谢与许可证

aide 的灵感来自 [odysseus](https://github.com/pewdiepie-archdaemon/odysseus)。alles 是独立实现的；[acknowledgments.md](../../ACKNOWLEDGMENTS.md) 列出了对该项目以及 alles 所用其他成果的致谢。第三方许可证见[第三方声明](../../THIRD_PARTY_NOTICES.md)。

alles 采用 [MIT 许可证](../../LICENSE)发布。
