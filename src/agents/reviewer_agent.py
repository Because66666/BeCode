"""Reviewer Agent — verifies the Coder Agent's work.

Role: Given the original user requirement + the Coder Agent's latest
natural-language report, the Reviewer uses the same tools to check
whether the implementation is complete and functional.

It does NOT see the coder's conversation history — only the requirement
and the final report.

Output: A natural-language review verdict:
- If PASS: states that everything is complete.
- If FAIL: lists exactly what is missing / broken, in enough detail
  that the Coder Agent can act on the feedback.

Uses ``create_agent`` from ``langchain.agents`` (LangGraph-based).

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - 工具列表已包含 web_search 和 web_fetch，      ║
║    系统提示词也已同步更新。                      ║
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

logger = logging.getLogger(__name__)

REVIEWER_SYSTEM_PROMPT = """You are a strict code review agent (Reviewer Agent). Your job is to verify
whether the Coder Agent has fully and correctly implemented the user's
requirements.

You have the same tools as the coder:
- read_file: Read file contents to inspect the implementation.
- edit_file: NOT needed for review (read-only), but available.
- bash_exec: Run commands to test the implementation.
- web_search: Search the web to verify external references or APIs.
- web_fetch: Fetch documentation pages to validate correctness.

Review process:
1. Read the user requirement carefully.
2. Read the coder's report of what was done.
3. Use the tools to VERIFY:
   a. Do the expected files exist?
   b. Does the code look correct?
   c. Does the program actually run without errors?
   d. Does it produce the expected output?
4. Produce a verdict.

Verdict format MUST be:
---
## 审查结论

### 状态: PASS / FAIL

### 验证过程
{what you checked and how}

### 详细意见
{for PASS: confirm everything is working}
{for FAIL: list exactly what is missing/broken, with file paths and line-level detail}

### 下一轮反馈（仅在 FAIL 时）
{actionable instructions for the coder on what to fix}
---

CRITICAL: You MUST run actual commands to test the code (e.g.
``python module.py``), not just read it.  If you cannot run the code,
note that as a limitation."""


def build_reviewer_agent(model_name: Optional[str] = None):
    """Build the Reviewer LangGraph agent."""
    llm = build_chat_model(temperature=0.0, model=model_name)
    tools = [read_file, edit_file, bash_exec, web_search, web_fetch]

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=REVIEWER_SYSTEM_PROMPT,
        debug=False,
    )
    return agent


def run_reviewer(requirement: str, coder_report: str, model_name: Optional[str] = None,
                 callbacks: Optional[Callbacks] = None) -> str:
    """Run the Reviewer Agent and return its verdict.

    Args:
        requirement: The original user requirement.
        coder_report: The Coder Agent's latest natural-language report.
        model_name: Optional model override.
        callbacks: Optional LangChain callbacks for UI capture.

    Returns:
        The review verdict string.
    """
    agent = build_reviewer_agent(model_name=model_name)

    # ── Load workspace context files (CLAUDE.md / AGENTS.md) ─────
    context = load_context_files()
    context_block = f"\n\n## 工作区上下文\n{context}" if context else ""

    user_message = (
        f"## 用户需求\n{requirement}\n\n"
        f"## 主智能体报告\n{coder_report}"
        f"{context_block}\n\n"
        "请审查以上实现是否完整满足用户需求。"
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

    logger.info("Reviewer agent finished. Output length=%d", len(output))
    return output
