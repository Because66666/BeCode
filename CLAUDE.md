## 约束

- 当用户想要做什么新功能或者实现什么新的产品的时候，先检索GitHub查看有无类似的开源项目。如果有比较贴近的，需要仔细分析它和用户想法的相似度和关联度，然后请示用户。如果没有或者大多不相关，则开始规划和开发。
- 每次对话结束后，要做到：根据用户的输入，推测用户的偏好，然后写入'./CLAUDE.md'的'## Learned User Preferences'章节；已实现的重要项目事实/工程记忆模块，需要避免的代码坑点，是需要写入'./CLAUDE.md'的'## Learned Workspace Facts'。



## Learned User Preferences

- 默认使用中文回复；技术术语可按需保留英文。
- 当你修复完bug后，一定要运行它，禁止修复完不检查不运行就交还给用户。
- 进行 git commit 时，提交信息必须包含 `Made-with: Because66666`，并偏好按功能点分组、附结构化需求块（如 FR/NFR/AC）。
- Plan 文档必须落盘到 `.trae/plans/` 并随代码一起提交，不能遗漏。
- **Plan 与 git commit 信息严禁出现客户信息**：不得在 plan 标题/正文、Plan-Id slug、commit subject/body 中写入客户名称、客户代号、客户目录路径或可识别标识；一律用「Enterprise 交付」「客户项目」「外部招标文档本地目录」等中性表述；Plan 文件名也不得嵌入客户 slug。
- 当用户需要你查找代码失败的原因/解决某一个bug的时候，通过调用各种工具，必须拿出代码级证据定位错误原因。
- 偏好 OpenAI 协议兼容模型（API Base/Key/Model 从 .env 读取），使用 LangChain 最新版（1.3+）的 `create_agent` API（LangGraph 架构），而非旧版 `AgentExecutor`。
- Bash 安全采用"规则（黑名单正则）+ 独立 LLM 审查"双层校验，LLM 审查使用无上下文的干净调用；LLM 不可达时规则层依然生效并放行（fail open with warning）。
- Agnet 工作流的设计模式：Coder Agent（实现）→ Reviewer Agent（审查）→ 反馈循环，每轮落盘持久化。
- 当前每完成一次工作后，对当前工作进行简短总结，使用git工具进行提交。**不要使用git push**。

## Learned Workspace Facts

- 项目 `new_agent_workflow` 实现了一个双智能体编码工作流系统，使用 LangChain 1.3+ / LangGraph 架构。
- 代码结构: `src/agents/`（coder + reviewer）、`src/tools/`（read_file, edit_file, bash_exec + bash_guard）、`src/core/`（config, llm_client, session_store, orchestrator）、`src/ui/`（console, callbacks, collapsible）。
- 关键依赖: `langchain>=0.3`, `langchain-openai`, `langgraph`, `python-dotenv`, `pydantic-settings`, `requests`, `beautifulsoup4`, `rich`, `keyboard`。
- 联网检索工具: `web_search` (基于 Bing 搜索, HTML scraping, 解析 li.b_algo 结果) 和 `web_fetch` (基于 requests+BeautifulSoup 的网页内容提取)，注册在 `src/tools/web_search.py` 中。
- 两个智能体（Coder & Reviewer）的工具列表均已包含 `web_search` 和 `web_fetch`，系统提示词也已同步更新。
- `BASH_GUARD_LLM_DISABLED=1` 环境变量可跳过 LLM 审查层（用于测试或无 API Key 环境）。
- **`content='` 显示问题修复**: LangChain 0.3+ 的 `on_tool_end` callback 传递的是 `ToolMessage` 对象而非纯字符串，`str()` 会产出 `content='...' tool_call_id='...'` 格式。修复方式是在 `callbacks.py` 中添加 `_extract_tool_output()` 函数，优先使用 `.content` 属性。
- **工具调用 Panel 简化 (3 行展示)**: `console.py` 的 `tool_call()` 方法现在只展示三行: 第一行工具调用名称（图标+标签），第二行参数（多个参数用 `|` 合并，文件路径自动转为相对路径并截断），第三行执行结果（单行截断 ≤100 字符）。不再使用富格式的 Syntax/Markdown 渲染。
- **移除所有键盘监听和 Ctrl+O 快捷键**: `collapsible.py` 完全移除了 `threading`、`keyboard` 依赖、`_keyboard_listener()` 方法、`start_interactive()` 方法、`toggle_last()`/`toggle_all()` 方法、`COLLAPSE_HINT` 常量以及 `rich.live.Live` 的使用。`CollapsibleDisplay` 简化为纯 section 存储容器。
- **取消并列报告输出**: `console.py` 的 `final_result()` 移除了 Coder 和 Reviewer 报告并排显示的 Table，仅保留紧凑统计信息 Panel（状态、轮次、会话ID、Coder 上下文长度）。
- **移除 `enter_interactive_mode()`**: `console.py` 移除了 `enter_interactive_mode()` 方法及相关交互模式入口。
- `console.py` 移除了 `tool_call_start` 和 `tool_call_end` 方法，新增 `tool_call` 方法实现 3 行精简展示。`collapsible.py` 简化为纯 section 管理器，不再依赖 `keyboard`、`threading`、`rich.live.Live`。
- **`edit_file` 自动创建文件优化**: `src/tools/tools.py` 的 `edit_file` 工具在文件不存在时，不再直接报错，而是检查父目录是否存在；如果父目录存在，则自动创建空文件后再执行替换逻辑（`old_string=""` 时匹配空文件内容，替换后写入 `new_string`）；如果父目录也不存在，则返回"文件路径不存在"错误。
- **Session 记录工具调用**: `ToolCallCapture`（`callbacks.py`）新增 `_tool_calls` 累加器和 `get_tool_calls()` 方法，在 `on_tool_start` 中记录工具名和参数（不含响应）。`Orchestrator.run()` 在每次 Coder/Reviewer 运行后，将工具调用列表通过 `metadata={"tool_calls": [...]}` 传入 `session.add_entry()`，最终持久化到 session JSON 的 `history[].metadata.tool_calls` 字段。
- **Inno Setup 安装程序语言配置**: `installer/becode_setup.iss` 的 `[Languages]` 节配置了三语言：`chinesesimp`（默认，排在首位）、`chinesetrad`（繁体中文）、`english`（英文）。Inno Setup 会使用第一个语言作为安装向导的默认显示语言。
- **`--hello` 参数**: `main.py` 新增 `--hello` 命令行参数，运行 `python main.py --hello` 输出 "hello world test"，实现后立即退出，不影响其他参数功能。
- **交互模式 Ctrl+C 修复**: `main.py` 移除了全局 `_has_formal_output` 标志，改为由 `orchestrator.run_interactive()` 通过返回值 `dict` 的 `interrupted` 和 `has_formal_output` 字段传递中断状态。`result` 变量在使用前已初始化为 `None`。
- **可编辑预填输入**: `console.py` 的 `interactive_prompt()` 支持平台特定的可编辑预填：Windows 上使用 `kernel32.WriteConsoleInputW` 注入按键事件，Unix/macOS 上使用 `readline.set_startup_hook` + `insert_text`。预填文本在输入框中出现且用户可直接编辑（光标在末尾）。
- **Hello World 实现**: `hello_world.py` 是独立的 Hello World 脚本，运行 `python hello_world.py` 输出 `hello world test`。`main.py` 的 `--hello` 参数（`python main.py --hello`）输出 `hello world test` 后立即退出，不影响其他参数功能。
- **`-e` / `--execute` 参数**: `main.py` 新增 `-e`/`--execute` 命令行参数，运行 `python main.py -e ".exit"` 执行 `.exit` 命令后退出程序。目前仅支持 `.exit` 命令（退出程序），未知命令会以 exit code 1 报错。该参数在 `--hello` 之后、数据目录初始化之前处理，与 `--hello` 等参数不冲突。

