"""Shared fixtures for BeCode test suite."""

import json
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from src.core.session_store import SessionStore


# ── Environment ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_env() -> Generator[None, None, None]:
    """Ensure a clean env before each test, restore after."""
    old = dict(os.environ)
    # Disable LLM calls in bash guard during unit tests
    os.environ["BASH_GUARD_LLM_DISABLED"] = "1"
    yield
    os.environ.clear()
    os.environ.update(old)


# ── Temporary Filesystem ─────────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True)
    return ws


@pytest.fixture
def sample_file(tmp_workspace: Path) -> Path:
    """Create a sample Python file in the workspace."""
    fp = tmp_workspace / "hello.py"
    fp.write_text("print('hello world')\n", encoding="utf-8")
    return fp


@pytest.fixture
def context_file(tmp_workspace: Path) -> Path:
    """Create a CLAUDE.md context file."""
    fp = tmp_workspace / "CLAUDE.md"
    fp.write_text("# Project Context\n\nThis is a test project.", encoding="utf-8")
    return fp


# ── Session Store ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_session_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Override SESSION_DIR to a temp path."""
    from src.core import config as cfg
    old_dir = cfg.SESSION_DIR
    new_dir = tmp_path / "sessions"
    new_dir.mkdir(parents=True)
    cfg.SESSION_DIR = new_dir
    yield new_dir
    cfg.SESSION_DIR = old_dir


@pytest.fixture
def session_store(tmp_session_dir: Path) -> SessionStore:
    """Create a fresh SessionStore in a temp directory."""
    return SessionStore()


# ── Sample session data ──────────────────────────────────────────────

@pytest.fixture
def loaded_session(tmp_session_dir: Path) -> SessionStore:
    """Create a session with some history entries."""
    store = SessionStore()
    store.requirement = "Write a test"
    store.status = "running"
    store.add_entry("coder", "Coder report 1",
                    metadata={"tool_calls": [{"tool": "read_file", "args": {"path": "test.py"}}]})
    store.add_entry("reviewer", "Review verdict 1")
    store.incr_turn()
    store.add_entry("coder", "Coder report 2")
    store.save()
    return store


# ── Verdict samples for orchestrator tests ───────────────────────────────

@pytest.fixture
def pass_verdict() -> str:
    return """## 审查结论

### 状态: PASS

### 验证过程
Ran the code, everything works.

### 详细意见
All requirements met.
"""


@pytest.fixture
def fail_verdict() -> str:
    return """## 审查结论

### 状态: FAIL

### 验证过程
Checked files, missing test for edge case.

### 详细意见
The implementation is missing error handling for empty input.

### 下一轮反馈
请添加对空输入的检查，并在 tests/ 中添加对应的测试用例。
"""
