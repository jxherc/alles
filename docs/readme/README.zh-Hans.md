# alles

> 2026 年 7 月 21 日完成审核 · 规范源文件：`README.md` · 源修订：
> `phase10-canonical-2026-07-21`

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) · **简体中文** ·
[繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [العربية](README.ar.md)

**alles** 是一款自托管的个人应用。一个 Python 程序整合了 Aide、搜索、邮件、互相链接的
Markdown 文档、日记、文件、日历、任务、财务、照片、联系人和加密密码库。本地数据保存在
由你控制的文件夹中。Alles 不收集遥测数据；外部服务只会收到你主动选择发送的请求。

## 快速开始

需要 Python 3.11 或更高版本。

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.lock
python app.py
```

打开 `http://localhost:6769`。启动不需要 API 密钥。只有在需要使用 Aide 时，才需要在
**设置 → 模型**中添加模型。

在 macOS/Linux 上进行托管安装可运行 `./alles install`。`alles update` 会暂存并健康检查
新版本；`alles update rollback` 会恢复匹配的旧代码与数据。`./alles uninstall` 不会删除个人数据。

Docker：

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

仅绑定本机回环地址，可让新容器保持在当前设备上。

## 数据、网络与备份

Alles 专为单用户设计。在允许网络访问前，请启用身份验证，设置强所有者密码，并配置真正的
`secret_key`。公开服务前请阅读[安全说明](../../specifications.md#security--read-before-exposing-it)。

你可以在**设置 → 备份**中创建加密本地备份，或手动发送到 WebDAV 或 S3 兼容存储。恢复密钥
必须单独保存。恢复流程会先验证和暂存数据，不会直接改动正在使用的数据。

## 更多信息

完整的应用、路由与架构说明见 [`specifications.md`](../../specifications.md)。依赖项及其许可证见
[`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md)。

## 许可证

MIT。参见 [`LICENSE`](../../LICENSE)。
