"""Orchestrator — the main workflow loop.

Flow:
  1. Receive user requirement.
  2. Loop (max_iterations):
     a. Coder Agent → implementation + report (with retry on failure)
     b. Reviewer Agent → verdict (PASS/FAIL)
     c. If PASS → exit
     d. If FAIL → extract feedback → back to (a)
  3. Return final outcome.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - run() 在每次 Coder/Reviewer 运行后，将工具   ║
║    调用列表通过 metadata={"tool_calls": [...]}   ║
║    传入 session.add_entry()，持久化到 session    ║
║    JSON 的 history[].metadata.tool_calls 字段。  ║
║  - 这些 tool_calls 仅用于审计/调试，绝不喂回     ║
║    Coder Agent。每轮 Coder 的 context 只包含:    ║
║      (a) 原始需求                                ║
║      (b) reviewer 的「下一轮反馈」(纯行动项)     ║
║      (c) 工作区上下文文件                         ║
║  - 容错机制: Coder Agent 失败时允许重试最多 3   ║
║    次（失败次数不跨迭代累计），第 4 次失败时     ║
║    退出系统并展示失败原因面板。                  ║
║  - 错误分类:                                     ║
║    - 大模型调用出错: LLM API 网络/鉴权/限流错误  ║
║    - 工具调用错误: 工具执行异常 + JSON 解析错误   ║
║    - 其他类型错误: 上述以外的未知错误             ║
╚══════════════════════════════════════════════════╝
"""

import logging
import re
import shutil
from typing import Optional
from enum import Enum

from rich.panel import Panel
from rich.text import Text
from rich import box

from src.agents.coder_agent import run_coder
from src.agents.reviewer_agent import run_reviewer
from src.core.config import settings
from src.core.session_store import SessionStore
from src.core.token_tracker import get_token_tracker
from src.tools.tools import set_user_requirement
from src.ui.console import get_console
from src.ui.callbacks import ToolCallCapture

logger = logging.getLogger(__name__)

# ── Retry / Error Classification ───────────────────────────────────────

MAX_CODER_RETRIES = 3  # 允许 coder 连续失败 3 次，第 4 次才退出


class ErrorCategory(str, Enum):
    """错误分类枚举。"""
    LLM_ERROR = "大模型调用出错"
    TOOL_ERROR = "工具调用错误"
    OTHER_ERROR = "其他类型错误"


def classify_coder_error(exc: Exception) -> ErrorCategory:
    """根据异常类型判断错误分类。

    - 大模型调用出错: 与 LLM API 通信相关的异常（网络、鉴权、限流等）。
    - 工具调用错误: 工具执行时抛出的异常 + JSON 解析错误（LLM 输出无法
      解析为合法的工具调用参数时 LangChain 抛出的 OutputParserException）。
    - 其他类型错误: 不属于上述两类的所有异常。
    """
    exc_name = type(exc).__name__
    exc_str = str(exc).lower()

    # ── 大模型调用出错 ────────────────────────────────────────────
    # OpenAI / 兼容 API 的错误
    if exc_name in (
        "APIError", "BadRequestError", "AuthenticationError",
        "PermissionDeniedError", "NotFoundError", "ConflictError",
        "UnprocessableEntityError", "RateLimitError",
        "InternalServerError", "APIConnectionError", "APITimeoutError",
    ):
        return ErrorCategory.LLM_ERROR

    # httpx / urllib3 网络层错误
    if exc_name in (
        "ConnectError", "ConnectionError", "TimeoutError",
        "ReadTimeout", "WriteTimeout", "RemoteProtocolError",
        "ProxyError",
    ):
        return ErrorCategory.LLM_ERROR

    if any(kw in exc_str for kw in [
        "connection", "timeout", "rate limit", "too many requests",
        "api key", "authentication", "unauthorized", "403", "401",
        "429", "500", "503", "service unavailable",
    ]):
        return ErrorCategory.LLM_ERROR

    # ── 工具调用错误（含 JSON 解析错误）─────────────────────────
    # OutputParserException = LLM 返回了非法格式（如坏的 JSON）
    # ToolException = 工具执行时出了问题
    if exc_name in ("OutputParserException", "ToolException", "ValidationError"):
        return ErrorCategory.TOOL_ERROR

    if any(kw in exc_str for kw in [
        "parse", "parsing", "json", "tool call", "tool_call",
        "invalid format", "malformed",
    ]):
        return ErrorCategory.TOOL_ERROR

    # ── 其他类型错误（兜底）───────────────────────────────────────
    return ErrorCategory.OTHER_ERROR


class Orchestrator:
    """Manages the Coder → Reviewer → feedback loop."""

    def __init__(self, session: Optional[SessionStore] = None, model_name: Optional[str] = None):
        self.session = session or SessionStore()
        self.model_name = model_name
        self.max_iterations = settings.max_iterations

    # ── public API ──────────────────────────────────────────────────

    def run_interactive(self, requirement: str, summary_context: list[str] | None = None) -> dict:
        """Execute the agent workflow in interactive mode with accumulated context.

        Differs from :meth:`run` in that it:
        1. Injects previous task summaries into the prompt context.
        2. Returns immediately on Ctrl+C with partial results.
        3. Does NOT exit the process after completion.

        Args:
            requirement: The user's request for this round.
            summary_context: List of one-line summaries from previous rounds.

        Returns:
            dict with keys:
              - success: bool
              - summary: str  (one-line summary of this round)
              - total_turns: int
              - session_id: str
              - coder_reports: list[str]
              - review_verdicts: list[str]
              - interrupted: bool  (True if Ctrl+C was caught)
              - has_formal_output: bool  (True if partial LLM output exists)
        """
        # Reset token tracker for this round's statistics
        get_token_tracker().reset()

        # Build the enriched requirement with previous task summaries
        enriched_requirement = requirement
        if summary_context:
            summary_block = "\n".join(
                f"- {s}" for s in summary_context[-10:]  # Keep last 10 summaries
            )
            enriched_requirement = (
                f"{requirement}\n\n"
                f"## 已完成任务的背景\n"
                f"以下是此前已完成的任务摘要，作为当前任务的上下文背景:\n"
                f"{summary_block}\n"
            )

        # Track whether we have formal output before any interruption
        has_formal_output = False
        interrupted = False
        result = None

        try:
            # Run the standard workflow
            result = self.run(enriched_requirement)
            has_formal_output = bool(
                result.get("coder_reports") and result["coder_reports"][-1]
            )
        except KeyboardInterrupt:
            interrupted = True
            # Check if partial results exist in the session
            if result is None:
                # Create a minimal result dict for interrupted state
                result = {
                    "success": False,
                    "summary": "被中断",
                    "total_turns": 0,
                    "session_id": self.session.session_id,
                    "coder_reports": [],
                    "review_verdicts": [],
                }
            else:
                has_formal_output = bool(
                    result.get("coder_reports") and result["coder_reports"][-1]
                )

        if result is None:
            result = {
                "success": False,
                "summary": "未知错误",
                "total_turns": 0,
                "session_id": self.session.session_id,
                "coder_reports": [],
                "review_verdicts": [],
            }

        # Generate a one-line summary of this round (only if not interrupted or has output)
        if not interrupted or has_formal_output:
            if result.get("success") and result.get("coder_reports"):
                from src.core.llm_client import summarize_completion
                try:
                    last_coder = result["coder_reports"][-1]
                    one_line = summarize_completion(
                        requirement=requirement,
                        coder_report=last_coder,
                        model=self.model_name,
                    )
                except Exception:
                    one_line = f"已完成: {requirement[:60]}..."
            else:
                one_line = f"部分完成（未通过审查）: {requirement[:60]}..."
        else:
            one_line = ""

        result["one_line_summary"] = one_line
        result["interrupted"] = interrupted
        result["has_formal_output"] = has_formal_output
        return result

    def run(self, requirement: str) -> dict:
        """Execute the full agent workflow.

        CONTEXT CLEANLINESS GUARANTEE:
        Each iteration invokes ``run_coder()`` with ONLY:
          1. The original ``requirement`` (unchanged across rounds)
          2. The reviewer's actionable feedback (``下一轮反馈`` section only)
          3. Workspace context files (CLAUDE.md / AGENTS.md)

        The Coder agent is re-built from scratch each round — it receives a
        single ``HumanMessage`` with no accumulated AI / Tool messages from
        previous rounds.  This ensures the Coder never sees its own previous
        chain-of-thought or tool-call traces.

        Args:
            requirement: The user's request.

        Returns:
            dict with keys:
              - success: bool
              - summary: str
              - total_turns: int
              - session_id: str
              - coder_reports: list[str]
              - review_verdicts: list[str]
        """
        self.session.requirement = requirement
        self.session.status = "running"
        self.session.save()
        # Reset token tracker for this run's statistics
        get_token_tracker().reset()
        # Expose the requirement to BashGuard so its LLM review can judge
        # commands against the actual task context.
        set_user_requirement(requirement)
        logger.info(
            "Orchestrator start | session=%s | max_iterations=%d",
            self.session.session_id,
            self.max_iterations,
        )

        console = get_console()

        coder_reports: list[str] = []
        review_verdicts: list[str] = []
        feedback = ""

        for iteration in range(1, self.max_iterations + 1):
            logger.info("=== Iteration %d / %d ===", iteration, self.max_iterations)
            console.start_iteration(iteration, self.max_iterations)

            # ── Step A: Coder (with retry logic) ────────────────────────
            # NOTE: run_coder() builds a BRAND-NEW agent each round and
            # passes only `requirement` + `feedback` (the reviewer's clean
            # actionable items).  No previous round's thoughts or tool calls
            # are included.  See `coder_agent.py` for details.
            #
            # RETRY POLICY:
            # Coder 调用可能因 LLM API 错误 / 工具执行错误 / JSON 解析
            # 错误而失败。允许最多连续失败 MAX_CODER_RETRIES 次（=3），
            # 期间不将主动权移交给 reviewer。第 4 次失败时退出系统。
            console.agent_thinking("coder", "正在分析需求并实现...")
            coder_callback = ToolCallCapture(agent_name="coder")

            coder_report = None
            coder_last_exception: Optional[Exception] = None

            for attempt in range(1, MAX_CODER_RETRIES + 2):  # 1..4
                try:
                    coder_report = run_coder(
                        requirement=requirement,
                        feedback=feedback,
                        model_name=self.model_name,
                        callbacks=[coder_callback],
                    )
                    # Success — exit retry loop
                    break
                except Exception as exc:
                    coder_last_exception = exc
                    category = classify_coder_error(exc)
                    logger.warning(
                        "Coder agent failed (attempt %d/%d): [%s] %s",
                        attempt, MAX_CODER_RETRIES + 1,
                        category.value, exc,
                    )

                    if attempt <= MAX_CODER_RETRIES:
                        # ── Retry: show warning, keep control with coder ──
                        console.print(
                            f"[bold yellow]⚠ Coder Agent 调用失败 "
                            f"(第 {attempt}/{MAX_CODER_RETRIES + 1} 次)"
                            f" — [{category.value}] {exc}[/]"
                        )
                        console.print(
                            "[dim italic]   将在本回合内自动重试，"
                            "不转移主动权给 Reviewer...[/]"
                        )
                        # Build a fresh callback for the next attempt so
                        # tool calls from different attempts don't mix.
                        coder_callback = ToolCallCapture(agent_name="coder")
                        continue

                    # ── 4th failure — exit with fatal panel ──────────
                    logger.critical(
                        "Coder agent failed %d consecutive times — exiting",
                        MAX_CODER_RETRIES + 1,
                    )
                    coder_report = (
                        f"[Coder 致命错误 — 已达最大重试次数 "
                        f"({MAX_CODER_RETRIES + 1})]\n"
                        f"错误分类: {category.value}\n"
                        f"异常详情: {exc}"
                    )
                    _show_coder_fatal_error(console, category, exc)
                    self.session.status = "coder_fatal_error"
                    self.session.save()
                    return self._result(
                        success=False,
                        summary=(
                            f"Coder Agent 连续失败 {MAX_CODER_RETRIES + 1} 次，"
                            f"已终止。原因: {category.value}"
                        ),
                        total_turns=iteration,
                        coder_reports=coder_reports,
                        review_verdicts=review_verdicts,
                    )

            # If we exited the loop without a report, it means all retries
            # were exhausted (should have been caught above, but safeguard).
            if coder_report is None:
                cat = classify_coder_error(coder_last_exception or Exception("未知错误"))
                coder_report = (
                    f"[Coder 异常 — 重试耗尽] "
                    f"{coder_last_exception or '未知错误'}"
                )
                _show_coder_fatal_error(console, cat, coder_last_exception)
                self.session.status = "coder_fatal_error"
                self.session.save()
                return self._result(
                    success=False,
                    summary=f"Coder Agent 重试耗尽。原因: {cat.value}",
                    total_turns=iteration,
                    coder_reports=coder_reports,
                    review_verdicts=review_verdicts,
                )

            # Capture tool calls from this round and pass as metadata
            coder_tool_calls = coder_callback.get_tool_calls()
            self.session.add_entry(
                "coder",
                coder_report,
                metadata={"tool_calls": coder_tool_calls} if coder_tool_calls else None,
            )
            self.session.save()
            coder_reports.append(coder_report)

            # Show coder's report summary
            console.agent_report("coder", coder_report)

            # ── Step B: Reviewer (with retry) ─────────────────────────────
            console.agent_thinking("reviewer", "正在审查实现代码...")
            reviewer_callback = ToolCallCapture(agent_name="reviewer")
            review_verdict = None

            for r_attempt in range(1, MAX_CODER_RETRIES + 2):  # 1..4
                try:
                    review_verdict = run_reviewer(
                        requirement=requirement,
                        coder_report=coder_report,
                        model_name=self.model_name,
                        callbacks=[reviewer_callback],
                    )
                    break
                except Exception as exc:
                    logger.warning(
                        "Reviewer agent failed (attempt %d/%d): %s",
                        r_attempt, MAX_CODER_RETRIES + 1, exc,
                    )
                    if r_attempt <= MAX_CODER_RETRIES:
                        console.print(
                            f"[bold yellow]⚠ Reviewer Agent 调用失败 "
                            f"(第 {r_attempt}/{MAX_CODER_RETRIES + 1} 次)"
                            f" — [{classify_coder_error(exc).value}] {exc}[/]"
                        )
                        console.print("[dim italic]   自动重试...[/]")
                        reviewer_callback = ToolCallCapture(agent_name="reviewer")
                        continue
                    # 4th failure: log error and produce a placeholder verdict
                    logger.exception("Reviewer agent crashed after all retries")
                    review_verdict = (
                        f"[Reviewer 异常 — 重试耗尽]\n"
                        f"错误分类: {classify_coder_error(exc).value}\n"
                        f"异常详情: {exc}"
                    )
                    console.error(f"Reviewer Agent 异常 (重试耗尽): {exc}")

            # Capture tool calls from this round and pass as metadata
            reviewer_tool_calls = reviewer_callback.get_tool_calls()
            self.session.add_entry(
                "reviewer",
                review_verdict,
                metadata={"tool_calls": reviewer_tool_calls} if reviewer_tool_calls else None,
            )
            self.session.save()
            review_verdicts.append(review_verdict)

            # Show reviewer's verdict
            console.agent_report("reviewer", review_verdict)

            # ── Step C: Check verdict ────────────────────────────────
            is_pass = self._is_pass(review_verdict)

            if is_pass:
                logger.info("Reviewer PASS — workflow complete")
                # 审查通过时才显示「审查通过」面板；失败时 reviewer 报告中已包含
                # 完整反馈，不再重复输出「需要修复」面板。
                console.review_verdict(is_pass=True)
                self.session.status = "completed"
                self.session.save()
                return self._result(
                    success=True,
                    summary="审查通过，需求已实现。",
                    total_turns=iteration,
                    coder_reports=coder_reports,
                    review_verdicts=review_verdicts,
                )

            # ── Step D: Extract feedback ─────────────────────────────
            # Extract ONLY the actionable "下一轮反馈" section — NOT the
            # full verdict.  This ensures the Coder's next round context
            # contains zero references to its own previous thoughts / tool
            # calls.
            feedback = self._extract_feedback(review_verdict)
            logger.info(
                "Reviewer FAIL — extracted %d chars of actionable feedback",
                len(feedback),
            )
            # 失败时不再重复输出「需要修复」面板，因为 reviewer 的完整报告中
            # 已包含「下一轮反馈」内容。见 console.review_verdict()。
            # console.review_verdict(is_pass=False, feedback=feedback)

        # ── Out of iterations ────────────────────────────────────────
        logger.warning("Max iterations (%d) reached without pass", self.max_iterations)
        self.session.status = "max_iterations_reached"
        self.session.save()
        return self._result(
            success=False,
            summary=f"已达最大迭代次数 ({self.max_iterations})，需求未完全实现。",
            total_turns=self.max_iterations,
            coder_reports=coder_reports,
            review_verdicts=review_verdicts,
        )

    # ── internals ───────────────────────────────────────────────────

    @staticmethod
    def _is_pass(verdict: str) -> bool:
        """Heuristic: look for PASS signal in the review verdict."""
        # Look for "状态: PASS" or "PASS" near the top in a markdown heading
        text = verdict.lower()
        # Check for the structured format first
        if re.search(r"状态:\s*PASS", verdict, re.I):
            return True
        # Also check for "PASS" as a standalone word in the conclusion section
        if re.search(r"## 审查结论.*?状态:?\s*PASS", verdict, re.I | re.DOTALL):
            return True
        # Fallback: simple keyword check (avoid false positives from "not pass")
        if re.search(r"\bPASS\b", text) and not re.search(r"not\s+pass|no[nt]\s+pass", text):
            # Make sure FAIL isn't also present
            if not re.search(r"\bFAIL\b", text):
                return True
        return False

    @staticmethod
    def _extract_feedback(verdict: str) -> str:
        """Extract ONLY the actionable feedback section from a FAIL verdict.

        Returns the ``下一轮反馈`` section content — pure action items for the
        Coder.  If that section is not found, falls back to ``详细意见``.
        NEVER returns the full verdict or the reviewer's analysis of what the
        Coder did (which would leak previous-round thoughts / tool calls).
        """
        # Look ONLY for "下一轮反馈" — this is the clean, actionable section
        for section in ["### 下一轮反馈", "下一轮反馈"]:
            idx = verdict.find(section)
            if idx != -1:
                after = verdict[idx + len(section):].strip()
                # Cut at the next heading (if any) to avoid bleeding into
                # unrelated sections
                next_heading = after.find("\n##")
                if next_heading != -1:
                    after = after[:next_heading].strip()
                return after[:2000]

        # Fallback 1: "详细意见" — still reasonably clean (what's wrong, not
        # how the coder got there)
        for section in ["### 详细意见", "详细意见"]:
            idx = verdict.find(section)
            if idx != -1:
                after = verdict[idx + len(section):].strip()
                next_heading = after.find("\n##")
                if next_heading != -1:
                    after = after[:next_heading].strip()
                return after[:2000]

        # Last resort: empty — better to give the Coder nothing than to leak
        # previous internal reasoning.
        return ""

    def _result(
        self,
        success: bool,
        summary: str,
        total_turns: int,
        coder_reports: list[str],
        review_verdicts: list[str],
    ) -> dict:
        return {
            "success": success,
            "summary": summary,
            "total_turns": total_turns,
            "session_id": self.session.session_id,
            "coder_reports": coder_reports,
            "review_verdicts": review_verdicts,
        }


# ── Module-level helpers ────────────────────────────────────────────────


def _show_coder_fatal_error(console, category: ErrorCategory, exc: Optional[Exception]):
    """Display a fatal error Panel explaining why the Coder Agent failed.

    Shown when the Coder has exhausted all retry attempts (4 consecutive
    failures).  The panel clearly indicates the error category so the user
    can take appropriate action.
    """
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                f"\n"
                f"  [bold red]🤖 Coder Agent 连续失败 {MAX_CODER_RETRIES + 1} 次[/]\n\n"
                f"  [white]错误分类:[/] [bold yellow]{category.value}[/]\n\n"
                f"  [white]异常信息:[/]\n"
                f"  [dim]{exc}[/]\n\n"
                f"  [bright_black]系统已终止当前工作流。"
                f"请检查以上错误原因后重试。[/]\n"
            ),
            box=box.HEAVY,
            border_style="red",
            width=min(shutil.get_terminal_size().columns, 100),
            title="[bold red]🚨 致命错误[/]",
        )
    )
    console.print()
