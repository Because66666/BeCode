# BeCode 代码地图

```
BeCode/
│
├── main.py                           # 主入口：交互式对话 / 单次运行
├── becode_cli.py                     # PyInstaller 打包入口，委托给 main.py
│
├── src/
│   ├── agents/
│   │   ├── coder_agent.py            # 编码 Agent：根据需求+审查反馈生成代码
│   │   └── reviewer_agent.py         # 审查 Agent：检查 Coder 输出质量，返回结构化反馈
│   │
│   ├── core/
│   │   ├── config.py                 # 全局配置：从 ~/.becode/.env 加载环境变量
│   │   ├── llm_client.py             # LLM 客户端封装：兼容 OpenAI / vLLM / Ollama 等
│   │   ├── orchestrator.py           # 工作流编排器：驱动 Coder↔Reviewer 迭代循环
│   │   ├── context_compressor.py     # 上下文压缩：Map-Reduce 策略压缩历史对话
│   │   ├── session_store.py          # 会话持久化：将对话写入 ~/.becode/sessions/ JSON
│   │   └── token_tracker.py          # Token 追踪：按 agent 分拆统计 + 重试回滚
│   │
│   ├── tools/
│   │   ├── __init__.py               # 导出 MCP 管理工具 (list_mcp_servers 等)
│   │   ├── tools.py                  # 核心工具：read_file, edit_file, bash_exec, load_context_files
│   │   ├── bash_guard.py             # Bash 安全审查：LLM 审查 + 规则审查双模式
│   │   ├── session_memory.py         # 会话记忆工具：记录/回顾交互式对话中的项目笔记
│   │   ├── web_search.py             # 网络搜索：Bing 抓取 (web_search) + 网页提取 (web_fetch)
│   │   ├── mcp_manager.py            # MCP 服务器管理：HTTP/Command 类型，动态发现工具
│   │   ├── prompt_platform_darwin.md # macOS 平台 bash 提示词模板
│   │   └── prompt_platform_windows.md# Windows 平台 bash 提示词模板
│   │
│   └── ui/
│       ├── console.py                # 终端渲染：Agent 消息、工具调用、统计面板、交互式 Prompt
│       ├── callbacks.py              # LangChain 回调：累加工具调用、捕获 CoT 推理文本
│       └── collapsible.py            # 可折叠面板容器
│
├── web/
│   ├── index.html                    # 会话查看器 SPA：离线浏览 session JSON（File System Access API）
│   ├── favicon.ico                   # 网站图标
│   └── assets/
│       ├── fonts.css                 # 字体声明：DM Sans / Fraunces / JetBrains Mono
│       ├── marked.min.js             # Markdown → HTML 渲染库
│       ├── purify.min.js             # DOMPurify XSS 防护库
│       └── fonts/                    # 8 个自托管 woff2 字体文件
│
└── tests/                            # pytest 测试套件，覆盖所有模块
```

维护说明：保持原有结构不变，新增代码文件需要修订目录结构，再用注释一句话表示这个文件的功能。