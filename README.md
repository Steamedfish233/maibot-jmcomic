# JMComic 助手 (maibot-jmcomic)

> 基于 `jmcomic` 的 MaiBot 第三方插件，支持 JM 作品搜索、验车预览、加密 PDF 发送和随机本子。

---

## 功能特性

| 功能 | 说明 |
|------|------|
| **JM搜索** | `/JM搜索 关键词` 或 `/JM 搜索 关键词` 搜索作品，并返回名称与 JM 车牌号 |
| **JM验车** | `/JM验车 123456` 发送作品信息和前几张预览图的 QQ 合并转发消息 |
| **PDF 发送** | `/JM下载 123456` 下载指定作品，转换为加密 PDF 后通过 NapCat 文件发送 |
| **PDF 密码** | 生成的 PDF 密码为作品车牌号，例如 `123456` |
| **随机本子** | `随机本子` 随机抽取一个作品，并按验车形式发送预览 |
| **白名单控制** | 仅允许配置中的用户/群聊使用下载、验车、搜索和随机功能 |
| **自动撤回** | 处理提示、完成提示和错误提示可按配置自动撤回，默认开启 |
| **AI 智能调用** | 用户自然语言表达“下载 JM”“验车”“搜索车号”“随机本子”等意图时，可由 MaiBot 调用工具 |
| **热重载配置** | 修改 `config.toml` 后通过 MaiBot 插件配置更新机制调用 `on_config_update`，无需重启主程序 |
| **临时文件清理** | 插件只临时下载、转换和发送；发送流程结束后自动删除临时图片与 PDF |

---

## 安装

将 `maibot-jmcomic` 文件夹放入 MaiBot 的 `plugins` 目录下：

    MaiBot/
    ├── plugins/
    │   └── maibot-jmcomic/
    │       ├── _manifest.json
    │       ├── plugin.py
    │       ├── config.toml
    │       ├── config.example.toml
    │       ├── .gitignore
    │       ├── README.md
    │       └── _locales/
    │           └── zh-CN.json
    └── ...

依赖已在 `_manifest.json` 中声明：

- `jmcomic`
- `pillow`
- `pypdf`

如需手动安装到 MaiBot 使用的 Python 环境：

    pip install jmcomic pillow pypdf -U

如果使用 MaiBot OneKey 自带 Python：

    "d:\maibot\MaiBot OneKey\resources\runtime\python\python.exe" -m pip install jmcomic pillow pypdf -U

---

## 配置说明

配置文件为 `config.toml`，也可在 MaiBot WebUI 配置编辑器中修改。

### 插件开关

    [plugin]
    enabled = true
    config_version = "1.0.0"

### JMComic 设置

    [jm]
    option_file = ""
    temp_dir = "data/temp"
    max_search_results = 5
    preview_image_count = 5

- `option_file`：自定义 JMComic `option.yml` 路径。留空时插件自动生成最小配置。
- `temp_dir`：临时目录，只用于下载、生成 PDF、准备验车图。
- `max_search_results`：搜索结果最多返回数量。
- `preview_image_count`：验车发送前几张图片，默认 5。

### 发送设置

    [send]
    notice_before_download = true
    pdf_quality = 90
    recall_notice_messages = true
    recall_after_seconds = 60

- `notice_before_download`：处理前是否发送提示。
- `pdf_quality`：PDF 图片质量，范围 1-95。
- `recall_notice_messages`：是否自动撤回处理提示、完成提示和错误提示。
- `recall_after_seconds`：提示消息自动撤回延迟秒数，设置为 `0` 表示不撤回。

### 隐私白名单

    [privacy]
    allowed_users = ["123456789"]
    allowed_groups = ["987654321"]

- `allowed_users`：允许使用插件功能的用户 QQ 号。
- `allowed_groups`：允许使用插件功能的群聊 QQ 号。
- 私聊调用：用户 QQ 必须在 `allowed_users` 中。
- 群聊调用：群号必须在 `allowed_groups` 中，发起命令的用户 QQ 也必须在 `allowed_users` 中。
- 两个白名单默认为空；空白名单表示没有任何用户/群聊可调用下载、验车、搜索和随机本子功能。

---

## 使用方法

### 命令调用

    /JM help
    /JM搜索 关键词
    /JM 搜索 关键词
    /JM验车 123456
    /JM下载 123456
    随机本子

### AI 智能调用示例

- “帮我下载 JM123456 发给我”
- “JM123456 验车”
- “搜一下关键词相关的 JM”
- “随机来一本”

---

## 热重载配置

插件实现了 `on_config_update`：

1. 在 WebUI 修改 `config.toml` 或插件配置。
2. 保存配置。
3. MaiBot 触发配置更新后，插件会重新读取临时目录、搜索数量、验车张数、PDF 质量和白名单配置。
4. 不需要重启 MaiBot 主程序。

---

## 文件结构

    maibot-jmcomic/
    ├── _manifest.json          # 插件元数据清单（manifest v2）
    ├── plugin.py               # 插件主入口（配置模型 + Tool + Command）
    ├── config.example.toml     # 配置模板文件
    ├── config.toml             # 用户配置文件
    ├── .gitignore              # Git 忽略规则
    ├── README.md               # 使用说明
    └── _locales/
        └── zh-CN.json          # 中文本地化信息

---

## 免责声明

1. 本项目仅用于 MaiBot 插件开发学习、技术研究和个人自动化实践。
2. 本项目不提供、存储、分发任何漫画、图片、文本或其他受版权保护的内容。
3. 本项目调用第三方库 `jmcomic` 访问外部站点；外部站点的可用性、内容合法性、版权归属与访问风险均与本项目作者无关。
4. 使用者应自行确认所在国家或地区的法律法规、平台规则、群聊规则以及内容版权要求，并自行承担使用本插件产生的一切后果。
5. 使用者不得将本插件用于传播侵权内容、违法内容、未成年人不宜内容或任何违反服务条款的行为。
6. 本项目作者不对因使用、修改、分发本插件导致的账号风险、数据损失、法律纠纷、平台封禁或其他直接/间接损失承担责任。
7. 如果你不同意本免责声明，请不要安装、运行、分发或使用本插件。

---

## 隐私声明

1. 本插件不包含遥测、埋点、远程统计或向插件作者上传数据的功能。
2. 本插件不会主动收集用户真实身份信息；但为实现白名单控制，会读取 MaiBot/NapCat 传入的 QQ 用户号、群号和会话信息。
3. 白名单数据仅保存在本地 `config.toml` 中，由部署者自行维护。
4. 下载、验车和 PDF 转换过程中会在本地临时目录生成图片和 PDF 文件；发送完成或流程结束后会自动清理。
5. 本插件会通过 NapCat API 向 QQ 会话发送文本、图片、合并转发消息和文件；相关消息内容会经过 QQ/NapCat/MaiBot 所在运行环境处理。
6. 本插件依赖 `jmcomic` 访问外部站点；外部站点可能根据其自身规则记录访问日志、请求信息或网络信息，本插件无法控制这些行为。
7. 请不要在 `config.toml`、`option.yml` 或仓库中提交账号、Cookie、Token、代理凭据、私密群号、私密 QQ 号等敏感信息。

---

## 发布到 GitHub 前建议

请确认以下文件不要提交：

- `config.toml`
- `data/`
- `__pycache__/`
- `*.pyc`
- 包含 Cookie、Token、账号、代理密码的 `option.yml`

插件目录内的 `.gitignore` 已默认忽略上述运行时文件。

---

## 注意事项

1. 本插件只修改自身插件目录，不修改 MaiBot 主程序。
2. PDF 发送和合并转发依赖 NapCat 适配器 API。
3. 如果 JMComic 无法访问站点，请配置自定义 `option.yml` 并在 `option_file` 填写路径。
4. 插件不会保留本子下载结果；图片和 PDF 都会在发送流程结束后清理。
5. 插件启动阶段只初始化路径和目录；`jmcomic`、`Pillow` 与 `pypdf` 在实际命令执行时才导入，避免加载阶段卡住。

---

## 许可证

MIT
