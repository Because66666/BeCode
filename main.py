#!/usr/bin/env python3
"""BeCode — 双智能体编码工作流系统 (交互式对话模式)。

Usage:
    becode "your requirement here"    # 单次运行模式
    becode --file requirement.txt     # 从文件读取
    becode                            # 无参数 → 进入交互式对话模式

Data directory: ~/.becode/  — sessions, .env, and logs are stored here.
"""

import argparse
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

from src.core.config import settings, BECODE_HOME, SESSION_DIR
from src.core.orchestrator import Orchestrator
from src.core.session_store import SessionStore
from src.tools.tools import set_workspace_root

# ── Application metadata ───────────────────────────────────────────
APP_NAME = "BeCode"
APP_VERSION = "1.0.0"

# Only WARNING and above (ERROR, CRITICAL) are shown on console
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ── Global Ctrl+C state ────────────────────────────────────────────
_ctrl_c_pressed = False
_has_formal_output = False


def _signal_handler(signum, frame):
    """Signal handler for SIGINT — sets global flag."""
    global _ctrl_c_pressed
    _ctrl_c_pressed = True
    # Re-raise KeyboardInterrupt so existing try/except blocks catch it
    raise KeyboardInterrupt()


# ── Interactive Mode ───────────────────────────────────────────────

def interactive_mode(orchestrator: Orchestrator, model_name: Optional[str] = None):
    """Run the interactive dialogue loop.

    Flow:
      1. Show welcome banner.
      2. Loop:
         a. Prompt user for input (pre-fill hint on Ctrl+C return).
         b. Run orchestrator with accumulated summary context.
         c. Generate LLM one-line summary.
         d. Display summary (light gray italic) and loop.
    """
    from src.ui.console import get_console
    console = get_console()

    # Register SIGINT handler
    global _ctrl_c_pressed
    _ctrl_c_pressed = False
    signal.signal(signal.SIGINT, _signal_handler)

    summary_context: list[str] = []  # Accumulated summaries for prompt context
    last_user_input: str = ""
    previous_result: Optional[dict] = None

    console.welcome(
        session_id=orchestrator.session.session_id,
        max_iterations=settings.max_iterations,
        model=settings.openai_model,
    )
    console.print(
        "[bold italic cyan]🤖 交互式对话模式[/] — 输入任务需求开始，输入 [bold].exit[/] 退出\n"
    )

    while True:
        global _has_formal_output
        _ctrl_c_pressed = False
        _has_formal_output = False

        # ── Step 1: Get user input ──────────────────────────────────
        try:
            if last_user_input and previous_result and not previous_result.get("interrupted", True):
                # Normal flow: fresh prompt
                pass  # Show normal prompt

            user_input = console.interactive_prompt(
                "请输入任务需求 (输入 .exit 退出):",
                prefill=last_user_input if _ctrl_c_pressed else "",
            )
        except KeyboardInterrupt:
            # Ctrl+C during input: loop back with pre-fill
            console.show_interrupt_message(has_output=False)
            continue

        if not user_input:
            console.print("[dim]空输入，请重新输入。[/]")
            continue

        if user_input == ".exit":
            console.print("[dim]👋 退出交互模式。[/]")
            break

        last_user_input = user_input

        # ── Step 2: Run orchestrator ────────────────────────────────
        console.print()
        console.print("[bold]━━━ 开始执行任务 ━━━[/]")
        console.print()

        try:
            result = orchestrator.run_interactive(
                requirement=user_input,
                summary_context=summary_context,
            )
            _has_formal_output = bool(
                result.get("coder_reports") and result["coder_reports"][-1]
            )

        except KeyboardInterrupt:
            # Ctrl+C during agent execution
            console.show_interrupt_message(has_output=_has_formal_output)

            if _has_formal_output and previous_result:
                # Partial output exists — treat as a completed task summary
                summary_context.append(
                    f"（被中断）任务: {user_input[:50]}..."
                )
                console.print(
                    "[dim italic]部分结果已保留到上下文中，可继续输入新需求。[/]"
                )
            else:
                # No formal output — go back to input with pre-fill
                console.print(
                    "[dim italic]无输出结果，返回输入状态。[/]"
                )
                # Keep last_user_input for pre-fill
            continue

        except Exception as exc:
            console.error(f"执行异常: {exc}")
            continue

        previous_result = result

        # ── Step 3: Display final stats ─────────────────────────────
        last_coder = result.get("coder_reports", ["(无)"])[-1]
        last_review = result.get("review_verdicts", ["(无)"])[-1]
        console.final_result(
            success=result.get("success", False),
            coder_report=last_coder,
            review_verdict=last_review,
            total_turns=result.get("total_turns", 0),
            session_id=result.get("session_id", ""),
        )

        # ── Step 4: Generate and display one-line summary ──────────
        one_line = result.get("one_line_summary", "")
        if one_line:
            console.show_summary(one_line)
            summary_context.append(one_line)

        # Keep the last 20 summaries to avoid context bloat
        if len(summary_context) > 20:
            summary_context = summary_context[-20:]

        # Print session file path for reference
        session_file = SESSION_DIR / f'session_{result["session_id"]}.json'
        console.print(f"[dim]📁 会话文件: {session_file}[/]")

    # ── Final message ───────────────────────────────────────────────
    console.print()
    console.print("[dim]👋 BeCode 交互模式已退出。[/]")
    sys.exit(0)


# ── Single-shot Mode ───────────────────────────────────────────────

def single_shot_mode(requirement: str, args: argparse.Namespace):
    """Run a single task and exit (original behavior)."""
    from src.ui.console import get_console

    workspace = Path.cwd().resolve()
    set_workspace_root(workspace)

    session = SessionStore()
    orchestrator = Orchestrator(session=session, model_name=args.model)

    console = get_console()
    console.welcome(
        session_id=session.session_id,
        max_iterations=settings.max_iterations,
        model=settings.openai_model,
    )
    console.show_requirement(requirement)

    # ── Run ─────────────────────────────────────────────────────────
    result = orchestrator.run(requirement)

    # ── Final output ────────────────────────────────────────────────
    last_coder = result["coder_reports"][-1] if result["coder_reports"] else "(无)"
    last_review = result["review_verdicts"][-1] if result["review_verdicts"] else "(无)"
    console.final_result(
        success=result["success"],
        coder_report=last_coder,
        review_verdict=last_review,
        total_turns=result["total_turns"],
        session_id=result["session_id"],
    )

    # Print session file path
    session_file = SESSION_DIR / f'session_{result["session_id"]}.json'
    console.print(f"\n📁 会话文件: {session_file}")

    # ── Exit ─────────────────────────────────────────────────────────
    console.print("[dim]工作流已完成，程序退出。[/]")


def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} — 双智能体编码工作流系统 v{APP_VERSION}",
    )
    parser.add_argument("--version", "-v", action="store_true", help="显示版本信息")
    parser.add_argument("--hello", action="store_true", help="打印 hello world test")
    src_grp = parser.add_mutually_exclusive_group()
    src_grp.add_argument("requirement", nargs="?", help="需求文本 (直接传入)")
    src_grp.add_argument("--file", "-f", type=str, help="从文件读取需求")
    parser.add_argument("--model", "-m", type=str, default=None, help="覆盖模型名称")
    parser.add_argument(
        "--max-iterations", type=int, default=None, help="覆盖最大迭代次数"
    )

    args = parser.parse_args()

    # ── Version ─────────────────────────────────────────────────────
    if args.version:
        print(f"{APP_NAME} v{APP_VERSION}")
        print(f"数据目录: {BECODE_HOME}")
        sys.exit(0)

    # ── Hello World ──────────────────────────────────────────────────
    if args.hello:
        print("hello world test")
        sys.exit(0)

    # ── Ensure data directory exists ────────────────────────────────
    BECODE_HOME.mkdir(parents=True, exist_ok=True)

    # ── Override max iterations if provided ─────────────────────────
    if args.max_iterations is not None:
        import os
        os.environ["MAX_ITERATIONS"] = str(args.max_iterations)

    # ── Resolve requirement ─────────────────────────────────────────
    requirement = ""
    if args.file:
        fpath = Path(args.file)
        if not fpath.exists():
            print(f"错误: 文件不存在: {fpath}")
            sys.exit(1)
        requirement = fpath.read_text(encoding="utf-8").strip()
    elif args.requirement:
        requirement = args.requirement.strip()

    # ── No args → Interactive mode ──────────────────────────────────
    if not requirement:
        workspace = Path.cwd().resolve()
        set_workspace_root(workspace)

        session = SessionStore()
        orchestrator = Orchestrator(session=session, model_name=args.model)
        interactive_mode(orchestrator, model_name=args.model)
        return  # Never reached

    # ── Single-shot mode ────────────────────────────────────────────
    single_shot_mode(requirement, args)


if __name__ == "__main__":
    main()
