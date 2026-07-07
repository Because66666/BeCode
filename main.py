#!/usr/bin/env python3
"""BeCode — 双智能体编码工作流系统。

Usage:
    becode "your requirement here"
    becode --file requirement.txt
    becode --interactive       # multi-line input

Data directory: ~/.becode/  — sessions, .env, and logs are stored here.
"""

import argparse
import logging
import sys
from pathlib import Path

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


def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} — 双智能体编码工作流系统 v{APP_VERSION}",
    )
    parser.add_argument("--version", "-v", action="store_true", help="显示版本信息")
    src_grp = parser.add_mutually_exclusive_group()
    src_grp.add_argument("requirement", nargs="?", help="需求文本 (直接传入)")
    src_grp.add_argument("--file", "-f", type=str, help="从文件读取需求")
    src_grp.add_argument("--interactive", "-i", action="store_true", help="交互式输入")
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

    # ── Ensure data directory exists ────────────────────────────────
    BECODE_HOME.mkdir(parents=True, exist_ok=True)

    # ── Resolve requirement ─────────────────────────────────────────
    requirement = ""
    if args.interactive:
        print("请输入需求（输入 .done 结束）:")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == ".done":
                break
            lines.append(line)
        requirement = "\n".join(lines).strip()
    elif args.file:
        fpath = Path(args.file)
        if not fpath.exists():
            print(f"错误: 文件不存在: {fpath}")
            sys.exit(1)
        requirement = fpath.read_text(encoding="utf-8").strip()
    elif args.requirement:
        requirement = args.requirement.strip()

    if not requirement:
        parser.print_help()
        sys.exit(1)

    # ── Override max iterations if provided ─────────────────────────
    if args.max_iterations is not None:
        import os
        os.environ["MAX_ITERATIONS"] = str(args.max_iterations)

    # ── Boot ────────────────────────────────────────────────────────
    workspace = Path.cwd().resolve()
    set_workspace_root(workspace)

    session = SessionStore()
    orchestrator = Orchestrator(session=session, model_name=args.model)

    from src.ui.console import get_console
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


if __name__ == "__main__":
    main()
