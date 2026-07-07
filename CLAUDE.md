## 约束

- 当用户想要做什么新功能或者实现什么新的产品的时候，先检索GitHub查看有无类似的开源项目。如果有比较贴近的，需要仔细分析它和用户想法的相似度和关联度，然后请示用户。如果没有或者大多不相关，则开始规划和开发。
- 每次对话结束后，要做到：根据用户的输入，推测用户的偏好，然后写入'./CLAUDE.md'的'## Learned User Preferences'章节。


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
- 具体的文件级工程记忆写入对应的文件头部注释，其余记忆写入`## Learned Workspace Facts`部分。

## Learned Workspace Facts

- 项目 `new_agent_workflow` 实现了一个双智能体编码工作流系统，使用 LangChain 1.3+ / LangGraph 架构。
- 代码结构: `src/agents/`（coder + reviewer）、`src/tools/`（read_file, edit_file, bash_exec + bash_guard）、`src/core/`（config, llm_client, session_store, orchestrator）、`src/ui/`（console, callbacks, collapsible）。
- 关键依赖: `langchain>=0.3`, `langchain-openai`, `langgraph`, `python-dotenv`, `pydantic-settings`, `requests`, `beautifulsoup4`, `rich`, `keyboard`。
- 具体的文件级工程记忆已移入对应源文件的头部注释中，搜索 `╔══════════════════════════════════════════════════╗` 即可查阅。

