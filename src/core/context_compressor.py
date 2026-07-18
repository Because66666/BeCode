"""Context Compressor — Map-Reduce context compression for long-running sessions.

This module implements a **Compressor Agent** that runs independently from
Coder/Reviewer agents. When the accumulated context reaches 90 % of the max
context length, the Compressor Agent:

  1. Analyzes the Coder agent's current session history
  2. Generates a structured compressed summary across 5 dimensions:
     a) 当前目标 (current goal)
     b) 已完成的执行路径 (completed work)
     c) 错误履历与免疫策略 (errors & how to avoid repeating them)
     d) 当前执行进度 (current step)
     e) 下一步候选计划 (next candidate plan)
  3. Assembles the new context as:
     - 用户要求原文 (original user request)
     - 压缩后的内容 (compressed summary)
     - 最近三轮工具调用及原始返回 (last 3 rounds tool calls + results)

Map-Reduce strategy:
  - Map phase: Split history into chunks (≤ compression_chunk_max_tokens tokens
    per chunk), generate per-chunk local summaries.
  - Reduce phase: Merge all local summaries into one final global summary.

Compression is triggered when estimated tokens >= max_context_length * 0.90
(0.90 is **hardcoded**, not read from config).

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - 压缩阈值: 0.90 硬编码, 不从配置读取。         ║
║  - Compressor Agent 独立运行, 不依赖              ║
║    Coder/Reviewer Agent。                        ║
║  - 压缩后新上下文 = 用户原文 + 压缩摘要           ║
║    + 最近三轮工具调用及结果。                     ║
║  - 每次压缩事件记录到 session 的                   ║
║    compression_events 列表中。                    ║
║  - Map-Reduce 确保每个 Chunk 的 LLM 调用           ║
║    不超过 compression_chunk_max_tokens。           ║
║  - Compressor Agent 的 token 用量通过              ║
║    TokenTracker (agent_name="compressor") 追踪。   ║
╚══════════════════════════════════════════════════╝
"""

import logging
import re
from typing import Any, Callable, Optional

from src.core.config import settings
from src.core.llm_client import build_chat_model, clean_call
from src.core.token_tracker import get_token_tracker
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# ── Hardcoded Constants ─────────────────────────────────────────────────

# 上下文压缩触发阈值（硬编码，不从配置文件读取）
# 当上下文 Token 数达到 max_context_length 的 90% 时触发压缩。
COMPRESSION_THRESHOLD_RATIO = 0.90

# ── Token Estimation ─────────────────────────────────────────────────────

# Rough estimate: ~2 UTF-8 characters per token for mixed Chinese/English text.
_CHARS_PER_TOKEN = 2.0


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses a rough heuristic (len/2) for mixed Chinese/English content.
    This is sufficient for threshold-trigger decisions.
    """
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


# ── Compression trigger (Compressor Agent entry) ────────────────────────


def should_compress(context_text: str) -> bool:
    """Check whether the given context text exceeds the compression threshold.

    Trigger condition (hardcoded 0.90):
      estimated_tokens >= max_context_length * COMPRESSION_THRESHOLD_RATIO

    When triggered, the Compressor Agent will be invoked to compress the
    accumulated history and free up context space for the Coder agent.
    """
    max_len = settings.max_context_length
    threshold = int(max_len * COMPRESSION_THRESHOLD_RATIO)
    estimated = estimate_tokens(context_text)

    logger.debug(
        "Compression check: estimated=%d, threshold=%.0f (max=%d * %.2f)",
        estimated, threshold, max_len, COMPRESSION_THRESHOLD_RATIO,
    )
    return estimated >= threshold


# ── Progress reporter type ──────────────────────────────────────────────

ProgressCallback = Callable[[int, int, str], None]
"""Signature: (step, total_steps, message) → None, called during compression."""

_NULL_CALLBACK: ProgressCallback = lambda step, total, msg: None


# ── Map-Reduce Prompts (Compressor Agent) ──────────────────────────────
#
# The Compressor Agent uses these prompts to analyze what the Coder Agent
# has done across 5 dimensions:
#   1. Current goal
#   2. Completed execution paths
#   3. Error history & immunity strategies
#   4. Current progress / step
#   5. Next candidate plan
#

_MAP_PROMPT = """你是一个上下文压缩专家（Compressor Agent）。请阅读以下对话片段，提取关键信息。

你需要分析的是「触发压缩的 Coder Agent 正在做的事情」，并按照以下五个维度用中文总结：

1. **当前目标**：Coder Agent 当下的目标是什么？用户在需求中要求实现什么？
2. **已完成的执行路径**：Coder Agent 已经完成了哪些具体步骤、模块或文件？
3. **错误履历与免疫策略**：遇到了哪些关键错误？Coder Agent 为了规避再次犯错采用了什么策略？
4. **当前执行进度**：Coder Agent 当前执行到了哪一步？（构建中？测试中？修复中？）
5. **下一步候选计划**：下一步的首选候选行动是什么？有哪些待办事项？

注意：请保持简洁，保留所有关键细节，不要丢失重要信息。

对话片段:
{chunk}
"""

_REDUCE_PROMPT = """你是一个上下文压缩专家（Compressor Agent）。请将以下多个局部摘要合并为一个统一的全局摘要。

请整合所有信息，用中文按照以下五个维度总结 Coder Agent 的工作状态：

1. **当前目标**：Coder Agent 当下的核心目标是什么？用户需求的本质是什么？
2. **已完成的执行路径**：总体完成了哪些具体步骤、模块或文件？
3. **错误履历与免疫策略**：遇到了哪些关键错误？为了规避再次犯错采用了什么固定策略？
4. **当前执行进度**：当前执行到了哪一步？（构建中？测试中？修复中？）
5. **下一步候选计划**：下一步的首选候选行动是什么？（此维度最为关键）

注意：消除重复信息，保留所有独特的关键细节。最终的摘要应当自包含，即使脱离原始上下文也能理解。

局部摘要:
{summaries}
"""

# ── Chunking logic ──────────────────────────────────────────────────────


def _build_round_text(entry: dict) -> str:
    """Format a single history entry as text for compression."""
    role = entry.get("role", "unknown")
    content = entry.get("content", "")
    metadata = entry.get("metadata")
    lines = [f"[{role.upper()} ROUND]"]
    if content:
        lines.append(content)
    if metadata and isinstance(metadata, dict):
        tc = metadata.get("tool_calls")
        if tc:
            for call in tc:
                tname = call.get("tool", "?")
                targs = call.get("args", {})
                lines.append(f"  → 工具调用: {tname}({targs})")
    return "\n".join(lines)


def _chunk_history(history: list[dict]) -> list[list[dict]]:
    """Split history into chunks, each within the max token limit.

    Critically, each tool call and its output are kept as a whole —
    we never cut in the middle of a single entry.
    """
    max_tokens = settings.compression_chunk_max_tokens
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    current_tokens = 0

    for entry in history:
        entry_text = _build_round_text(entry)
        entry_tokens = estimate_tokens(entry_text)

        # If a single entry is larger than max_tokens, we put it alone
        # in its own chunk as a best-effort approach.
        if entry_tokens > max_tokens:
            # Flush current chunk first if non-empty
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_tokens = 0
            chunks.append([entry])
            continue

        if current_tokens + entry_tokens > max_tokens and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [entry]
            current_tokens = entry_tokens
        else:
            current_chunk.append(entry)
            current_tokens += entry_tokens

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


# ── Map-Reduce compression ──────────────────────────────────────────────


def _llm_summarize(prompt: str, progress: ProgressCallback,
                    step: int, total_steps: int, label: str) -> str:
    """Run an LLM summarization call, tracking tokens."""
    progress(step, total_steps, f"正在{label}...")
    llm = build_chat_model(temperature=0.0)
    tracker = get_token_tracker()

    # We need to estimate input tokens for tracking
    response = clean_call(llm, [HumanMessage(content=prompt)],
                          system_prompt="你是一个专业的上下文压缩助手，擅长提取关键信息并生成简洁的摘要。")

    # Estimate and track token usage
    inp_tok = estimate_tokens(prompt)
    out_tok = estimate_tokens(response)
    tracker.add_usage(inp_tok, out_tok, agent_name="compressor")

    return response


def compress_history(history: list[dict],
                     progress: ProgressCallback = _NULL_CALLBACK) -> str:
    """Run Map-Reduce compression on a list of history entries.

    Args:
        history: List of session history dicts (each with keys: role, content, metadata).
        progress: Optional callback for UI progress updates.

    Returns:
        The compressed global summary string (Part A content).
    """
    if not history:
        return "(无历史记录)"

    # ── Map phase ────────────────────────────────────────────────────
    progress(0, 0, "正在切分历史记录...")
    chunks = _chunk_history(history)
    total_steps = len(chunks) + 1  # Map steps + 1 Reduce step
    local_summaries: list[str] = []

    for i, chunk in enumerate(chunks):
        chunk_text = "\n\n---\n\n".join(_build_round_text(e) for e in chunk)
        prompt = _MAP_PROMPT.format(chunk=chunk_text)
        step = i + 1
        progress(step, total_steps, f"生成局部摘要 {step}/{total_steps}")
        summary = _llm_summarize(prompt, progress, step, total_steps,
                                 f"生成局部摘要 {step}/{total_steps}")
        local_summaries.append(summary)

    # ── Reduce phase ─────────────────────────────────────────────────
    combined = "\n\n---\n\n".join(
        f"### 局部摘要 {i + 1}\n{s}" for i, s in enumerate(local_summaries)
    )
    reduce_step = total_steps
    progress(reduce_step, total_steps, f"合并摘要 {reduce_step}/{total_steps}")
    reduce_prompt = _REDUCE_PROMPT.format(summaries=combined)
    global_summary = _llm_summarize(
        reduce_prompt, progress, reduce_step, total_steps,
        f"合并摘要 {reduce_step}/{total_steps}"
    )

    progress(total_steps, total_steps, "压缩完成 ✓")
    return global_summary


# ── Compressor Agent: Context reconstruction ───────────────────────────
#
# After Map-Reduce compression, the Compressor Agent assembles the new
# context that will be fed to the triggering Coder Agent. The structure is:
#
#   1. 用户要求原文 (original user request text)
#   2. 压缩后的内容 (compressed summary from Map-Reduce)
#   3. 最近三轮工具调用及原始返回 (last 3 rounds tool calls + results)
#
# The Coder Agent's new context = 用户要求原文 + 压缩后的内容 (no old history).


def _build_last_n_tool_calls(history: list[dict], n_rounds: int = 3) -> str:
    """Extract the last N rounds of tool calls with their results from history.

    Each "round" consists of a coder entry followed by a reviewer entry.
    We look backwards through history to find the last N coder entries and
    extract their tool-call metadata.

    Args:
        history: Full session history list.
        n_rounds: Number of recent rounds to extract (default 3).

    Returns:
        A formatted string describing the recent tool calls.
    """
    if not history:
        return "(无历史记录)"

    # Find last N "coder" entries (each round has 1 coder entry)
    coder_entries = []
    for entry in reversed(history):
        if entry.get("role") == "coder":
            coder_entries.append(entry)
            if len(coder_entries) >= n_rounds:
                break
    coder_entries.reverse()

    if not coder_entries:
        return "(无工具调用记录)"

    lines = []
    for i, entry in enumerate(coder_entries):
        round_num = len(history) - coder_entries.index(entry)  # approximate
        lines.append(f"### 第 {round_num} 轮 — Coder Agent 工具调用\n")

        metadata = entry.get("metadata", {})
        tool_calls = metadata.get("tool_calls", []) if isinstance(metadata, dict) else []

        if not tool_calls:
            lines.append("(本轮无工具调用记录)\n")
        else:
            for j, tc in enumerate(tool_calls):
                tname = tc.get("tool", "?")
                targs = tc.get("args", {})
                args_str = ", ".join(f"{k}={v}" for k, v in targs.items())
                lines.append(f"  {j + 1}. **{tname}**({args_str})")

        # Also include the agent's report content as "result"
        content = entry.get("content", "")
        if content:
            # Truncate very long content for readability
            if len(content) > 500:
                content = content[:497] + "..."
            lines.append(f"\n  → 执行报告:\n{content}\n")

    return "\n".join(lines)


def build_compressed_context(
    requirement: str,
    history: list[dict],
    compressed_summary: str,
    recent_rounds: int = 3,
) -> str:
    """Build the new context string from compressed parts.

    The Compressor Agent assembles the context that the triggering Coder
    Agent will receive. It contains:
      1. 用户要求原文 (original user request)
      2. 压缩后的内容 (compressed summary from Map-Reduce)
      3. 最近三轮工具调用及原始返回 (last N rounds tool calls + results)

    The old accumulated history is **removed** and replaced by the compressed
    summary. Only the user's original requirement and the compressed content
    form the Coder Agent's context. The recent tool calls are appended as
    auxiliary reference.

    Args:
        requirement: The original user requirement text.
        history: Full session history list (for extracting recent tool calls).
        compressed_summary: Output from compress_history().
        recent_rounds: Number of recent rounds to include tool calls for
                       (default 3, hardcoded per spec).

    Returns:
        The reconstructed context string ready for the Coder Agent.
    """

    # ── Part 1: 用户要求原文 ─────────────────────────────────────────
    part_user = (
        "## 📋 用户要求原文\n\n"
        f"{requirement}\n"
    )

    # ── Part 2: 压缩后的内容（Compressor Agent 输出）─────────────────
    part_compressed = (
        "## 📦 上下文压缩摘要（Compressor Agent 输出）\n\n"
        f"{compressed_summary}\n"
    )

    # ── Part 3: 最近三轮工具调用及原始返回 ──────────────────────────
    part_recent_calls = _build_last_n_tool_calls(history, n_rounds=recent_rounds)
    part_tools = (
        "## 🔧 最近三轮工具调用记录\n\n"
        f"{part_recent_calls}\n"
    )

    # ── Assemble full context ────────────────────────────────────────
    context = (
        f"{part_user}\n\n"
        f"{part_compressed}\n\n"
        f"{part_tools}\n\n"
        "请基于以上上下文继续执行任务。"
        "「上下文压缩摘要」部分已替代旧的历史记录，无需重复执行已完成的步骤。"
        "「最近三轮工具调用记录」仅供参考，帮助你了解最近的执行情况。"
    )
    return context


def _extract_blocker_from_summary(summary: str) -> str:
    """Extract the '当前卡点与待办清单' section from a compressed summary.

    Falls back to the full summary if the section isn't found.
    """
    markers = [
        "**当前卡点与待办清单**",
        "4. **当前卡点与待办清单**",
        "- **当前卡点与待办清单**",
        "当前卡点与待办清单",
    ]
    for marker in markers:
        idx = summary.find(marker)
        if idx != -1:
            # Return everything from the marker to the end (or next section)
            after = summary[idx:]
            # Cut at next top-level heading or double-newline section
            for cut in ["\n# ", "\n## **"]:
                cut_idx = after.find(cut)
                if cut_idx != -1:
                    after = after[:cut_idx]
            return after.strip()

    # Fallback: try to find "4." prefix
    import re
    m = re.search(r'4\.\s*\*{0,2}当前卡点与待办清单\*{0,2}(.*?)(?:\n\s*\d+\.|\Z)', summary, re.DOTALL)
    if m:
        return m.group(0).strip()

    # Last resort
    return summary.strip()


# ── Compression event record ────────────────────────────────────────────


def record_compression_event(
    session: Any,
    before_chars: int,
    after_chars: int,
) -> dict:
    """Record a compression event in the session store.

    Args:
        session: SessionStore instance.
        before_chars: Character count before compression.
        after_chars: Character count after compression.

    Returns:
        dict describing the compression event.
    """
    ratio = 0.0
    if before_chars > 0:
        ratio = (1 - after_chars / before_chars) * 100

    event = {
        "event": "context_compression",
        "before_chars": before_chars,
        "after_chars": after_chars,
        "compression_ratio_pct": round(ratio, 1),
    }

    # Record in session metadata
    session._data.setdefault("compression_events", []).append(event)
    session.save()

    logger.info(
        "Context compression: %d → %d chars (%.1f%% reduction)",
        before_chars, after_chars, ratio,
    )
    return event