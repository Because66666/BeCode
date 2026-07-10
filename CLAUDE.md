## 约束

- 当用户想要做什么新功能或者实现什么新的产品的时候，先检索GitHub查看有无类似的开源项目。如果有比较贴近的，需要仔细分析它和用户想法的相似度和关联度，然后请示用户。如果没有或者大多不相关，则开始规划和开发。
- 每次对话结束后，要做到：根据用户的输入，推测用户的偏好，然后写入'./CLAUDE.md'的'## Learned User Preferences'章节。

## CodeGraph

当你需要探索项目代码的时候，**优先使用CodeGraph**理解和定位代码。具体方式如下：

- **Shell 命令**：执行 `codegraph explore "<符号名或问题>"` 一次调用即可回答大多数代码问题——它会返回相关符号的**逐行源代码（带行号）**，以及这些符号之间的**调用路径**，甚至能跟踪**动态分发（dynamic dispatch）跳转**。你可以在查询中指定某个文件或符号名，以读取其当前带行号的源代码。如果输出中列出某项但标记为“延迟加载（deferred）”，可通过工具搜索按名称加载它。

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
- 具体的文件级工程记忆写入对应的文件头部注释，其余记忆写入`## Learned Workspace Facts`部分。

## Learned Workspace Facts

- 使用 `scripts/crop_circle.py` 将 `favicon.png` 裁剪为正圆形，基于 Pillow (PIL) 实现，输出 `favicon_circle.png`。
- 项目 `new_agent_workflow` 实现了一个双智能体编码工作流系统，使用 LangChain 1.3+ / LangGraph 架构。
- 代码结构: `src/agents/`（coder + reviewer）、`src/tools/`（read_file, edit_file, bash_exec + bash_guard）、`src/core/`（config, llm_client, session_store, orchestrator）、`src/ui/`（console, callbacks, collapsible）。
- 关键依赖: `langchain>=0.3`, `langchain-openai`, `langgraph`, `python-dotenv`, `pydantic-settings`, `requests`, `beautifulsoup4`, `rich`, `keyboard`。
- 具体的文件级工程记忆已移入对应源文件的头部注释中，搜索 `╔══════════════════════════════════════════════════╗` 即可查阅。
- Coder Agent 调用失败时最多重试 3 次（`MAX_CODER_RETRIES = 3`），
  期间不将主动权移交给 Reviewer。第 4 次失败时退出系统并展示
  `_show_coder_fatal_error()` 面板（红色边框，含错误分类）。
- 错误分类由 `classify_coder_error()` 实现，基于异常类型名称（如
  `APIError` → 大模型调用出错，`OutputParserException` → 工具调用错误）
  和异常消息关键词匹配。
- JSON 解析错误（`OutputParserException`）归类为「工具调用错误」。
- Reviewer Agent 同样有重试机制（3 次重试，第 4 次产生占位判决，
  不中断循环）。
- `bash_guard.py` 新增 allowlist 机制（`ALLOWED_PREFIXES` 列表 + `_is_allowed()`），
  匹配的命令可跳过规则检查和 LLM 审查直接放行。当前 allowlist 包含 `codegraph explore`。
- 测试文件位于 `tests/` 目录，覆盖所有模块：config, llm_client, session_store, tools,
  bash_guard, web_search, orchestrator, console, callbacks, collapsible,
  coder_agent, reviewer_agent, main。
- 运行全部测试命令：`python -m pytest tests/ -v`（或 `pytest tests/ -v`）。
- 由于 `@tool` 装饰器返回 `StructuredTool` 对象，测试中使用 `tool.func()` 
  调用原始函数（通过 `_call(tool, *args)` 辅助函数）。
- 环境变量 `BASH_GUARD_LLM_DISABLED=1` 在测试中自动设置以跳过 LLM 安全审查层。
- Token 用量追踪: `src/core/token_tracker.py` 提供全局 `TokenTracker` 单例（`get_token_tracker()`），
  在 `ToolCallCapture.on_llm_end()` 中自动捕获每次 LLM 调用的输入/输出 tokens
  （从 `LLMResult.llm_output.token_usage` 或 `AIMessage.usage_metadata` 提取），
  并累计到会话级计数器。
- Orchestrator 在每次 `run()` 和 `run_interactive()` 开始时调用
  `get_token_tracker().reset()` 重置计数器。
- 统计信息面板（`console.final_result()`）新增显示「输入Tokens」「输出Tokens」「合计」，
  支持 K/M 单位格式化。
- 工具返回值长度限制: 所有 Agent 工具（read_file, edit_file, bash_exec, web_search,
  web_fetch）的返回值若超过 40,000 字符，会被强制替换为提示消息
  「命令返回长度超过10ktoken，请检查后重试」。
  实现在 `src/tools/tools.py` 和 `src/tools/web_search.py` 中的
  `_apply_output_limit()` 函数，常量 `MAX_TOOL_OUTPUT_LENGTH = 40000`。

