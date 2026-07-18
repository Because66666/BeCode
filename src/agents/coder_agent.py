"""Coder Agent — the main coding agent.

Role: Reads the user requirement (plus any reviewer feedback), plans what
to do, then uses the available tools (read_file, edit_file, bash_exec) to
implement the solution.  After finishing, it produces a natural-language
report describing what was done.

Uses ``create_agent`` from ``langchain.agents`` (LangGraph-based).

MCP Server Integration:
- MCP (Model Context Protocol) servers provide additional tools that are
  dynamically discovered at agent build time.
- Both HTTP type and Command type MCP servers are supported.
- The agent receives a formatted context describing all configured MCP
  servers and their available tools.
- A ``list_mcp_servers`` tool allows the agent to inspect configured
  servers at runtime.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - 工具列表已包含 web_search 和 web_fetch，      ║
║    系统提示词也已同步更新。                      ║
║  - 每轮调用 run_coder() 均创建全新的 Agent       ║
║    实例，只传递本轮所需的 requirement + feedback，║
║    绝不携带前一轮的思考内容或工具调用记录。       ║
║    上下文仅包含：需求 / 审查反馈 / 工作区文件。   ║
║  - MCP 服务器支持: HTTP 和 Command 两种类型。    ║
║  - MCP 工具在 Agent 构建时动态发现并注入。       ║
║  - list_mcp_servers 工具供 Agent 查询可用 MCP    ║
║    服务器及其工具列表。                          ║
╚══════════════════════════════════════════════════╝
"""

import logging
from typing import Any, Optional

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.callbacks import Callbacks

from src.core.llm_client import build_chat_model
from src.tools.tools import read_file, edit_file, bash_exec, load_context_files
from src.tools.web_search import web_search, web_fetch
from src.tools.mcp_manager import (
    get_available_mcp_tools,
    format_mcp_context,
    list_mcp_servers_tool,
)
from src.tools.session_memory import session_memory, load_session_memory

logger = logging.getLogger(__name__)

# ── Base system prompt (without MCP section) ───────────────────────────────

CODER_SYSTEM_PROMPT_BASE = """You are an expert coding assistant (Coder Agent) in BeCode. Your goal is to implement
the user's requirements by reading, editing files and running commands.

You have access to these tools:"""


def _build_mcp_tool_descriptions(mcp_tools: list) -> str:
    """Build a formatted description of MCP tools for the system prompt."""
    if not mcp_tools:
        return ""

    lines = []
    # Group tools by server name
    server_groups: dict[str, list[str]] = {}
    for tool in mcp_tools:
        name = tool.name if hasattr(tool, "name") else str(tool)
        # Extract server name from tool name: mcp_{server}_{tool_name}
        parts = name.split("_", 2)
        if len(parts) >= 2:
            server = parts[1]
        else:
            server = "unknown"
        server_groups.setdefault(server, []).append(name)

    lines.append("\n### MCP 服务器工具 (动态扩展)")
    for svr, tool_names in sorted(server_groups.items()):
        lines.append(f"- **{svr}**: {', '.join(sorted(tool_names))}")
    lines.append("")
    return "\n".join(lines)


def _build_system_prompt(mcp_tools_str: str) -> str:
    """Build the complete system prompt including MCP context."""
    mcp_context = format_mcp_context()

    tools_description = """- read_file: Read a file's content (with optional line offset/limit).
- edit_file: Edit a file by exact string replacement (search-and-replace).
- bash_exec: Run a bash command (safety-checked automatically).
- web_search: Search the web for information (e.g., docs, libraries, solutions).
- web_fetch: Fetch and extract text content from a web page URL.
- list_mcp_servers: List all configured MCP servers and their available tools.
- session_memory: 记录/回顾当前交互式对话中的重要项目知识和信息。支持两个模式: write(写入) 和 read only(只读)。当完成任务后有重要信息要记录时使用 write 模式；当对项目感到困惑时使用 read only 模式检查笔记内容。"""

    prompt = f"""You are an expert coding assistant (Coder Agent) in BeCode. Your goal is to implement
the user's requirements by reading, editing files and running commands.

You have access to these tools:
{tools_description}
{mcp_tools_str}
Workflow:
1. First, understand the requirement and plan your approach.
2. If you need external information (library APIs, bug solutions, docs), use web_search.
3. Read any relevant existing files.
4. Create / edit files as needed.
5. Run build / test commands to verify your work.
6. When done, produce a FINAL REPORT that concisely describes:
   - What was implemented
   - Which files were created or modified
   - What commands were run and their results
   - Any issues or limitations

IMPORTANT: Always verify your work by running the code after making changes.
Do not claim completion without testing.

Do NOT run destructive commands like rm -rf / — they will be blocked anyway."

{mcp_context}"""
    return prompt


def build_coder_agent(model_name: Optional[str] = None):
    """Build the Coder LangGraph agent with MCP tool integration.

    Dynamically discovers MCP tools from configured MCP servers and adds
    them to the agent's tool list alongside the built-in tools.
    """
    llm = build_chat_model(temperature=0.0, model=model_name)

    # ── Built-in tools ────────────────────────────────────────────────
    tools = [read_file, edit_file, bash_exec, web_search, web_fetch,
             list_mcp_servers_tool, session_memory]

    # ── MCP tools ─────────────────────────────────────────────────────
    mcp_tools = get_available_mcp_tools()
    tools.extend(mcp_tools)

    # ── Build system prompt with MCP context ──────────────────────────
    mcp_tools_str = _build_mcp_tool_descriptions(mcp_tools)
    system_prompt = _build_system_prompt(mcp_tools_str)

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        debug=False,
    )
    return agent


def run_coder(requirement: str, feedback: str = "", model_name: Optional[str] = None,
              callbacks: Optional[Callbacks] = None) -> str:
    """Run the Coder Agent and return its final report.

    IMPORTANT DESIGN CONSTRAINT:
    Each invocation creates a BRAND-NEW agent instance and builds a single
    ``HumanMessage`` containing ONLY:
      - The original user requirement
      - The reviewer's actionable feedback (if any) — extracted from the
        ``下一轮反馈`` section of the reviewer's verdict, NOT the full review
      - Workspace context files (CLAUDE.md / AGENTS.md)

    **No** previous round's chain-of-thought, tool-call traces, or intermediate
    AI/Tool messages are passed.  This ensures the Coder starts each round with
    a clean context.

    Args:
        requirement: The user's original request.
        feedback: Optional reviewer feedback from a previous round.
        model_name: Optional model override.
        callbacks: Optional LangChain callbacks for UI capture.

    Returns:
        The agent's final natural-language report.
    """
    agent = build_coder_agent(model_name=model_name)

    # ── Load workspace context files (CLAUDE.md / AGENTS.md) ─────
    context = load_context_files()
    context_block = f"\n\n## 工作区上下文\n{context}" if context else ""

    # ── Load session memory (interactive mode notes) ────────────
    session_memory_block = load_session_memory()

    user_message = (
        f"## 用户需求\n{requirement}\n\n"
        f"## 之前的审查反馈\n{feedback if feedback else '(无 — 首轮编码)'}"
        f"{context_block}"
        f"{session_memory_block}\n\n"
        "请实现以上需求，完成后输出 FINAL REPORT。"
    )

    # Build config with callbacks if provided
    config = {}
    if callbacks:
        config["callbacks"] = callbacks

    result = agent.invoke({"messages": [HumanMessage(content=user_message)]}, config=config)

    messages = result.get("messages", [])
    if messages:
        output = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])
    else:
        output = str(result)

    logger.info("Coder agent finished. Output length=%d", len(output))
    return output
