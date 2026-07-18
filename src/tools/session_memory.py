"""Session Memory Tool — persistent note-taking across interactive sessions.

Stores structured notes in ``~/.becode/session/<session_id>.md``.

Two modes:
- ``write``: Append notes to the session memory file.  The notes are
  prepended with a newline character before appending.
- ``read only``: Return the full content of the session memory file (no
  changes are made).

The session ID is an 8-character hex string obtained when entering
interactive dialogue mode.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - _current_session_id 模块级变量，在            ║
║    interactive_mode() 入口处由                    ║
║    set_session_memory_id() 设置。                ║
║  - 工具仅注册到 Coder Agent，且始终可用，        ║
║    但仅在交互式对话中有实际效果（session ID      ║
║    会被设置）。                                  ║
║  - 记忆文件路径: ~/.becode/session/{id}.md       ║
╚══════════════════════════════════════════════════╝
"""

import logging
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from src.core.config import SESSION_MEMORY_DIR

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────
# Set by main.py's interactive_mode() at the start of each interactive
# session so the tool knows which session file to read / write.

_current_session_id: str = ""


def set_session_memory_id(session_id: str) -> None:
    """Set the current interactive session ID.

    Called by ``interactive_mode()`` in ``main.py`` before the main loop.
    The ID is an 8-character hex string (same as the SessionStore ID).
    """
    global _current_session_id
    _current_session_id = session_id


def load_session_memory() -> str:
    """Read the session memory file for the current session (if it exists).

    Returns:
        The file content as a formatted string prefixed with a header,
        or an empty string if no memory file exists.
    """
    if not _current_session_id:
        return ""
    mem_file = SESSION_MEMORY_DIR / f"{_current_session_id}.md"
    if not mem_file.exists():
        return ""
    try:
        content = mem_file.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            return ""
        return f"\n\n## 会话记忆\n{content}"
    except Exception as exc:
        logger.warning("Failed to read session memory file %s: %s", mem_file, exc)
        return ""


# ── Tool function exposed to the Coder Agent ──────────────────────────


@tool
def session_memory(mode: str, notes: Optional[str] = "") -> str:
    """记录/回顾当前交互式对话中的重要项目知识和信息。

    有两种模式：
    - write: 将要点记入会话记忆文件。如果文件不存在则创建，已存在则追加。
      注意：追加前会自动在传入的字符串前添加换行符。
    - read only: 读取并返回当前会话的所有记忆内容。此时可忽略 notes 参数。

    适合使用的时机：
    - 完成一项重要任务后，有重要的项目知识和信息需要记录下来供后续参考。
    - 对项目感到困惑时，调用此工具检查之前记录的内容。

    Args:
        mode: 操作模式。"write" 表示写入记忆，"read only" 表示读取记忆。
        notes: 要记录的要点字符串（多行格式），仅在 write 模式下使用。
               例如: "- 项目使用了 FastAPI 框架\n- 数据库为 PostgreSQL"
               在 read only 模式下此参数会被忽略。

    Returns:
        操作结果的消息，或 read only 模式下返回记忆文件的内容字符串。
    """
    global _current_session_id

    if not _current_session_id:
        return "错误: 当前未处于交互式对话模式，无会话 ID。"

    mem_file = SESSION_MEMORY_DIR / f"{_current_session_id}.md"

    if mode == "write":
        # Ensure directory exists
        SESSION_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

        # Determine content to write
        write_content = notes or ""

        try:
            if mem_file.exists():
                # Append: read existing content, then append with newline prefix
                existing = mem_file.read_text(encoding="utf-8", errors="replace")
                mem_file.write_text(
                    f"{existing}\n{write_content}",
                    encoding="utf-8",
                )
                logger.info("Appended session memory to %s", mem_file)
                return f"✅ 已追加记忆到会话文件: {mem_file}"
            else:
                # Create new file
                mem_file.write_text(write_content, encoding="utf-8")
                logger.info("Created session memory file %s", mem_file)
                return f"✅ 已创建新的会话记忆文件: {mem_file}"
        except Exception as exc:
            logger.error("Failed to write session memory: %s", exc)
            return f"❌ 写入会话记忆失败: {exc}"

    elif mode == "read only":
        if not mem_file.exists():
            return "📭 当前会话暂无记忆内容。"

        try:
            content = mem_file.read_text(encoding="utf-8", errors="replace")
            if content.strip():
                return f"📖 当前会话记忆内容:\n\n{content}"
            else:
                return "📭 当前会话记忆文件为空。"
        except Exception as exc:
            logger.error("Failed to read session memory: %s", exc)
            return f"❌ 读取会话记忆失败: {exc}"

    else:
        return f"❌ 未知模式: {mode}。请使用 \"write\" 或 \"read only\"。"
