"""Tool functions exposed to the agents.

Three tools:
1. read_file   — read a file's content from disk
2. edit_file   — apply an exact-string-replacement edit to a file
3. bash_exec   — run a bash command (goes through BashGuard first)

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - edit_file 自动创建文件优化: 文件不存在时，    ║
║    检查父目录是否存在；如果父目录存在，则自动    ║
║    创建空文件后再执行替换逻辑（old_string=""     ║
║    时匹配空文件内容）；如果父目录也不存在，      ║
║    则返回"文件路径不存在"错误。                  ║
║  - bash_exec 工具输出首行现在包含安全审查结果:   ║
║    "🔒 安全审查: {reason}"，取代此前安全模型      ║
║    输出被误渲染为 agent 思考过程(show_thinking)   ║
║    的问题。                                      ║
║  - bash_exec 现将当前 user_requirement 传给      ║
║    BashGuard（由 Orchestrator 经                 ║
║    set_user_requirement() 设置），供 LLM 审查     ║
║    时结合任务上下文判断命令意图。                 ║
║  - 工具返回值长度限制: 所有工具的返回值若超过                               ║
║    MAX_TOOL_OUTPUT_LENGTH(=40000) 字符，会被强制替换为提示消息              ║
║    「命令返回长度超过10ktoken，请检查后重试」。                             ║
║    _apply_output_limit() 为辅助函数，封装截断逻辑。                        ║
╚══════════════════════════════════════════════════╝
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from src.tools.bash_guard import check_command

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT: Optional[Path] = None
_USER_REQUIREMENT: str = ""


def set_workspace_root(path: str | Path):
    """Set the allowed workspace root for file operations."""
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = Path(path).resolve()


def set_user_requirement(requirement: str):
    """Set the current user requirement.

    Passed to BashGuard so the LLM safety review can judge the command
    against the actual task context. Should be called by the Orchestrator
    at the start of each run.
    """
    global _USER_REQUIREMENT
    _USER_REQUIREMENT = requirement or ""


def load_context_files() -> str:
    """Read CLAUDE.md and AGENTS.md from the workspace root (if they exist)
    and return a formatted string to be injected into the agent prompt.

    Each file's content is prefixed with its file name as a header.
    Returns an empty string if neither file exists.
    """
    root = _WORKSPACE_ROOT.resolve() if _WORKSPACE_ROOT else Path.cwd().resolve()
    parts: list[str] = []

    for fname in ("CLAUDE.md", "AGENTS.md"):
        fpath = root / fname
        if fpath.exists() and fpath.is_file():
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                continue
            if content:
                parts.append(f"## 文件: {fname}\n{content}")

    if not parts:
        return ""

    return "\n\n".join(parts)


def _resolve_path(path: str | Path) -> Path:
    """Resolve a path, ensuring it is inside the workspace root."""
    p = Path(path)
    if not p.is_absolute():
        p = (_WORKSPACE_ROOT or Path.cwd()).resolve() / p
    p = p.resolve()
    root = _WORKSPACE_ROOT.resolve() if _WORKSPACE_ROOT else Path.cwd().resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise PermissionError(f"Path {p} is outside workspace root {root}")
    return p


# ── Tool output length constraint ────────────────────────────────────

MAX_TOOL_OUTPUT_LENGTH = 40000
_TOOL_OUTPUT_TOO_LONG_MSG = "命令返回长度超过10ktoken，请检查后重试"


def _apply_output_limit(result: str) -> str:
    """Enforce a maximum character length on tool return values.

    If the result string exceeds ``MAX_TOOL_OUTPUT_LENGTH`` characters, it is
    replaced with a fixed prompt asking the agent to retry with a narrower
    scope.
    """
    if len(result) > MAX_TOOL_OUTPUT_LENGTH:
        return _TOOL_OUTPUT_TOO_LONG_MSG
    return result


# ── Tool 1: read_file ──────────────────────────────────────────────


@tool
def read_file(path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> str:
    """Read the content of a file from disk.

    Args:
        path: Absolute or workspace-relative file path.
        offset: Optional line number to start from (1-indexed).
        limit: Optional max number of lines to read.

    Returns:
        The file content with line numbers.
    """
    try:
        p = _resolve_path(path)
    except PermissionError as e:
        return _apply_output_limit(f"错误: {e}")
    except Exception as e:
        return _apply_output_limit(f"路径解析失败: {e}")

    if not p.exists():
        return _apply_output_limit(f"错误: 文件不存在: {p}")
    if not p.is_file():
        return _apply_output_limit(f"错误: 路径不是文件: {p}")

    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except Exception as e:
        return _apply_output_limit(f"读取文件失败: {e}")

    total = len(lines)

    if offset is not None:
        start = max(1, offset) - 1
    else:
        start = 0

    if limit is not None:
        end = min(start + limit, total)
    else:
        end = total

    selected = lines[start:end]
    numbered = "".join(f"{i + 1}\t{line}" for i, line in enumerate(selected, start=start + 1))
    summary = f"文件: {p} ({total} 行, 显示 {start + 1}-{end})\n"
    return _apply_output_limit(summary + numbered)


# ── Tool 2: edit_file ──────────────────────────────────────────────


@tool
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Edit a file by doing an exact-string replacement.

    Works like search-and-replace: finds the *unique* occurrence of
    ``old_string`` in the file and replaces it with ``new_string``.

    Args:
        path: Absolute or workspace-relative file path.
        old_string: The exact text to search for (must match exactly).
        new_string: The replacement text.

    Returns:
        Success or error message.
    """
    try:
        p = _resolve_path(path)
    except PermissionError as e:
        return _apply_output_limit(f"错误: {e}")
    except Exception as e:
        return _apply_output_limit(f"路径解析失败: {e}")

    if not p.exists():
        # 文件不存在时，如果父目录存在则自动创建文件（而非报错）
        if not p.parent.exists():
            return _apply_output_limit(f"错误: 文件路径不存在: {p.parent}")
        try:
            p.touch(exist_ok=True)
        except Exception as e:
            return _apply_output_limit(f"创建文件失败: {e}")

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return _apply_output_limit(f"读取文件失败: {e}")

    if old_string not in content:
        return _apply_output_limit("错误: 未找到要替换的字符串，请确保 `old_string` 与文件内容完全匹配")

    count = content.count(old_string)
    if count > 1:
        return _apply_output_limit(f"错误: `old_string` 在文件中出现 {count} 次，请确保唯一性")

    new_content = content.replace(old_string, new_string, 1)
    try:
        p.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return _apply_output_limit(f"写入文件失败: {e}")

    return _apply_output_limit(f"成功: 已编辑文件 {p} (替换了 {len(old_string)} → {len(new_string)} 个字符)")


# ── Tool 3: bash_exec ──────────────────────────────────────────────


@tool
def bash_exec(command: str, timeout_seconds: int = 60) -> str:
    """Execute a bash command on the local machine.

    The command goes through a two-layer safety check before running:
    1. Static rules (blocking rm -rf /, dd, mkfs, etc.)
    2. LLM semantic review (judges intent)

    Args:
        command: The bash command string to execute.
        timeout_seconds: Max execution time (default 60, max 300).

    Returns:
        stdout + stderr of the command, or an error message.
    """
    # 1. Safety check via BashGuard
    guard_result = check_command(command, user_requirement=_USER_REQUIREMENT)

    # Build guard info line (shown first in tool output)
    guard_info = f"安全审查: {guard_result.reason}"

    if not guard_result.approved:
        return _apply_output_limit(
            f"⛔ 命令被安全系统拦截\n"
            f"{guard_info}\n"
            f"命令: {command[:200]}"
        )

    # 2. Execute
    timeout = min(max(timeout_seconds, 1), 300)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_WORKSPACE_ROOT) if _WORKSPACE_ROOT else None,
        )
    except subprocess.TimeoutExpired:
        return _apply_output_limit(f"⏱️ 命令执行超时 (>{timeout}s)\n命令: {command[:200]}")
    except Exception as e:
        return _apply_output_limit(f"执行失败: {e}")

    # 3. Build output (prepend guard info)
    output_parts = [guard_info]
    if result.stdout:
        output_parts.append(f"--- stdout ---\n{result.stdout.rstrip()}")
    if result.stderr:
        output_parts.append(f"--- stderr ---\n{result.stderr.rstrip()}")

    if not output_parts:
        output_parts.append("(命令执行完毕，无输出)")

    body = "\n".join(output_parts)
    retcode = result.returncode
    summary = f"exit code: {retcode}"
    return _apply_output_limit(f"{summary}\n{body}")
