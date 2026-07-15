"""Tests for src.tools.tools — read_file, edit_file, bash_exec, load_context_files."""

import sys
from pathlib import Path

import pytest

from src.tools.tools import (
    read_file,
    edit_file,
    bash_exec,
    load_context_files,
    load_platform_prompt,
    set_workspace_root,
    set_user_requirement,
    _apply_output_limit,
    _PLATFORM_PROMPT,
    MAX_TOOL_OUTPUT_LENGTH,
)


# LangChain @tool wraps functions in StructuredTool — unwrap with .func
def _call(tool, /, *args, **kwargs):
    return tool.func(*args, **kwargs)


class TestSetWorkspaceRoot:
    """Verify workspace root configuration."""

    def test_set_workspace_root(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        from src.tools import tools as t
        root = t._WORKSPACE_ROOT
        assert root is not None
        assert root.resolve() == tmp_workspace.resolve()


class TestLoadContextFiles:
    """Verify load_context_files reads CLAUDE.md and AGENTS.md."""

    def test_load_context_files_found(self, tmp_workspace: Path, context_file: Path):
        set_workspace_root(tmp_workspace)
        result = load_context_files()
        assert "CLAUDE.md" in result
        assert "Project Context" in result

    def test_load_context_files_not_found(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        result = load_context_files()
        assert result == ""

    def test_load_context_files_with_agents_md(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        (tmp_workspace / "CLAUDE.md").write_text("# Claude", encoding="utf-8")
        (tmp_workspace / "AGENTS.md").write_text("# Agents", encoding="utf-8")
        result = load_context_files()
        assert "CLAUDE.md" in result
        assert "AGENTS.md" in result


class TestReadFile:
    """Verify read_file tool."""

    def test_read_existing_file(self, tmp_workspace: Path, sample_file: Path):
        set_workspace_root(tmp_workspace)
        result = _call(read_file, str(sample_file))
        assert "hello world" in result
        assert "文件:" in result

    def test_read_with_offset_and_limit(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        # Create a multi-line file
        fp = tmp_workspace / "multi.py"
        fp.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
        result = _call(read_file, str(fp), 2, 3)
        assert "line2" in result
        assert "line3" in result
        assert "line4" in result
        assert "line1" not in result
        assert "line5" not in result

    def test_read_nonexistent_file(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        result = _call(read_file, str(tmp_workspace / "nope.txt"))
        assert "文件不存在" in result

    def test_read_directory_as_file(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        result = _call(read_file, str(tmp_workspace))
        assert "不是文件" in result

    def test_read_outside_workspace(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        result = _call(read_file, str(Path.home() / "secret.txt"))
        assert "错误" in result or "outside" in result


class TestEditFile:
    """Verify edit_file tool."""

    def test_edit_existing_file(self, tmp_workspace: Path, sample_file: Path):
        set_workspace_root(tmp_workspace)
        result = _call(edit_file, str(sample_file), "print('hello world')", "print('hello universe')")
        assert "成功" in result
        assert sample_file.read_text(encoding="utf-8") == "print('hello universe')\n"

    def test_edit_nonexistent_string(self, tmp_workspace: Path, sample_file: Path):
        set_workspace_root(tmp_workspace)
        result = _call(edit_file, str(sample_file), "nonexistent", "replacement")
        assert "未找到" in result

    def test_edit_nonexistent_file_creates_it(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        fp = tmp_workspace / "new_file.py"
        result = _call(edit_file, str(fp), "", "# New file")
        assert "成功" in result
        assert fp.exists()
        assert fp.read_text(encoding="utf-8") == "# New file"

    def test_edit_file_without_parent_dir(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        fp = tmp_workspace / "nonexistent" / "file.py"
        result = _call(edit_file, str(fp), "", "x")
        assert "文件路径不存在" in result

    def test_edit_unique_violation(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        fp = tmp_workspace / "dup.py"
        fp.write_text("a\na\n", encoding="utf-8")
        result = _call(edit_file, str(fp), "a", "b")
        assert "出现" in result


class TestBashExec:
    """Verify bash_exec tool (with LLM guard disabled)."""

    def test_echo_command(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        result = _call(bash_exec, "echo hello test")
        assert "hello test" in result
        assert "exit code: 0" in result

    def test_failing_command(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        # On Windows, use a non-existent command to trigger a non-zero exit
        result = _call(bash_exec, "python -c \"import sys; sys.exit(1)\"")
        assert "exit code: 1" in result

    def test_timeout(self, tmp_workspace: Path):
        set_workspace_root(tmp_workspace)
        result = _call(bash_exec, "echo fast", 5)
        assert "exit code: 0" in result

    def test_safety_block(self, tmp_workspace: Path):
        """rm -rf / should be blocked by static rules."""
        set_workspace_root(tmp_workspace)
        result = _call(bash_exec, "rm -rf /")
        assert "被安全系统拦截" in result or "⛔" in result


class TestSetUserRequirement:
    """Verify set_user_requirement stores the value."""

    def test_set_and_retrieve(self):
        from src.tools import tools as t
        set_user_requirement("Test requirement")
        assert t._USER_REQUIREMENT == "Test requirement"

    def test_set_empty(self):
        from src.tools import tools as t
        set_user_requirement("")
        assert t._USER_REQUIREMENT == ""


class TestApplyOutputLimit:
    """Verify _apply_output_limit truncates long tool outputs."""

    def test_short_string_passes_through(self):
        short = "Hello, world!"
        assert _apply_output_limit(short) == short

    def test_exact_max_length_passes_through(self):
        exact = "x" * MAX_TOOL_OUTPUT_LENGTH
        assert _apply_output_limit(exact) == exact

    def test_exceeds_max_length_truncated(self):
        long_str = "x" * (MAX_TOOL_OUTPUT_LENGTH + 1)
        result = _apply_output_limit(long_str)
        expected = "命令返回长度超过10ktoken，请检查后重试"
        assert result == expected

    def test_empty_string_passes_through(self):
        assert _apply_output_limit("") == ""


class TestPlatformPrompt:
    """Verify platform auto-detection and prompt injection into bash_exec."""

    def test_load_platform_prompt_returns_string(self):
        """load_platform_prompt() should return a non-empty string on
        supported platforms (Windows/darwin), or an empty string on others."""
        prompt = load_platform_prompt()
        if sys.platform == "win32":
            assert "Windows" in prompt
        elif sys.platform == "darwin":
            assert "macOS" in prompt or "darwin" in prompt
        else:
            assert prompt == ""

    def test_platform_prompt_in_bash_exec_description(self):
        """bash_exec.description should contain platform-specific content
        on supported platforms."""
        desc = bash_exec.description
        if sys.platform == "win32":
            assert "Windows" in desc
            assert "%USERPROFILE%" in desc
        elif sys.platform == "darwin":
            assert "macOS" in desc or "darwin" in desc
            assert "$HOME" in desc
        else:
            # On unsupported platforms, description should remain unchanged
            assert "Execute a bash command" in desc

    def test_platform_prompt_constant_is_loaded(self):
        """_PLATFORM_PROMPT global should be a string (possibly empty)."""
        assert isinstance(_PLATFORM_PROMPT, str)
