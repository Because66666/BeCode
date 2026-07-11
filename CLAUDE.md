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
- 进行 git commit 时，提交信息必须包含 `Made-with: Because66666`，并偏好按功能点分组、附结构化需求块（如 FR/NFR/AC）。
- **Plan 与 git commit 信息严禁出现客户信息**：不得在 plan 标题/正文、Plan-Id slug、commit subject/body 中写入客户名称、客户代号、客户目录路径或可识别标识；一律用「Enterprise 交付」「客户项目」「外部招标文档本地目录」等中性表述；Plan 文件名也不得嵌入客户 slug。
- 当用户需要你查找代码失败的原因/解决某一个bug的时候，通过调用各种工具，必须拿出代码级证据定位错误原因。
- 用户对容错性有较高要求：LLM 调用或工具调用失败时不应直接中断，
  应重试多次后再决定是否退出；JSON 解析错误应归入工具调用错误类别。
- Agnet 工作流的设计模式：Coder Agent（实现）→ Reviewer Agent（审查）→ 反馈循环，每轮落盘持久化。
- 当前每完成一次工作后，对当前工作进行简短总结，使用git工具进行提交。**不要使用git push**。
- 具体的文件级工程记忆写入对应的文件头部注释，其余重要的记忆写入`## Learned Workspace Facts`部分。只写你认为以后用的上的，至于你具体实现了什么不必写。

## Learned Workspace Facts

- 代码结构: `src/agents/`（coder + reviewer）、`src/tools/`（read_file, edit_file, bash_exec + bash_guard）、`src/core/`（config, llm_client, session_store, orchestrator）、`src/ui/`（console, callbacks, collapsible）。
- 关键依赖: `langchain>=0.3`, `langchain-openai`, `langgraph`, `python-dotenv`, `pydantic-settings`, `requests`, `beautifulsoup4`, `rich`, `keyboard`。
- 具体的文件级工程记忆已移入对应源文件的头部注释中，搜索 `╔══════════════════════════════════════════════════╗` 即可查阅。
- 测试文件位于 `tests/` 目录，覆盖所有模块：config, llm_client, session_store, tools,
  bash_guard, web_search, orchestrator, console, callbacks, collapsible,
  coder_agent, reviewer_agent, main, mcp_manager。
- 运行全部测试命令：`python -m pytest tests/ -v`（或 `pytest tests/ -v`）。
- 由于 `@tool` 装饰器返回 `StructuredTool` 对象，测试中使用 `tool.func()` 
  调用原始函数（通过 `_call(tool, *args)` 辅助函数）。
- 环境变量 `BASH_GUARD_LLM_DISABLED=1` 在测试中自动设置以跳过 LLM 安全审查层。
- MCP Server 支持: `src/tools/mcp_manager.py`，支持 HTTP 和 Command 两种类型。
- MCP 配置文件: `~/.becode/mcp.json`（主），`~/.becode/mcp_servers.json`（兼容旧版）。
  同时会加载项目根目录 `mcp.json` 并与之合并（项目配置优先级更高）。
- 首次运行时静默创建 `~/.becode/.env` 和 `~/.becode/mcp.json`（即 `ensure_config()` 不再弹出交互式提示）。
- MCP 工具在 `build_coder_agent()` 时动态发现，包装为 `StructuredTool` 注入 Agent。
- `list_mcp_servers` 工具让 Agent 可见所有已配置的 MCP 服务器及其工具。
- HTTP 类型的 MCP 服务器支持 `headers` 配置项，支持 `${ENV_VAR}` 环境变量替换。
  GitHub MCP 使用 `Authorization: Bearer ${GITHUB_TOKEN}` 进行认证。
- TokenTracker 改为按 agent（coder/reviewer）分开统计，支持 snapshot/restore
  机制避免重试时的重复计数。Orchestrator 在每次 agent 尝试前调用
  `snapshot()`，失败后调用 `restore()` 回滚。
- `console.final_result()` 展示按 agent 拆分的 token 统计（coder/reviewer/合计）。
- KeyboardInterrupt 三层防御: (1) `run_interactive()` 内部捕获 → 返回 `interrupted=True`; (2) `interactive_mode()` 内部循环和 while 外围各有一个 except; (3) `main()` 顶层兜底。所有入口统一用 `show_interrupt_message()` 显示「用户已取消任务」，不渲染 traceback。
