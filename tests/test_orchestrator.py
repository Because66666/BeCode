"""Tests for src.core.orchestrator — error classification, verdict parsing, feedback extraction."""

from unittest.mock import MagicMock

import pytest

from src.core.orchestrator import (
    ErrorCategory,
    classify_coder_error,
    Orchestrator,
)


class TestErrorCategory:
    """Verify ErrorCategory enum values."""

    def test_enum_values(self):
        assert ErrorCategory.LLM_ERROR.value == "大模型调用出错"
        assert ErrorCategory.TOOL_ERROR.value == "工具调用错误"
        assert ErrorCategory.OTHER_ERROR.value == "其他类型错误"


class TestClassifyByExceptionName:
    """Test classify_coder_error via dynamically created exception classes."""

    @pytest.mark.parametrize("name", [
        "APIError", "RateLimitError", "APIConnectionError",
        "AuthenticationError", "InternalServerError", "BadRequestError",
        "PermissionDeniedError", "NotFoundError", "ConflictError",
        "UnprocessableEntityError", "APITimeoutError",
    ])
    def test_llm_error_by_name(self, name):
        """Any exception with a known LLM-error class name."""
        exc = type(name, (Exception,), {})("test error")
        assert classify_coder_error(exc) == ErrorCategory.LLM_ERROR

    @pytest.mark.parametrize("name", [
        "OutputParserException", "ToolException", "ValidationError",
    ])
    def test_tool_error_by_name(self, name):
        """Any exception with a known tool-error class name."""
        exc = type(name, (Exception,), {})("test error")
        assert classify_coder_error(exc) == ErrorCategory.TOOL_ERROR


class TestClassifyByMessage:
    """Test classify_coder_error via exception message keywords."""

    @pytest.mark.parametrize("msg", [
        "Connection refused",
        "timeout after 30s",
        "rate limit exceeded",
        "API key is invalid",
        "HTTP 401 Unauthorized",
        "HTTP 429 Too Many Requests",
        "HTTP 500 Internal Server Error",
        "HTTP 503 Service Unavailable",
    ])
    def test_llm_keywords(self, msg: str):
        assert classify_coder_error(Exception(msg)) == ErrorCategory.LLM_ERROR

    @pytest.mark.parametrize("msg", [
        "Failed to parse JSON",
        "malformed tool call",
        "JSON parse error",
        "invalid format in tool_call",
    ])
    def test_tool_keywords(self, msg: str):
        assert classify_coder_error(Exception(msg)) == ErrorCategory.TOOL_ERROR


class TestClassifyOther:
    """Verify fallback to OTHER_ERROR."""

    @pytest.mark.parametrize("msg", [
        "Unknown error",
        "Division by zero",
        "KeyError: 'missing'",
    ])
    def test_other_errors(self, msg: str):
        assert classify_coder_error(Exception(msg)) == ErrorCategory.OTHER_ERROR


class TestOrchestratorIsPass:
    """Verify _is_pass verdict parsing."""

    def test_pass_with_structured_format(self, pass_verdict: str):
        assert Orchestrator._is_pass(pass_verdict) is True

    def test_fail_with_structured_format(self, fail_verdict: str):
        assert Orchestrator._is_pass(fail_verdict) is False

    def test_simple_pass_marker(self):
        assert Orchestrator._is_pass("状态: PASS") is True

    def test_simple_fail_marker(self):
        assert Orchestrator._is_pass("状态: FAIL") is False

    def test_not_pass_keywords(self):
        assert Orchestrator._is_pass("This does NOT pass.") is False
        assert Orchestrator._is_pass("not pass") is False

    def test_empty_verdict(self):
        assert Orchestrator._is_pass("") is False


class TestOrchestratorExtractFeedback:
    """Verify _extract_feedback extracts only actionable items."""

    def test_extracts_next_round_feedback(self, fail_verdict: str):
        feedback = Orchestrator._extract_feedback(fail_verdict)
        assert "空输入" in feedback
        assert "测试用例" in feedback
        # Should NOT contain the full verdict
        assert "审查结论" not in feedback
        assert "状态: FAIL" not in feedback

    def test_falls_back_to_detail(self):
        verdict = """## 审查结论
### 详细意见
请修复这个问题。
"""
        feedback = Orchestrator._extract_feedback(verdict)
        assert "请修复" in feedback

    def test_no_feedback_section(self):
        verdict = "## 审查结论\n\n状态: PASS\n\nAll good."
        feedback = Orchestrator._extract_feedback(verdict)
        assert feedback == ""

    def test_feedback_truncated(self):
        """Feedback should be limited to 2000 chars."""
        long_detail = "a" * 3000
        verdict = f"""## 审查结论
### 下一轮反馈
{long_detail}
"""
        feedback = Orchestrator._extract_feedback(verdict)
        assert len(feedback) <= 2000

    def test_feedback_stops_at_next_heading(self):
        verdict = """### 下一轮反馈
Fix this bug.
## Another Section
More text that should not be included.
"""
        feedback = Orchestrator._extract_feedback(verdict)
        assert "Fix this bug." in feedback
        assert "Another Section" not in feedback
