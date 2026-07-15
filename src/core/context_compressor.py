"""Context Compressor — Map-Reduce context compression for long-running sessions.

This module provides a Compressor Agent that reduces accumulated conversation
history into a concise summary across four dimensions:
  1. Ultimate goal & dynamic constraints
  2. Completed execution paths
  3. Error history & immunity strategies
  4. Current blockers & todo list (most critical)

Map-Reduce strategy:
  - Map phase: Split history into chunks (≤ compression_chunk_max_tokens tokens
    per chunk), generate per-chunk local summaries.
  - Reduce phase: Merge all local summaries into one final global summary.

Compression is triggered when the estimated context size reaches the configured
threshold (max_context_length * (1 - context_margin_ratio) tokens remaining).

The compressed output is structured as Part A (long-term summary) + Part B (last
N rounds raw) + Part C (blocker/todo system prompt).

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - Estimated token count: len(text) / 2 (UTF-8  ║
║    characters → approximate token count).        ║
║  - Map-Reduce ensures each per-chunk LLM call    ║
║    stays under compression_chunk_max_tokens.      ║
║  - Progress callback reports (step, total) for    ║
║    real-time UI updates during compression.       ║
║  - Compressor agent's token usage is tracked via  ║
║    TokenTracker (agent_name="compressor").        ║
╚══════════════════════════════════════════════════╝
"""

import logging
import math
from typing import Any, Callable, Optional

from src.core.config import settings
from src.core.llm_client import build_chat_model, clean_call
from src.core.token_tracker import get_token_tracker
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# ── Token Estimation ─────────────────────────────────────────────────────

# Rough estimate: ~2 UTF-8 characters per token for mixed Chinese/English text.
_CHARS_PER_TOKEN = 2.0


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses a rough heuristic (len/2) for mixed Chinese/English content.
    This is sufficient for threshold-trigger decisions.
    """
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


# ── Compression trigger ─────────────────────────────────────────────────


def should_compress(context_text: str) -> bool:
    """Check whether the given context text exceeds the compression threshold.

    Trigger condition: estimated tokens + margin >= max_context_length
    where margin = max_context_length * context_margin_ratio

    i.e., compression triggers when estimated tokens >=
    max_context_length * (1 - context_margin_ratio)
    """
    max_len = settings.max_context_length
    margin_ratio = settings.context_margin_ratio

    # Margin = max * margin_ratio (default: max * 0.95 = 950000)
    # Trigger: current + margin >= max
    #   → current >= max - margin
    #   → current >= max * (1 - margin_ratio)
    threshold = int(max_len * (1 - margin_ratio))
    estimated = estimate_tokens(context_text)

    logger.debug(
        "Compression check: estimated=%d, margin_ratio=%.2f, threshold=%d",
        estimated, margin_ratio, threshold,
    )
    return estimated >= threshold


# ── Progress reporter type ──────────────────────────────────────────────

ProgressCallback = Callable[[int, int, str], None]
"""Signature: (step, total_steps, message) → None, called during compression."""

_NULL_CALLBACK: ProgressCallback = lambda step, total, msg: None


# ── Map-Reduce Prompts ──────────────────────────────────────────────────

_MAP_PROMPT = """你是一个上下文压缩专家。请阅读以下对话片段，提取关键信息。

请用中文总结以下四个维度：

1. **终极目标与动态约束**：这段对话反映了用户的什么核心需求？有没有追加的硬性修正指令？
2. **已完成的执行路径**：当前已经完成了哪些具体步骤或模块？
3. **错误履历与免疫策略**：遇到了哪些关键错误？为了规避再犯采用了什么策略？
4. **当前卡点与待办清单**：执行流程被阻塞在哪一步？下一步的首选候选行动是什么？

注意：请保持简洁，保留所有关键细节，不要丢失重要信息。

对话片段:
{chunk}
"""

_REDUCE_PROMPT = """你是一个上下文压缩专家。请将以下多个局部摘要合并为一个统一的全局摘要。

请整合所有信息，用中文总结以下四个维度：

1. **终极目标与动态约束**：用户最原始的核心需求是什么？交互过程中追加了哪些硬性修正指令？
2. **已完成的执行路径**：总体完成了哪些具体步骤或模块？
3. **错误履历与免疫策略**：遇到了哪些关键错误？当前系统为了规避再次犯错采用了什么固定策略？
4. **当前卡点与待办清单**：执行流程被阻塞在哪一步？下一步的首选候选行动是什么？（此维度最为关键）

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


# ── Context reconstruction (Part A + B + C) ─────────────────────────────


def build_compressed_context(
    requirement: str,
    history: list[dict],
    compressed_summary: str,
    recent_rounds: Optional[int] = None,
) -> str:
    """Build the new context string from compressed parts.

    Structure:
      Part A — Long-term compressed summary (from compress_history)
      Part B — Last N rounds of raw, unmodified conversation
      Part C — Current blocker & todo list as system instruction

    Args:
        requirement: The original user requirement.
        history: Full session history list.
        compressed_summary: Output from compress_history().
        recent_rounds: Number of recent rounds to keep raw (default from config).

    Returns:
        The reconstructed context string ready for injection.
    """
    recent = recent_rounds if recent_rounds is not None else settings.compression_recent_rounds

    # ── Part A: Compressed summary ───────────────────────────────────
    part_a = (
        "## 📦 Part A — 长期固化记忆（上下文压缩摘要）\n\n"
        f"{compressed_summary}\n"
    )

    # ── Part B: Recent raw history ───────────────────────────────────
    # Keep last N "rounds" worth of entries (each round = coder + reviewer)
    if recent > 0 and len(history) > 0:
        # Take the last recent*2 entries (coder + reviewer per round, roughly)
        # but at minimum keep recent*2 entries
        keep_count = min(len(history), max(recent * 2, recent))
        recent_entries = history[-keep_count:]
        part_b_lines = [
            "## 📝 Part B — 短期热数据（最近原始对话）\n",
        ]
        for entry in recent_entries:
            role = entry.get("role", "?")
            content = entry.get("content", "")
            part_b_lines.append(f"### [{role.upper()}]\n{content}\n")
        part_b = "\n".join(part_b_lines)
    else:
        part_b = "## 📝 Part B — 短期热数据\n\n(无)\n"

    # ── Part C: Blocker / todo from compressed summary ───────────────
    # Extract the "当前卡点与待办清单" section from the compressed summary
    part_c_blocker = _extract_blocker_from_summary(compressed_summary)

    part_c = (
        "## 🎯 Part C — 即时激活器（当前卡点与待办清单）\n\n"
        f"{part_c_blocker}\n"
    )

    # ── Assemble full context ────────────────────────────────────────
    context = (
        f"## 原始用户需求\n{requirement}\n\n"
        f"{part_a}\n\n"
        f"{part_b}\n\n"
        f"{part_c}\n\n"
        "请基于以上上下文（原始需求 + 长期记忆 + 短期热数据 + 当前卡点）"
        "继续执行任务。注意：Part B 中的历史对话仅供参考，无需重复执行已完成的步骤。"
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