## 约束

- 当用户想要做什么新功能或者实现什么新的产品的时候，先检索GitHub查看有无类似的开源项目。如果有比较贴近的，需要仔细分析它和用户想法的相似度和关联度，然后请示用户。如果没有或者大多不相关，则开始规划和开发。
- 每次对话结束后，要做到：根据用户的输入，推测用户的偏好，然后写入'./CLAUDE.md'的'## Learned User Preferences'章节。
- **绝对禁止**：在探索项目结构、查找函数/类定义、定位文件或追踪调用关系时，严禁第一时间使用 find 或 ls -R 等 Bash 命令进行全局检索。
- **唯一入口**：上述场景下，必须且只能先调用 CodeGraph 获取语义索引和结构关系：执行 `codegraph explore "<符号名或问题>"` 一次调用即可回答大多数代码问题——它会返回相关符号的逐行源代码（带行号），以及这些符号之间的调用路径，能跟踪动态分发（dynamic dispatch）跳转。你可以在查询中指定某个文件或符号名，以读取其当前带行号的源代码。如果输出中列出某项但标记为“延迟加载（deferred）”，可通过工具搜索按名称加载它。
以下为几个示例及说明：
- **查询某个函数的实现**：执行 `codegraph explore "read_file"` 即可查看 `read_file` 函数的实现代码。
- **查跨文件调用链**：执行 `codegraph explore "Orchestrator.run"` 即可查看 `Orchestrator.run` 其调用链。
注意，`codegraph`已经注册到系统里了，你可以安全的调用它。该程序并不在当前目录下，你没有必要去寻找它。但是系统里没有安装`grep`命令，调用会报错。

## Learned User Preferences

- 默认使用中文回复；技术术语可按需保留英文。
- 当你修复完bug后，一定要运行它，禁止修复完不检查不运行就交还给用户。
- 进行 git commit 时，提交信息必须按功能点分组、附结构化需求块（如 FR/NFR/AC）。
- **Plan 与 git commit 信息严禁出现客户信息**：不得在 plan 标题/正文、Plan-Id slug、commit subject/body 中写入客户名称、客户代号、客户目录路径或可识别标识；一律用「Enterprise 交付」「客户项目」「外部招标文档本地目录」等中性表述；Plan 文件名也不得嵌入客户 slug。
- 当用户需要你查找代码失败的原因/解决某一个bug的时候，通过调用各种工具，必须拿出代码级证据定位错误原因。
- 用户对容错性有较高要求：LLM 调用或工具调用失败时不应直接中断，
  应重试多次后再决定是否退出；JSON 解析错误应归入工具调用错误类别。
- Agnet 工作流的设计模式：Coder Agent（实现）→ Reviewer Agent（审查）→ 反馈循环，每轮落盘持久化。
- 当前每完成一次工作后，对当前工作进行简短总结，使用git工具进行提交。**不要使用git push**。
- 具体的文件级工程记忆写入对应的文件头部注释。
- **飞书集成偏好**：用户明确要求**不使用第三方开源项目**，倾向使用飞书官方提供的 MCP 服务器或飞书开放平台的原生能力。用户在 Issue #5 的讨论中拒绝了第三方开源 MCP 项目方案。

## Learned Workspace Facts

- 运行全部测试命令：`python -m pytest tests/ -v`（或 `pytest tests/ -v`）。
- 环境变量 `BASH_GUARD_LLM_DISABLED=1` 在测试中自动设置以跳过 LLM 安全审查层。
- MCP Server 支持: `src/tools/mcp_manager.py`，支持 HTTP 和 Command 两种类型。
- MCP 配置文件: `~/.becode/mcp.json`（主），`~/.becode/mcp_servers.json`（兼容旧版）。
  同时会加载项目根目录 `mcp.json` 并与之合并（项目配置优先级更高）。
- 首次运行时静默创建 `~/.becode/.env` 和 `~/.becode/mcp.json`（即 `ensure_config()` 不再弹出交互式提示）。
- `/CODE_MAP.md` 文件为代码地图，包含目录结构与代码文件的简要说明。
- **Compressor Agent**: `src/core/context_compressor.py` 实现独立的 Compressor Agent，
  当上下文达到 `max_context_length` 的 90%（硬编码阈值）时触发 Map-Reduce 压缩。
  压缩后 Coder Agent 上下文 = 用户原文 + 压缩摘要 + 最近三轮工具调用记录。
  压缩事件记录在 session 的 `compression_events` 列表中。
- **MCP args_schema 关键修复**: `StructuredTool.from_function(func=fn)` 无 `args_schema`
  参数时，对于 `**kwargs` 函数会生成仅含 `kwargs: dict` 的 schema，导致 LLM 传入
  的参数被 LangChain 静默丢弃。`_create_args_schema()` 将 MCP 工具的 `input_schema.
  properties` 转为 Pydantic model，确保参数正确传递。`_make_mcp_tool_fn()` 中还会
  在调用前过滤掉值为 `None` 的参数，避免 MCP 服务器拒绝 `null` 值。
- **飞书机器人集成背景**：
  - 飞书（Feishu/Lark）开放平台提供 Bot API：消息推送、事件订阅、交互式卡片。
  - 官方 Python SDK: `lark-oapi`。
  - ❗ **飞书官方 MCP Server 已存在**：`larksuite/lark-openapi-mcp`（npm: `@larksuiteoapi/lark-mcp`），由 Lark 官方 GitHub 组织发布，非第三方项目。已将飞书开放平台 300+ API 封装为 MCP 工具（文档/消息/日历/多维表格/通讯录/任务等）。状态为 Beta（v0.5.1），770 stars，支持 stdio/SSE/StreamableHTTP 三种传输模式。
  - **用户明确要求**：不使用第三方开源项目，倾向飞书官方 MCP 服务器或开放平台原生能力。
  - BeCode 集成推荐路线：直接使用飞书官方 MCP Server（`@larksuiteoapi/lark-mcp`），通过 BeCode 的 `mcp_manager.py` 加载 Command 类型 MCP Server，**不需要自实现 MCP Server 代码**。
  - 配置方式：`"command": "npx", "args": ["-y", "@larksuiteoapi/lark-mcp", "mcp", "-a", "<APP_ID>", "-s", "<APP_SECRET>"]`
  - 支持两种认证模式：`tenant_access_token`（应用级）和 `user_access_token`（OAuth 用户级扫码授权）。
  - 支持双版本：国内版默认（`open.feishu.cn`），国际版 `--domain https://open.larksuite.com`。
  - BeCode 仓库已存在 issues：#1（GitHub MCP 测试）、#5（飞书机器人支持提议）。
  - **飞书 MCP 快速接入体系（7 个快捷方式，按推荐优先级排列）**：
    1. **预设工具集（Presets）**：按场景打包 API 工具，`-t preset.im.default` 一行配置代替手工挑选 300+ API。可用预设：`preset.default`（默认，通用）、`preset.light`（最小化）、`preset.im.default`（消息）、`preset.base.default`（多维表格）、`preset.doc.default`（文档）、`preset.task.default`（任务）、`preset.calendar.default`（日历）。
    2. **批量导入权限 JSON 模板**：`mcp_larkbot_demo` 已提供完整权限模板，粘贴即用，无需手工勾选。
    3. **官方 Demo 模板（lark-samples）**：[lark-samples](https://github.com/larksuite/lark-samples) 仓库提供可直接运行的模板：`mcp_larkbot_demo/nodejs`（MCP 飞书 Bot Agent，含 AI 集成）、`mcp_quick_demo/{python,go,java,nodejs}`（多语言 MCP 快速入门）、`robot_quick_start/python`（飞书机器人快速开发）。
    4. **OAuth 扫码登录**：一人配置 App ID/Secret，全团队扫码使用；支持 `--scope offline_access docx:document` 等细粒度授权范围。
    5. **WebSocket 长连接**：跳过 HTTP 回调配置，无需公网 IP/域名/HTTPS。
    6. **多语言 SDK 框架支持**：LangChain（Python/Node.js）、Spring AI（Java）、Vercel AI SDK（Node.js）、`@larksuiteoapi/node-sdk`、`lark-oapi`（Python），均提供完整示例。
    7. **MCP 一键安装按钮**：支持 Cursor/Trae 等 AI IDE 的一键安装（deep link）。
  - **lark-openapi-mcp 关键特性**：
    - 依赖：`@larksuiteoapi/node-sdk ^1.50.0`、`@modelcontextprotocol/sdk ^1.12.1`、`commander ^13.1.0`
    - 支持配置文件：通过 `--config ./config.json` 传入 JSON 配置（支持 `appId`/`appSecret`/`tools`/`language`/`oauth`/`tokenMode`/`mode`/`host`/`port` 等字段）
    - 支持环境变量：`APP_ID`、`APP_SECRET`、`LARK_TOOLS`（工具列表）、`LARK_DOMAIN`、`LARK_TOKEN_MODE`
    - OAuth 登录命令：`npx -y @larksuiteoapi/lark-mcp login -a <APP_ID> -s <APP_SECRET>`（默认重定向 URL: http://localhost:3000/callback）
    - 清空登录令牌：`npx -y @larksuiteoapi/lark-mcp logout -a <APP_ID>`
  - **飞书应用商店模式**：应用上架到飞书应用商店后，企业管理员可扫码一键安装，但需通过飞书审核流程。