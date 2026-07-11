"""Tests for src.agents.coder_agent — build_coder_agent, run_coder."""

from unittest.mock import patch, MagicMock

import pytest


class TestBuildCoderAgent:
    """Verify build_coder_agent creates an agent with tools."""

    def test_build_returns_agent(self):
        from src.agents.coder_agent import build_coder_agent
        agent = build_coder_agent()
        assert agent is not None

    def test_agent_has_tools(self):
        from src.agents.coder_agent import build_coder_agent
        agent = build_coder_agent()
        # The agent should have tools bound
        bound_tools = getattr(agent, "tools", None) or getattr(agent, "bound_tools", None)
        if bound_tools:
            tool_names = {t.name if hasattr(t, "name") else str(t) for t in bound_tools}
            assert "read_file" in tool_names
            assert "bash_exec" in tool_names
            assert "web_search" in tool_names


class TestCoderPrompt:
    """Verify system prompt content (built dynamically, including MCP context)."""

    def test_prompt_contains_tool_list(self):
        from src.agents.coder_agent import _build_system_prompt
        prompt = _build_system_prompt("")
        assert "read_file" in prompt
        assert "edit_file" in prompt
        assert "bash_exec" in prompt
        assert "web_search" in prompt
        assert "web_fetch" in prompt
        assert "list_mcp_servers" in prompt

    def test_prompt_contains_workflow(self):
        from src.agents.coder_agent import _build_system_prompt
        prompt = _build_system_prompt("")
        assert "FINAL REPORT" in prompt
        assert "Do NOT run destructive commands" in prompt


class TestRunCoder:
    """Verify run_coder constructs the right message and invokes agent."""

    @patch("src.agents.coder_agent.build_coder_agent")
    def test_run_coder_basic(self, mock_build):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="FINAL REPORT\nAll done.")]
        }
        mock_build.return_value = mock_agent

        from src.agents.coder_agent import run_coder
        result = run_coder("Write tests")
        assert "FINAL REPORT" in result

    @patch("src.agents.coder_agent.build_coder_agent")
    def test_run_coder_with_feedback(self, mock_build):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Fixed.")]
        }
        mock_build.return_value = mock_agent

        from src.agents.coder_agent import run_coder
        result = run_coder("Write tests", feedback="Add more tests")
        assert result == "Fixed."
        # Verify the message contains both requirement and feedback
        call_args = mock_agent.invoke.call_args[0][0]
        msgs = call_args.get("messages", [])
        assert any("Write tests" in str(m.content) for m in msgs)
        assert any("Add more tests" in str(m.content) for m in msgs)

    @patch("src.agents.coder_agent.build_coder_agent")
    def test_run_coder_fallback_no_messages(self, mock_build):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": []}
        mock_build.return_value = mock_agent

        from src.agents.coder_agent import run_coder
        result = run_coder("Test")
        # Should fallback to str(result)
        assert result is not None
