"""Tests for src.ui.callbacks — ToolCallCapture callback handler."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.ui.callbacks import ToolCallCapture, _extract_tool_output


class TestExtractToolOutput:
    """Verify _extract_tool_output handles various output types."""

    def test_plain_string(self):
        assert _extract_tool_output("hello") == "hello"

    def test_none_output(self):
        assert _extract_tool_output(None) == "(无输出)"

    def test_message_like_object(self):
        """Objects with .content attribute should use that."""
        obj = MagicMock()
        obj.content = "file content"
        assert _extract_tool_output(obj) == "file content"

    def test_message_with_empty_content(self):
        obj = MagicMock()
        obj.content = ""
        assert _extract_tool_output(obj) == "(无输出)"

    def test_message_with_none_content(self):
        obj = MagicMock()
        obj.content = None
        assert _extract_tool_output(obj) == "(无输出)"


class TestToolCallCapture:
    """Verify ToolCallCapture lifecycle."""

    def setup_method(self):
        self.capture = ToolCallCapture(agent_name="coder")

    def test_initial_state(self):
        assert self.capture.agent_name == "coder"
        assert self.capture.get_tool_calls() == []

    def test_on_tool_start_records_call(self):
        serialized = {"name": "read_file"}
        self.capture.on_tool_start(
            serialized=serialized,
            input_str="",
            run_id=uuid4(),
            inputs={"path": "test.py"},
        )
        calls = self.capture.get_tool_calls()
        assert len(calls) == 1
        assert calls[0]["tool"] == "read_file"
        assert calls[0]["args"]["path"] == "test.py"

    def test_on_tool_start_without_inputs(self):
        serialized = {"name": "bash_exec"}
        self.capture.on_tool_start(
            serialized=serialized,
            input_str="echo hello",
            run_id=uuid4(),
        )
        calls = self.capture.get_tool_calls()
        assert len(calls) == 1
        assert calls[0]["tool"] == "bash_exec"

    def test_on_tool_end_clears_state(self):
        self.capture._current_tool = "bash_exec"
        self.capture._current_tool_args = {"command": "echo hi"}
        self.capture.on_tool_end(output="hi", run_id=uuid4())
        assert self.capture._current_tool is None
        assert self.capture._current_tool_args is None

    def test_on_tool_error_clears_state(self):
        self.capture._current_tool = "bash_exec"
        self.capture.on_tool_error(
            Exception("Command failed"),
            run_id=uuid4(),
        )
        assert self.capture._current_tool is None
        assert self.capture._current_tool_args is None

    def test_clear_tool_calls(self):
        serialized = {"name": "read_file"}
        self.capture.on_tool_start(
            serialized=serialized,
            input_str="",
            run_id=uuid4(),
            inputs={"path": "x.py"},
        )
        assert len(self.capture.get_tool_calls()) == 1
        self.capture.clear_tool_calls()
        assert self.capture.get_tool_calls() == []
