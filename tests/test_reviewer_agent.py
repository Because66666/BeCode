"""Tests for src.agents.reviewer_agent — build_reviewer_agent, run_reviewer."""

from unittest.mock import patch, MagicMock

import pytest


class TestBuildReviewerAgent:
    """Verify build_reviewer_agent creates an agent."""

    def test_build_returns_agent(self):
        from src.agents.reviewer_agent import build_reviewer_agent
        agent = build_reviewer_agent()
        assert agent is not None

    def test_agent_has_tools(self):
        from src.agents.reviewer_agent import build_reviewer_agent
        agent = build_reviewer_agent()
        bound_tools = getattr(agent, "tools", None) or getattr(agent, "bound_tools", None)
        if bound_tools:
            tool_names = {t.name if hasattr(t, "name") else str(t) for t in bound_tools}
            assert "read_file" in tool_names
            assert "bash_exec" in tool_names


class TestReviewerPrompt:
    """Verify REVIEWER_SYSTEM_PROMPT content."""

    def test_prompt_contains_verdict_format(self):
        from src.agents.reviewer_agent import REVIEWER_SYSTEM_PROMPT
        assert "审查结论" in REVIEWER_SYSTEM_PROMPT
        assert "PASS" in REVIEWER_SYSTEM_PROMPT
        assert "FAIL" in REVIEWER_SYSTEM_PROMPT
        assert "下一轮反馈" in REVIEWER_SYSTEM_PROMPT

    def test_prompt_contains_tools(self):
        from src.agents.reviewer_agent import REVIEWER_SYSTEM_PROMPT
        assert "read_file" in REVIEWER_SYSTEM_PROMPT
        assert "bash_exec" in REVIEWER_SYSTEM_PROMPT


class TestRunReviewer:
    """Verify run_reviewer constructs message correctly."""

    @patch("src.agents.reviewer_agent.build_reviewer_agent")
    def test_run_reviewer_basic(self, mock_build):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="## 审查结论\n\n### 状态: PASS")]
        }
        mock_build.return_value = mock_agent

        from src.agents.reviewer_agent import run_reviewer
        result = run_reviewer("Write tests", "All done")
        assert "状态: PASS" in result

    @patch("src.agents.reviewer_agent.build_reviewer_agent")
    def test_run_reviewer_includes_context(self, mock_build):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Review done.")]
        }
        mock_build.return_value = mock_agent

        from src.agents.reviewer_agent import run_reviewer
        result = run_reviewer("Requirement", "Coder report")
        assert result == "Review done."

    @patch("src.agents.reviewer_agent.build_reviewer_agent")
    def test_run_reviewer_fallback(self, mock_build):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": []}
        mock_build.return_value = mock_agent

        from src.agents.reviewer_agent import run_reviewer
        result = run_reviewer("Req", "Report")
        assert result is not None
