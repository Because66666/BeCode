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

    def save(self):
        """Flush in-memory state to disk."""
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

    def get_coder_context(self) -> str:
        """Build the prompt context for the Coder agent, preserving history."""
        lines = [f"# 用户原始需求\n{self.requirement}\n"]
        for entry in self.history:
            role_label = {"user": "用户反馈", "coder": "主智能体报告", "reviewer": "审查意见"}.get(
                entry["role"], entry["role"]
            )
            lines.append(f"## {role_label} (第 {entry['turn']} 轮)\n{entry['content']}\n")
        return "\n".join(lines)

    def get_reviewer_context(self) -> str:
        """Build the prompt context for the Reviewer agent — only sees
        the original requirement + the latest coder report."""
        lines = [f"# 用户原始需求\n{self.requirement}\n"]
        for entry in reversed(self.history):
            if entry["role"] == "coder":
                lines.append(f"## 主智能体最新报告\n{entry['content']}\n")
                break
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"SessionStore(id={self.session_id}, turn={self.turn}, status={self.status})"
