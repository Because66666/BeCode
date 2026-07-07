# BeCode — 双智能体编码工作流

> 基于 LangChain 1.3+  架构的双智能体协作编码系统，实现 **Coder Agent（编码）→ Reviewer Agent（审查）→ 反馈循环** 的自反馈系统。致力于通过提示词工程，让普通模型的编码能力和工程完成度获得提升。

*建议选用模型上下文长度为1M的模型。成本敏感者慎用。*


---

## 作者有话说
- *既然fable5代表着模型进步，会消解之前所做的所有跟提示词相关的工作，那么反推过来，能否通过编排和提示词控制，让现有模型达到那种高度？*
- *当前BeCode的开发，除去第一次构建使用deepseek v4 flash驱动的Claude Code完成编码，为其提供了初始的文件编辑工具和命令运行工具。后面的迭代均使用BeCode自己进行开发（deepseek v4 flash驱动）。*
- *少即是多。*

## ✨ 特性

| 特性 | 说明 |
|------|------|
| **双智能体协作** | Coder Agent 负责需求实现，Reviewer Agent 负责代码审查，形成闭环 |
| **多轮迭代反馈** | 支持最多 N 轮（默认 10 轮）的「编码 → 审查 → 修复」循环，直至审查通过 |
| **文件/命令操作** | 提供 `read_file`、`edit_file`、`bash_exec` 三大核心工具，安全可控 |
| **联网搜索能力** | 集成 `web_search`（Bing 搜索）和 `web_fetch`（网页抓取），可查阅文档/资料 |
| **Bash 安全防护** | 双层安全校验（静态规则 + LLM 语义审查），防止误执行危险命令 |
| **会话持久化** | 每轮对话自动保存到 JSON 文件，支持断点续查 |
| **终端 UI** | 基于 Rich 库的精美命令行界面，实时展示工具调用和智能体报告 |
| **OpenAI 协议兼容** | 支持 OpenAI、DeepSeek、vLLM、OneAPI、Ollama 等任意 OpenAI 兼容 API |

---

## 📦 项目结构

```
├── main.py                      # 入口文件
├── .env                         # 环境变量配置（API Key / Model / 最大轮次）
├── requirements.txt             # Python 依赖
├── CLAUDE.md                    # 工作记忆（约束 / 偏好 / 项目事实）
├── sessions/                    # 会话持久化目录（JSON）
│
├── src/
│   ├── __init__.py
│   │
│   ├── agents/
│   │   ├── coder_agent.py       # Coder Agent — 需求实现智能体
│   │   └── reviewer_agent.py    # Reviewer Agent — 代码审查智能体
│   │
│   ├── core/
│   │   ├── config.py            # 配置管理（从 .env 加载）
│   │   ├── llm_client.py        # LLM 客户端封装（OpenAI 协议）
│   │   ├── orchestrator.py      # 工作流编排器（主循环）
│   │   └── session_store.py     # 会话持久化存储
│   │
│   ├── tools/
│   │   ├── tools.py             # 核心工具（read_file / edit_file / bash_exec）
│   │   ├── bash_guard.py        # Bash 命令安全防护（规则 + LLM 双层校验）
│   │   └── web_search.py        # 联网搜索工具（web_search / web_fetch）
│   │
│   └── ui/
│       ├── console.py           # 终端 UI（AgentConsole — Rich 渲染）
│       ├── callbacks.py         # LangChain 回调处理器（实时展示工具调用）
│       └── collapsible.py       # 输出分段管理器
│
├── web/                         # 会话查看网页（纯前端，本地打开即用）
│   ├── index.html               # 单页应用入口
│   └── assets/                  # 本地化字体 + JS 库（不依赖 CDN）
│
└── .trae/plans/                 # 开发计划文档
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

编辑 `.env` 文件：

```ini
# LLM 配置（OpenAI 协议兼容）
OPENAI_API_BASE=https://api.deepseek.com
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=deepseek-v4-flash

# 工作流配置
MAX_ITERATIONS=10
SESSION_DIR=./sessions

# 日志级别（WARNING 及以上显示到控制台）
LOG_LEVEL=WARNING
```

支持任意 OpenAI 兼容 API（OpenAI、DeepSeek、vLLM、OneAPI、Ollama 等）。

### 3. 运行

```bash
# 方式一：直接传入需求
python main.py "创建一个 Python 脚本，实现斐波那契数列"

# 方式二：从文件读取需求
python main.py --file prompt.txt

# 方式三：交互式输入
python main.py --interactive
```

### 可选参数

| 参数 | 说明 |
|------|------|
| `-m`, `--model` | 覆盖 .env 中的模型名称 |
| `--max-iterations` | 覆盖最大迭代轮数 |

---

## 🧩 工作流架构

```
┌──────────────┐     ┌──────────────┐
│  Coder Agent │ ──→ │ Reviewer     │
│  (实现需求)   │     │ Agent (审查)  │
└──────┬───────┘     └──────┬───────┘
       │                    │
       │  ◄── FAIL ────    │
       │         + 反馈     │
       │                    │
       └──── PASS ────────→ ✅ 完成
```

### 流程说明

1. **用户输入需求** → 系统接收需求文本
2. **Coder Agent** → 分析需求，使用工具（读文件、编辑文件、执行命令、联网搜索）实现代码
3. **Coder 输出报告** → 描述实现内容、修改了哪些文件、运行结果
4. **Reviewer Agent** → 阅读需求和 Coder 报告，使用相同工具验证实现是否完整正确
5. **审查判定**：
   - **PASS** ✅ → 工作流完成，输出最终结果
   - **FAIL** ❌ → 提取详细反馈，返回第 2 步进入下一轮迭代
6. **达最大轮次** → 输出未完成状态和已有成果

---

## 🛠 工具详解

### 核心工具

| 工具 | 功能 | 安全约束 |
|------|------|----------|
| `read_file` | 读取文件内容（支持行偏移/行数限制） | 仅限工作区目录 |
| `edit_file` | 精确字符串替换编辑文件 | 仅限工作区目录，必须唯一匹配 |
| `bash_exec` | 执行 Shell 命令 | **双层安全防护** |

### 联网工具

| 工具 | 功能 | 说明 |
|------|------|------|
| `web_search` | Bing 搜索引擎搜索（HTML 解析） | 本地访问和解析 |
| `web_fetch` | 网页内容提取（BeautifulSoup） | 自动去除导航/脚本/样式 |

### BashGuard 安全防护

所有通过 `bash_exec` 执行的命令均经过 **双层安全校验**：

1. **规则层** — 静态正则黑名单拦截（`rm -rf /`、`mkfs`、`dd`、`shutdown` 等）
2. **LLM 审查层** — 调用独立 LLM 语义判断命令意图（安全/不安全）

> 环境变量 `BASH_GUARD_LLM_DISABLED=1` 可跳过 LLM 审查层（用于测试或无 API Key 环境）。

---

## 📝 会话管理

- 每次运行自动生成唯一会话 ID（8 位 UUID）
- 每轮对话的智能体输出自动保存到 `sessions/session_{id}.json`
- 会话文件包含：原始需求、每轮 Coder 报告、Reviewer 判定、时间戳

---

## 🌐 会话查看网页

项目内置一个纯前端会话查看网页，用于浏览和回顾历史对话记录，无需启动后端服务。

### 特性

- **纯前端实现** — 基于 File System Access API 选择会话文件夹，默认路径提示 `%username%/.becode`
- **本地持久化** — 通过 IndexedDB 保存目录句柄，刷新页面后无需重选文件夹
- **Markdown 渲染** — 智能体报告支持完整 Markdown 渲染（marked.js + DOMPurify）
- **工具调用折叠** — 默认折叠显示工具图标 + 名称 + 参数预览，可批量展开/折叠
- **资产本地化** — 字体（Google Fonts woff2）和 JS 库均已下载到本地，不依赖 CDN
- **中文化界面** — UI 说明文字均为中文，专有名词（BeCode、coder/reviewer 等）保留英文

### 使用方式

1. 使用 **Chrome 或 Edge 86+** 打开 `web/index.html`（直接双击文件即可）
2. 点击顶部路径栏，选择会话文件夹（默认推荐 `%username%/.becode/sessions`）
3. 左侧侧栏显示会话列表，支持按 ID 或需求关键词搜索
4. 点击会话项，右侧详情区展示完整对话时间线、Markdown 报告和工具调用

> 设计风格：白色主题 + 浅蓝副色，编辑型技术日志风格（Fraunces 衬线展示字 + DM Sans 正文 + JetBrains Mono 代码）。

---

## 🎨 终端 UI

基于 Rich 库构建的友好命令行界面：

- 🚀 **启动面板** → 显示会话 ID、模型、最大轮次
- 📋 **需求展示** → 黄色边框 Panel 显示用户需求
- 🤖 **智能体思考** → 绿色/品红色提示当前智能体工作状态
- 💻 **工具调用** → 精简 3 行 Panel（工具名 → 参数 → 结果摘要）
- 📝 **智能体报告** → Markdown 渲染的完整报告
- 🎉 **审查判定** → 通过/未通过的可视化反馈
- 📊 **最终统计** → 状态、轮次、上下文长度统计

---

## 🔧 依赖项

| 依赖 | 版本 | 用途 |
|------|------|------|
| `langchain` | ≥ 0.3.0 |  智能体框架 |
| `langchain-community` | ≥ 0.3.0 | 社区工具/模型 |
| `langchain-openai` | ≥ 0.3.0 | OpenAI 协议 LLM 客户端 |
| `python-dotenv` | ≥ 1.0.0 | .env 环境变量加载 |
| `pydantic` | ≥ 2.0.0 | 数据模型 |
| `pydantic-settings` | ≥ 2.0.0 | 配置管理 |
| `requests` | ≥ 2.31.0 | HTTP 请求 |
| `beautifulsoup4` | ≥ 4.12.0 | HTML 解析 |
| `rich` | ≥ 13.0.0 | 终端 UI 渲染 |

---

## 📄 示例会话

```bash
# 1. 运行系统
python main.py "创建一个 hello.py，打印 'Hello Agent Workflow'"

# 2. 系统输出（精简）
🚀 启动                          会话ID: a1b2c3d4 | 模型: gpt-4o | 最大轮次: 10

📋 用户需求
创建一个 hello.py，打印 'Hello Agent Workflow'

━━━ 第 1/10 轮 ━━━

🤖 Coder Agent 思考中...
💻 命令调用 | command=python hello.py | exit code: 0\nHello Agent Workflow
📝 Coder Agent 报告
已创建 hello.py，运行输出: Hello Agent Workflow

🔍 Reviewer Agent 思考中...
📖 文件读取 | path=hello.py | 文件行数: 1
💻 命令调用 | command=python hello.py | exit code: 0\nHello Agent Workflow
🔍 Reviewer Agent 报告
✅ 审查通过！代码正确输出 "Hello Agent Workflow"。

🎉 审查通过
📊 统计信息 | 状态: ✅ 成功 | 轮次: 1 | 会话ID: a1b2c3d4 | Coder上下文: 0.5K

📁 会话文件: ./sessions/session_a1b2c3d4.json
```

---

## 📜 许可证

本项目仅供学习和参考使用。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。建议先在 Issue 中讨论设计方案。
