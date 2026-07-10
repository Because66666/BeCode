"""Tests for src.core.llm_client — chat model, clean_call, summarize."""

from unittest.mock import MagicMock, patch

import pytest


class TestBuildChatModel:
    """Verify build_chat_model returns a configured ChatOpenAI instance."""

    def test_build_chat_model_defaults(self):
        from src.core.llm_client import build_chat_model
        llm = build_chat_model()
        assert llm is not None
        assert llm.temperature == 0.0
        assert llm.max_retries == 2

    def test_build_chat_model_overrides(self):
        from src.core.llm_client import build_chat_model
        llm = build_chat_model(temperature=0.5, model="gpt-3.5-turbo", max_retries=3)
        assert llm.temperature == 0.5
        assert llm.model == "gpt-3.5-turbo"
        assert llm.max_retries == 3


class TestCleanCall:
    """Verify clean_call sends messages and suppresses callbacks."""

    def test_clean_call_with_system_prompt(self):
        from src.core.llm_client import clean_call
        mock_model = MagicMock()
        mock_model.invoke.return_value.content = "Hello, world!"

        from langchain_core.messages import HumanMessage
        result = clean_call(mock_model, [HumanMessage(content="Hi")], system_prompt="Be helpful.")
        assert result == "Hello, world!"
        # Verify system prompt was prepended
        args, kwargs = mock_model.invoke.call_args
        messages = args[0]
        assert len(messages) == 2
        assert messages[0].type == "system"
        assert messages[0].content == "Be helpful."
        assert messages[1].type == "human"

    def test_clean_call_suppresses_callbacks(self):
        from src.core.llm_client import clean_call
        mock_model = MagicMock()
        mock_model.invoke.return_value.content = "OK"
        from langchain_core.messages import HumanMessage
        clean_call(mock_model, [HumanMessage(content="test")])
        args, kwargs = mock_model.invoke.call_args
        assert "config" in kwargs
        assert kwargs["config"].get("callbacks") == []


class TestCleanPromptCall:
    """Verify one-shot prompt call."""

    @patch("src.core.llm_client.build_chat_model")
    def test_clean_prompt_call(self, mock_build):
        mock_model = MagicMock()
        mock_model.invoke.return_value.content = "Response"
        mock_build.return_value = mock_model

        from src.core.llm_client import clean_prompt_call
        result = clean_prompt_call("Hello", system_prompt="Be concise.")
        assert result == "Response"


class TestSummarizeCompletion:
    """Verify summarize_completion produces a short one-line summary."""

    @patch("src.core.llm_client.build_chat_model")
    def test_summarize_returns_string(self, mock_build):
        mock_model = MagicMock()
        mock_model.invoke.return_value.content = "完成了测试功能。"
        mock_build.return_value = mock_model

        from src.core.llm_client import summarize_completion
        result = summarize_completion(
            requirement="Write tests",
            coder_report="Implemented all tests"
        )
        assert isinstance(result, str)
        assert len(result) > 0
        assert result == "完成了测试功能。"

    @patch("src.core.llm_client.build_chat_model")
    def test_summarize_truncates_long_output(self, mock_build):
        """Very long summaries should be truncated."""
        mock_model = MagicMock()
        long_text = "A" * 200
        mock_model.invoke.return_value.content = long_text
        mock_build.return_value = mock_model

        from src.core.llm_client import summarize_completion
        result = summarize_completion(requirement="x", coder_report="y")
        assert len(result) <= 120
