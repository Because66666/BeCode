"""Tests for src.ui.console — AgentConsole basic methods."""

from unittest.mock import MagicMock, patch

import pytest


class TestAgentConsole:
    """Verify AgentConsole basic methods."""

    def test_get_console_singleton(self):
        from src.ui.console import get_console
        c1 = get_console()
        c2 = get_console()
        assert c1 is c2

    def test_welcome_calls_print(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.welcome("test-session", 10, "gpt-4o")
            assert mock_print.called

    def test_show_requirement(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.show_requirement("Test requirement")
            assert mock_print.called

    def test_agent_thinking_coder(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.agent_thinking("coder", "thinking...")
            assert mock_print.called

    def test_agent_thinking_reviewer(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.agent_thinking("reviewer")
            assert mock_print.called

    def test_agent_report(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.agent_report("coder", "Report content")
            assert mock_print.called

    def test_review_verdict_pass(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.review_verdict(is_pass=True)
            assert mock_print.called

    def test_review_verdict_fail(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.review_verdict(is_pass=False, feedback="Fix it")
            assert mock_print.called

    def test_final_result(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.final_result(
                success=True,
                coder_report="Done",
                review_verdict="PASS",
                total_turns=2,
                session_id="abc123",
            )
            assert mock_print.called

    def test_start_iteration(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.start_iteration(1, 5)
            assert mock_print.called

    @patch("src.ui.console.AgentConsole._prefill_input")
    def test_interactive_prompt_with_prefill(self, mock_prefill):
        mock_prefill.return_value = "test input"
        from src.ui.console import AgentConsole
        console = AgentConsole()
        result = console.interactive_prompt("Enter:", prefill="prev")
        assert result == "test input"
        mock_prefill.assert_called_once_with("Enter:", "prev")

    def test_error(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.error("Something went wrong")
            assert mock_print.called

    def test_separator(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.separator()
            assert mock_print.called

    def test_print(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.print("Hello")
            mock_print.assert_called_once_with("Hello")

    def test_show_summary(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.show_summary("Task completed")
            assert mock_print.called

    def test_show_interrupt_message(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.show_interrupt_message(has_output=True)
            assert mock_print.called
            console.show_interrupt_message(has_output=False)
            assert mock_print.called


class TestToolCall:
    """Verify tool_call display."""

    def test_tool_call_bash_exec(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.tool_call("bash_exec", {"command": "echo hello"}, "hello")
            assert mock_print.called

    def test_tool_call_read_file(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.tool_call("read_file", {"path": "test.py"}, "file content")
            assert mock_print.called

    def test_tool_call_edit_file(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.tool_call("edit_file", {"path": "test.py"}, "Success")
            assert mock_print.called

    def test_tool_call_web_search(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        with patch.object(console._console, "print") as mock_print:
            console.tool_call("web_search", {"query": "test"}, "Results")
            assert mock_print.called

    def test_tool_call_long_result_truncated(self):
        from src.ui.console import AgentConsole
        console = AgentConsole()
        long_result = "x" * 200
        with patch.object(console._console, "print") as mock_print:
            console.tool_call("bash_exec", {"command": "echo"}, long_result)
            # Should not raise
            assert True
