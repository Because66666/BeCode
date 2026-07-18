"""Session persistence — saves / loads conversation state to disk.

Each session is a JSON file under the configured session directory.
The store keeps the full turn history so the process can be resumed
after an interruption.

Each history entry may include ``metadata.tool_calls`` — a list of
tool invocations (name + arguments, without responses) made during
that agent round.

╔══════════════════════════════════════════════════╗
║  Learned Workspace Facts                        ║
║  - 通过 metadata={"tool_calls": [...]} 传入      ║
║    session.add_entry()，持久化到 session JSON    ║
║    的 history[].metadata.tool_calls 字段。       ║
║  - ⚠️ 这些 history/tool_calls 仅供审计/调试      ║
║    使用，**绝不**应喂回 Coder Agent 的 prompt。  ║
║    每轮 Coder 必须从干净的上下文开始。            ║
╚══════════════════════════════════════════════════╝
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.core.config import SESSION_DIR


class SessionStore:
    """Manages one coding session's lifecycle."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self._base: Path = SESSION_DIR
        self._base.mkdir(parents=True, exist_ok=True)
        self._file: Path = self._base / f"session_{self.session_id}.json"
        self._data: dict[str, Any] = self._load_or_create()

    # ── public helpers ──────────────────────────────────────────────

    @property
    def turn(self) -> int:
        return self._data.get("turn", 0)

    def incr_turn(self) -> int:
        self._data["turn"] = self.turn + 1
        return self.turn

    @property
    def history(self) -> list[dict[str, Any]]:
        return self._data.get("history", [])

    def add_entry(self, role: str, content: str, metadata: Optional[dict] = None):
        entry = {
            "turn": self.turn,
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            entry["metadata"] = metadata
        self._data.setdefault("history", []).append(entry)

    @property
    def status(self) -> str:
        return self._data.get("status", "pending")

    @status.setter
    def status(self, value: str):
        self._data["status"] = value

    @property
    def requirement(self) -> str:
        return self._data.get("requirement", "")

    @requirement.setter
    def requirement(self, value: str):
        self._data["requirement"] = value

    @property
    def compression_events(self) -> list[dict]:
        return self._data.get("compression_events", [])

    def record_token_usage(self, usage_data: dict):
        """Record per-agent token usage data into the session.

        Args:
            usage_data: dict from TokenTracker.get_all_usage()
        """
        self._data["token_usage"] = usage_data

    def save(self):
        """Flush in-memory state to disk."""
        # Record token usage before saving
        try:
            from src.core.token_tracker import get_token_tracker
            tracker = get_token_tracker()
            self.record_token_usage(tracker.get_all_usage())
        except Exception:
            pass
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._file.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))

    # ── internals ───────────────────────────────────────────────────

    def _load_or_create(self) -> dict[str, Any]:
        if self._file.exists():
            raw = self._file.read_text(encoding="utf-8")
            return json.loads(raw)
        return {
            "session_id": self.session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "turn": 0,
            "status": "pending",
            "requirement": "",
            "history": [],
        }

    # NOTE: 不再提供 get_coder_context() / get_reviewer_context() 方法。
    #
    # 根据设计约束，Coder Agent 在后续轮次中不应看到前一轮的思考内容
    # 和工具调用记录。Orchestrator 只将 reviewer 的「下一轮反馈」
    # （纯行动项）传递给 Coder，而非完整历史。
    # Reviewer 也仅收到原始需求 + Coder 最新报告，不走 session history。

    def __repr__(self) -> str:
        return f"SessionStore(id={self.session_id}, turn={self.turn}, status={self.status})"
