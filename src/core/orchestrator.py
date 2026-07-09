"""Orchestrator — the main workflow loop.

Flow:
  1. Receive user requirement.
  2. Loop (max_iterations):
     a. Coder Agent → implementation + report
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
╚══════════════════════════════════════════════════╝
"""

import logging
import re
from typing import Optional

from src.agents.coder_agent import run_coder
from src.agents.reviewer_agent import run_reviewer
from src.core.config import settings
from src.core.session_store import SessionStore
from src.tools.tools import set_user_requirement
from src.ui.console import get_console
from src.ui.callbacks import ToolCallCapture

logger = logging.getLogger(__name__)


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

            # ── Step A: Coder ────────────────────────────────────────
            # NOTE: run_coder() builds a BRAND-NEW agent each round and
            # passes only `requirement` + `feedback` (the reviewer's clean
            # actionable items).  No previous round's thoughts or tool calls
            # are included.  See `coder_agent.py` for details.
            console.agent_thinking("coder", "正在分析需求并实现...")
            coder_callback = ToolCallCapture(agent_name="coder")

            try:
                coder_report = run_coder(
                    requirement=requirement,
                    feedback=feedback,
                    model_name=self.model_name,
                    callbacks=[coder_callback],
                )
            except Exception as exc:
                logger.exception("Coder agent crashed")
                coder_report = f"[Coder 异常] {exc}"
                console.error(f"Coder Agent 异常: {exc}")

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

            # ── Step B: Reviewer ─────────────────────────────────────
            console.agent_thinking("reviewer", "正在审查实现代码...")
            reviewer_callback = ToolCallCapture(agent_name="reviewer")

            try:
                review_verdict = run_reviewer(
                    requirement=requirement,
                    coder_report=coder_report,
                    model_name=self.model_name,
                    callbacks=[reviewer_callback],
                )
            except Exception as exc:
                logger.exception("Reviewer agent crashed")
                review_verdict = f"[Reviewer 异常] {exc}"
                console.error(f"Reviewer Agent 异常: {exc}")

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
            console.review_verdict(is_pass=False, feedback=feedback)

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
